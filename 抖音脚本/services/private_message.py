"""
私信服务 - 向已采集的用户发送私信（乐观输入策略 + 关注幂等 + 节流保护）
"""
import time
import random
import asyncio
from services.base_service import BaseService
from core.config_manager import config_manager
from utils.data_storage import data_storage
import re
class PrivateMessageService(BaseService):
    """私信服务 - 乐观输入策略 + 关注幂等 + 节流保护"""
    
    def __init__(self):
        super().__init__()
        self.vision_debug = True
        self.message_sent_count = 0
        self.vision_helper = None
        self._last_follow_click_ts = 0  # 关注点击节流
        
        # 统一选择器
        self.IM_DIALOG_SELECTORS = [
            'div[role="dialog"]',
            '.im-dialog,.im-chat,.chatroom'
        ]

        self.IM_INPUT_SELECTORS = [
            'div[role="dialog"] div[contenteditable="true"]',
            'div[role="dialog"] textarea',
        ]

        self.IM_SEND_BUTTON_SELECTORS = [
            'div[role="dialog"] button:has-text("发送")',
            'button:has-text("发送")'
        ]

        self.SEARCH_INPUT_SELECTORS = [
            'input[placeholder*="搜索"]',
            '[data-e2e="search-input"] input',
            'input[type="search"]'
        ]

        self.FOLLOW_BUTTON_SELECTORS = [
            'button:has-text("关注")',
            'button:has-text("已关注")',
            'button:has-text("互相关注")'
        ]
    async def _go_to_recommend_page(self, page):
        """
        导航到抖音推荐页并确认首屏可互动。
        不改你的点赞流程，只保证“起点正确”。
        """
        try:
            # 1) 直接去首页（桌面端首页默认就是‘推荐’流）
            await page.goto("https://www.douyin.com/?recommend=1", wait_until="domcontentloaded", timeout=5000)

            try:
                await page.wait_for_selector(
                    'a[href*="/video/"], [data-e2e*="feed"] a[href*="/video/"], video',
                    timeout=5000
                )
            except:
                # 兜底：轻滚一下触发懒加载再等一会
                await page.evaluate("()=>window.scrollBy({top:200,left:0,behavior:'instant'})")
                await page.wait_for_timeout(150)
                await page.wait_for_selector('a[href*="/video/"], video', timeout=3000)

            # 5) 让页面聚焦到播放器区域，避免热键打空
        
                    # 点页面中上部区域也可以激活键盘
                vw, vh = await page.evaluate("()=>[window.innerWidth, window.innerHeight]")
                await page.mouse.click(vw//2, int(vh*0.4))

            return True
        except Exception as e:
            await self._emit_event("warning", f"⚠️ 导航推荐页失败，继续按原逻辑: {e}")
            return False
    async def _browse_videos_for(self, seconds: float, like_probability: float):
        """在指定秒数内刷视频，并按给定概率进行快捷键点赞"""
        bm = await self._get_browser_manager()
        await self._go_to_recommend_page(bm.page)
        behavior = config_manager.get('behavior', {})
        min_watch = behavior.get('min_watch_time', 5)
        max_watch = behavior.get('max_watch_time', 25)

        douyin = config_manager.get('douyin', {})
        shortcuts = douyin.get('shortcuts', {})
        next_key = shortcuts.get('next_video', 'ArrowDown')
        like_key = shortcuts.get('like', 'z')

        end = time.time() + seconds
        while time.time() < end and not await self._check_stop():
            # 观看当前视频一段时间
            watch_time = random.uniform(min_watch, max_watch)
            await self._emit_event("operation", f"📺 刷视频 {watch_time:.1f} 秒（间隔期）")

            start = time.time()
            while time.time() - start < watch_time and not await self._check_stop():
                # 偶发微操作，拟人化
                if random.random() < 0.1:
                    from utils.advanced_anti_detection import anti_detection
                    await anti_detection._random_micro_operation()
                await self._interruptible_sleep(0.1)

            # 概率点赞（快捷键）
            if random.random() < like_probability:
                await bm.press_key(like_key)
                await self.pause(0.5, 1.5, 'like')

            # 切到下一个视频
            await bm.press_key(next_key)
            await self.pause(2, 4, 'video_switch')

    async def execute(self, message_template="您好，看到您的评论，很高兴认识您！", duration_minutes=10, user_urls=None, **kwargs):
        """
        执行私信发送功能
        
        Args:
            message_template: 私信模板
            duration_minutes: 运行时间(分钟)
        """
        interval_minutes = kwargs.get('interval_minutes', 4)
        like_probability = kwargs.get('like_probability', config_manager.get('behavior.like_probability', 0.6))
        # 保护
        interval_minutes = max(1, int(interval_minutes))
        like_probability = max(0.0, min(1.0, float(like_probability)))
        rotate_accounts = bool(kwargs.get('rotate_accounts', False))
        raw_dirs = kwargs.get('account_dirs', '') or ''
        # 允许换行/空格/逗号分隔
        profile_dirs = [d.strip() for d in re.split(r'[\n\r,]+', str(raw_dirs)) if d.strip()]  # 保留路径中的空格
        # 轮询提示
        if rotate_accounts and profile_dirs:
            await self._emit_event("operation", f"🔁 多账号轮询启用：共 {len(profile_dirs)} 个账号")


        await self._emit_event("operation", f"🚀 开始私信发送任务（节流保护版本）")
        await self._emit_event("operation", f"💌 私信模板: {message_template}")
        await self._emit_event("operation", f"⏰ 总时长: {duration_minutes} 分钟")
        
        # 确保浏览器就绪
        if not await self._ensure_browser_ready():
            await self._emit_event("error", "❌ 浏览器未就绪")
            return
        
        browser_manager = await self._get_browser_manager()
        storage = await self._get_data_storage()
        
        # 初始化视觉助手
        self.vision_helper = self._get_vision_helper(browser_manager.page)
        
        end_time = time.time() + duration_minutes * 60
        total_messages_sent = 0
        total_users_processed = 0
        
        try:
            # 获取待发送私信的用户
            pending_users = [{'username':'','user_url':u} for u in (user_urls or [])] if (user_urls and len(user_urls)>0) else storage.get_pending_users(limit=1000)
            
            if not pending_users:
                await self._emit_event("operation", "ℹ️ 没有待发送私信的用户")
                return
            await self._emit_event("operation", f"📋 找到 {len(pending_users)} 个待发送用户")
            for user in pending_users:
                if time.time() >= end_time or await self._check_stop():
                    break
                total_users_processed += 1
                await self._emit_event("operation", f"💌 处理用户: {user['username']} ({total_users_processed}/{len(pending_users)})")
                # —— 多账号轮询：每个用户前切到下一个 profile ——
                if rotate_accounts and profile_dirs:
                    idx = (total_users_processed - 1) % len(profile_dirs)  # 第1位对应第1个账号     
                    target_profile = profile_dirs[idx]
                    ok = await browser_manager.switch_profile(target_profile)
                    if ok:
                        # 切换后页面对象变化，刷新视觉助手
                        self.vision_helper = self._get_vision_helper(browser_manager.page)
                        await self._emit_event("operation", f"👤 使用账号[{idx+1}/{len(profile_dirs)}]: {target_profile}")
                    else:
                        await self._emit_event("warning", f"⚠️ 切换账号失败: {target_profile}，继续使用当前账号")

                # 发送私信给单个用户（节流保护版本）
                if await self._send_message_to_user_optimistic(browser_manager, storage, user, message_template):
                    total_messages_sent += 1
                    await self._emit_event("operation", f"✅ 成功发送私信给: {user['username']}")
                else:
                    await self._emit_event("error", f"❌ 发送私信失败: {user['username']}")
                
                # 智能延迟，避免操作过于频繁
                if rotate_accounts and profile_dirs:
                    # 轮询场景：不等待，直接下一个账号发下一位
                    await self._emit_event("operation", "🔁 轮询已启用：跳过等待，继续下一位")
                else:
                    await self._emit_event("operation", f"⏳ 等待 {interval_minutes} 分钟（刷视频中）")
                    await self._browse_videos_for(interval_minutes * 60, like_probability)

                
                # 每发送5条消息后智能休息
                if total_messages_sent % 5 == 0 and total_messages_sent > 0:
                    from utils.advanced_anti_detection import anti_detection
                    await anti_detection.smart_rest(30, 60)
            
            # 任务完成
            final_msg = f"🏁 私信发送完成。共处理 {total_users_processed} 个用户，成功发送 {total_messages_sent} 条私信。"
            await self._emit_event("finished", final_msg)
            
        except Exception as e:
            error_msg = f"❌ 私信发送任务异常: {str(e)}"
            await self._emit_event("error", error_msg)

    def _get_vision_helper(self, page):
        """获取视觉助手"""
        from core.vision_helper import get_vision_helper
        return get_vision_helper(page)
    
    async def _send_message_to_user_optimistic(self, browser_manager, storage, user, message_template):
        """节流保护版本私信发送"""
        try:
            username = user.get('username', '未知用户')
            await self._emit_event("operation", f"👤 正在处理用户: {username}")
            
            # 检查用户URL是否有效
            if not user.get('user_url') or not user['user_url'].startswith('http'):
                await self._emit_event("error", f"❌ 用户URL无效: {user['user_url']}")
                return False
            
            # 导航到用户主页
            await self._emit_event("operation", f"🌐 导航到用户主页: {username}")
            try:
                await browser_manager.page.goto(user['user_url'], wait_until='domcontentloaded', timeout=45000)
            except Exception as e:
                await self._emit_event("warning", f"⚠️ 导航警告（继续探针）: {e}")
            
            # 统一就绪探针
            ready = await browser_manager.state_detector.wait_for_user_profile_ready(timeout=12000)
            if not ready:
                # 轻量兜底：小幅滚动 + 短等待，再试一次就绪探针
                try:
                    await browser_manager.page.evaluate("window.scrollBy(0, 200)")
                    await self.pause(0.6, 1.0, 'page_probe_retry')
                    ready = await browser_manager.state_detector.wait_for_user_profile_ready(timeout=6000)
                except Exception as e:
                    await self._emit_event("debug", f"⚠️ 兜底滚动失败: {e}")

            if not ready:
                await self._emit_event("error", f"❌ 用户页仍未就绪，跳过该用户: {username}")
                return False
            
            await self.pause(2, 4, 'user_avatar_click')
            
            # 点击关注按钮（节流幂等版本）
            follow_success = await self._ensure_followed(browser_manager.page, username)
            if not follow_success:
                await self._emit_event("warning", f"⚠️ 关注用户失败: {username}")
                # 继续尝试发送私信
            
            await self.pause(1, 2, 'follow')
            
            # 点击私信按钮（DOM优先 + 锚点法 + 视觉兜底）
            if not await self._click_message_button_enhanced(browser_manager, username):
                await self._emit_event("error", f"❌ 找不到私信按钮: {username}")
                return False
            
            await self.pause(1, 2, 'message_send')
            
            # 确保私信对话框打开
            if not await self._ensure_message_dialog_open(browser_manager):
                await self._emit_event("error", f"❌ 私信对话框未打开: {username}")
                return False
            
            # 乐观输入并发送消息（三段式发送版本）
            if not await self._type_and_send_optimistic(browser_manager.page, message_template, username):
                await self._emit_event("error", f"❌ 输入发送消息失败: {username}")
                return False
            
            await self.pause(2, 3, 'message_send')
            
            # 验证消息是否发送成功
            if not await self._verify_message_sent_fixed(browser_manager, username):
                await self._emit_event("error", f"❌ 消息发送验证失败: {username}")
                return False
            
            # 标记用户为已发送
            if storage.mark_message_sent(user['user_url']):
                await self._emit_event("operation", f"✅ 标记用户状态为已发送: {username}")
                self.message_sent_count += 1
            else:
                await self._emit_event("error", f"❌ 标记用户状态失败: {username}")
            
            return True
            
        except Exception as e:
            await self._emit_event("error", f"❌ 发送私信失败 {username}: {str(e)}")
            return False

    # ==================== 新增：节流保护关注方法 ====================
    async def _ensure_followed(self, page, username) -> bool:
        """幂等关注：一次点击 + 等待状态变化；内置 2s 节流，避免连点。"""
        btn = page.locator(" , ".join(self.FOLLOW_BUTTON_SELECTORS))
        if await btn.count() == 0:
            await self._emit_event("warning", f"⚠️ 未找到关注按钮: {username}")
            return False

        # 已处于关注状态
        try:
            txt = (await btn.first.inner_text()).strip()
            if any(k in txt for k in ["已关注", "互相关注"]):
                await self._emit_event("operation", f"✅ 已处于关注状态: {username}")
                return True
        except:
            pass

        # 节流：2s 内不再点击（防止上一轮还在变更时又点一次）
        now = time.time()
        if now - self._last_follow_click_ts < 2.0:
            await self._emit_event("warning", f"⏱️ 距上次关注点击过近，跳过二次点击: {username}")
            return False
        self._last_follow_click_ts = now

        try:
            # 禁用"微操作"（避免随机点击/按键干扰）
            await page.evaluate("window.__NO_MICRO_OPS__ = true")

            await btn.first.wait_for(state="visible", timeout=3000)
            await btn.first.hover()
            await page.wait_for_timeout(80)
            await btn.first.click(no_wait_after=True)

            # 最多 5 次轮询（~2.5s）
            for i in range(5):
                await page.wait_for_timeout(500)
                try:
                    t = (await btn.first.inner_text()).strip()
                    if any(k in t for k in ["已关注", "互相关注"]):
                        await self._emit_event("operation", f"✅ 关注成功: {username}")
                        return True
                except:
                    pass
                if await page.locator('text=取消关注').count() > 0:
                    await page.mouse.click(10, 10)
                    await self._emit_event("operation", f"✅ 关注成功（通过菜单判断）: {username}")
                    return True

            await self._emit_event("warning", f"⚠️ 关注状态未改变，可能被限流/按钮异常: {username}")
            return False
        except Exception as e:
            await self._emit_event("error", f"❌ 点击关注失败 {username}: {e}")
            return False
        finally:
            await page.evaluate("window.__NO_MICRO_OPS__ = false")

    # ==================== 重写：一次输入 + 三段式发送 ====================
    async def _type_and_send_optimistic(self, page, message: str, username: str) -> bool:
        """一次输入 + 三段式发送（Enter→按钮→Ctrl+Enter），不重输。"""

        # 0) 若顶部搜索框激活，先 blur，避免截胡键盘
        try:
            await page.evaluate("""(sels)=>{ 
                for(const s of sels){
                    const el=document.querySelector(s);
                    if(el && el===document.activeElement) el.blur(); 
                } 
            }""", self.SEARCH_INPUT_SELECTORS)
        except: 
            pass

        # 1) 确保焦点大概率在 IM 对话框内；若不在，则点击对话框底部一次
        active_inside = await page.evaluate("""(rootSels)=>{
            const a=document.activeElement;
            return !!a && rootSels.some(sel=>{
                const r=document.querySelector(sel);
                return r && r.contains(a);
            });
        }""", self.IM_DIALOG_SELECTORS)
        
        if not active_inside:
            await self._simple_focus_fallback(page)

        # 2) 记一次"发送前"消息数
        def _count_bubbles_script():
            return """(roots)=>{
                let n=0; 
                for(const s of roots){
                    const r=document.querySelector(s);
                    if(!r) continue; 
                    n += r.querySelectorAll('[class*="bubble"],[class*="msg"],[class*="message"]').length;
                }
                return n;
            }"""
        pre_cnt = await page.evaluate(_count_bubbles_script(), self.IM_DIALOG_SELECTORS)

        # 3) 清空并只输入"一次"
        try:
            await page.keyboard.down("Control")
            await page.keyboard.press("A")
            await page.keyboard.up("Control")
            await page.keyboard.press("Backspace")
            await page.wait_for_timeout(60)
            await page.keyboard.type(message, delay=random.randint(10, 25))
        except Exception as e:
            await self._emit_event("error", f"❌ 输入异常 {username}: {e}")
            return False

        # 通用校验：是否"看起来"已发送（气泡增/输入清空）
        async def _looks_sent() -> bool:
            try:
                await page.wait_for_timeout(350)
                post = await page.evaluate(_count_bubbles_script(), self.IM_DIALOG_SELECTORS)
                if post > pre_cnt: 
                    return True
                    
                cleared = await page.evaluate("""(roots)=>{
                    for(const s of roots){
                        const r=document.querySelector(s); 
                        if(!r) continue;
                        const el=r.querySelector('[contenteditable="true"],textarea'); 
                        if(!el) continue;
                        const val=('value' in el)? el.value : (el.innerText||el.textContent||'');
                        if(val && val.trim().length>0) return false;
                    } 
                    return true;
                }""", self.IM_DIALOG_SELECTORS)
                return cleared
            except:
                return False

        # 4) 三段式发送流程（不重输）
        # 4.1 Enter
        await page.keyboard.press("Enter")
        if await _looks_sent():
            await self._emit_event("operation", f"✅ 使用回车发送: {username}")
            return True

        # 4.2 点击"发送"按钮
        try:
            send_btn = None
            for sel in self.IM_SEND_BUTTON_SELECTORS:
                loc = page.locator(sel)
                if await loc.count() > 0: 
                    send_btn = loc.first
                    break
                    
            if send_btn:
                await send_btn.click()
                if await _looks_sent():
                    await self._emit_event("operation", f"✅ 点击发送按钮: {username}")
                    return True
        except Exception as e:
            await self._emit_event("debug", f"发送按钮异常 {username}: {e}")

        # 4.3 Ctrl+Enter 兜底
        await page.keyboard.press("Control+Enter")
        if await _looks_sent():
            await self._emit_event("operation", f"✅ Ctrl+Enter 兜底发送: {username}")
            return True

        # 5) 最后一次"仅发送"重试（不重输）
        await self._emit_event("warning", f"⚠️ 首次发送未确认，做一次仅发送重试: {username}")
        await page.keyboard.press("Enter")
        if await _looks_sent():
            await self._emit_event("operation", f"✅ 重试发送成功: {username}")
            return True

        await self._emit_event("error", f"❌ 私信发送失败（多次发送动作均未确认）: {username}")
        return False

    async def _simple_focus_fallback(self, page):
        """
        简单聚焦兜底：以 IM 弹窗为容器，点击底部 1/3 的区域以获取光标，
        再 Ctrl+A + Backspace 清空。不会滚动，避免闪烁。
        """
        try:
            dlg = None
            for sel in self.IM_DIALOG_SELECTORS:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    dlg = loc.first
                    break
            if not dlg:
                return

            box = await dlg.bounding_box()
            if not box:
                return

            x = int(box["x"] + box["width"] * 0.5)
            y = int(box["y"] + box["height"] * 0.84)  # 底部偏上，通常是输入区
            await page.mouse.click(x, y)
            await page.wait_for_timeout(100)
            await page.keyboard.down("Control")
            await page.keyboard.press("A")
            await page.keyboard.up("Control")
            await page.keyboard.press("Backspace")
            await page.wait_for_timeout(100)
        except Exception as e:
            await self._emit_event("debug", f"简单聚焦兜底失败: {e}")

    # ==================== 原有的私信按钮点击方法 ====================
    async def _click_message_button_enhanced(self, browser_manager, username):
        """增强版私信按钮点击 - DOM优先 + 锚点法 + 视觉兜底"""
        page = browser_manager.page

        # 1) DOM 优先
        try:
            selectors = [
                'button:has-text("私信")',
                'button:has-text("发消息")',
                '[data-e2e="message-btn"]',
                '.message-button'
            ]
            
            for selector in selectors:
                try:
                    btn = page.locator(selector)
                    if await btn.count() > 0:
                        await btn.first.click(timeout=2000)
                        await self._emit_event("operation", f"✅ DOM点击: 私信 - {username}")
                        return True
                except Exception:
                    continue
        except Exception as e:
            await self._emit_event("debug", f"DOM点击失败: {e}")

        # 2) 锚点法：以"关注/已关注"为锚点，在其右侧小ROI内找"私信"
        try:
            follow_locator = page.locator('button:has-text("关注"), button:has-text("已关注")').first
            if await follow_locator.count() > 0:
                box = await follow_locator.bounding_box()
                if box:
                    pad = 16
                    roi = (
                        int(box["x"] + box["width"] + pad),
                        int(box["y"] - 20),
                        int(box["width"] * 1.6),
                        int(box["height"] + 50)
                    )
                    ok = await self.vision_helper.click_element_in_region(
                        'message_button', region=roi, confidence=0.72, allow_scroll=False
                    )
                    if ok:
                        await self._emit_event("operation", f"✅ 锚点视觉: 私信 - {username}")
                        return True
        except Exception as e:
            await self._emit_event("debug", f"锚点法失败: {e}")

        # 3) 视觉兜底：固定顶栏ROI，不滚动，至多3次轻微偏移重试
        roi0 = self.vision_helper.get_top_actionbar_roi()
        for i in range(3):
            dx = int(self.vision_helper.screen_width * 0.03 * i)  # 轻微向左扩展
            roi = (max(0, roi0[0] - dx), roi0[1], roi0[2] + dx, roi0[3])
            ok = await self.vision_helper.click_element_in_region(
                'message_button', region=roi, confidence=0.74, allow_scroll=False
            )
            if ok:
                await self._emit_event("operation", f"✅ 视觉兜底成功(i={i}) - {username}")
                return True
            await self.pause(0.5, 1, 'vision_retry')

        await self._emit_event("error", f"❌ 定位失败: message_button（DOM/锚点/视觉均未命中）- {username}")
        return False

    async def _ensure_message_dialog_open(self, browser_manager):
        """确保私信对话框已打开"""
        try:
            # 检查私信对话框是否打开
            await self.pause(1.5, 2.5, 'dialog_wait')
            
            # 检查是否有输入框
            input_selectors = [
                'textarea',
                'input[type="text"]',
                '[contenteditable="true"]'
            ]
            
            for selector in input_selectors:
                try:
                    element = await browser_manager.page.query_selector(selector)
                    if element and await element.is_visible():
                        return True
                except:
                    continue
            
            # 如果没打开，尝试再次点击私信按钮
            await self._click_message_button_enhanced(browser_manager, "重新打开对话框")
            await self.pause(2, 3, 'retry_dialog')
            
            # 再次检查
            for selector in input_selectors:
                try:
                    element = await browser_manager.page.query_selector(selector)
                    if element and await element.is_visible():
                        return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            await self._emit_event("error", f"❌ 确保私信对话框打开失败: {str(e)}")
            return False

    async def _verify_message_sent_fixed(self, browser_manager, username):
        """验证私信是否发送成功（修复版）"""
        try:
            await self._emit_event("operation", f"🔍 正在验证消息发送状态: {username}")
            
            # 方法1: 检测消息输入框是否清空
            input_selectors = [
                'textarea',
                'input[type="text"]',
                '[contenteditable="true"]'
            ]
            
            for selector in input_selectors:
                try:
                    input_element = await browser_manager.page.query_selector(selector)
                    if input_element:
                        text = await input_element.inner_text()
                        if not text.strip():
                            await self._emit_event("operation", f"✅ 输入框已清空，消息可能已发送: {username}")
                            return True
                except:
                    continue
            
            # 方法2: 检测发送按钮状态变化
            send_selectors = [
                'button:has-text("发送")',
                '[data-e2e="send-btn"]'
            ]
            
            for selector in send_selectors:
                try:
                    send_button = await browser_manager.page.query_selector(selector)
                    if send_button:
                        is_disabled = await send_button.get_attribute('disabled')
                        if is_disabled:
                            await self._emit_event("operation", f"✅ 发送按钮已禁用，消息可能已发送: {username}")
                            return True
                except:
                    continue
            
            # 方法3: 检测页面URL或状态变化
            current_url = browser_manager.page.url
            if "message" not in current_url and "chat" not in current_url:
                await self._emit_event("operation", f"✅ 已离开消息页面，消息可能已发送: {username}")
                return True
            
            await self._emit_event("warning", f"⚠️ 无法确认消息发送状态: {username}")
            return True  # 无法验证时默认成功
            
        except Exception as e:
            await self._emit_event("error", f"❌ 验证消息发送状态失败: {str(e)}")
            return True  # 验证失败时默认成功