# utils/data_storage.py
"""
数据存储模块 - SQLite（修复UNIQUE约束和锁问题 + 添加数据清除功能）
"""
import sqlite3
from typing import List, Dict, Any
from datetime import datetime, timedelta


class DataStorage:
    """数据存储管理器"""

    def __init__(self, db_path: str = "douyin_data.db"):
        self.db_path = db_path
        self.init_database()
    def _table_has_column(self, table: str, column: str) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        conn.close()
        return column in cols

    def _ensure_column(self, table: str, column: str, ddl: str):
        if not self._table_has_column(table, column):
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            conn.commit()
            conn.close()

    def _parse_time_ago_to_epoch(self, text: str) -> int:
        """
		把 “5分钟前 / 2小时前 / 3天前 / 4周前 / 7月前 / 1年前 / 刚刚” 转成 epoch 秒（用于排序）。
		无效返回 0。
		"""
        if not text:
            return 0
        text = str(text).strip()
        if text == "刚刚":
            return int(datetime.now().timestamp())
        import re
        m = re.search(r'(\d+)\s*个?(分钟|小時|小时|天|周|月|年)前', text)
        if not m:
            return 0
        n = int(m.group(1))
        unit = m.group(2)
        sec_map = {
			"分钟": 60, "小時": 3600, "小时": 3600, "天": 86400, "周": 604800,
			"月": 2592000,  # 30天
			"年": 31536000
		}
        seconds = n * sec_map[unit]
        return int((datetime.now().timestamp()) - seconds)

    def get_connection(self):
        """获取数据库连接（字典行模式）"""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        
        # 启用WAL模式和设置busy_timeout解决锁问题
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")

        return conn

    def init_database(self):
        """
        初始化表结构；移除users.user_url的UNIQUE约束
        """
        conn = self.get_connection()
        cur = conn.cursor()

        # 用户表 - 移除user_url的唯一约束
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                user_url TEXT,
                comment_text TEXT,
                ip_location TEXT,
                video_url TEXT,
                video_desc TEXT,
                matched_keyword TEXT,
                collected_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                message_status TEXT DEFAULT 'pending',
                last_message_time TIMESTAMP,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 视频表（不对video_url做UNIQUE约束）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_url TEXT,
                video_desc TEXT,
                keyword TEXT,
                collected_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                view_count INTEGER DEFAULT 0,
                like_count INTEGER DEFAULT 0
            )
        """)

        # 任务日志表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT,
                task_status TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                details TEXT,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        		# —— 新增的列，向后兼容（若不存在则添加）——
        self._ensure_column("videos", "publish_time", "TEXT")
        self._ensure_column("videos", "publish_ts", "INTEGER DEFAULT 0")
        self._ensure_column("users", "comment_time", "TEXT")
        self._ensure_column("users", "comment_ts", "INTEGER DEFAULT 0")
        self._ensure_column("videos", "author_name", "TEXT")
        self._ensure_column("videos", "author_url", "TEXT")
        self._ensure_column("videos", "like_count", "INTEGER DEFAULT 0")
        # 添加评论数 / 收藏数字段（若未存在）
        self._ensure_column("videos", "comment_count", "INTEGER DEFAULT 0")
        self._ensure_column("videos", "collect_count", "INTEGER DEFAULT 0")



        # 检查是否需要迁移users表（移除UNIQUE约束）
        try:
            cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
            row = cur.fetchone()
            if row and row["sql"] and "UNIQUE" in row["sql"].upper():
                # 迁移users表
                cur.execute("ALTER TABLE users RENAME TO users_old")
                cur.execute("""
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL,
                        user_url TEXT,
                        comment_text TEXT,
                        ip_location TEXT,
                        video_url TEXT,
                        video_desc TEXT,
                        matched_keyword TEXT,
                        collected_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        message_status TEXT DEFAULT 'pending',
                        last_message_time TIMESTAMP,
                        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        comment_time TEXT,
                        comment_ts INTEGER DEFAULT 0
                    )
                """)
                cur.execute("""
                    INSERT INTO users (username, user_url, comment_text, ip_location, video_url, video_desc, matched_keyword, collected_time, message_status, last_message_time, created_time)
                    SELECT username, user_url, comment_text, ip_location, video_url, video_desc, matched_keyword, collected_time, message_status, last_message_time, created_time
                    FROM users_old
                """)
                cur.execute("DROP TABLE users_old")
                print("✅ 成功迁移users表，移除UNIQUE约束")
        except Exception as e:
            print(f"迁移users表失败或无须迁移: {e}")

        # 索引（注意不要创建唯一索引）
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(message_status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_videos_keyword ON videos(keyword)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_time ON task_logs(created_time)")

        conn.commit()
        conn.close()

    def save_user(self, user_data: Dict[str, Any]) -> bool:
        """保存用户信息（使用INSERT OR IGNORE避免重复）"""
        try:
            comment_time = user_data.get("comment_time") or ""
            comment_ts = user_data.get("comment_ts") or self._parse_time_ago_to_epoch(comment_time)
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT OR IGNORE INTO users
                (username, user_url, comment_text, ip_location, video_url, video_desc, matched_keyword, comment_time, comment_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_data.get("username"),
                user_data.get("user_url"),
                user_data.get("comment_text"),
                user_data.get("ip_location"),
                user_data.get("video_url"),
                user_data.get("video_desc"),
                user_data.get("matched_keyword"),
                comment_time,
                int(comment_ts or 0),
            ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"保存用户失败: {e}")
            return False

    def save_video(self, video_data: Dict[str, Any]) -> bool:
        """保存视频信息（允许重复，不去重）"""
        try:
            publish_time = video_data.get("publish_time") or ""
            publish_ts = video_data.get("publish_ts") or self._parse_time_ago_to_epoch(publish_time)
            author_name = video_data.get("author_name") or ""
            author_url = video_data.get("author_url") or ""
            like_count = video_data.get("like_count") or 0
            comment_count = video_data.get("comment_count") or 0
            collect_count = video_data.get("collect_count") or 0
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO videos 
                (video_url, video_desc, keyword, publish_time, publish_ts, author_name, author_url, like_count, comment_count, collect_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                video_data.get("video_url"),
                video_data.get("video_desc"),
                video_data.get("keyword"),
                publish_time,
                int(publish_ts or 0),
                author_name,
                author_url,
                int(like_count),
                int(comment_count),
                int(collect_count),
            ))

            conn.commit()
            conn.close()

            return True
        except Exception as e:
            print(f"保存视频失败: {e}")
            return False

    def mark_message_sent(self, user_url: str) -> bool:
        """标记用户为已发送私信"""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE users
                SET message_status = 'sent', last_message_time = CURRENT_TIMESTAMP
                WHERE user_url = ?
            """, (user_url,))
            conn.commit()
            conn.close()
            return cur.rowcount > 0
        except Exception as e:
            print(f"标记用户私信状态失败: {e}")
            return False

    def mark_users_pending(self, user_urls: List[str]) -> int:
        """将选中的用户批量标记为pending"""
        try:
            if not user_urls:
                return 0
            conn = self.get_connection()
            cur = conn.cursor()
            count = 0
            for u in user_urls:
                cur.execute('UPDATE users SET message_status="pending" WHERE user_url = ?', (u,))
                count += cur.rowcount
            conn.commit()
            conn.close()
            return count
        except Exception as e:
            print(f"标记选中用户为待发送失败: {e}")
            return 0

    def get_pending_users(self, limit: int = 100) -> List[Dict]:
        """获取待发送私信的用户"""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM users
                WHERE message_status = 'pending'
                ORDER BY collected_time ASC
                LIMIT ?
            """, (limit,))
            rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"获取待发送用户失败: {e}")
            return []

    def get_recent_users(self, limit: int = 50, sort_by: str = "time") -> List[Dict]:
        """获取最近采集的用户，支持排序"""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
            if sort_by == "ip":
                query = """
                    SELECT * FROM users
                    ORDER BY ip_location ASC, collected_time DESC
                    LIMIT ?
                """
            elif sort_by == "publish":
                query = """
                    SELECT * FROM users
                    ORDER BY comment_ts DESC, collected_time DESC
                    LIMIT ?
                """
            else:
                query = """
                    SELECT * FROM users
                    ORDER BY collected_time DESC
                    LIMIT ?
                """
            cur.execute(query, (limit,))
            rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"获取最近用户失败: {e}")
            return []

    def get_recent_videos(self, limit: int = 0 ,sort_by:str ="time") -> List[Dict]:
        """获取最近采集的视频"""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            if sort_by == "publish":
                cur.execute("""
                    SELECT * FROM videos
                    ORDER BY publish_ts DESC
                    LIMIT ?
                """, (limit,))
            else:
                cur.execute("""
                    SELECT * FROM videos
                    ORDER BY collected_time DESC
                    LIMIT ?
                """, (limit,))
            rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"获取最近视频失败: {e}")
            return []
    def get_users_dedup(self, limit: int = 0, sort_by: str = "time") -> List[Dict]:
        """按用户名去重（同昵称只保留最新采集的一条），支持全量"""
        try:
            conn = self.get_connection()
            cur = conn.cursor()

            base_sql = """
                SELECT *
                FROM users
                WHERE id IN (
                    SELECT MAX(id)
                    FROM users
                    GROUP BY COALESCE(username, '')
                )
            """
            order_map = {
                "ip": " ORDER BY ip_location ASC, collected_time DESC",
                "publish": " ORDER BY comment_ts DESC, collected_time DESC"
            }
            limit_sql = "" if not limit or limit <= 0 else " LIMIT ?"
            order_sql = order_map.get(sort_by, " ORDER BY collected_time DESC")
            sql = base_sql + order_sql + limit_sql

            if limit_sql:
                cur.execute(sql, (limit,))
            else:
                cur.execute(sql)

            rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"获取去重用户失败: {e}")
            return []

    def get_videos_dedup_by_desc(self, limit: int = 0,sort_by:str="time") -> List[Dict]:
        """按视频文案去重（同文案只保留最新采集的一条），支持全量"""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            order_sql = " ORDER BY publish_ts DESC, collected_time DESC" if sort_by == "publish" else " ORDER BY collected_time DESC"
            base_sql = f"""
                SELECT *
                FROM videos
                WHERE id IN (
                    SELECT MAX(id)
                    FROM videos
                    GROUP BY COALESCE(video_desc, '')
                )
                {order_sql}
            """
            limit_sql = "" if not limit or limit <= 0 else " LIMIT ?"
            sql = base_sql + limit_sql

            if limit_sql:
                cur.execute(sql, (limit,))
            else:
                cur.execute(sql)

            rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"获取去重视频失败: {e}")
            return []

    def get_user_stats(self) -> Dict[str, Any]:
            """统计数据（去重 + 本地日历日）"""
            try:
                conn = self.get_connection()
                cur = conn.cursor()

                # 以 user_url 为唯一标识；若 user_url 为空则回退到 username
                # SQLite: COUNT(DISTINCT x) 不统计 NULL，这里用 IFNULL 兜底
                cur.execute("SELECT COUNT(DISTINCT IFNULL(user_url, username)) AS total FROM users")
                total_row = cur.fetchone()
                total = total_row[0] if total_row else 0

                cur.execute("""
                    SELECT COUNT(DISTINCT IFNULL(user_url, username)) AS pending
                    FROM users
                    WHERE message_status = 'pending'
                """)
                pending_row = cur.fetchone()
                pending = pending_row[0] if pending_row else 0

                cur.execute("""
                    SELECT COUNT(DISTINCT IFNULL(user_url, username)) AS sent
                    FROM users
                    WHERE message_status = 'sent'
                """)
                sent_row = cur.fetchone()
                sent = sent_row[0] if sent_row else 0

                # 今日按本地日历日统计（而不是 UTC）
                cur.execute("""
                    SELECT COUNT(DISTINCT IFNULL(user_url, username)) AS today
                    FROM users
                    WHERE date(collected_time, 'localtime') = date('now', 'localtime')
                """)
                today_row = cur.fetchone()
                today = today_row[0] if today_row else 0

                conn.close()
                return {
                    "total_users": total,
                    "pending_users": pending,
                    "sent_users": sent,
                    "today_users": today,
                }
            except Exception:
                return {
                    "total_users": 0,
                    "pending_users": 0,
                    "sent_users": 0,
                    "today_users": 0,
                }

    # 新增：数据清除方法
    def clear_users(self, scope: str = "all", ids: list | None = None, days: int = 7) -> int:
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            if scope == "selected" and ids:
                placeholders = ','.join(['?' for _ in ids])
                cur.execute(f"DELETE FROM users WHERE id IN ({placeholders})", [int(x) for x in ids])

            elif scope == "sent":
                cur.execute("DELETE FROM users WHERE message_status = 'sent'")
            elif scope == "unsent":
                cur.execute("DELETE FROM users WHERE COALESCE(message_status, 'pending') <> 'sent'")
            elif scope == "days":
                # 按评论时间的时间戳 comment_ts 清理：
                # 1）优先删除 comment_ts 对应的“评论时间早于 N 天”的数据
                # 2）对没有 comment_ts 的记录，退回按 created_time 来清理
                cutoff_ts = int((datetime.now() - timedelta(days=int(days))).timestamp())
                cur.execute("""
                    DELETE FROM users
                    WHERE 
                        (comment_ts IS NOT NULL AND comment_ts > 0 AND comment_ts < ?)
                        OR (
                            (comment_ts IS NULL OR comment_ts = 0)
                            AND created_time < datetime('now', ?)
                        )
                """, (cutoff_ts, f"-{int(days)} days"))

            elif scope == "all":
                cur.execute("DELETE FROM users")
            else:
                # 未知 scope，直接不动数据，返回 0
                return 0
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def clear_videos(self, scope: str = "all", ids: list | None = None, days: int = 7) -> int:
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            if scope == "selected" and ids:
                placeholders = ','.join(['?' for _ in ids])
                cur.execute(f"DELETE FROM videos WHERE id IN ({placeholders})", [int(x) for x in ids])
            elif scope == "days":
                # 按视频发布时间的时间戳 publish_ts 清理：
                # 1）优先删除 publish_ts 对应的“发布时间早于 N 天”的数据
                # 2）对没有 publish_ts 的记录，退回按 collected_time 来清理
                cutoff_ts = int((datetime.now() - timedelta(days=int(days))).timestamp())
                cur.execute("""
                    DELETE FROM videos
                    WHERE 
                        (publish_ts IS NOT NULL AND publish_ts > 0 AND publish_ts < ?)
                        OR (
                            (publish_ts IS NULL OR publish_ts = 0)
                            AND collected_time < datetime('now', ?)
                        )
                """, (cutoff_ts, f"-{int(days)} days"))

            else:
                cur.execute("DELETE FROM videos")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def clear_task_logs(self, scope: str = "all", days: int = 7) -> int:
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            if scope == "days":
                cur.execute("DELETE FROM task_logs WHERE created_time < datetime('now', ?)", (f"-{int(days)} days",))
            else:
                cur.execute("DELETE FROM task_logs")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def update_video(self, data: Dict[str, Any]) -> bool:
        """
        根据 video_url 更新视频详情字段：
        - video_desc
        - keyword
        - publish_time / publish_ts
        - author_name / author_url
        - like_count / comment_count / collect_count
        """
        url = data.get("video_url")
        if not url:
            return False

        try:
            conn = self.get_connection()
            cur = conn.cursor()

            cur.execute("""
                UPDATE videos
                SET 
                    video_desc = COALESCE(?, video_desc),
                    keyword = COALESCE(?, keyword),
                    publish_time = COALESCE(?, publish_time),
                    publish_ts = COALESCE(?, publish_ts),
                    author_name = COALESCE(?, author_name),
                    author_url = COALESCE(?, author_url),
                    like_count = COALESCE(?, like_count),
                    comment_count = COALESCE(?, comment_count),
                    collect_count = COALESCE(?, collect_count)
                WHERE video_url = ?
            """, (
                data.get("video_desc"),
                data.get("keyword"),
                data.get("publish_time"),
                data.get("publish_ts"),
                data.get("author_name"),
                data.get("author_url"),
                data.get("like_count"),
                data.get("comment_count"),
                data.get("collect_count"),
                url
            ))

            conn.commit()
            conn.close()

            return cur.rowcount > 0

        except Exception as e:
            print(f"更新视频失败: {e}")
            return False

# 全局实例
data_storage = DataStorage()