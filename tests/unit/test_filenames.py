import pytest

from app.core.filenames import sanitize_filename


def test_sanitize_filename_simple():
    assert sanitize_filename("resume.pdf") == "resume.pdf"


def test_sanitize_filename_strips_directory_paths():
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename("C:\\Users\\admin\\Desktop\\resume.pdf") == "resume.pdf"
    assert sanitize_filename("folder/subfolder/doc.docx") == "doc.docx"
    assert sanitize_filename("a/b\\c.pdf") == "c.pdf"


def test_sanitize_filename_drops_control_and_odd_characters():
    assert sanitize_filename("file\x00name\r\n.pdf") == "filename.pdf"
    assert sanitize_filename("my resume (1) [final]!@#$%^&*.pdf") == "my resume _1_ _final________.pdf"


def test_sanitize_filename_strips_leading_dots_and_spaces():
    assert sanitize_filename("...   hidden.pdf") == "hidden.pdf"
    assert sanitize_filename(".bashrc") == "bashrc"


def test_sanitize_filename_length_capped_at_100_keeping_extension():
    long_name = "a" * 150 + ".pdf"
    sanitized = sanitize_filename(long_name)
    assert len(sanitized) <= 100
    assert sanitized.endswith(".pdf")
    # Base name capped to 100 - len('.pdf') = 96
    assert sanitized == "a" * 96 + ".pdf"


def test_sanitize_filename_empty_or_stripped_returns_file():
    assert sanitize_filename("") == "file"
    assert sanitize_filename("   ") == "file"
    assert sanitize_filename("...") == "file"
    assert sanitize_filename("///\\\\") == "file"
    assert sanitize_filename("\x00\x01\x02") == "file"
