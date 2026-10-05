"""Screenshots, annotated screenshots, test videos and bug clips.

* Step screenshots are stored as JPEG (quality 78): a full run has hundreds of them.
* Videos are built from the step screenshots with captions burned in, using the ffmpeg binary bundled with
  `imageio-ffmpeg` (nothing to install). Each step is held long enough to read its caption.
* Bug clips are the last few steps before the failure (10–25 s), ending on the annotated screenshot.
"""

from __future__ import annotations

import io
import textwrap
from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FRAME_W, FRAME_H = 1280, 800
RED = (220, 38, 38)
BAR = (10, 15, 28)


def to_jpeg(png: bytes, quality: int = 78) -> bytes:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def model_image(png: bytes, width: int = 1280) -> bytes:
    """Downscaled JPEG for the model: ~1.3k image tokens per turn instead of ~2k+."""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    if img.width > width:
        img = img.resize((width, int(img.height * width / img.width)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=65, optimize=True)
    return buf.getvalue()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (
        "Inter-SemiBold.ttf",
        "Arial Bold.ttf",
        "Arial.ttf",
        "DejaVuSans-Bold.ttf",
        "Helvetica.ttc",
        "arialbd.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def annotate(
    image: bytes, rect: dict[str, float] | None, caption: str, viewport_width: int | None = None
) -> bytes:
    """Red box around the element involved in the failure, caption bar at the bottom. Returns PNG bytes."""
    img = Image.open(io.BytesIO(image)).convert("RGB")
    draw = ImageDraw.Draw(img)
    if rect and rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
        # rect is in CSS pixels of the viewport; the screenshot may be device-scaled
        scale = img.width / viewport_width if viewport_width else 1.0
        x0, y0 = rect["x"] * scale - 6, rect["y"] * scale - 6
        x1, y1 = (rect["x"] + rect["width"]) * scale + 6, (rect["y"] + rect["height"]) * scale + 6
        for i in range(4):
            draw.rounded_rectangle([x0 - i, y0 - i, x1 + i, y1 + i], radius=8, outline=RED)
    _caption(img, draw, caption, highlight=True)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _caption(img: Image.Image, draw: ImageDraw.ImageDraw, caption: str, highlight: bool = False) -> None:
    size = max(18, img.width // 64)
    font = _font(size)
    lines = textwrap.wrap(caption, width=max(40, img.width // (size // 2 + 1)))[:3]
    line_h = int(size * 1.35)
    height = line_h * len(lines) + 24
    overlay = Image.new("RGBA", (img.width, height), (*BAR, 225))
    img.paste(overlay, (0, img.height - height), overlay)
    if highlight:
        draw.rectangle([0, img.height - height, 8, img.height], fill=RED)
    for i, line in enumerate(lines):
        draw.text((24, img.height - height + 12 + i * line_h), line, fill=(255, 255, 255), font=font)


def _frame(path: Path, caption: str, load: Callable[[Path], bytes] | None = None) -> bytes:
    img = Image.open(io.BytesIO(load(path)) if load else path).convert("RGB")
    img.thumbnail((FRAME_W, FRAME_H), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (FRAME_W, FRAME_H), BAR)
    canvas.paste(img, ((FRAME_W - img.width) // 2, 0))
    if caption:
        _caption(canvas, ImageDraw.Draw(canvas), caption)
    return canvas.tobytes()


def build_video(
    frames: Iterable[tuple[Path, str]],
    out: Path,
    seconds_per_frame: float = 2.0,
    load: Callable[[Path], bytes] | None = None,
) -> Path | None:
    """MP4 (H.264) from (image, caption) pairs. Returns None when there is nothing to encode."""
    import imageio_ffmpeg

    items = [(p, c) for p, c in frames if p.exists()]
    if not items:
        return None
    fps = 2
    hold = max(1, round(seconds_per_frame * fps))
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio_ffmpeg.write_frames(
        str(out),
        (FRAME_W, FRAME_H),
        fps=fps,
        codec="libx264",
        pix_fmt_out="yuv420p",
        quality=6,
        macro_block_size=8,
        ffmpeg_log_level="error",
    )
    writer.send(None)
    try:
        for path, caption in items:
            data = _frame(path, caption, load)
            for _ in range(hold):
                writer.send(data)
    finally:
        writer.close()
    return out


def build_clip(
    frames: list[tuple[Path, str]],
    annotated: Path | None,
    out: Path,
    load: Callable[[Path], bytes] | None = None,
) -> Path | None:
    """10–25 s: up to the last 6 steps (2 s each), then the annotated failure screen for 4 s."""
    tail = frames[-6:]
    seq = list(tail)
    if annotated and annotated.exists():
        seq += [(annotated, "")] * 2
    if not seq:
        return None
    while len(seq) < 5:  # at least ~10 s
        seq.insert(0, seq[0])

    # the annotated image is already blurred when privacy is on, so it is loaded as-is
    def loader(p: Path) -> bytes:
        return p.read_bytes() if (annotated and p == annotated) or load is None else load(p)

    return build_video(seq, out, seconds_per_frame=2.0, load=loader)
