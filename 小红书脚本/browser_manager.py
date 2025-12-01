# browser_manager.py
import asyncio
import os
from typing import Optional

try:
    from playwright.async_api import Error, TargetClosedError, async_playwright, BrowserContext, Page
except ImportError:
    # 兼容旧版 Playwright，缺失 TargetClosedError 时降级为基础错误类型
    from playwright.async_api import Error, async_playwright, BrowserContext, Page
    try:
        from playwright._impl._api_types import TargetClosedError  # type: ignore
    except Exception:  # pragma: no cover - 仅在旧版 Playwright 下兜底
        TargetClosedError = Error


class BrowserManager:
    def __init__(self, user_data_dir: str):
        self.user_data_dir = user_data_dir
        self._pw = None
        self._context: Optional[BrowserContext] = None
        self._browser = None
        self._page: Optional[Page] = None
        self._lock = asyncio.Lock()
        os.makedirs(user_data_dir, exist_ok=True)

    async def start(self, headless: bool = False):
        """
        启动一次浏览器上下文，只启动一次，后续全部复用。
        """
        if self._browser and self._context and self._page:
            return self._page

        self._pw = await async_playwright().start()

        # 统一走 edge（与你抖音相同）
        browser = await self._pw.chromium.launch(
            channel="msedge",
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        self._browser = browser
        self._context = await browser.new_context(
            user_agent=None,
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True
        )
        # 只创建一个 page
        self._page = await self._context.new_page()
        return self._page

    async def goto(self, url: str, wait: str = "networkidle"):
        """
        统一入口，永远复用同一个 page，不再 new_page()。
        """
        page = await self.start()
        await page.goto(url, wait_until=wait)
        return page
    async def _reset_context(self):
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    async def ensure_browser(self):
        async with self._lock:
            if self._context is not None:
                is_closed = getattr(self._context, "is_closed", None)
                try:
                    if callable(is_closed) and not is_closed():
                        return
                    if is_closed is None:
                        _ = self._context.pages
                        return
                except Exception:
                    pass
            await self._reset_context()
            self._pw = await async_playwright().start()
            # 持久化 context，保留登录态
            self._context = await self._pw.chromium.launch_persistent_context(
                channel="msedge",
                user_data_dir=self.user_data_dir,
                headless=False,
                args=["--no-sandbox"],
            )
            self._browser = self._context.browser

    async def new_page(self) -> Page:
        # 改为“复用优先”：如果已有未关闭的页，就复用；没有再新建
        last_error = None
        for _ in range(2):
            await self.ensure_browser()
            assert self._context is not None
            try:
                pages = [p for p in self._context.pages if not p.is_closed()]
            except Exception:
                pages = []

            if pages:
                page = pages[0]
                try:
                    await page.bring_to_front()
                except Exception:
                    pass
                print("🧭 [XHS][Browser] 复用现有标签页")
                return page
            try:
                page = await self._context.new_page()
                await page.goto("https://www.xiaohongshu.com/explore")
                print("🧭 [XHS][Browser] 新建标签页")
                return page
            except (TargetClosedError, Error) as e:
                last_error = e
                await self._reset_context()

        raise RuntimeError("浏览器已关闭，无法新建标签页") from last_error


    async def close(self):
        await self._reset_context()