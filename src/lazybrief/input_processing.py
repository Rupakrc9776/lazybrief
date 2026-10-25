"""Validation for pasted text and supported text uploads."""

from __future__ import annotations

from lazybrief.config import MAX_INPUT_BYTES, MAX_INPUT_CHARS


class InputValidationError(ValueError):
    """Raised when text is empty, too large, or not a supported text file."""


def validate_text(text: str) -> str:
    """Return trimmed text if it is within limits and safely decodable."""
    if not isinstance(text, str):
        raise InputValidationError("Input must be text.")
    normalized = text.strip()
    if not normalized:
        raise InputValidationError("Add or upload some text before generating a brief.")
    if len(normalized) > MAX_INPUT_CHARS:
        raise InputValidationError(
            f"Text exceeds the {MAX_INPUT_CHARS:,}-character limit."
        )
    if "\x00" in normalized:
        raise InputValidationError("The document contains binary data, not plain text.")
    return normalized


def decode_upload(filename: str, content: bytes) -> str:
    """Validate and decode a UTF-8 TXT or Markdown upload without saving it."""
    suffix = filename.rsplit(".", maxsplit=1)[-1].lower() if "." in filename else ""
    if suffix not in {"txt", "md"}:
        raise InputValidationError("Only .txt and .md files are supported.")
    if not content:
        raise InputValidationError("The uploaded file is empty.")
    if len(content) > MAX_INPUT_BYTES:
        raise InputValidationError(
            f"Files must be no larger than {MAX_INPUT_BYTES // 1024:,} KB."
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputValidationError(
            "The file is not valid UTF-8 text. Save it as UTF-8 and try again."
        ) from exc
    return validate_text(text)
