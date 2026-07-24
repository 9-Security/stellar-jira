"""Normalize JJNET logo for Word report headers (crop, true RGBA, header size)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_LOGO = REPO_ROOT / "assets" / "jjnet_logo.png"
DEFAULT_HEADER_LOGO = REPO_ROOT / "assets" / "jjnet_header_logo.png"
DEFAULT_WATERMARK_CACHE = REPO_ROOT / "reports" / ".cache" / "jjnet_watermark.jpg"

HEADER_MAX_HEIGHT_PX = 64
HEADER_MAX_WIDTH_PX = 220
HEADER_PADDING_PX = 6
MASTER_MAX_EDGE_PX = 800


def is_background_pixel(r: int, g: int, b: int, a: int) -> bool:
    """Transparent, near-white margins, or checkerboard export artifacts."""
    if a < 32:
        return True
    if r >= 250 and g >= 250 and b >= 250:
        return True
    # 常見「去背預覽」棋盤格：#C0C0C0 / #E0E0E0 / #D9D9D9 等中性灰（仍為不透明像素）
    if abs(r - g) <= 12 and abs(g - b) <= 12 and abs(r - b) <= 12 and r >= 168:
        return True
    return False


def content_bbox(img) -> tuple[int, int, int, int] | None:
    """Bounding box of non-background pixels."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    alpha = rgba.split()[3]
    alpha_bbox = alpha.point(lambda a: 255 if a > 32 else 0).getbbox()
    if alpha_bbox:
        aw = alpha_bbox[2] - alpha_bbox[0]
        ah = alpha_bbox[3] - alpha_bbox[1]
        if aw < w * 0.98 or ah < h * 0.98:
            return alpha_bbox

    px = rgba.load()
    min_x, min_y, max_x, max_y = w, h, 0, 0
    found = False
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if is_background_pixel(r, g, b, a):
                continue
            found = True
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if not found:
        return alpha_bbox
    return min_x, min_y, max_x + 1, max_y + 1


def debackground_rgba(img) -> "Image.Image":
    """將透明區／白底／棋盤格匯出殘影的 alpha 設為 0（避免浮水印帶灰格）。"""
    from PIL import Image

    rgba = img.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 32 or is_background_pixel(r, g, b, a):
                px[x, y] = (r, g, b, 0)
    return rgba


def _crop_with_padding(img, *, padding_px: int = HEADER_PADDING_PX):
    from PIL import Image

    bbox = content_bbox(img)
    if not bbox:
        return img.convert("RGBA")
    l, t, r, b = bbox
    l = max(0, l - padding_px)
    t = max(0, t - padding_px)
    r = min(img.size[0], r + padding_px)
    b = min(img.size[1], b + padding_px)
    return img.crop((l, t, r, b)).convert("RGBA")


def normalize_logo(
    src: Path,
    dest: Path,
    *,
    max_height_px: int = HEADER_MAX_HEIGHT_PX,
    max_width_px: int = HEADER_MAX_WIDTH_PX,
    force: bool = False,
) -> Path:
    """Crop to logo artwork, save transparent PNG sized for Word header."""
    from PIL import Image

    src = src.resolve()
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = dest.with_suffix(".png")

    if not src.is_file():
        raise FileNotFoundError(f"Logo source not found: {src}")

    if (
        not force
        and out.is_file()
        and out.stat().st_mtime >= src.stat().st_mtime
    ):
        return out

    img = _crop_with_padding(Image.open(src))
    img.thumbnail((max_width_px, max_height_px), Image.Resampling.LANCZOS)
    img.save(out, "PNG", optimize=True)
    return out


def normalize_master_logo(src: Path, dest: Path, *, max_edge_px: int = MASTER_MAX_EDGE_PX, force: bool = False) -> Path:
    """Crop source to true RGBA master (larger than header); optional replacement for jjnet_logo.png."""
    from PIL import Image

    src = src.resolve()
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = dest.with_suffix(".png")

    if not src.is_file():
        raise FileNotFoundError(f"Logo source not found: {src}")

    if not force and out.is_file() and out.stat().st_mtime >= src.stat().st_mtime:
        return out

    img = _crop_with_padding(Image.open(src))
    img.thumbnail((max_edge_px, max_edge_px), Image.Resampling.LANCZOS)
    img.save(out, "PNG", optimize=True)
    return out


def prepare_watermark_jpg(
    src: Path,
    dest: Path,
    *,
    opacity: float = 0.22,
    max_edge_px: int = 520,
) -> Path:
    """淡色白底 JPEG，供 Word 頁首 anchor 底圖（可見且不依賴 PNG 透明）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = dest.with_suffix(".jpg")
    try:
        from PIL import Image
    except ImportError:
        import shutil
        shutil.copy2(src, out)
        return out

    img = debackground_rgba(_crop_with_padding(Image.open(src)))
    img.thumbnail((max_edge_px, max_edge_px), Image.Resampling.LANCZOS)
    white = Image.new("RGB", img.size, (255, 255, 255))
    fade = img.getchannel("A").point(lambda a: int(a * opacity))
    img.putalpha(fade)
    white.paste(img, mask=img.split()[3])
    white.save(out, "JPEG", quality=92)
    return out


def ensure_watermark_png(
    *,
    source: Path | None = None,
    dest: Path | None = None,
    force: bool = False,
) -> Path:
    """Return path to watermark JPEG (default ``reports/.cache/jjnet_watermark.jpg``)."""
    source_path = (source or DEFAULT_SOURCE_LOGO).resolve()
    dest_path = (dest or DEFAULT_WATERMARK_CACHE).resolve()
    dest_path = dest_path.with_suffix(".jpg")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if not force and dest_path.exists() and dest_path.stat().st_mtime >= source_path.stat().st_mtime:
        return dest_path
    if not source_path.is_file():
        header = DEFAULT_HEADER_LOGO
        if header.is_file():
            source_path = header
        else:
            raise FileNotFoundError(f"Watermark source missing: {source_path}")
    return prepare_watermark_jpg(source_path, dest_path)


def ensure_header_logo(
    *,
    source: Path | None = None,
    header: Path | None = None,
    force: bool = False,
) -> Path:
    """
    Return path to ``assets/jjnet_header_logo.png``, generating from source when missing or stale.

    Resolution order for *source* when ``assets/jjnet_logo.png`` is absent:
    use existing header file if present.
    """
    header_path = (header or DEFAULT_HEADER_LOGO).resolve()
    source_path = (source or DEFAULT_SOURCE_LOGO).resolve()

    if source_path.is_file():
        return normalize_logo(source_path, header_path, force=force)

    if header_path.is_file():
        return header_path

    raise FileNotFoundError(
        f"Report logo missing: add {DEFAULT_SOURCE_LOGO.name} or {DEFAULT_HEADER_LOGO.name} under assets/"
    )
