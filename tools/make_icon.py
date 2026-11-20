"""Render the Phase Guard brand icons (shield + three phase-shifted sine waves).

Usage: python tools/make_icon.py  ->  writes custom_components/phase_guard/brand/*.png
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "phase_guard" / "brand"
SS = 4  # supersampling factor
WAVES = ("#FFB300", "#FF5252", "#40C4FF")  # L1, L2, L3


def _bezier(p0, p1, p2, n=60):
    return [
        ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0],
         (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1])
        for t in (i / n for i in range(n + 1))
    ]


def shield(size: float) -> list[tuple[float, float]]:
    """Classic heater shield: flat top with rounded corners, straight sides, pointed tip."""
    s = size
    left, right, top, r = 0.10 * s, 0.90 * s, 0.04 * s, 0.07 * s
    shoulder, tip = 0.50 * s, (0.5 * s, 0.97 * s)
    pts = []
    pts += _bezier((left, top + r), (left, top), (left + r, top), 12)          # top-left corner
    pts += _bezier((right - r, top), (right, top), (right, top + r), 12)       # top-right corner
    pts.append((right, shoulder))                                              # right side
    pts += _bezier((right, shoulder), (right, 0.80 * s), tip, 60)[1:]          # right curve to tip
    pts += _bezier(tip, (left, 0.80 * s), (left, shoulder), 60)[1:]            # left curve back up
    return pts


def render(px: int, dark: bool) -> Image.Image:
    s = px * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # shield body with vertical gradient
    body_top, body_bot = ((0x1E, 0x88, 0xE5), (0x0D, 0x3B, 0x8C)) if not dark else (
        (0x2A, 0x3F, 0x66),
        (0x12, 0x1B, 0x2E),
    )
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / (s - 1)
        c = tuple(round(a + (b - a) * t) for a, b in zip(body_top, body_bot))
        gd.line([(0, y), (s, y)], fill=c + (255,))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).polygon(shield(s), fill=255)
    img.paste(grad, (0, 0), mask)

    # rim
    rim = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(rim).line(
        shield(s) + [shield(s)[0]], fill=(255, 255, 255, 70 if not dark else 90), width=round(s * 0.02), joint="curve"
    )
    img = Image.alpha_composite(img, rim)

    # three sine waves, 120 degrees apart, clipped to the shield
    waves = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    wd = ImageDraw.Draw(waves)
    x0, x1 = 0.20 * s, 0.80 * s
    cy, amp = 0.45 * s, 0.15 * s
    r = s * 0.024
    steps = 3000
    for k, color in enumerate(WAVES):
        phase = k * 2 * math.pi / 3
        for i in range(steps + 1):  # stamp discs densely -> smooth round-capped stroke
            u = i / steps
            x = x0 + (x1 - x0) * u
            y = cy - amp * math.sin(2 * math.pi * 1.0 * u + phase)
            wd.ellipse([x - r, y - r, x + r, y + r], fill=color)
    glow = waves.filter(ImageFilter.GaussianBlur(s * 0.01))
    clip = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    clip.paste(Image.alpha_composite(glow, waves), (0, 0), mask)
    img = Image.alpha_composite(img, clip)

    img = img.resize((px, px), Image.LANCZOS)
    return img.crop(img.getbbox()).resize((px, px), Image.LANCZOS) if img.getbbox() else img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for dark in (False, True):
        prefix = "dark_" if dark else ""
        render(256, dark).save(OUT / f"{prefix}icon.png", optimize=True)
        render(512, dark).save(OUT / f"{prefix}icon@2x.png", optimize=True)
    print("written:", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
