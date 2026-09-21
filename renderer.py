"""Render a palace-inspired five-element circulation chart as a local PNG."""

from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

try:
    from .engine import DivinationResult, yin_yang_summary
    from .element_icons import load_icons
except ImportError:  # pragma: no cover - direct local execution
    from engine import DivinationResult, yin_yang_summary
    from element_icons import load_icons


WIDTH = 1440
HEIGHT = 1900
PAPER = "#F3E7CF"
PAPER_LIGHT = "#FBF5E8"
INK = "#241D18"
MUTED = "#736556"
PALACE_RED = "#7E251E"
IMPERIAL_GOLD = "#B88933"
JADE = "#315E4B"

ELEMENT_STYLE = {
    "水": {"fill": "#234E70", "line": "#9FC7D9", "text": "#FFFFFF", "pattern": "wave"},
    "火": {"fill": "#A9362A", "line": "#F0B09D", "text": "#FFFFFF", "pattern": "flame"},
    "木": {"fill": "#3F684D", "line": "#A7C39D", "text": "#FFFFFF", "pattern": "leaf"},
    "金": {"fill": "#C49A42", "line": "#F2D994", "text": "#241D18", "pattern": "coin"},
    "土": {"fill": "#855B43", "line": "#D7B49A", "text": "#FFFFFF", "pattern": "mountain"},
}

RELATION_STYLE = {
    "相生": ("#315E4B", False),
    "同气": ("#B88933", False),
    "逆生泄气": ("#65727E", True),
    "逆生不接": ("#65727E", True),
    "我克耗气": ("#B06B2F", True),
    "受克阻断": ("#9B2F28", True),
}

BUNDLED_FONT_PATH = (
    Path(__file__).resolve().parent
    / "assets"
    / "fonts"
    / "NotoSansCJKsc-Regular.otf"
)


class ChartRenderError(RuntimeError):
    """Raised when a chart cannot be rendered."""


class WuxingChartRenderer:
    """Draw a deterministic chart; only the supplied symbolism text is model-authored."""

    def __init__(self, font_path: str | Path | None = None):
        custom = Path(font_path).expanduser() if font_path else None
        self._font_path = custom if custom and custom.is_file() else self._find_font()
        try:
            self._icons = load_icons()
        except (OSError, ValueError):
            # A missing optional sprite must not break the chart or its verdict.
            self._icons = {}

    def render(
        self,
        result: DivinationResult,
        *,
        question: str,
        matter_type: str,
        symbolic_meanings: Sequence[str],
        symbolic_summary: str,
        symbolism_source: str = "当前会话模型",
        output_path: str | Path | None = None,
    ) -> Path:
        meanings = [self._clean(value)[:28] for value in symbolic_meanings]
        if len(meanings) != 5 or any(not value for value in meanings):
            raise ChartRenderError("象意必须恰好包含五条非空内容")

        fonts = {
            "title": self._font(58),
            "subtitle": self._font(27),
            "section": self._font(32),
            "body": self._font(27),
            "small": self._font(22),
            "tiny": self._font(18),
            "digit": self._font(70),
            "element": self._font(32),
            "verdict": self._font(46),
        }
        canvas = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
        draw = ImageDraw.Draw(canvas)
        self._draw_background(draw)
        self._draw_header(draw, result, fonts)
        self._draw_meta(draw, question, matter_type, symbolism_source, fonts)
        self._draw_cycle(canvas, draw, result, meanings, fonts)
        self._draw_interpretation(draw, result, symbolic_summary, fonts)

        path = self._output_path(output_path)
        try:
            canvas.save(path, "PNG", optimize=True)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise ChartRenderError(f"保存五行流转图失败：{exc}") from exc
        return path

    @staticmethod
    def _draw_background(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((0, 0, WIDTH, HEIGHT), fill=PAPER)
        for y in range(0, HEIGHT, 64):
            color = "#E9D8B8" if (y // 64) % 2 == 0 else "#EDDFC5"
            draw.line((0, y, WIDTH, y), fill=color, width=1)
        draw.rectangle((20, 20, WIDTH - 20, HEIGHT - 20), outline=IMPERIAL_GOLD, width=3)
        draw.rectangle((31, 31, WIDTH - 31, HEIGHT - 31), outline="#D2B574", width=1)

    def _draw_header(self, draw, result, fonts) -> None:
        draw.rounded_rectangle((45, 42, WIDTH - 45, 208), radius=28, fill=PALACE_RED)
        draw.text((78, 70), "五行数字卦 · 元素流转图", font=fonts["title"], fill="#FFF6DE")
        subtitle = "水火木金土 · 专属元素徽记" if self._icons else "五行纹样 · 元素标志暂不可用"
        draw.text((82, 151), subtitle, font=fonts["small"], fill="#F2D48C")
        draw.text(
            (WIDTH - 80, 78),
            f"根气 · {result.root}",
            font=fonts["section"],
            fill="#F2D48C",
            anchor="ra",
        )
        verdict_color = "#F3D780" if result.verdict == "成" else "#FFF6DE"
        draw.text(
            (WIDTH - 80, 133),
            f"断 · {result.verdict}",
            font=fonts["verdict"],
            fill=verdict_color,
            anchor="ra",
        )

    def _draw_meta(self, draw, question, matter_type, source, fonts) -> None:
        draw.rounded_rectangle(
            (64, 234, WIDTH - 64, 390),
            radius=22,
            fill=PAPER_LIGHT,
            outline="#CDAF74",
            width=2,
        )
        draw.text((90, 258), "所问", font=fonts["section"], fill=PALACE_RED)
        question_lines = self._wrap(draw, self._clean(question) or "未填写", fonts["body"], 1010)
        for index, line in enumerate(question_lines[:2]):
            draw.text((200, 260 + index * 38), line, font=fonts["body"], fill=INK)
        draw.rounded_rectangle((90, 330, 340, 374), radius=18, fill=JADE)
        draw.text((215, 352), f"事类 · {self._clean(matter_type)[:10] or '综合'}", font=fonts["small"], fill="#FFFFFF", anchor="mm")
        draw.text((WIDTH - 90, 352), f"象意来源 · {self._clean(source)[:18]}", font=fonts["small"], fill=MUTED, anchor="rm")

    def _draw_cycle(self, canvas, draw, result, meanings, fonts) -> None:
        panel = (64, 418, WIDTH - 64, 1332)
        draw.rounded_rectangle(panel, radius=26, fill="#F8EFDC", outline="#CDAF74", width=2)
        draw.text((92, 444), "五宫流转", font=fonts["section"], fill=PALACE_RED)
        draw.text((WIDTH - 92, 454), "顺时针读取 · 末位回到首位", font=fonts["small"], fill=MUTED, anchor="ra")

        centers = [(720, 590), (1080, 785), (940, 1120), (500, 1120), (360, 785)]
        radius = 128
        for index, transition in enumerate(result.transitions):
            start = centers[index]
            end = centers[(index + 1) % 5]
            self._draw_relation(draw, start, end, radius, transition.name, fonts)

        yin_yang, _ = yin_yang_summary(result.digits)
        for index, center in enumerate(centers):
            self._draw_node(
                canvas,
                draw,
                center,
                radius,
                position=index + 1,
                digit=result.digits[index],
                yin_yang=yin_yang[index],
                element=result.elements[index],
                meaning=meanings[index],
                is_root=result.elements[index] == result.root,
                fonts=fonts,
            )

        legend_y = 1282
        labels = (("相生", "#315E4B"), ("同气", "#B88933"), ("耗/逆", "#B06B2F"), ("受克", "#9B2F28"))
        for index, (label, color) in enumerate(labels):
            x = 480 + index * 170
            draw.line((x, legend_y, x + 44, legend_y), fill=color, width=8)
            draw.text((x + 56, legend_y), label, font=fonts["tiny"], fill=INK, anchor="lm")

    def _draw_relation(self, draw, start, end, radius, relation, fonts) -> None:
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = math.hypot(dx, dy)
        ux, uy = dx / distance, dy / distance
        a = (start[0] + ux * (radius + 8), start[1] + uy * (radius + 8))
        b = (end[0] - ux * (radius + 16), end[1] - uy * (radius + 16))
        color, dashed = RELATION_STYLE.get(relation, (MUTED, True))
        if dashed:
            self._dashed_line(draw, a, b, color, 10)
        else:
            draw.line((*a, *b), fill=color, width=10)
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        wing = 18
        back = 28
        p1 = (b[0] - back * math.cos(angle) + wing * math.sin(angle), b[1] - back * math.sin(angle) - wing * math.cos(angle))
        p2 = (b[0] - back * math.cos(angle) - wing * math.sin(angle), b[1] - back * math.sin(angle) + wing * math.cos(angle))
        draw.polygon((b, p1, p2), fill=color)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        label = "逆生" if relation in {"逆生泄气", "逆生不接"} else relation.replace("耗气", "").replace("阻断", "")
        bbox = draw.textbbox((0, 0), label, font=fonts["tiny"])
        width = bbox[2] - bbox[0] + 22
        height = bbox[3] - bbox[1] + 14
        draw.rounded_rectangle((mx - width / 2, my - height / 2, mx + width / 2, my + height / 2), radius=10, fill=PAPER_LIGHT, outline=color, width=2)
        draw.text((mx, my), label, font=fonts["tiny"], fill=color, anchor="mm")

    def _draw_node(self, canvas, draw, center, radius, *, position, digit, yin_yang, element, meaning, is_root, fonts) -> None:
        cx, cy = center
        style = ELEMENT_STYLE[element]
        outer = 10 if is_root else 5
        draw.ellipse((cx - radius - outer, cy - radius - outer, cx + radius + outer, cy + radius + outer), fill="#E9D29A" if is_root else "#D8C18A", outline=PALACE_RED if is_root else IMPERIAL_GOLD, width=4)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=style["fill"])
        text_color = style["text"]
        draw.text((cx, cy - 100), f"第{position}数 · {yin_yang}", font=fonts["tiny"], fill=text_color, anchor="ma")
        icon = self._icons.get(element)
        if icon is not None:
            # Keep the generated icon's white background inside a white medallion.
            # Digits and symbolism occupy separate areas for clear reading.
            ix, iy = cx - 51, cy - 24
            draw.ellipse((ix - 49, iy - 49, ix + 49, iy + 49), fill="#FFFFFF")
            canvas.paste(icon, (ix - icon.width // 2, iy - icon.height // 2))
            draw.text((cx + 47, cy - 27), digit, font=fonts["digit"], fill=text_color, anchor="mm")
        else:
            self._draw_pattern(draw, center, radius, style["pattern"], style["line"])
            draw.text((cx, cy - 72), digit, font=fonts["digit"], fill=text_color, anchor="ma")
        root_suffix = " · 根" if is_root else ""
        draw.text((cx, cy + 22), f"{element}{root_suffix}", font=fonts["element"], fill=text_color, anchor="ma")
        lines = self._wrap(draw, meaning, fonts["tiny"], 188)
        for index, line in enumerate(lines[:2]):
            draw.text((cx, cy + 66 + index * 24), line, font=fonts["tiny"], fill=text_color, anchor="ma")

    @staticmethod
    def _draw_pattern(draw, center, radius, pattern, color) -> None:
        cx, cy = center
        if pattern == "wave":
            for offset in (-62, -30, 2, 34, 66):
                draw.arc((cx - 84, cy + offset - 18, cx, cy + offset + 18), 190, 350, fill=color, width=3)
                draw.arc((cx, cy + offset - 18, cx + 84, cy + offset + 18), 190, 350, fill=color, width=3)
        elif pattern == "flame":
            for angle in range(0, 360, 30):
                rad = math.radians(angle)
                draw.line((cx + 72 * math.cos(rad), cy + 72 * math.sin(rad), cx + 112 * math.cos(rad), cy + 112 * math.sin(rad)), fill=color, width=3)
        elif pattern == "leaf":
            draw.line((cx - 88, cy + 76, cx + 80, cy - 84), fill=color, width=4)
            for offset in (-52, -14, 24, 62):
                x = cx + offset
                y = cy - offset
                draw.ellipse((x - 28, y - 12, x + 2, y + 12), outline=color, width=3)
        elif pattern == "coin":
            for ring in (56, 86, 112):
                draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=color, width=3)
            draw.rectangle((cx - 24, cy - 24, cx + 24, cy + 24), outline=color, width=3)
        else:
            for offset in (-66, -22, 22, 66):
                draw.line((cx - 105, cy + offset, cx - 52, cy + offset - 42, cx, cy + offset, cx + 52, cy + offset - 42, cx + 105, cy + offset), fill=color, width=3)

    def _draw_interpretation(self, draw, result, summary, fonts) -> None:
        draw.rounded_rectangle((64, 1360, WIDTH - 64, 1808), radius=26, fill=PAPER_LIGHT, outline="#CDAF74", width=2)
        draw.text((92, 1387), "总象与断语", font=fonts["section"], fill=PALACE_RED)
        summary_lines = self._wrap(draw, self._clean(summary) or "象意未生成。", fonts["body"], WIDTH - 220)
        y = 1440
        for line in summary_lines[:3]:
            draw.text((92, y), line, font=fonts["body"], fill=INK)
            y += 40
        y += 10
        draw.line((92, y, WIDTH - 92, y), fill="#D4BC8B", width=2)
        y += 28
        relation_lines = [f"{index + 1}→{(index + 1) % 5 + 1}  {item.source}→{item.target} · {item.name}" for index, item in enumerate(result.transitions)]
        for index, line in enumerate(relation_lines):
            column = index % 2
            row = index // 2
            draw.text((92 + column * 630, y + row * 36), line, font=fonts["small"], fill=MUTED)
        verdict_y = y + 126
        verdict_fill = "#E8F0E8" if result.verdict == "成" else "#F4E5DE"
        draw.rounded_rectangle((92, verdict_y, WIDTH - 92, verdict_y + 92), radius=20, fill=verdict_fill)
        draw.text((116, verdict_y + 46), f"断语 · {result.phrase}", font=fonts["body"], fill=PALACE_RED, anchor="lm")
        draw.text((92, 1825), "水 · 浪纹    火 · 烈焰    木 · 枝叶    金 · 金锋    土 · 山岩", font=fonts["small"], fill=MUTED)
        draw.text((WIDTH - 92, 1842), "wuxing_num", font=fonts["small"], fill=MUTED, anchor="ra")

    @staticmethod
    def _dashed_line(draw, start, end, color, width) -> None:
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = math.hypot(dx, dy)
        if distance <= 0:
            return
        ux, uy = dx / distance, dy / distance
        step, dash = 24, 14
        cursor = 0.0
        while cursor < distance:
            stop = min(cursor + dash, distance)
            draw.line((start[0] + ux * cursor, start[1] + uy * cursor, start[0] + ux * stop, start[1] + uy * stop), fill=color, width=width)
            cursor += step

    @staticmethod
    def _wrap(draw, text, font, max_width) -> list[str]:
        lines: list[str] = []
        for paragraph in (text or "").splitlines() or [""]:
            current = ""
            for char in paragraph:
                candidate = current + char
                if current and draw.textlength(candidate, font=font) > max_width:
                    lines.append(current)
                    current = char
                else:
                    current = candidate
            lines.append(current)
        return lines or [""]

    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self._font_path), size=size)

    @staticmethod
    def _find_font() -> Path:
        candidates = (
            BUNDLED_FONT_PATH,
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/simhei.ttf"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
            Path("/System/Library/Fonts/PingFang.ttc"),
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ChartRenderError("未找到可用于五行流转图的中文字体")

    @staticmethod
    def _output_path(output_path: str | Path | None) -> Path:
        if output_path is not None:
            path = Path(output_path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        fd, raw_path = tempfile.mkstemp(prefix="wuxing_num_", suffix=".png")
        os.close(fd)
        return Path(raw_path).resolve()

    @staticmethod
    def _clean(value: str) -> str:
        return " ".join(str(value or "").replace("\x00", "").split())
