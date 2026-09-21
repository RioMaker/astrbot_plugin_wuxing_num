"""Original five-element emblem atlas, generated from a visual style reference."""

from pathlib import Path

from PIL import Image, ImageChops


ICON_STRIP = Path(__file__).resolve().parent / "assets" / "icons" / "wuxing_emblems.png"
# One 3 x 2 atlas; the last cell is intentionally empty.
ICON_BOXES = {
    "水": (0, 0, 512, 512),
    "火": (512, 0, 1024, 512),
    "木": (1024, 0, 1536, 512),
    "金": (0, 512, 512, 1024),
    "土": (512, 512, 1024, 1024),
}
ICON_EXPLANATION = (
    "卦图采用专为五行生成的元素徽记：水为浪纹、火为烈焰、木为枝叶根系、"
    "金为金属刃面与菱形、土为层叠山岩。金就是金属，不对应雷。"
    "象意、根气和生克按五行解释，不引入游戏元素反应或角色设定。"
)


def load_icons(path: Path = ICON_STRIP) -> dict[str, Image.Image]:
    """Read sprites at runtime, keeping the original asset unchanged on disk."""
    with Image.open(path) as strip:
        if strip.size != (1536, 1024):
            raise ValueError("五行徽记图集应为 1536 × 1024 图片")
        icons = {}
        for element, box in ICON_BOXES.items():
            icon = strip.crop(box).convert("RGB")
            # Ignore near-white margins when sizing sprites. Never rewrite the
            # generated asset: this is the chart renderer's runtime layout.
            red, green, blue = icon.split()
            darkest = ImageChops.darker(ImageChops.darker(red, green), blue)
            bounds = darkest.point(lambda value: 255 if value < 190 else 0).getbbox()
            if bounds is None:
                raise ValueError(f"{element}徽记为空")
            icon = icon.crop(bounds)
            icon.thumbnail((68, 68), Image.Resampling.LANCZOS)
            icons[element] = icon
        return icons
