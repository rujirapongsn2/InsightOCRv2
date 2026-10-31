"""One text normalizer for searching documents and verifying quotes against them."""
from __future__ import annotations

import re
import unicodedata

_THAI_DIGIT_TRANSLATION = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def normalize_search_text(value: object) -> str:
    """Normalize Thai/Arabic digits, case, and whitespace for document search."""
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_THAI_DIGIT_TRANSLATION)
    return re.sub(r"\s+", " ", text.casefold()).strip()


def compact_search_text(value: object) -> str:
    """normalize_search_text without any whitespace: OCR of Thai text puts spaces inside words."""
    return re.sub(r"\s+", "", normalize_search_text(value))
