"""Small compatibility helpers for Poppler PDF page render output."""
from __future__ import annotations

import glob
import os


def find_pdftoppm_page_png(output_prefix: str, page_number: int) -> str | None:
    """Find the PNG emitted for one requested page regardless of zero padding.

    Poppler versions differ in whether a single rendered page is suffixed as
    ``-1.png`` or ``-01.png``. Match the numeric suffix instead of assuming
    one filename convention.
    """
    prefix = f"{output_prefix}-"
    for candidate in sorted(glob.glob(f"{prefix}*.png")):
        basename = os.path.basename(candidate)
        if not basename.startswith(os.path.basename(prefix)):
            continue
        suffix = basename[len(os.path.basename(prefix)):-len(".png")]
        if suffix.isdigit() and int(suffix) == page_number:
            return candidate
    return None
