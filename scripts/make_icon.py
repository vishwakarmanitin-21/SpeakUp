"""Generate the SpeakUp app icon (assets/icon.ico + icon.png) from the logo mark.

One-off generator — run after changing the logo:
    python scripts/make_icon.py

Requires Pillow (build-time only; not a runtime dependency):
    pip install pillow
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 256
BLUE = (47, 143, 208, 255)   # #2f8fd0 — app accent
WHITE = (255, 255, 255, 255)


def _draw(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    # Rounded-square tile
    d.rounded_rectangle([8, 8, 248, 248], radius=56, fill=BLUE)
    # Microphone body (capsule)
    d.rounded_rectangle([106, 54, 150, 150], radius=22, fill=WHITE)
    # Cradle (bowl under the mic)
    d.arc([88, 82, 168, 178], start=20, end=160, fill=WHITE, width=12)
    # Stand + base
    d.line([128, 176, 128, 204], fill=WHITE, width=12)
    d.line([104, 206, 152, 206], fill=WHITE, width=12)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    _draw(img)
    img.save(ASSETS / "icon.png")
    img.save(
        ASSETS / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {ASSETS / 'icon.ico'} and icon.png")


if __name__ == "__main__":
    main()
