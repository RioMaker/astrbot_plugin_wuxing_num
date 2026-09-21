"""Modern five-element chart with translucent emblem watermarks."""

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
except ImportError:
    from engine import DivinationResult, yin_yang_summary
    from element_icons import load_icons

WIDTH, HEIGHT = 1440, 1900
BACKGROUND, INK, MUTED, BORDER = "#F3F5F9", "#192438", "#647187", "#E2E8F0"
WATERMARK_OPACITY = 0.13
CENTERS = [(720, 634), (1090, 840), (954, 1150), (486, 1150), (350, 840)]
NODE_HALF_WIDTH, NODE_HALF_HEIGHT = 138, 124
ELEMENT_STYLE = {
    "水": {"fill": "#EDF6FE", "accent": "#2275AC", "pattern": "wave"},
    "火": {"fill": "#FEF1EE", "accent": "#BD503D", "pattern": "flame"},
    "木": {"fill": "#ECF7F1", "accent": "#287755", "pattern": "leaf"},
    "金": {"fill": "#FBF6E7", "accent": "#946A18", "pattern": "metal"},
    "土": {"fill": "#F6EFEA", "accent": "#96613E", "pattern": "mountain"},
}
RELATION_STYLE = {
    "相生": ("#288271", False), "同气": ("#AB8533", False),
    "逆生泄气": ("#75809B", True), "逆生不接": ("#75809B", True),
    "我克耗气": ("#AC7137", True), "受克阻断": ("#BB4D5C", True),
}
VERDICT_STYLE = {
    "成": ("#216D5B", "#EAF6F0"), "败": ("#A74650", "#FFF0F1"),
    "死卦": ("#5C608C", "#F0F0FA"),
}
BUNDLED_FONT_PATH = Path(__file__).resolve().parent / "assets/fonts/NotoSansCJKsc-Regular.otf"


class ChartRenderError(RuntimeError):
    """Raised when a chart cannot be rendered."""


class WuxingChartRenderer:
    def __init__(self, font_path: str | Path | None = None):
        custom = Path(font_path).expanduser() if font_path else None
        self._font_path = custom if custom and custom.is_file() else self._find_font()
        try:
            self._icons = load_icons()
        except (OSError, ValueError):
            self._icons = {}

    def render(
        self, result: DivinationResult, *, question: str, matter_type: str,
        symbolic_meanings: Sequence[str], symbolic_summary: str,
        symbolism_source: str = "当前会话模型", output_path: str | Path | None = None,
    ) -> Path:
        meanings = [self._clean(value)[:28] for value in symbolic_meanings]
        if len(meanings) != 5 or any(not value for value in meanings):
            raise ChartRenderError("象意必须恰好包含五条非空内容")
        f = {name: self._font(size) for name, size in {
            "title": 62, "section": 30, "body": 26, "small": 22,
            "tiny": 18, "digit": 76, "element": 36, "verdict": 42,
        }.items()}
        canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        draw = ImageDraw.Draw(canvas)
        self._header(draw, result, f)
        self._question(draw, question, matter_type, symbolism_source, f)
        self._cycle(canvas, draw, result, meanings, f)
        self._interpretation(draw, result, symbolic_summary, f)
        draw.text((64, 1840), "WUXING  /  五行数字卦", font=f["tiny"], fill=MUTED, anchor="lt")
        draw.text((1376, 1840), "水 · 火 · 木 · 金 · 土", font=f["tiny"], fill=MUTED, anchor="rt")
        path = self._output_path(output_path)
        try:
            canvas.save(path, "PNG", optimize=True)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise ChartRenderError(f"保存五行流转图失败：{exc}") from exc
        return path

    @staticmethod
    def _panel(draw, box, *, fill="#FFFFFF", radius=28):
        x1, y1, x2, y2 = box
        draw.rounded_rectangle((x1, y1 + 5, x2, y2 + 5), radius=radius, fill="#E9EDF4")
        draw.rounded_rectangle(box, radius=radius, fill=fill)

    def _header(self, draw, result, f):
        draw.text((64, 48), "WUXING  /  ELEMENT FLOW", font=f["tiny"], fill=MUTED, anchor="lt")
        draw.text((60, 92), "五行流转", font=f["title"], fill=INK, anchor="lt")
        draw.text((65, 176), "由数见象，循气而行。", font=f["small"], fill=MUTED, anchor="lt")
        color, tint = VERDICT_STYLE[result.verdict]
        draw.rounded_rectangle((1120, 70, 1376, 201), radius=26, fill=tint)
        draw.text((1146, 93), "本次判定", font=f["tiny"], fill=color, anchor="lt")
        draw.text((1283, 158), result.verdict, font=f["verdict"], fill=color, anchor="mm")

    def _question(self, draw, question, matter_type, source, f):
        self._panel(draw, (64, 234, 1376, 400))
        draw.text((92, 260), "所问", font=f["small"], fill=MUTED, anchor="lt")
        lines, font = self._fit(draw, self._clean(question) or "未填写", 1120, 2, 28, 22)
        for i, line in enumerate(lines):
            draw.text((192, 257 + i * 35), line, font=font, fill=INK, anchor="lt")
        kind = self._clean(matter_type)[:10] or "综合"
        draw.text((92, 353), f"事类  {kind}", font=f["small"], fill=INK, anchor="lt")
        draw.text((1348, 355), f"象意 · {self._clean(source)[:18]}", font=f["tiny"], fill=MUTED, anchor="rt")

    def _cycle(self, canvas, draw, result, meanings, f):
        self._panel(draw, (64, 428, 1376, 1360))
        draw.text((92, 456), "01   五行流转", font=f["section"], fill=INK, anchor="lt")
        draw.text((1348, 464), "依数字顺序 · 顺时针闭环", font=f["tiny"], fill=MUTED, anchor="rt")
        for i, transition in enumerate(result.transitions):
            self._relation(draw, CENTERS[i], CENTERS[(i + 1) % 5], transition.name, f)
        yin_yang, _ = yin_yang_summary(result.digits)
        for i, center in enumerate(CENTERS):
            self._node(canvas, draw, center, i + 1, result.digits[i], yin_yang[i],
                       result.elements[i], meanings[i], result.elements[i] == result.root, f)
        draw.text((720, 868), "根气", font=f["small"], fill=MUTED, anchor="mm")
        draw.text((720, 920), result.root, font=f["verdict"], fill=ELEMENT_STYLE[result.root]["accent"], anchor="mm")
        yang = yin_yang.count("阳")
        draw.text((720, 970), f"阳 {yang}  /  阴 {5 - yang}", font=f["tiny"], fill=MUTED, anchor="mm")
        legend = [("相生", "相生"), ("同气", "同气"), ("逆生", "逆生泄气"),
                  ("我克", "我克耗气"), ("受克", "受克阻断")]
        for i, (label, key) in enumerate(legend):
            x, y = 358 + 158 * i, 1317
            color, dashed = RELATION_STYLE[key]
            if dashed:
                self._dashed_line(draw, (x, y), (x + 30, y), color, 4)
            else:
                draw.line((x, y, x + 30, y), fill=color, width=4)
            draw.text((x + 42, y), label, font=f["tiny"], fill=MUTED, anchor="lm")

    def _relation(self, draw, start, end, relation, f):
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = math.hypot(dx, dy)
        ux, uy = dx / distance, dy / distance
        reach = min(NODE_HALF_WIDTH / abs(ux) if ux else float("inf"),
                    NODE_HALF_HEIGHT / abs(uy) if uy else float("inf"))
        a = (start[0] + ux * (reach + 8), start[1] + uy * (reach + 8))
        b = (end[0] - ux * (reach + 10), end[1] - uy * (reach + 10))
        color, dashed = RELATION_STYLE.get(relation, (MUTED, True))
        if dashed:
            self._dashed_line(draw, a, b, color, 4)
        else:
            draw.line((*a, *b), fill=color, width=4)
        draw.polygon((b, (b[0] - 14 * ux - 7 * uy, b[1] - 14 * uy + 7 * ux),
                      (b[0] - 14 * ux + 7 * uy, b[1] - 14 * uy - 7 * ux)), fill=color)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        # Keep short arrows visible by placing labels inside the ring.
        mx, my = mx - 42 * uy, my + 42 * ux
        label = "逆生" if relation.startswith("逆生") else relation.replace("耗气", "").replace("阻断", "")
        draw.rounded_rectangle((mx - 34, my - 18, mx + 34, my + 18), radius=10, fill="#FFFFFF")
        draw.text((mx, my), label, font=f["tiny"], fill=color, anchor="mm")

    def _node(self, canvas, draw, center, position, digit, yin_yang, element, meaning, is_root, f):
        cx, cy = center
        style = ELEMENT_STYLE[element]
        box = (cx - NODE_HALF_WIDTH, cy - NODE_HALF_HEIGHT, cx + NODE_HALF_WIDTH, cy + NODE_HALF_HEIGHT)
        draw.rounded_rectangle(box, radius=28, fill=style["fill"],
                               outline=style["accent"] if is_root else BORDER, width=3 if is_root else 1)
        self._watermark(canvas, center, element)
        # All text is painted after the watermark, at full opacity.
        left = cx - 112
        draw.text((left, cy - 97), f"0{position}  /  {yin_yang}", font=f["tiny"], fill=MUTED, anchor="lt")
        if is_root:
            draw.rounded_rectangle((cx + 60, cy - 103, cx + 116, cy - 69), radius=10, fill=style["accent"])
            draw.text((cx + 88, cy - 86), "根气", font=self._font(16), fill="#FFFFFF", anchor="mm")
        draw.text((left - 2, cy - 64), digit, font=f["digit"], fill=INK, anchor="lt")
        draw.text((cx + 46, cy - 2), element, font=f["element"], fill=style["accent"], anchor="mm")
        lines, font = self._fit(draw, meaning, 224, 2, 21, 15)
        for i, line in enumerate(lines):
            draw.text((left, cy + 62 + 25 * i), line, font=font, fill=INK, anchor="lt")

    def _watermark(self, canvas, center, element):
        icon = self._icons.get(element)
        if icon is None:
            return
        icon = icon.copy()
        icon.thumbnail((196, 196), Image.Resampling.LANCZOS)
        layer = Image.new("RGBA", icon.size, ELEMENT_STYLE[element]["accent"])
        layer.putalpha(icon.getchannel("A").point(lambda value: round(value * WATERMARK_OPACITY)))
        cx, cy = center
        canvas.paste(layer, (cx + 12 - layer.width // 2, cy - 4 - layer.height // 2), layer)

    def _interpretation(self, draw, result, summary, f):
        self._panel(draw, (64, 1388, 1376, 1808))
        draw.text((92, 1418), "02   象意与断语", font=f["section"], fill=INK, anchor="lt")
        lines, font = self._fit(draw, self._clean(summary) or "象意未生成。", 1252, 3, 26, 22)
        for i, line in enumerate(lines):
            draw.text((92, 1470 + 34 * i), line, font=font, fill=INK, anchor="lt")
        # Fixed reserved sections keep the verdict visible even with long text.
        for i, item in enumerate(result.transitions):
            x, y = 92 + (i % 3) * 420, 1590 + (i // 3) * 34
            color = RELATION_STYLE.get(item.name, (MUTED, True))[0]
            draw.text((x, y), f"{i + 1}→{(i + 1) % 5 + 1}  {item.source}→{item.target} · {item.name}",
                      font=f["tiny"], fill=color, anchor="lt")
        color, tint = VERDICT_STYLE[result.verdict]
        draw.rounded_rectangle((92, 1677, 1348, 1780), radius=20, fill=tint)
        draw.text((118, 1700), "断语", font=f["tiny"], fill=color, anchor="lt")
        lines, font = self._fit(draw, result.phrase, 1110, 2, 26, 22)
        for i, line in enumerate(lines):
            draw.text((214, 1698 + i * 33), line, font=font, fill=color, anchor="lt")

    @staticmethod
    def _dashed_line(draw, start, end, color, width):
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = math.hypot(dx, dy)
        if distance <= 0:
            return
        ux, uy = dx / distance, dy / distance
        cursor = 0.0
        while cursor < distance:
            stop = min(cursor + 9, distance)
            draw.line((start[0] + ux * cursor, start[1] + uy * cursor,
                       start[0] + ux * stop, start[1] + uy * stop), fill=color, width=width)
            cursor += 16

    @staticmethod
    def _wrap(draw, text, font, max_width):
        lines, current = [], ""
        for char in text:
            if current and draw.textlength(current + char, font=font) > max_width:
                if char in "，。；：！？、）】”" and len(current) > 1:
                    last, current = current[-1], current[:-1]
                    lines.append(current)
                    current = last + char
                else:
                    lines.append(current)
                    current = char
            else:
                current += char
        lines.append(current)
        return lines

    def _fit(self, draw, text, width, max_lines, size, minimum):
        for font_size in range(size, minimum - 1, -1):
            font = self._font(font_size)
            lines = self._wrap(draw, text, font, width)
            if len(lines) <= max_lines:
                return lines, font
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last + "…"
        return lines, font

    def _font(self, size):
        return ImageFont.truetype(str(self._font_path), size=size)

    @staticmethod
    def _find_font():
        for candidate in (BUNDLED_FONT_PATH, Path("C:/Windows/Fonts/msyh.ttc"),
                          Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                          Path("/System/Library/Fonts/PingFang.ttc")):
            if candidate.is_file():
                return candidate
        raise ChartRenderError("未找到可用于五行流转图的中文字体")

    @staticmethod
    def _output_path(output_path):
        if output_path is not None:
            path = Path(output_path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        fd, raw_path = tempfile.mkstemp(prefix="wuxing_num_", suffix=".png")
        os.close(fd)
        return Path(raw_path).resolve()

    @staticmethod
    def _clean(value):
        return " ".join(str(value or "").replace("\x00", "").split())
