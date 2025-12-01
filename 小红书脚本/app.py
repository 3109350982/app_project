# app.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import asyncio
import os
from typing import Dict, Any, List

from settings import SETTINGS
from license_client import get_client, lic_status
from data_storage import DataStorage
from browser_manager import BrowserManager
from task_scheduler import TaskScheduler

app = FastAPI(title="小红书自动化系统")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# 静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 全局对象
license_client = get_client()
storage = DataStorage(SETTINGS["DB_PATH"])
browser_manager = BrowserManager(SETTINGS["BROWSER_USER_DATA_DIR"])
scheduler = TaskScheduler(browser_manager, storage, license_client)


class WSManager:
    def __init__(self):
        self._clients: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)
        await self.send_json(
            {"type": "connected", "msg": "WebSocket 已连接（小红书脚本）"}
        )

    def disconnect(self, ws: WebSocket):
        if ws in self._clients:
            self._clients.remove(ws)

    async def send_json(self, data: Dict[str, Any]):
        removed = []
        for ws in self._clients:
            try:
                await ws.send_json(data)
            except Exception:
                removed.append(ws)
        for ws in removed:
            self.disconnect(ws)


ws_manager = WSManager()


@app.on_event("startup")
async def _startup():
    storage.init_database()
    # license 本地缓存已经在 get_client() 中初始化
    asyncio.create_task(
        license_client.periodic_local_check(60, scheduler.shutdown_if_expired)
    )
    asyncio.create_task(
        license_client.periodic_remote_check(3600, scheduler.shutdown_if_expired)
    )
    asyncio.create_task(scheduler.run_loop())


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # 前端目前不需要发指令，这里仅保持连接
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# 许可证接口
@app.get("/api/license/status")
async def api_license_status():
    return lic_status()


@app.post("/api/license/activate")
async def api_license_activate(payload: Dict[str, Any] = Body(...)):
    key = (payload.get("key") or "").strip()
    if not key:
        return {"ok": False, "message": "empty key"}
    ok, msg = await license_client.activate(key)
    if ok:
        await ws_manager.send_json(
            {"type": "operation", "msg": f"🎫 许可证激活成功: {msg}"}
        )
    else:
        await ws_manager.send_json(
            {"type": "error", "msg": f"🎫 许可证激活失败: {msg}"}
        )
    return {"ok": ok, "message": msg}


# 浏览器启动
@app.post("/api/browser/start")
async def api_browser_start():
    try:
        await browser_manager.ensure_browser()
        await browser_manager.new_page()
        
        await ws_manager.send_json(
            {"type": "operation", "msg": "🖥️ 浏览器已启动（小红书）"}
        )
        return {"ok": True}
    except Exception as e:
        await ws_manager.send_json(
            {"type": "error", "msg": f"🖥️ 浏览器启动失败: {e}"}
        )
        return {"ok": False, "message": str(e)}


# 采集
@app.post("/api/xhs/collect/start")
async def api_xhs_collect_start(payload: Dict[str, Any] = Body(...)):
    if not lic_status().get("valid"):
        return {"ok": False, "message": "license invalid"}
    keywords = payload.get("keywords", "")
    items_per_keyword = int(payload.get("items_per_keyword", 10))
    item_type = payload.get("type", "note")
    ok = await scheduler.start_service(
        "XHSCollectorService",
        keywords=keywords,
        items_per_keyword=items_per_keyword,
        item_type=item_type,
    )
    
    if ok:
        await ws_manager.send_json(
            {
                "type": "operation",
                "msg": f"📎 开始采集：{keywords} 每个关键词 {items_per_keyword} 条",
            }
        )
    return {"ok": ok}


# 评论
@app.post("/api/xhs/comment/start")
async def api_xhs_comment_start(payload: Dict[str, Any] = Body(...)):
    if not lic_status().get("valid"):
        return {"ok": False, "message": "license invalid"}
    ok = await scheduler.start_service(
        "XHSCommenterService",
        message=payload.get("message", ""),
        selected_items=payload.get("selected_items") or [],
        min_interval_min=int(payload.get("min_interval_min", 3)),
        max_interval_min=int(payload.get("max_interval_min", 60)),
        max_total=int(payload.get("max_total", 999)),
    )
    if ok:
        await ws_manager.send_json(
            {"type": "operation", "msg": "💬 评论任务已启动"}
        )
    return {"ok": ok}


# 监听 + 自动回复
@app.post("/api/xhs/watch/start")
async def api_xhs_watch_start(payload: Dict[str, Any] = Body(...)):
    if not lic_status().get("valid"):
        return {"ok": False, "message": "license invalid"}
    ok = await scheduler.start_service(
        "XHSListenerService",
        watch_items=payload.get("watch_items") or [],
        rule_groups=payload.get("rule_groups") or [],
    )
    if ok:
        await ws_manager.send_json(
            {"type": "operation", "msg": "👀 监听任务已启动"}
        )
    return {"ok": ok}


# 列表接口：供前端刷新右侧列表
@app.get("/api/xhs/items/list")
async def api_xhs_items_list(sort: str = Query("collect_time")):
    items = storage.list_items(sort)
    return {"ok": True, "items": items}


# 停止所有任务（前端“停止所有任务”按钮）
@app.post("/api/app/stop_all")
async def api_app_stop_all():
    await scheduler.shutdown_all()
    await ws_manager.send_json(
        {"type": "operation", "msg": "🛑 已请求停止所有任务"}
    )
    return {"ok": True}


# 退出程序（前端“退出”按钮会调这个，实际只返回 ok，真正退出你在打包层处理）
@app.post("/api/app/quit")
async def api_app_quit():
    return {"ok": True}
