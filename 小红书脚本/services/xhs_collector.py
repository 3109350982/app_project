# services/xhs_collector.py
import asyncio
import time
from typing import List

from browser_manager import BrowserManager
from data_storage import DataStorage
from settings import SETTINGS


class XHSCollectorService:
    def __init__(self, browser_manager: BrowserManager, storage: DataStorage):
        self.browser_manager = browser_manager
        self.storage = storage
        self._running = False

    async def run(
        self,
        keywords,                      # 兼容 string 或 list[str]
        items_per_keyword: int = 30,   # 与 app.py 路由保持一致
        item_type: str = "video_or_note",
    ):
        """
        只在搜索结果页采集；每个关键词限制数量；逐个调用现有的 _collect_for_keyword。
        """
        self._running = True

        # 允许 keywords 传入字符串（空格/逗号分隔）或 list[str]
        if isinstance(keywords, str):
            kws = [k for k in keywords.replace("，", " ").replace(",", " ").split() if k]
        else:
            kws = [k for k in (keywords or []) if isinstance(k, str) and k.strip()]

        print(f"🔎 [XHS][Collector] 收到任务：{kws}，items_per_keyword={items_per_keyword}, item_type={item_type}")

        for kw in kws:
            if not self._running:
                break
            await self._collect_for_keyword(kw, items_per_keyword, item_type)

        self._running = False



    async def stop(self):
        self._running = False

    async def _collect_for_keyword(
        self, kw: str, items_per_keyword: int, item_type: str
    ):
        page = await self.browser_manager.new_page()
        print(f"🔎 [XHS][Collector] 准备采集关键词: {kw}，期望数量: {items_per_keyword}")
        url = SETTINGS["XHS"]["SEARCH_URL_TEMPLATE"].format(kw=kw)
        selectors = SETTINGS["XHS"]["SELECTORS"]

        try:
            print(f"🌐 [XHS][Collector] 跳转搜索页: {url}")
            await page.goto(url, timeout=60000)
            print("🌐 [XHS][Collector] 搜索页加载完成，开始解析卡片...")
            await asyncio.sleep(2)

            collected = 0
            max_scroll = 40
            scroll_count = 0

            while collected < items_per_keyword and scroll_count < max_scroll:
                cards = await page.query_selector_all(
                    selectors["search_result_item"]
                )
                card_count = len(cards)
                print(
                    f"🔎 [XHS][Collector] 本次滚动后检测到卡片数量: {card_count}，已采集: {collected}，scroll={scroll_count}"
                )
                for card in cards:
                    if collected >= items_per_keyword:
                        break
                    try:
                        link_el = await card.query_selector(selectors["item_link"])
                        if not link_el:
                            continue
                        href = await link_el.get_attribute("href")
                        if not href:
                            continue
                        if href.startswith("/"):
                            href = "https://www.xiaohongshu.com" + href

                        title_el = await card.query_selector(
                            selectors["item_title"]
                        )
                        title = (
                            (await title_el.inner_text()).strip()
                            if title_el
                            else ""
                        )
                        # 原 _parse_int 替换为：
                        def _parse_int(text: str) -> int:
                            t = (text or "").strip().lower()
                            # 统一去掉空格和符号
                            t = t.replace("+", "").replace(",", "")
                            # 特殊单位：万 / w / k
                            if "万" in t or "w" in t:
                                # 例: "1.2万" / "2w" / "2.3w+"
                                num = "".join(c for c in t if (c.isdigit() or c == ".")) or "0"
                                return int(float(num) * 10000)
                            if "k" in t:
                                # 例: "3k" => 3000
                                num = "".join(c for c in t if (c.isdigit() or c == ".")) or "0"
                                return int(float(num) * 1000)
                            # 纯数字
                            digits = "".join(c for c in t if c.isdigit())
                            return int(digits) if digits else 0


                        like_count = 0
                        comment_count = 0

                        if selectors["item_like_count"]:
                            el = await card.query_selector(
                                selectors["item_like_count"]
                            )
                            if el:
                                like_count = _parse_int(
                                    (await el.inner_text()).strip()
                                )

                        if selectors["item_comment_count"]:
                            el = await card.query_selector(
                                selectors["item_comment_count"]
                            )
                            if el:
                                comment_count = _parse_int(
                                    (await el.inner_text()).strip()
                                )

                        publish_time = ""
                        publish_ts = int(time.time())

                        item = {
                            "source": "xhs",
                            "item_url": href,
                            "title": title,
                            "keyword": kw,
                            "publish_time": publish_time,
                            "publish_ts": publish_ts,
                            "like_count": like_count,
                            "collect_count": 0,
                            "comment_count": comment_count,
                            "type": item_type,
                        }
                        self.storage.insert_or_update_item(item)
                        collected += 1
                        print(
                            f"✅ [XHS][Collector] 采集成功：kw={kw} url={href} title={title} like={like_count}"
                        )
                    except Exception as e:
                        print("[XHSCollector] card parse error", e)

                if collected >= items_per_keyword:
                    break

                await page.evaluate(
                    "window.scrollBy(0, window.innerHeight || 800);"
                )
                await asyncio.sleep(1)
                scroll_count += 1
            print(
                f"✅ [XHS][Collector] 关键词 {kw} 采集结束，最终数量={collected}，总滚动次数={scroll_count}"
            )
        finally:
            try:
                await page.close()
            except Exception:
                pass
