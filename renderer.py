"""Deterministic ink-dark 五行数字卦 chart; interpretation stays in the engine."""

from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    from .element_icons import load_icons
    from .engine import DivinationResult, yin_yang_summary
    from .visual_effects import glass_node, luminous_path, soft_halo
except ImportError:
    from element_icons import load_icons
    from engine import DivinationResult, yin_yang_summary
    from visual_effects import glass_node, luminous_path, soft_halo

WIDTH, HEIGHT = 1440, 1900
BACKGROUND, INK, MUTED, BORDER = "#091219", "#F0EBDD", "#ABB5B8", "#30434B"
GOLD = "#DCC49A"
TITLE = "五行数字卦"
BACKGROUND_PATH = (
    Path(__file__).resolve().parent / "assets/backgrounds/ink_mountains_v1.png"
)
ELEMENT_EMISSION = {
    "水": "#39B6F4",
    "木": "#4BE4AA",
    "火": "#FF753C",
    "金": "#FFE0A1",
    "土": "#EAB05A",
}
WATERMARK_OPACITY = 0.13
ORBIT_CENTER, ORBIT_RADIUS, NODE_RADIUS = (720, 890), 465, 164
ANGLES = tuple(-90 + i * 72 for i in range(5))


def orbit_point(angle, radius=ORBIT_RADIUS):
    radians = math.radians(angle)
    return (
        ORBIT_CENTER[0] + radius * math.cos(radians),
        ORBIT_CENTER[1] + radius * math.sin(radians),
    )


CENTERS = tuple(orbit_point(angle) for angle in ANGLES)
ELEMENT_STYLE = {
    "水": {"fill": "#0E2533", "accent": "#8CCDE2", "pattern": "wave"},
    "火": {"fill": "#30201F", "accent": "#E6A28A", "pattern": "flame"},
    "木": {"fill": "#142B27", "accent": "#A0D1AC", "pattern": "leaf"},
    "金": {"fill": "#282821", "accent": "#E3D0A4", "pattern": "metal"},
    "土": {"fill": "#2A241D", "accent": "#D4B486", "pattern": "mountain"},
}
RELATION_STYLE = {
    "相生": ("#A4D7C6", False),
    "同气": ("#DCC49A", False),
    "逆生泄气": ("#A7B7D1", True),
    "逆生不接": ("#A7B7D1", True),
    "我克耗气": ("#DDB488", True),
    "受克阻断": ("#E69C9F", True),
}
VERDICT_STYLE = {
    "成": (GOLD, "#142722"),
    "败": ("#E6A1A0", "#2C1E24"),
    "死卦": ("#B5BBD3", "#1D2230"),
}
BUNDLED_FONT_PATH = (
    Path(__file__).resolve().parent / "assets/fonts/NotoSansCJKsc-Regular.otf"
)


class ChartRenderError(RuntimeError):
    """Raised when a chart cannot be rendered."""


class WuxingChartRenderer:
    def __init__(self, font_path: str | Path | None = None):
        custom = Path(font_path).expanduser() if font_path else None
        self._font_path = custom if custom and custom.is_file() else self._find_font()
        self._fonts = {}
        try:
            self._icons = load_icons()
        except (OSError, ValueError):
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
        meanings = [self._clean(value) for value in symbolic_meanings]
        if len(meanings) != 5 or any(not value for value in meanings):
            raise ChartRenderError("象意必须恰好包含五条非空内容")
        f = {
            name: self._font(size)
            for name, size in {
                "title": 78,
                "section": 30,
                "body": 28,
                "small": 24,
                "tiny": 20,
                "digit": 110,
                "element": 32,
                "verdict": 118,
            }.items()
        }
        canvas = self._background()
        draw = ImageDraw.Draw(canvas)
        self._header(draw, result, f)
        self._question(draw, question, matter_type, f)
        self._cycle(canvas, draw, result, meanings, f)
        soft_halo(
            canvas,
            (204, 1600),
            VERDICT_STYLE[result.verdict][0],
            radius=70,
            strength=0.22 if result.is_dead else 0.38,
        )
        self._interpretation(draw, result, symbolic_summary, f)
        draw.text(
            (64, 1854), "WUXING  /  五行数字卦", font=f["tiny"], fill=MUTED, anchor="lt"
        )
        source = self._clean(symbolism_source) or "未标注"
        lines, font = self._fit(draw, f"象意 · {source}", 660, 1, 20, 18)
        draw.text((1376, 1854), lines[0], font=font, fill=MUTED, anchor="rt")
        path = self._output_path(output_path)
        try:
            canvas.save(path, "PNG", optimize=True)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise ChartRenderError(f"保存五行流转图失败：{exc}") from exc
        return path

    @staticmethod
    def _background():
        try:
            with Image.open(BACKGROUND_PATH) as source:
                light = ImageOps.fit(
                    source.convert("RGB"),
                    (WIDTH, HEIGHT),
                    method=Image.Resampling.LANCZOS,
                )
        except (OSError, ValueError):
            light = WuxingChartRenderer._fallback_background()
        # A soft scrim preserves paragraph contrast without a visible panel edge.
        scrim = Image.new("L", (1, HEIGHT))
        scrim.putdata(
            [round(120 * max(0, min(1, (y - 1430) / 180))) for y in range(HEIGHT)]
        )
        light.paste(
            Image.new("RGB", light.size, BACKGROUND), (0, 0), scrim.resize(light.size)
        )
        draw = ImageDraw.Draw(light)
        for x in (40, WIDTH - 40):
            draw.line((x, 280, x, 1390), fill="#455058", width=1)
            for y in (285, 1370):
                draw.polygon(
                    ((x, y - 5), (x + 4, y), (x, y + 5), (x - 4, y)), fill="#AB9472"
                )
        return light

    @staticmethod
    def _fallback_background():
        # All ornament is local and deterministic, never baked into a screenshot
        # containing example numbers or text. Work small for the soft light field.
        light = Image.new("RGB", (360, 475), BACKGROUND)
        glow = ImageDraw.Draw(light)
        glow.ellipse((35, 30, 320, 345), fill="#172D35")
        light = light.filter(ImageFilter.GaussianBlur(65)).resize((WIDTH, HEIGHT))
        draw = ImageDraw.Draw(light)
        # Fine, layered silhouettes stay at the periphery of the data diagram.
        for depth, color in enumerate(("#15232C", "#101E26", "#0C181F")):
            ridge = []
            for x in range(0, WIDTH + 1, 4):
                edge = abs(x - WIDTH / 2) / (WIDTH / 2)
                crags = (
                    abs(math.sin(x / 113 + depth)) * 100
                    + abs(math.sin(x / 43 + depth * 2)) * 48
                    + abs(math.sin(x / 17 + depth)) * 16
                )
                y = 1445 - edge**1.6 * (230 + crags) + depth * 46
                ridge.append((x, min(1450, y)))
            draw.polygon([*ridge, (WIDTH, 1450), (0, 1450)], fill=color)
        return light

    def _header(self, draw, result, f):
        draw.text((64, 62), "W U X I N G", font=f["tiny"], fill=MUTED, anchor="lt")
        draw.line((64, 111, 252, 111), fill="#827A66", width=1)
        draw.text((720, 92), TITLE, font=f["title"], fill=GOLD, anchor="mm")
        draw.text(
            (1376, 62),
            f"根气 · {result.root}",
            font=f["small"],
            fill=MUTED,
            anchor="rt",
        )
        draw.text(
            (1376, 108),
            " / ".join(result.digits),
            font=f["tiny"],
            fill=MUTED,
            anchor="rt",
        )

    def _question(self, draw, question, matter_type, f):
        lines, font = self._fit(
            draw, self._clean(question) or "未填写", 1220, 2, 36, 26
        )
        for i, line in enumerate(lines):
            draw.text((720, 175 + i * 44), line, font=font, fill=INK, anchor="mt")
        kind, kind_font = self._fit(
            draw, self._clean(matter_type) or "综合", 470, 1, 22, 18
        )
        draw.text(
            (64, 248), f"事类  {kind[0]}", font=kind_font, fill=MUTED, anchor="lt"
        )
        draw.text(
            (1376, 248),
            "按输入顺序 · 顺时针流转",
            font=f["tiny"],
            fill=MUTED,
            anchor="rt",
        )

    def _cycle(self, canvas, draw, result, meanings, f):
        if not result.is_dead:
            soft_halo(
                canvas,
                (720, 885),
                ELEMENT_EMISSION[result.root],
                radius=90,
                strength=0.19,
            )
        for radius in (285, 300, ORBIT_RADIUS):
            cx, cy = ORBIT_CENTER
            box = (cx - radius, cy - radius, cx + radius, cy + radius)
            if result.is_dead and radius < ORBIT_RADIUS:
                for start in range(0, 360, 40):
                    draw.arc(box, start, start + 20, fill=BORDER, width=1)
            else:
                draw.arc(
                    box, 4, 176, fill="#615D4C" if radius == 285 else BORDER, width=1
                )
                draw.arc(
                    box, 184, 356, fill="#615D4C" if radius == 285 else BORDER, width=1
                )
        for angle in range(0, 360, 5):
            x, y = orbit_point(angle, 355)
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill="#73664E")
        for i, transition in enumerate(result.transitions):
            self._relation(canvas, draw, i, transition, result, f)
        yin_yang, _ = yin_yang_summary(result.digits)
        for i, center in enumerate(CENTERS):
            self._node(
                canvas,
                draw,
                center,
                i + 1,
                result.digits[i],
                yin_yang[i],
                result.elements[i],
                meanings[i],
                result.elements[i] == result.root,
                f,
                energy=0.2 if result.is_dead else 1.0,
            )
        draw.text((720, 790), "所 问 根 气", font=f["small"], fill=INK, anchor="mm")
        root_color = MUTED if result.is_dead else ELEMENT_STYLE[result.root]["accent"]
        draw.text(
            (720, 885), result.root, font=self._font(126), fill=root_color, anchor="mm"
        )
        draw.text(
            (720, 992),
            self._root_caption(result),
            font=f["small"],
            fill=INK,
            anchor="mm",
        )
        yang = yin_yang.count("阳")
        draw.text(
            (720, 1042),
            f"阳 {yang}  /  阴 {5 - yang}",
            font=f["tiny"],
            fill=MUTED,
            anchor="mm",
        )
        draw.line((670, 1102, 770, 1102), fill="#827A66", width=1)
        draw.polygon(((720, 1096), (726, 1102), (720, 1108), (714, 1102)), fill=GOLD)

    @staticmethod
    def _root_caption(result):
        if result.is_dead:
            return result.dead_reason or "卦象未立"
        return "根气可通 · 成局" if result.verdict == "成" else "根气可辨 · 成局不足"

    @staticmethod
    def _arc_points(index):
        # Circle/chord intersection leaves a real gap around every node.
        gap = math.degrees(2 * math.asin((NODE_RADIUS + 16) / (2 * ORBIT_RADIUS)))
        start, stop = ANGLES[index] + gap, ANGLES[index] + 72 - gap
        return [orbit_point(start + (stop - start) * step / 80) for step in range(81)]

    def _relation(self, canvas, draw, index, transition, result, f):
        points = self._arc_points(index)
        color, dashed = RELATION_STYLE.get(transition.name, (MUTED, True))
        if transition.name == "相生":
            color = ELEMENT_STYLE[transition.source]["accent"]
        # Only true flowing edges emit light; blocked paths remain visibly dashed.
        luminous_path(
            canvas,
            points,
            color,
            width=4.5,
            dashed=dashed,
            energy=1.0 if transition.flowing and not result.is_dead else 0,
            emission=ELEMENT_EMISSION[transition.source],
        )
        b, a = points[-1], points[-3]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        ux, uy = dx / length, dy / length
        draw.polygon(
            (
                b,
                (b[0] - 18 * ux - 9 * uy, b[1] - 18 * uy + 9 * ux),
                (b[0] - 18 * ux + 9 * uy, b[1] - 18 * uy - 9 * ux),
            ),
            fill=color,
        )
        if transition.name == "受克阻断":
            midpoint = ANGLES[index] + 36
            draw.line(
                (
                    *orbit_point(midpoint, ORBIT_RADIUS - 10),
                    *orbit_point(midpoint, ORBIT_RADIUS + 10),
                ),
                fill=color,
                width=4,
            )
        # Full four-character names need room beyond the tangent, not over it.
        mx, my = orbit_point(ANGLES[index] + 36, ORBIT_RADIUS + 76)
        draw.text(
            (mx, my),
            transition.name,
            font=f["small"],
            fill=color,
            anchor="mm",
            stroke_width=2,
            stroke_fill=BACKGROUND,
        )

    def _node(
        self,
        canvas,
        draw,
        center,
        position,
        digit,
        yin_yang,
        element,
        meaning,
        is_root,
        f,
        energy=1.0,
    ):
        cx, cy = center
        style = ELEMENT_STYLE[element]
        glass_node(
            canvas,
            center,
            NODE_RADIUS,
            style["fill"],
            style["accent"],
            ELEMENT_EMISSION[element],
            energy=energy,
        )
        self._watermark(canvas, center, element)
        # All text is painted after the watermark, at full opacity.
        draw.text(
            (cx, cy - 121),
            f"0{position}" + (" · 根气" if is_root else ""),
            font=self._font(18),
            fill=MUTED,
            anchor="mm",
        )
        draw.text((cx, cy - 35), digit, font=f["digit"], fill=INK, anchor="mm")
        draw.text(
            (cx, cy + 45),
            f"{element} · {yin_yang}",
            font=f["element"],
            fill=INK,
            anchor="mm",
        )
        lines, font = self._fit(draw, meaning, 208, 2, 26, 20)
        for i, line in enumerate(lines):
            draw.text((cx, cy + 72 + 28 * i), line, font=font, fill=INK, anchor="mt")

    def _watermark(self, canvas, center, element):
        icon = self._icons.get(element)
        if icon is None:
            return
        icon = icon.copy()
        icon.thumbnail((240, 240), Image.Resampling.LANCZOS)
        layer = Image.new("RGBA", icon.size, ELEMENT_STYLE[element]["accent"])
        layer.putalpha(
            icon.getchannel("A").point(lambda value: round(value * WATERMARK_OPACITY))
        )
        cx, cy = center
        canvas.paste(
            layer,
            (round(cx - layer.width // 2), round(cy - 20 - layer.height // 2)),
            layer,
        )

    def _interpretation(self, draw, result, summary, f):
        draw.line((64, 1476, 1376, 1476), fill="#827A66", width=1)
        color, _ = VERDICT_STYLE[result.verdict]
        verdict_font = self._font(76) if result.is_dead else f["verdict"]
        draw.text(
            (204, 1600), result.verdict, font=verdict_font, fill=color, anchor="mm"
        )
        draw.text((204, 1690), "本 次 判 定", font=f["tiny"], fill=MUTED, anchor="mm")
        draw.line((344, 1512, 344, 1730), fill="#827A66", width=1)
        heading = {
            "成": "根气可通，流转成局",
            "败": "成局不足，此事不成",
            "死卦": "卦象未立，请重新起卦",
        }[result.verdict]
        draw.text((386, 1520), heading, font=f["body"], fill=color, anchor="lt")
        # Fixed engine verdict is always distinct from model-generated symbolism.
        lines, font = self._fit(draw, result.phrase, 970, 2, 34, 26)
        for i, line in enumerate(lines):
            draw.text((386, 1577 + i * 46), line, font=font, fill=INK, anchor="lt")
        draw.line((386, 1688, 1376, 1688), fill=BORDER, width=1)
        lines, font = self._fit(
            draw, self._clean(summary) or "象意未生成。", 970, 3, 25, 22
        )
        for i, line in enumerate(lines):
            draw.text((386, 1710 + i * 33), line, font=font, fill=MUTED, anchor="lt")
        draw.line((64, 1824, 1376, 1824), fill=BORDER, width=1)

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
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(str(self._font_path), size=size)
        return self._fonts[size]

    @staticmethod
    def _find_font():
        for candidate in (
            BUNDLED_FONT_PATH,
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/System/Library/Fonts/PingFang.ttc"),
        ):
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
