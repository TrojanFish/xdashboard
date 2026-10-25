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
    row2 = [
        {"text": "🤖 AI 重塑", "callback_data": f"synth:{post_id}"},
        {"text": "✅ 标为发布", "callback_data": f"pub:{post_id}"},
    ]
    row3 = [
        {"text": "🗑️ 归档跳过", "callback_data": f"arch:{post_id}"},
    ]

    if status == "published":
        row2[1] = {"text": "✅ 已发布", "callback_data": f"noop:{post_id}"}
    elif status == "archived":
        row3[0] = {"text": "📦 已归档", "callback_data": f"noop:{post_id}"}

    buttons.append(row1)
    buttons.append(row2)
    buttons.append(row3)

    return {"inline_keyboard": buttons}


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
    return """🕹️ <b>Alpha Studio 指令与操作指南</b>
━━━━━━━━━━━━━━━━━━━━
/scan - 🚀 手机端随时远程点火，触发全网实时情报扫描
/status - 📊 查看 VPS 运行状态、库藏草稿与采集数据统计
/auto - ⚡ 一键切换「全自动二创」与「省 Token / 仅抓取」模式
/help - 📖 显示操作说明

💡 <b>移动端外链投喂</b>:
直接将任何 GitHub 仓库、推文或技术文章链接发送给本机器人，AI 将自动解析提炼并生成草稿入库！"""
