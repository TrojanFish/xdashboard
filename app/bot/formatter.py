import html
import urllib.parse
from typing import Dict, Any, List, Optional


def escape(text: Optional[str]) -> str:
    """对原始字符串执行安全 HTML 转义，防止 Telegram API 报错"""
    if not text:
        return ""
    return html.escape(str(text))


def format_signal_card(draft: Dict[str, Any], raw_sig: Dict[str, Any]) -> str:
    """格式化单条情报为高信噪比卡片消息（HTML 规范）"""
    category = raw_sig.get("category", "ALL")
    subreddit = raw_sig.get("subreddit", "unknown")
    title = raw_sig.get("title", "")
    permalink = raw_sig.get("permalink", "")
    score = raw_sig.get("score", 0)
    velocity = raw_sig.get("velocity", 0.0)
    controversy = raw_sig.get("controversy", 0.0)
    status = draft.get("status", "pending")
    is_raw = (status == "raw_unprocessed")

    # 草稿二创属性
    framework = draft.get("narrative_framework", "Deep Dive")
    tier = draft.get("content_tier", "DEEP_DIVE_MEMO")
    short_post = draft.get("short_post", "")
    hooks = draft.get("hooks", []) or draft.get("hook_options", [])
    first_hook = hooks[0] if hooks else ""

    # 图标与赛道徽章
    if category == "GITHUB_TRENDING":
        source_badge = "⭐ <b>[GitHub Trending]</b>"
        metrics_line = f"📈 <b>新增 Star</b>: +{score} | <b>增速</b>: {velocity} stars/h"
    elif subreddit == "hackernews":
        source_badge = "🟠 <b>[Hacker News]</b>"
        metrics_line = f"🔥 <b>点赞</b>: {score} | <b>评论</b>: {raw_sig.get('num_comments', 0)} | <b>斜率</b>: {velocity}/m"
    else:
        source_badge = f"👾 <b>[r/{escape(subreddit)}]</b>"
        metrics_line = f"▲ <b>Score</b>: {score} | 💬 <b>Comments</b>: {raw_sig.get('num_comments', 0)} | ⚡ <b>Vel</b>: {velocity}/m"

    if is_raw:
        lines = [
            f"{source_badge} {escape(title)}",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🏷️ <b>赛道</b>: <code>{escape(category)}</code> | <b>状态</b>: ⏳ 待手动二创 (省 Token 模式)",
            metrics_line,
            "",
            "<b>【原始线索提示】</b>",
            f"<i>{escape(short_post or '新捕获高信噪比线索，尚未消耗 AI Token。点击下方 [🤖 立即 AI 二创] 启动深度合成。')}</i>",
            "",
            f"🔗 <a href=\"{escape(permalink)}\">查看原帖讨论 ↗</a>"
        ]
        return "\n".join(lines)

    lines = [
        f"{source_badge} {escape(title)}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🏷️ <b>赛道</b>: <code>{escape(category)}</code> | <b>阶梯</b>: <code>{escape(tier)}</code>",
        metrics_line,
        f"💡 <b>叙事框架</b>: <code>{escape(framework)}</code>",
    ]

    if first_hook:
        lines.extend([
            "",
            "<b>【黄金两行 Hook】</b>",
            f"<i>{escape(first_hook)}</i>"
        ])

    if short_post:
        lines.extend([
            "",
            "<b>【短推速览】</b>",
            escape(short_post)
        ])

    lines.extend([
        "",
        f"🔗 <a href=\"{escape(permalink)}\">查看原帖讨论 ↗</a>"
    ])

    return "\n".join(lines)


def build_signal_inline_keyboard(post_id: str, long_post: str = "", status: str = "pending") -> Dict[str, Any]:
    """生成情报交互内联键盘"""
    # 构造 X 发帖唤起 URL
    tweet_text = long_post[:260] if long_post else ""
    x_intent_url = f"https://x.com/intent/tweet?text={urllib.parse.quote(tweet_text)}"

    buttons: List[List[Dict[str, str]]] = []

    row1 = [
        {"text": "📋 提取长推", "callback_data": f"copy:{post_id}"},
        {"text": "🚀 唤起 X 发帖", "url": x_intent_url},
    ]

    synth_btn_text = "🤖 立即 AI 二创" if status == "raw_unprocessed" else "🤖 AI 重塑"
    row2 = [
        {"text": synth_btn_text, "callback_data": f"synth:{post_id}"},
        {"text": "✅ 标为发布", "callback_data": f"pub:{post_id}"},
    ]
    row3 = [
        {"text": "🗑️ 归档跳过", "callback_data": f"arch:{post_id}"},
    ]

    if status == "published":
        row2[1] = {"text": "↩️ 撤回待发布", "callback_data": f"unpub:{post_id}"}
    elif status == "archived":
        row3[0] = {"text": "↩️ 恢复待发布", "callback_data": f"unarch:{post_id}"}

    buttons.append(row1)
    buttons.append(row2)
    buttons.append(row3)

    return {"inline_keyboard": buttons}


def build_main_menu_keyboard() -> Dict[str, Any]:
    """生成手机端底部常驻快捷操作面板 (点击即可触发，彻底告别手动打字输入指令)"""
    return {
        "keyboard": [
            [{"text": "⚡ 立即全网扫描"}, {"text": "📊 系统运行状态"}],
            [{"text": "⚙️ 切换二创模式"}, {"text": "📖 操作使用指南"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }


def format_channel_post(draft: Dict[str, Any], raw_sig: Dict[str, Any]) -> str:
    """格式化发布到公开/VIP 频道的推文广播格式"""
    title = raw_sig.get("title", "")
    permalink = raw_sig.get("permalink", "")
    short_post = draft.get("short_post", "") or (draft.get("long_post", "")[:280] if draft.get("long_post") else "")
    framework = draft.get("narrative_framework", "Alpha Breakdown")

    lines = [
        f"💎 <b>{escape(title)}</b>",
        "",
        escape(short_post),
        "",
        f"📌 <i>Framework: {escape(framework)}</i>",
        f"🔗 <a href=\"{escape(permalink)}\">Original Source</a> | #Alpha #Tech"
    ]
    return "\n".join(lines)


def format_status_message(stats: Dict[str, Any]) -> str:
    """系统状态报告模版"""
    return f"""📊 <b>Personal Alpha Studio 运行状态</b>
━━━━━━━━━━━━━━━━━━━━
⏱️ <b>定时巡航</b>: <code>{stats.get('scan_interval', 30)} 分钟/次</code> ({stats.get('auto_scan_text', '启用')})
🤖 <b>二创模式</b>: <code>{stats.get('auto_synth_text', '全自动合成')}</code>
🤖 <b>AI 模型</b>: <code>{stats.get('synthesis_model', 'gemini-3.1-pro-preview')}</code>

📦 <b>情报池统计</b>:
• 原始情报总量: <b>{stats.get('total_raw', 0)}</b> 条
• 待二创 / 待发草稿: <b>{stats.get('pending_drafts', 0)}</b> 条
• 已标记发布: <b>{stats.get('published_drafts', 0)}</b> 条
• 已归档过滤: <b>{stats.get('archived_drafts', 0)}</b> 条

🛰️ <b>最近扫描</b>: {stats.get('last_scan', '尚未执行或就绪中')}"""


def format_help_message() -> str:
    """机器人帮助说明"""
    return """🕹️ <b>Personal Alpha Studio 移动操作指南</b>
━━━━━━━━━━━━━━━━━━━━
💡 <b>免输入极速交互</b>：
无需手动打字！直接点击屏幕底部的<b>【快捷操作面板】</b>或输入框左侧的 <b>【Menu 菜单】</b>即可一键操作：

• <b>[⚡ 立即全网扫描]</b>：随时远程点火，抓取最新全球热点
• <b>[📊 系统运行状态]</b>：查看今日采集、待办草稿与巡航状态
• <b>[⚙️ 切换二创模式]</b>：随时切换「省 Token 模式」与「全自动模式」
• <b>[📖 操作使用指南]</b>：查看本帮助与说明

📥 <b>移动端外链投喂 (Drop-in Curation)</b>：
手机上刷到任何有价值的 GitHub 项目链接或技术文章，直接转发/发送给机器人，AI 自动提取关键逻辑并二创入库！"""
