# license_client.py
import json
import time
import asyncio
import platform
import uuid
import hashlib
from typing import Callable, Optional, Dict, Any

import aiohttp

from settings import SETTINGS


def _hwid() -> str:
    parts = [
        platform.system(),
        platform.release(),
        platform.machine(),
        platform.node(),
        str(uuid.getnode()),
    ]
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()


def _pick_license_exp(d: Dict[str, Any]) -> int:
    """
    兼容抖音服务器多种字段：
    license_exp / license_exp_ts / license_until / lic_exp / lic_expire_ts / expire_at / expires_at
    """
    candidates = [
        "license_exp",
        "license_exp_ts",
        "license_until",
        "lic_exp",
        "lic_expire_ts",
        "expire_at",
        "expires_at",
    ]
    for k in candidates:
        if k in d and d.get(k):
            v = int(d.get(k) or 0)
            # 毫秒时间戳转秒
            if v > 10**12:
                v //= 1000
            return v
    return 0


class LicenseClient:
    def __init__(self, cache_path: str, server_url: str):
        self.cache_path = cache_path
        # 这里的 server_url 是根域名，例如 https://license.cjylkr20241008.top
        self.server_url = server_url.rstrip("/")
        self.data: Dict[str, Any] = {
            "valid": False,
            "expires_at": 0,
            "key": None,
            "token": "",
            "token_exp": 0,
            "lic_exp": 0,
        }

    # ---------- 本地缓存 ----------
    def init_from_cache(self):
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
        except Exception:
            cached = {}

        # 默认结构
        self.data = {
            "valid": False,
            "expires_at": 0,
            "key": None,
            "token": "",
            "token_exp": 0,
            "lic_exp": 0,
        }

        if isinstance(cached, dict):
            # 兼容旧字段
            if "key" in cached:
                self.data["key"] = cached.get("key")
            if "token" in cached:
                self.data["token"] = cached.get("token") or ""
            if "token_exp" in cached:
                self.data["token_exp"] = int(cached.get("token_exp") or 0)
            if "lic_exp" in cached:
                self.data["lic_exp"] = int(cached.get("lic_exp") or 0)
            if "expires_at" in cached:
                self.data["expires_at"] = int(cached.get("expires_at") or 0)
            if "valid" in cached:
                self.data["valid"] = bool(cached.get("valid"))

        # 启动时同步一次 expires_at
        self._sync_exp()

    def _dump(self):
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _sync_exp(self):
        now = int(time.time())
        lic_exp = int(self.data.get("lic_exp") or 0)
        token_exp = int(self.data.get("token_exp") or 0)
        exp = lic_exp or token_exp or int(self.data.get("expires_at") or 0)

        if exp <= 0:
            self.data["valid"] = False
            self.data["expires_at"] = 0
            return

        self.data["expires_at"] = exp
        self.data["valid"] = exp > now

    def status(self) -> Dict[str, Any]:
        self._sync_exp()
        return {
            "valid": bool(self.data.get("valid")),
            "expires_at": int(self.data.get("expires_at") or 0),
            "key": self.data.get("key"),
        }

    # ---------- 激活 ----------
    async def activate(self, key: str) -> (bool, str):
        base = self.server_url.rstrip("/")
        activate_url = f"{base}/v1/licenses/activate"
        payload = {
            "key": key,
            "hwid": _hwid(),
            "product": "xhs-auto",  # 和你原来抖音脚本保持一致
            "ttl_hours": 1,
        }

        async with aiohttp.ClientSession() as session:
            try:
                resp = await session.post(activate_url, json=payload, timeout=15)
                j = await resp.json()

                if j.get("status") == "ok":
                    token = j.get("token") or ""
                    token_exp = int(j.get("exp") or 0)
                    if token_exp > 10**12:
                        token_exp //= 1000

                    lic_exp = _pick_license_exp(j)
                    exp = lic_exp or token_exp
                    if exp <= 0:
                        exp = int(time.time()) + 3600

                    self.data = {
                        "valid": True,
                        "expires_at": exp,
                        "key": key,
                        "token": token,
                        "token_exp": token_exp,
                        "lic_exp": lic_exp,
                    }
                    self._dump()
                    return True, "activated"

                msg = j.get("message") or j.get("error") or "invalid"
                print("DEBUG activate url:", activate_url)
                print("DEBUG activate payload:", payload)
                print("DEBUG activate status:", resp.status)
                print("DEBUG activate response:", j)
                return False, msg
            except Exception as e:
                # 调试阶段保留离线 1 小时
                now = int(time.time())
                self.data = {
                    "valid": True,
                    "expires_at": now + 3600,
                    "key": key,
                    "token": "",
                    "token_exp": now + 3600,
                    "lic_exp": 0,
                }
                self._dump()
                return True, f"activated_offline({e})"

    # ---------- 周期检测 ----------
    async def periodic_local_check(self, seconds: int, on_expired: Callable[[], Any]):
        while True:
            await asyncio.sleep(seconds)
            if not self.status().get("valid"):
                try:
                    res = on_expired()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass

    async def periodic_remote_check(self, seconds: int, on_expired: Callable[[], Any]):
        base = self.server_url.rstrip("/")
        verify_url = f"{base}/v1/licenses/verify"

        while True:
            await asyncio.sleep(seconds)
            token = self.data.get("token") or ""
            if not token:
                continue
            payload = {
                "token": token,
                "hwid": _hwid(),
            }
            async with aiohttp.ClientSession() as session:
                try:
                    resp = await session.post(verify_url, json=payload, timeout=15)
                    j = await resp.json()

                    if j.get("status") != "ok":
                        # 服务端明确返回无效
                        self.data["valid"] = False
                        self._dump()
                        try:
                            res = on_expired()
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            pass
                        continue

                    lic_exp = _pick_license_exp(j)
                    if lic_exp > 0:
                        self.data["lic_exp"] = lic_exp
                        self.data["expires_at"] = lic_exp
                        self.data["valid"] = lic_exp > int(time.time())
                        self._dump()
                except Exception:
                    # 网络错误直接忽略，不改变当前状态
                    pass


_global_client: Optional[LicenseClient] = None


def get_client() -> LicenseClient:
    global _global_client
    if _global_client is None:
        _global_client = LicenseClient(
            cache_path=SETTINGS["LICENSE_CACHE_PATH"],
            server_url=SETTINGS["LICENSE_SERVER"],
        )
        _global_client.init_from_cache()
    return _global_client


def lic_status() -> Dict[str, Any]:
    return get_client().status()
