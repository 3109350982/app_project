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
                    # 预设变量，避免解析过程中异常导致未赋值的局部变量被引用
                    href = ""
                    title = ""
                    author_name = ""
                    try:
                        link_el = await card.query_selector(selectors["item_link"])
                        if not link_el:
                            continue
                        href = await link_el.get_attribute("href")
                        if not href:
                            continue
                        if href.startswith("/"):
                            href = "https://www.xiaohongshu.com" + href

                        async def _first_text(el, sel_list):
                            # 兼容字符串或列表传入
                            if isinstance(sel_list, str):
                                selectors_list = [sel_list]
                            else:
                                selectors_list = sel_list or []

                            async def _extract_from_element(elem):
                                if not elem:
                                    return ""
                                # 尝试读取可见文本
                                text = (await elem.inner_text() or "").strip()
                                if not text:
                                    text = (await elem.text_content() or "").strip()
                                if text:
                                    return text

                                # 常见属性兜底
                                for attr in [
                                    "title",
                                    "aria-label",
                                    "alt",
                                    "data-title",
                                    "data-desc",
                                    "data-name",
                                    "data-nickname",
                                ]:
                                    attr_text = await elem.get_attribute(attr)
                                    if attr_text and attr_text.strip():
                                        return attr_text.strip()
                                return ""

                            for sel in selectors_list:
                                if not sel:
                                    continue
                                targets = await el.query_selector_all(sel)
                                for target in targets:
                                    text = await _extract_from_element(target)
                                    if text:
                                        return text
                            return ""

                        title_selectors = (
                            selectors.get("item_title_selectors")
                            or [selectors.get("item_title")]
                        )
                        try:
                            title = await _first_text(card, title_selectors)
                        except Exception as e:
                            # 标题解析异常直接兜底为空，避免中断
                            print(f"[XHSCollector] title parse error: {e}")
                            title = ""

                        # 有些卡片把标题放在链接的 title/aria-label 上，做补充兜底
                        if (not title) and link_el:
                            link_title = (
                                (await link_el.get_attribute("title"))
                                or (await link_el.get_attribute("aria-label"))
                                or (await link_el.get_attribute("alt"))
                                or ""
                            ).strip()
                            if link_title:
                                title = link_title

                        # 如果标题仍为空，尝试从整张卡片的文本中粗略提取
                        if not title:
                            try:
                                raw_card_text = await card.inner_text()
                            except Exception:
                                raw_card_text = ""

                            lines = [
                                l.strip()
                                for l in (raw_card_text or "").replace("\r", "").split("\n")
                                if l.strip()
                            ]

                            # 过滤明显不是标题的行（点赞、评论、作者等）
                            noise_keywords = [
                                "赞",
                                "评论",
                                "收藏",
                                "转发",
                                "发布",
                                "小时前",
                                "刚刚",
                                "昨天",
                                "前",
                                "后",
                            ]
                            candidate_lines = []
                            for line in lines:
                                # 排除已经解析到的作者、时间、点赞等内容
                                if (author_name and line == author_name) or (
                                    publish_time and line == publish_time
                                ):
                                    continue
                                if like_text and line == like_text:
                                    continue
                                if any(kw in line for kw in noise_keywords):
                                    continue
                                candidate_lines.append(line)

                            # 优先选择最长的候选行，尽量接近期望的标题
                            if candidate_lines:
                                title = max(candidate_lines, key=len)

                        try:
                            author_name = await _first_text(
                                card, selectors.get("item_author_selectors", [])
                            )
                        except Exception as e:
                            print(f"[XHSCollector] author parse error: {e}")
                            author_name = ""
                        if not author_name:
                            # 兼容部分卡片作者昵称在 data-* 属性里
                            data_attrs = [
                                "data-author-name",
                                "data-nickname",
                                "data-user-name",
                                "data-user",
                            ]
                            data_author = ""
                            if link_el:
                                for attr in data_attrs:
                                    val = await link_el.get_attribute(attr)
                                    if val and val.strip():
                                        data_author = val.strip()
                                        break
                            if not data_author:
                                # 有些昵称挂在最外层卡片节点上
                                for attr in data_attrs:
                                    val = await card.get_attribute(attr)
                                    if val and val.strip():
                                        data_author = val.strip()
                                        break

                            if data_author:
                                author_name = data_author
                            else:
                                author_name = await _first_text(
                                    card, selectors.get("item_author_fallback_selectors", [])
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

                        try:
                            like_text = await _first_text(
                                card, selectors.get("item_like_count_selectors", [])
                            )
                        except Exception as e:
                            print(f"[XHSCollector] like parse error: {e}")
                            like_text = ""
                        if like_text:
                            like_count = _parse_int(like_text)

                        try:
                            comment_text = await _first_text(
                                card, selectors.get("item_comment_count_selectors", [])
                            )
                        except Exception as e:
                            print(f"[XHSCollector] comment parse error: {e}")
                            comment_text = ""
                        if comment_text:
                            comment_count = _parse_int(comment_text)

                        try:
                            publish_time = await _first_text(
                                card, selectors.get("item_publish_time_selectors", [])
                            )
                        except Exception as e:
                            print(f"[XHSCollector] publish time parse error: {e}")
                            publish_time = ""
                        publish_ts = int(time.time())
                        # 如果卡片缺失字段，则尝试从搜索页全局状态 JSON 兜底提取
                        if (not title or not author_name or like_count == 0) and href:
                            note_id = href.split("/")[-1].split("?")[0]
                            state_info = await self._fetch_state_info(page, note_id)
                            title = title or state_info.get("title", "")
                            author_name = author_name or state_info.get("author_name", "")
                            like_count = like_count or state_info.get("like_count", 0)
                            comment_count = comment_count or state_info.get("comment_count", 0)
                            publish_time = publish_time or state_info.get("publish_time", "")
                            publish_ts = state_info.get("publish_ts", publish_ts)

                        # 确保关键字段为字符串，避免空值导致的异常
                        title = title or ""
                        author_name = author_name or ""

                        item = {
                            "source": "xhs",
                            "item_url": href,
                            "title": title,
                            "author_name": author_name,
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
                        try:
                            snapshot = (await card.inner_html()) if card else ""
                        except Exception:
                            snapshot = ""
                        print(
                            "[XHSCollector] card parse error",
                            e,
                            "| partial data => href:",
                            href,
                            "title:",
                            title,
                            "author:",
                            author_name,
                        )
                        if snapshot:
                            print("[XHSCollector] card html snippet:", snapshot[:500])

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

    async def _fetch_state_info(self, page, note_id: str) -> dict:
        """从搜索页的全局 JSON 里按 note_id 兜底取标题/作者/互动数据"""
        info = {
            "title": "",
            "author_name": "",
            "like_count": 0,
            "comment_count": 0,
            "publish_time": "",
            "publish_ts": 0,
        }

        if not note_id:
            return info

        try:
            state = await page.evaluate(
                """
                (id) => {
                    const raw = window.__INITIAL_STATE__ || window.__REDUX_STATE__ || {};
                    const notesFromList = raw?.feed?.notes || raw?.search?.notes || [];
                    const noteMap = raw?.note?.noteMap || raw?.feed?.noteMap || raw?.noteMap || raw?.feedNoteMap || {};
                    const findNote = (n) => n && (n.id === id || n.noteId === id || n.note_id === id);
                    const noteFromList = Array.isArray(notesFromList) ? notesFromList.find(findNote) : null;
                    const noteFromMap = noteMap[id] || noteMap[id?.toLowerCase?.()] || null;
                    const note = noteFromList || noteFromMap || {};

                    const interact = note.interactInfo || note.interactionInfo || note.stats || {};
                    const user = note.user || note.creator || note.author || {};

                    return {
                        title: note.title || note.desc || note.displayTitle || '',
                        author_name: user.nickname || user.nickName || user.name || '',
                        like_count: Number(interact.likedCount || interact.likeCount || interact.likes || interact.liked || 0) || 0,
                        comment_count: Number(interact.commentCount || interact.comments || interact.comment || 0) || 0,
                        publish_time: note.time || note.displayTime || note.createTime || note.publishedAt || '',
                        publish_ts: Number(note.time || note.createTime || note.timestamp || note.publishedAt || 0) || 0,
                    };
                }
                """,
                note_id,
            )
            if state:
                info.update({k: v for k, v in state.items() if v})
        except Exception:
            pass

        if not info["publish_ts"] and info["publish_time"]:
            try:
                info["publish_ts"] = int(info["publish_time"])
            except Exception:
                info["publish_ts"] = int(time.time())

        return info