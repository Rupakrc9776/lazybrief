import pytest

from lazybrief.config import MAX_INPUT_BYTES
from lazybrief.input_processing import (
    InputValidationError,
    decode_upload,
    validate_text,
)


def test_validate_text_trims_and_returns_text():
    assert validate_text("  meeting notes  ") == "meeting notes"


@pytest.mark.parametrize("value", ["", " \n\t "])
def test_validate_text_rejects_empty_input(value):
    with pytest.raises(InputValidationError, match="Add or upload"):
        validate_text(value)


def test_validate_text_rejects_binary_marker():
    with pytest.raises(InputValidationError, match="binary data"):
        validate_text("notes\x00content")


def test_decode_upload_accepts_utf8_markdown_with_bom():
    assert decode_upload("NOTES.MD", b"\xef\xbb\xbf# Notes\nHello") == "# Notes\nHello"


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        pytest.param("notes.pdf", b"contents", "Only .txt and .md", id="unsupported-extension"),
        pytest.param("notes.txt", b"", "file is empty", id="empty-file"),
        pytest.param("notes.txt", b"\xff", "not valid UTF-8", id="invalid-utf8"),
        pytest.param(
            "notes.txt",
            b"x" * (MAX_INPUT_BYTES + 1),
            "no larger than",
            id="oversized-file",
        ),
    ],
)
def test_decode_upload_rejects_unsupported_or_invalid_files(filename, content, message):
    with pytest.raises(InputValidationError, match=message):
        decode_upload(filename, content)
