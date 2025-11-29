# services/xhs_commenter.py
import asyncio
import random
import time
from typing import List

from browser_manager import BrowserManager
from data_storage import DataStorage
from settings import SETTINGS


class XHSCommenterService:
    def __init__(self, browser_manager: BrowserManager, storage: DataStorage):
        self.browser_manager = browser_manager
        self.storage = storage
        self._running = False
        self._last_comment_ts = 0

    async def run(
        self,
        message: str,
        selected_items: List[str],
        min_interval_min: int = 3,
        max_interval_min: int = 3600,
        max_total: int = 999,
    ):
        self._running = True
        total = 0
        selectors = SETTINGS["XHS"]["SELECTORS"]

        for url in selected_items:
            if not self._running:
                break
            if total >= max_total:
                break

            now = int(time.time())
            min_seconds = int(min_interval_min) * 60
            elapsed = now - self._last_comment_ts
            if self._last_comment_ts > 0 and elapsed < min_seconds:
                await asyncio.sleep(min_seconds - elapsed)

            page = await self.browser_manager.new_page()
            print(f"📝 [XHS][Comment] 准备对 {url} 发表评论")
            try:
                print(f"🌐 [XHS][Comment] 跳转笔记: {url}")
                await page.goto(url, timeout=60000)
                await asyncio.sleep(2)

                await page.wait_for_selector(
                    selectors["comment_input"], timeout=15000
                )
                await page.click(selectors["comment_input"])
                await page.fill(selectors["comment_input"], message)

                send_btn_sel = selectors["comment_send_button"]
                btn = await page.query_selector(send_btn_sel)
                if btn:
                    await btn.click()
                else:
                    await page.keyboard.press("Enter")

                await asyncio.sleep(3)

                ts = int(time.time())
                self.storage.mark_item_commented(url, ts)
                self._last_comment_ts = ts
                total += 1
            except Exception as e:
                print("[XHSCommenter] error", e)
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

            wait_min = max(min_interval_min, 1)
            wait_max = max(max_interval_min, wait_min)
            interval = random.randint(wait_min * 60, wait_max * 60)
            # 不一次性 sleep 太久，避免无法停止
            slept = 0
            while self._running and slept < interval:
                step = min(10, interval - slept)
                await asyncio.sleep(step)
                slept += step

        self._running = False

    async def stop(self):
        self._running = False
