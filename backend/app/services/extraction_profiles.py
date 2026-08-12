"""Shared rules for schema-controlled extraction pipelines."""
from __future__ import annotations


EXTRACTION_PROFILES = frozenset({"legacy", "anydoc_hybrid"})
ANYDOC_IMAGE_MIME_TYPES = frozenset({
    "image/bmp",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/tiff",
    "image/webp",
})
ANYDOC_IMAGE_EXTENSIONS = (".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp")


def supports_anydoc_source(filename: str | None, mime_type: str | None) -> bool:
    """Return whether a document can enter an AnyDoc PDF or image pipeline."""
    normalized_filename = (filename or "").lower()
    normalized_mime_type = (mime_type or "").lower()
    return (
        normalized_mime_type == "application/pdf"
        or normalized_filename.endswith(".pdf")
        or normalized_mime_type in ANYDOC_IMAGE_MIME_TYPES
        or normalized_filename.endswith(ANYDOC_IMAGE_EXTENSIONS)
    )


def validate_extraction_profile(document_type: str | None, profile: str | None) -> str:
    """Normalize an internal compatibility profile.

    Schema Mapping runs after text extraction, so the document type does not
    control routing. ``legacy`` remains an internal fallback for unsupported
    files.
    """
    del document_type
    normalized_profile = (profile or "anydoc_hybrid").lower()

    if normalized_profile not in EXTRACTION_PROFILES:
        raise ValueError(f"Unsupported extraction profile: {profile}")
    return normalized_profile
