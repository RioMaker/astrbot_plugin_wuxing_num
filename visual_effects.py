"""Local, data-independent lighting primitives for the Pillow chart renderer."""

import math

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter


def _tint(canvas, mask, color, origin):
    # Blur coverage only, then tint. Blurring RGB and alpha together darkens the
    # edge twice during paste and was why the old bloom was almost invisible.
    canvas.paste(Image.new("RGB", mask.size, color), origin, mask)


def luminous_path(
    canvas, points, color, *, width=4, energy=1.0, emission=None, dashed=False
):
    """Antialiased stroke plus independent broad bloom, tight bloom and bright core."""
    pad, scale = 72, 3
    x0 = math.floor(min(x for x, _ in points)) - pad
    y0 = math.floor(min(y for _, y in points)) - pad
    x1 = math.ceil(max(x for x, _ in points)) + pad
    y1 = math.ceil(max(y for _, y in points)) + pad
    size = (x1 - x0, y1 - y0)
    local = [((x - x0) * scale, (y - y0) * scale) for x, y in points]

    def coverage(thickness):
        mask = Image.new("L", (size[0] * scale, size[1] * scale))
        draw = ImageDraw.Draw(mask)
        if dashed:
            for step in range(0, len(local) - 1, 8):
                draw.line(
                    local[step : step + 5],
                    fill=255,
                    width=max(1, round(thickness * scale)),
                    joint="curve",
                )
        else:
            draw.line(
                local, fill=255, width=max(1, round(thickness * scale)), joint="curve"
            )
        return mask.resize(size, Image.Resampling.LANCZOS)

    mask = coverage(width)
    if energy > 0:
        for radius, gain in ((20, 2.8), (6, 1.6)):
            blur = mask.filter(ImageFilter.GaussianBlur(radius))
            blur = blur.point(
                lambda value, gain=gain: min(255, round(value * gain * energy))
            )
            _tint(canvas, blur, emission or color, (x0, y0))
    _tint(canvas, mask, color, (x0, y0))
    if energy > 0:
        rgb = ImageColor.getrgb(color)
        white = 0.65 * min(1, energy)
        core = tuple(round(channel * (1 - white) + 255 * white) for channel in rgb)
        _tint(canvas, coverage(max(0.8, width * 0.33)), core, (x0, y0))


def soft_halo(canvas, center, color, *, radius=55, strength=0.3):
    pad = radius * 3
    mask = Image.new("L", (pad * 2, pad * 2))
    draw = ImageDraw.Draw(mask)
    draw.ellipse((pad - radius, pad - radius, pad + radius, pad + radius), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius * 0.65))
    mask = mask.point(lambda value: round(value * strength))
    _tint(canvas, mask, color, (round(center[0] - pad), round(center[1] - pad)))


def glass_node(canvas, center, radius, fill, accent, emission, *, energy=1.0):
    """Dark translucent body, subtle material grain and lit double rim."""
    cx, cy = center
    r = radius
    origin = (round(cx - r), round(cy - r))
    size = (r * 2 + 1, r * 2 + 1)
    box = (*origin, origin[0] + size[0], origin[1] + size[1])
    surface = Image.blend(canvas.crop(box), Image.new("RGB", size, fill), 0.84)
    # The grain is deterministic and decorative; it contains no divination data.
    grain = Image.new("L", (96, 96))
    grain.putdata(
        [
            round(
                3
                + 1.5 * math.sin(x * 3.7 + y * 9.1)
                + 1.5 * math.sin(x * 0.41 - y * 0.73)
            )
            for y in range(96)
            for x in range(96)
        ]
    )
    grain = grain.resize(size, Image.Resampling.BILINEAR).convert("RGB")
    surface = ImageChops.add(surface, grain)
    highlight = Image.new("L", size)
    ImageDraw.Draw(highlight).ellipse((-70, -95, r + 90, r + 65), fill=26)
    highlight = highlight.filter(ImageFilter.GaussianBlur(50))
    _tint(surface, highlight, accent, (0, 0))
    circle = Image.new("L", (size[0] * 3, size[1] * 3))
    ImageDraw.Draw(circle).ellipse(
        (0, 0, circle.width - 1, circle.height - 1), fill=255
    )
    circle = circle.resize(size, Image.Resampling.LANCZOS)
    canvas.paste(surface, origin, circle)

    def ring(rad, start=0, stop=360):
        return [
            (
                cx + rad * math.cos(math.radians(start + (stop - start) * i / 240)),
                cy + rad * math.sin(math.radians(start + (stop - start) * i / 240)),
            )
            for i in range(241)
        ]

    luminous_path(canvas, ring(r), accent, width=1.8, energy=energy, emission=emission)
    luminous_path(canvas, ring(r - 7), accent, width=0.8, energy=0)
    # A soft highlight catches the upper-left glass rim, not another flow arrow.
    luminous_path(
        canvas,
        ring(r - 2, 205, 290),
        accent,
        width=2.2,
        energy=energy * 0.6,
        emission=emission,
    )
