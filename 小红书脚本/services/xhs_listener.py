# services/xhs_listener.py
import asyncio
import time
from typing import List, Dict, Any

from browser_manager import BrowserManager
from data_storage import DataStorage
from settings import SETTINGS


class XHSListenerService:
    def __init__(self, browser_manager: BrowserManager, storage: DataStorage):
        self.browser_manager = browser_manager
        self.storage = storage
        self._running = False
        self._tasks: List[asyncio.Task] = []

    async def run(
        self,
        watch_items: List[str],
        rule_groups: List[Dict[str, Any]],
        poll_interval: int = 30,
    ):
        self._running = True
        self._tasks = []
        for url in watch_items:
            t = asyncio.create_task(
                self._monitor_item(url, rule_groups, poll_interval)
            )
            self._tasks.append(t)
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass
        self._running = False

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    async def _monitor_item(
        self, url: str, rule_groups: List[Dict[str, Any]], poll_interval: int
    ):
        selectors = SETTINGS["XHS"]["SELECTORS"]
        page = await self.browser_manager.new_page()
        last_seen_ids = set()

        try:
            await page.goto(url, timeout=60000)
            await asyncio.sleep(2)

            while self._running:
                try:
                    await page.wait_for_selector(
                        selectors["comment_container"], timeout=15000
                    )
                    comment_nodes = await page.query_selector_all(
                        selectors["comment_item"]
                    )
                    new_comments: List[Dict[str, Any]] = []

                    for node in comment_nodes:
                        try:
                            cid = await node.get_attribute("data-comment-id")
                            import hashlib  # 文件顶部已有则忽略

                            if not cid:
                                txt_el = await node.query_selector(selectors["comment_text"])
                                txt = ((await txt_el.inner_text()).strip() if txt_el else "")
                                cid = "md5_" + hashlib.md5(txt.encode("utf-8")).hexdigest()


                            if cid in last_seen_ids:
                                continue
                            last_seen_ids.add(cid)

                            text_el = await node.query_selector(
                                selectors["comment_text"]
                            )
                            text = (
                                (await text_el.inner_text()).strip()
                                if text_el
                                else ""
                            )

                            user_el = await node.query_selector(
                                selectors["comment_user"]
                            )
                            user_name = (
                                (await user_el.inner_text()).strip()
                                if user_el
                                else ""
                            )

                            time_el = await node.query_selector(
                                selectors["comment_time"]
                            )
                            tstr = (
                                (await time_el.inner_text()).strip()
                                if time_el
                                else ""
                            )

                            rec = {
                                "item_url": url,
                                "comment_id": cid,
                                "user_name": user_name,
                                "comment_text": text,
                                "comment_time": int(time.time()),
                            }
                            self.storage.add_comment_record(rec)
                            new_comments.append(rec)
                        except Exception as e:
                            print("[XHSListener] parse comment error", e)

                    for rec in new_comments:
                        matched_keyword = ""
                        reply_text = ""
                        for group in rule_groups:
                            kws = group.get("keywords") or []
                            reply = group.get("reply", "")
                            for kw in kws:
                                if kw and kw in rec["comment_text"]:
                                    matched_keyword = kw
                                    reply_text = reply
                                    break
                            if matched_keyword:
                                break

                        if matched_keyword and reply_text:
                            try:
                                await self._reply_to_comment(
                                    url, rec, reply_text, matched_keyword
                                )
                            except Exception as e:
                                print("[XHSListener] reply error", e)

                except Exception as e:
                    print("[XHSListener] monitor loop error", e)

                await asyncio.sleep(poll_interval)
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def _reply_to_comment(
        self,
        url: str,
        comment_record: Dict[str, Any],
        reply_text: str,
        matched_keyword: str,
    ):
        selectors = SETTINGS["XHS"]["SELECTORS"]
        page = await self.browser_manager.new_page()
        try:
            await page.goto(url, timeout=60000)
            await asyncio.sleep(2)

            # 这里为了简单，直接在底部输入框回复（不是点“回复某人”）
            await page.wait_for_selector(
                selectors["comment_input"], timeout=15000
            )
            await page.click(selectors["comment_input"])
            await page.fill(selectors["comment_input"], reply_text)

            btn = await page.query_selector(selectors["comment_send_button"])
            if btn:
                await btn.click()
            else:
                await page.keyboard.press("Enter")

            await asyncio.sleep(3)

            rec = {
                "item_url": url,
                "comment_id": comment_record.get("comment_id"),
                "user_name": comment_record.get("user_name"),
                "comment_text": comment_record.get("comment_text"),
                "comment_time": comment_record.get("comment_time", 0),
                "replied": 1,
                "reply_text": reply_text,
                "matched_keyword": matched_keyword,
            }
            self.storage.add_comment_record(rec)
        finally:
            try:
                await page.close()
            except Exception:
                pass
