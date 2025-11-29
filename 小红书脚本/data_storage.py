# data_storage.py
import sqlite3
import threading
import time
from typing import Optional, Dict, Any, List

from settings import SETTINGS

_LOCK = threading.Lock()


class DataStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def init_database(self):
        conn = self.get_conn()
        with _LOCK:
            cur = conn.cursor()
            # 小红书笔记/视频
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS xhs_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                item_url TEXT UNIQUE,
                title TEXT,
                keyword TEXT,
                publish_time TEXT,
                publish_ts INTEGER,
                like_count INTEGER DEFAULT 0,
                collect_count INTEGER DEFAULT 0,
                comment_count INTEGER DEFAULT 0,
                type TEXT,
                collected_time INTEGER,
                comment_status TEXT DEFAULT '',
                last_comment_time INTEGER DEFAULT 0
            )
            """
            )

            # 评论记录（监听 + 自动回复）
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS xhs_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_url TEXT,
                comment_id TEXT,
                user_name TEXT,
                comment_text TEXT,
                comment_time INTEGER,
                replied INTEGER DEFAULT 0,
                reply_text TEXT,
                matched_keyword TEXT
            )
            """
            )
            conn.commit()

    def insert_or_update_item(self, item: Dict[str, Any]):
        conn = self.get_conn()
        now = int(time.time())
        with _LOCK:
            cur = conn.cursor()
            cur.execute(
                """
            INSERT INTO xhs_items
              (source, item_url, title, keyword, publish_time, publish_ts,
               like_count, collect_count, comment_count, type, collected_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_url) DO UPDATE SET
               title = excluded.title,
               keyword = excluded.keyword,
               publish_time = excluded.publish_time,
               publish_ts = excluded.publish_ts,
               like_count = excluded.like_count,
               collect_count = excluded.collect_count,
               comment_count = excluded.comment_count,
               type = excluded.type,
               collected_time = excluded.collected_time
            """,
                (
                    item.get("source", "xhs"),
                    item["item_url"],
                    item.get("title", ""),
                    item.get("keyword", ""),
                    item.get("publish_time", ""),
                    int(item.get("publish_ts", 0)),
                    int(item.get("like_count", 0)),
                    int(item.get("collect_count", 0)),
                    int(item.get("comment_count", 0)),
                    item.get("type", "note"),
                    now,
                ),
            )
            conn.commit()

    def mark_item_commented(self, item_url: str, reply_ts: int):
        conn = self.get_conn()
        with _LOCK:
            cur = conn.cursor()
            cur.execute(
                "UPDATE xhs_items SET comment_status=?, last_comment_time=? WHERE item_url=?",
                ("commented", reply_ts, item_url),
            )
            conn.commit()

    def add_comment_record(self, record: Dict[str, Any]):
        conn = self.get_conn()
        with _LOCK:
            cur = conn.cursor()
            cur.execute(
                """
            INSERT INTO xhs_comments
               (item_url, comment_id, user_name, comment_text,
                comment_time, replied, reply_text, matched_keyword)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    record.get("item_url"),
                    record.get("comment_id"),
                    record.get("user_name"),
                    record.get("comment_text"),
                    int(record.get("comment_time", 0)),
                    int(record.get("replied", 0)),
                    record.get("reply_text"),
                    record.get("matched_keyword"),
                ),
            )
            conn.commit()

    def list_items(self, sort: str = "collect_time") -> List[Dict[str, Any]]:
        conn = self.get_conn()
        with _LOCK:
            cur = conn.cursor()
            if sort == "publish_time":
                cur.execute("SELECT * FROM xhs_items ORDER BY publish_ts DESC")
            elif sort == "like_count":
                cur.execute("SELECT * FROM xhs_items ORDER BY like_count DESC")
            elif sort == "comment_count":
                cur.execute("SELECT * FROM xhs_items ORDER BY comment_count DESC")
            else:
                cur.execute("SELECT * FROM xhs_items ORDER BY collected_time DESC")
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def get_items_by_urls(self, urls: List[str]) -> List[Dict[str, Any]]:
        if not urls:
            return []
        conn = self.get_conn()
        with _LOCK:
            cur = conn.cursor()
            q = ",".join("?" for _ in urls)
            cur.execute(f"SELECT * FROM xhs_items WHERE item_url IN ({q})", urls)
            return [dict(r) for r in cur.fetchall()]
