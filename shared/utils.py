"""
Shared utilities for tabletop-print-tools scripts.

Usage in any PDF-generating script:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
    from utils import mm_to_pt, get_page_size, compute_fit, IMAGE_EXTS
"""
from __future__ import annotations

from reportlab.lib.pagesizes import letter, A4

# Image file extensions recognised across all tools.
IMAGE_EXTS: set[str] = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def mm_to_pt(mm: float) -> float:
    """Convert millimetres to PDF points (72 pt = 1 inch = 25.4 mm)."""
    return mm / 25.4 * 72.0


def get_page_size(paper: str) -> tuple[float, float]:
    """Return a ReportLab (width_pt, height_pt) page-size tuple.

    Accepted values (case-insensitive): 'letter', 'a4'.
    """
    p = paper.lower()
    if p in ("letter", "us-letter"):
        return letter   # 612 × 792 pt  (8.5 × 11 in)
    if p == "a4":
        return A4       # 595 × 842 pt  (210 × 297 mm)
    raise ValueError(f"Unsupported paper size: {paper!r}. Use 'letter' or 'a4'.")


def compute_fit(
    w_px: int, h_px: int, max_w_pt: float, max_h_pt: float
) -> tuple[float, float]:
    """Return (w_pt, h_pt) fitted within (max_w_pt × max_h_pt), preserving aspect ratio."""
    aspect = w_px / h_px
    w_pt = min(max_w_pt, max_h_pt * aspect)
    h_pt = w_pt / aspect
    return w_pt, h_pt
