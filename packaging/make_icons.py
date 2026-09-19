"""
Regenerates assets/app.ico (Windows) and assets/app.icns (macOS) from assets/ds_media_icon.jpg.

Run from the repository root after replacing the source image:  python packaging/make_icons.py
The icon is the original image, only scaled: no margin, no rounded corners, no retouching.
The current source is only 32x32 px, so the large sizes are upscaled and soft; a bigger source
(square, at least 512 px) gives a much sharper result without any change to this script.
"""
from pathlib import Path

from PIL import Image

SOURCE = Path("assets/ds_media_icon.jpg")
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def scaled(source: Image.Image, size: int) -> Image.Image:
    return source.resize((size, size), Image.LANCZOS)


def main() -> None:
    source = Image.open(SOURCE).convert("RGB")

    ico = [scaled(source, size) for size in ICO_SIZES]
    ico[-1].save("assets/app.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=ico[:-1])

    icns = [scaled(source, size) for size in ICNS_SIZES]
    icns[-1].save("assets/app.icns", append_images=icns[:-1])


if __name__ == "__main__":
    main()
