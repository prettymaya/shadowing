from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def make_icon(size: int, out: Path) -> None:
    scale = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(10 + 9 * t)
        g = int(118 - 32 * t)
        b = int(110 + 32 * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    pad = int(96 * scale)
    draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=int(188 * scale), outline=(255, 255, 255, 44), width=max(2, int(8 * scale)))

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([int(318 * scale), int(240 * scale), int(706 * scale), int(628 * scale)], fill=(250, 204, 21, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(int(42 * scale)))
    img.alpha_composite(glow)
    draw = ImageDraw.Draw(img)

    cx = size / 2
    cy = size / 2
    draw.ellipse(
        [cx - 122 * scale, cy - 122 * scale, cx + 122 * scale, cy + 122 * scale],
        fill=(255, 255, 255, 255),
    )
    draw.ellipse(
        [cx - 61 * scale, cy - 61 * scale, cx + 61 * scale, cy + 61 * scale],
        fill=(15, 118, 110, 255),
    )

    line = max(28, int(58 * scale))
    draw.arc(
        [cx - 276 * scale, cy - 276 * scale, cx + 276 * scale, cy + 276 * scale],
        start=206,
        end=334,
        fill=(255, 255, 255, 245),
        width=line,
    )
    draw.arc(
        [cx - 384 * scale, cy - 384 * scale, cx + 384 * scale, cy + 384 * scale],
        start=214,
        end=326,
        fill=(255, 255, 255, 170),
        width=max(20, int(42 * scale)),
    )
    draw.rounded_rectangle(
        [cx - 152 * scale, cy + 200 * scale, cx + 152 * scale, cy + 252 * scale],
        radius=int(28 * scale),
        fill=(250, 204, 21, 255),
    )

    img.save(out)


def main() -> None:
    make_icon(192, STATIC / "icon-192.png")
    make_icon(512, STATIC / "icon-512.png")
    make_icon(180, STATIC / "apple-touch-icon.png")
    print("Icons generated")


if __name__ == "__main__":
    main()
