"""Claim pages as model-ready JPEG images: PDF pages rendered at 150 dpi, long edge at most 2000 px, JPEG,
at most 100 images and about 3.3 MB of image bytes per request, with a shrink ladder when a request is too big.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

import fitz  # PyMuPDF
from PIL import Image

PDF_DPI = 150
MAX_SIDE = 2000
JPEG_QUALITY = 85
MAX_IMAGES_PER_REQUEST = 100
MAX_REQUEST_IMAGE_BYTES = 3_300_000
# (max side, JPEG quality) tried in order when a request's images are over the byte limit.
SHRINK_LADDER: Tuple[Tuple[int, int], ...] = ((1600, 80), (1100, 65), (800, 55), (560, 45))
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


@dataclass
class PageImage:
    """One page of one claim file: where it came from and the rendered image."""
    source_file: str
    page_in_file: int  # 1-based page number inside source_file
    image: Image.Image


def pdf_to_images(pdf_bytes: bytes, dpi: int = PDF_DPI) -> List[Image.Image]:
    """Render every PDF page to an RGB image (RGB straight from the pixmap)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        images = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        return images
    finally:
        doc.close()


def load_file_pages(path: Path) -> List[PageImage]:
    """All pages of one claim file (PDF or image)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return [PageImage(path.name, i + 1, img) for i, img in enumerate(pdf_to_images(path.read_bytes()))]
    if suffix in IMAGE_SUFFIXES:
        img = Image.open(path)
        img.load()
        return [PageImage(path.name, 1, img.convert("RGB"))]
    raise ValueError(f"unsupported file type: {path.name}")


def load_claim_pages(folder: Path) -> List[PageImage]:
    """Every page of every readable file in a claim folder, files in name order."""
    pages: List[PageImage] = []
    for path in sorted(p for p in folder.iterdir() if p.is_file()):
        if path.suffix.lower() == ".pdf" or path.suffix.lower() in IMAGE_SUFFIXES:
            pages.extend(load_file_pages(path))
    return pages


def encode_jpeg(image: Image.Image, max_side: int = MAX_SIDE, quality: int = JPEG_QUALITY) -> bytes:
    """One page as a JPEG no longer than max_side on its long edge."""
    frame = image.convert("RGB")
    if max(frame.size) > max_side:
        frame = frame.copy()
        frame.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    frame.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def encode_for_request(images: Sequence[Image.Image]) -> List[bytes]:
    """JPEGs for one request, shrunk down the ladder until the request fits Bedrock's limits."""
    if len(images) > MAX_IMAGES_PER_REQUEST:
        raise ValueError(f"{len(images)} images in one request; the limit is {MAX_IMAGES_PER_REQUEST}")
    encoded = [encode_jpeg(img) for img in images]
    for max_side, quality in SHRINK_LADDER:
        if sum(len(b) * 4 // 3 for b in encoded) <= MAX_REQUEST_IMAGE_BYTES:
            break
        encoded = [encode_jpeg(img, max_side, quality) for img in images]
    return encoded


def image_block(jpeg: bytes) -> dict:
    """OpenAI-style content block (what litellm sends to Bedrock)."""
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")}}


def batches(items: Sequence, size: int) -> List[Tuple[int, list]]:
    """(start index, chunk) pairs; bills go 1 page per request, other documents 4."""
    return [(start, list(items[start:start + size])) for start in range(0, len(items), max(1, size))]
