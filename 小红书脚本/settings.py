# settings.py
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS = {
    # SQLite 数据库
    "DB_PATH": os.path.join(ROOT_DIR, "xhs_data.db"),

    # 许可证缓存与服务器地址（你可以直接换成你现在抖音用的那个验证接口）
    "LICENSE_CACHE_PATH": os.path.join(ROOT_DIR, "license_cache.json"),
    "LICENSE_SERVER": "https://license.cjylkr20241008.top",

    # 浏览器用户数据目录（用于保存小红书登录态）
    "BROWSER_USER_DATA_DIR": os.path.join(ROOT_DIR, "xhs_browser_profile"),

    # 小红书相关配置
    "XHS": {
        # 关键词搜索页面 URL 模板（type=51 综合）
        "SEARCH_URL_TEMPLATE": "https://www.xiaohongshu.com/search_result?keyword={kw}&type=51",

        "SELECTORS": {
            # 列表/搜索卡片
            "grid_card":        "section.note-item",
            # 搜索卡片封面链接：<section class="note-item"> <a class="cover mask" href="...">
            # 同时兼容 a.cover / a.cover.mask / a.note-link / 探索页 explore 链接
            "item_link":        "a.cover, a.cover.mask, a.note-link, a[href^='/explore/']",
            # 标题：<div class="title"><span>标题</span></div>
            "item_title":       "div.title span",
            # 作者昵称（多备用选择器）
            "item_author_selectors": [
                "div.info a.user",
                "div.info a.author",
                "div.info div.user span.name",
                "div.user-info a",
                "div.author a",
                "div.author a.name",
                "div.bottom-wrapper .author a",
                "div.footer div.author a",
                "div.footer div.author a.name",
            ],
            # 底部各种数值区域（如果后面要扩展可复用）
            "item_counts":      ".card-bottom-wrapper .count",
            "grid_title_link":  "div.title",
            # 点赞数：<div class="like-wrapper"><span class="count">101</span></div>
            "item_like_count_selectors": [
                "div.like-wrapper span.count",
                "span.like-wrapper span.count",
                "div.interactions span.count",
                "span.engage span.count",
                "div.footer div.action span.count",
                "div.footer .actions span.count",
                "div.note-interactions span.count",
                "div.action span.count",
            ],
            # 评论数备用选择器
            "item_comment_count_selectors": [
                "div.comment-wrapper span.count",
                "div.interactions span.comment",
                "span.comment-wrapper span.count",
                "div.footer div.comment span.count",
                "div.footer .comment-wrapper span.count",
            ],
            # 发布时间：<div class="time"><span>08-25</span></div>
            "item_publish_time_selectors": [
                "div.time span",
                "span.publish-time",
                "div.footer div.time span",
            ],
            "item_collect_count": "",
            "grid_publish_time": "div.time span",
            # 每个搜索结果卡片最外层
            "search_result_item": "section.note-item",

            # 详情页（备用）
            "detail_publish_time": "div.note-content .date span",

            # 评论区（监听/回复）
            "comment_list_root":  'div.comments-el div[name="list"]',
            "comment_item":       "div.comment-item",
            "comment_text":       "div.content span.note-text > span",
            "comment_time":       "div.info > div.date > span",
            "comment_location":   "div.info .location",
            "comment_count":      "div.interactions .count",
            "comment_user":       "div.comment-item .author a.name",
            "comment_container":  "div.comments-container",
            "comment_reply_btn":  "div.interactions .reply-icon-container, svg.reds-icon.reply-icon",
            "comment_reply_button": "div.comment-item svg.reply-icon",

            # 发评论（根据你第三张截图中的 DOM）
            # <div id="content-textarea" class="content-edit" contenteditable="true">
            "comment_input":       "#content-textarea[contenteditable='true']",
            "comment_send_button": "svg.reply-icon",

        }
    }
}
