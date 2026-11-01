"""
16:9 Dark Mode Data Card Renderer
Generates a professional PNG image from visual_card_metrics JSON for X (Twitter) attachment.
Requires only Pillow (added to requirements.txt).
"""
import io
import math
from typing import Dict, Any, List, Optional
from app.config import settings

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ── Color Palette (Dark Mode Editorial) ─────────────────────────────────────
BG_COLOR       = (18, 18, 22)
PANEL_COLOR    = (28, 28, 36)
BORDER_COLOR   = (50, 50, 66)
ACCENT_COLOR   = (204, 90, 43)
POS_COLOR      = (46, 125, 50)
NEG_COLOR      = (192, 57, 43)
NEU_COLOR      = (112, 107, 99)
TEXT_PRIMARY   = (240, 235, 228)
TEXT_SECONDARY = (140, 134, 125)
DOT_SIZE       = 10


def _load_font(size: int, bold: bool = False) -> Any:
    """Try to load a system font (with CJK support), fall back to PIL default."""
    import os
    try:
        candidates = (
            [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "C:/Windows/Fonts/msyhbd.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            ]
            if bold else
            [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]
        )
        for path in candidates:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()


def _wrap_text(text: str, max_units: int) -> str:
    """
    智能折行算法：根据中英文视觉字符宽度换行。
    CJK 全角字符计 2 宽度单位，西文字符计 1 宽度单位，避免中文无空格长串溢出画布。
    """
    if not text:
        return ""
    lines = []
    for paragraph in str(text).split("\n"):
        cur_line = []
        cur_units = 0
        for char in paragraph:
            char_unit = 2 if ord(char) > 127 else 1
            if cur_units + char_unit > max_units:
                lines.append("".join(cur_line))
                cur_line = [char]
                cur_units = char_unit
            else:
                cur_line.append(char)
                cur_units += char_unit
        if cur_line:
            lines.append("".join(cur_line))
    return "\n".join(lines)


def render_card(
    card_data: Dict[str, Any],
    signal_title: str = "",
    category: str = "",
    source_label: str = "",
) -> Optional[bytes]:
    """
    Render a 16:9 dark-mode intelligence card as PNG bytes.
    Returns None if Pillow is unavailable.

    card_data: { "title": str, "type": str,
                 "metrics": [{"label":str,"value":str,"sentiment":"positive"|"negative"|"neutral"}] }
    """
    if not PIL_AVAILABLE:
        return None

    W, H = 1200, 675
    img  = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Fonts
    f_title  = _load_font(30, bold=True)
    f_label  = _load_font(14)
    f_value  = _load_font(20, bold=True)
    f_cap    = _load_font(13)
    f_brand  = _load_font(13, bold=True)

    # ── Top accent stripe ───────────────────────────────────────────────────
    draw.rectangle([(0, 0), (W, 5)], fill=ACCENT_COLOR)

    # ── Category badge + source label ───────────────────────────────────────
    header_y = 22
    badge_txt = (category or "INTELLIGENCE").upper()
    bw = len(badge_txt) * 9 + 20
    draw.rounded_rectangle([(28, header_y), (28 + bw, header_y + 22)],
                            radius=4, fill=(55, 35, 18), outline=ACCENT_COLOR, width=1)
    draw.text((28 + 10, header_y + 4), badge_txt, font=f_cap, fill=ACCENT_COLOR)

    if source_label:
        draw.text((W - 28, header_y + 4), source_label, font=f_cap,
                  fill=TEXT_SECONDARY, anchor="ra")

    # ── Card title ──────────────────────────────────────────────────────────
    card_title = (card_data.get("title") or signal_title or "Alpha Intelligence Card")
    wrapped_title = _wrap_text(card_title, max_units=54)
    draw.text((28, header_y + 36), wrapped_title, font=f_title, fill=TEXT_PRIMARY)

    # Divider beneath title
    title_lines = wrapped_title.count("\n") + 1
    divider_y = header_y + 36 + title_lines * 40 + 10
    draw.line([(28, divider_y), (W - 28, divider_y)], fill=BORDER_COLOR, width=1)

    # ── Metrics grid ────────────────────────────────────────────────────────
    metrics: List[Any] = card_data.get("metrics") or []
    if not metrics:
        draw.text((W // 2, H // 2), "No metrics — run AI synthesis first",
                  font=f_label, fill=TEXT_SECONDARY, anchor="mm")
    else:
        cols      = 2 if len(metrics) > 2 else min(len(metrics), 4)
        rows      = math.ceil(len(metrics) / cols)
        g_top     = divider_y + 18
        g_bottom  = H - 48
        g_left    = 28
        g_right   = W - 28
        cell_w    = (g_right - g_left) // cols
        cell_h    = (g_bottom - g_top) // max(rows, 1)

        for i, m in enumerate(metrics[:8]):
            row = i // cols
            col = i % cols
            x0  = g_left + col * cell_w + 6
            y0  = g_top  + row * cell_h + 6
            x1  = x0 + cell_w - 12
            y1  = y0 + cell_h - 12

            m_dict = m if isinstance(m, dict) else {}
            sent = m_dict.get("sentiment", "neutral")
            label = str(m_dict.get("label", "")).upper()
            val = str(m_dict.get("value", ""))

            if sent == "positive":
                bc, dc, bg = POS_COLOR, POS_COLOR, (18, 38, 20)
            elif sent == "negative":
                bc, dc, bg = NEG_COLOR, NEG_COLOR, (38, 16, 16)
            else:
                bc, dc, bg = BORDER_COLOR, NEU_COLOR, PANEL_COLOR

            draw.rounded_rectangle([(x0, y0), (x1, y1)],
                                   radius=8, fill=bg, outline=bc, width=1)
            draw.ellipse([(x0+12, y0+14), (x0+12+DOT_SIZE, y0+14+DOT_SIZE)], fill=dc)
            draw.text((x0+12+DOT_SIZE+8, y0+14),
                      label, font=f_label, fill=TEXT_SECONDARY)
            draw.text((x0+12, y0+42),
                      _wrap_text(val, max_units=36),
                      font=f_value, fill=TEXT_PRIMARY)

    # ── Bottom brand bar ────────────────────────────────────────────────────
    draw.rectangle([(0, H - 42), (W, H)], fill=(20, 20, 26))
    draw.line([(0, H - 42), (W, H - 42)], fill=BORDER_COLOR, width=1)
    draw.text((28, H - 21), "Alpha Studio  •  Powered by Gemini",
              font=f_brand, fill=TEXT_SECONDARY, anchor="lm")
    watermark = settings.X_HANDLE if (hasattr(settings, "X_HANDLE") and settings.X_HANDLE) else "alpha-studio.io"
    draw.text((W - 28, H - 21), watermark,
              font=f_brand, fill=ACCENT_COLOR, anchor="rm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()
