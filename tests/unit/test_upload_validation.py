import io
import zipfile

import pytest

from app.core.exceptions import ValidationError
from app.core.upload_validation import validate_document_upload


def _make_docx_bytes(with_word_doc: bool = True) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        if with_word_doc:
            zf.writestr("word/document.xml", "<xml></xml>")
        else:
            zf.writestr("some/other.txt", "content")
    return bio.getvalue()


def test_validate_document_upload_allowed_pdf():
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n..."
    clean_name, ext, ctype = validate_document_upload("resume.pdf", pdf_bytes)
    assert clean_name == "resume.pdf"
    assert ext == "pdf"
    assert ctype == "application/pdf"


def test_validate_document_upload_allowed_jpeg():
    jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF..."
    clean_name, ext, ctype = validate_document_upload("photo.jpg", jpeg_bytes)
    assert clean_name == "photo.jpg"
    assert ext == "jpg"
    assert ctype == "image/jpeg"

    clean_name2, ext2, ctype2 = validate_document_upload("photo.jpeg", jpeg_bytes)
    assert clean_name2 == "photo.jpeg"
    assert ext2 == "jpeg"
    assert ctype2 == "image/jpeg"


def test_validate_document_upload_allowed_png():
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR..."
    clean_name, ext, ctype = validate_document_upload("avatar.png", png_bytes)
    assert clean_name == "avatar.png"
    assert ext == "png"
    assert ctype == "image/png"


def test_validate_document_upload_allowed_docx():
    docx_bytes = _make_docx_bytes(with_word_doc=True)
    clean_name, ext, ctype = validate_document_upload("contract.docx", docx_bytes)
    assert clean_name == "contract.docx"
    assert ext == "docx"
    assert ctype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_validate_document_upload_rejected_empty_bytes():
    with pytest.raises(ValidationError):
        validate_document_upload("empty.pdf", b"")


def test_validate_document_upload_rejected_bad_extension():
    pdf_bytes = b"%PDF-1.4\n..."
    with pytest.raises(ValidationError):
        validate_document_upload("test.exe", pdf_bytes)

    with pytest.raises(ValidationError):
        validate_document_upload("test.txt", b"plain text")


def test_validate_document_upload_rejected_renamed_exe_as_pdf():
    # .pdf extension with non-PDF content (e.g. PE header MZ)
    with pytest.raises(ValidationError):
        validate_document_upload("malware.pdf", b"MZ\x90\x00\x03\x00\x00\x00")


def test_validate_document_upload_rejected_pdf_named_png():
    # PDF bytes named .png
    pdf_bytes = b"%PDF-1.4\n..."
    with pytest.raises(ValidationError):
        validate_document_upload("fake.png", pdf_bytes)


def test_validate_document_upload_rejected_docx_missing_word_document_xml():
    zip_bytes = _make_docx_bytes(with_word_doc=False)
    with pytest.raises(ValidationError):
        validate_document_upload("corrupt.docx", zip_bytes)


def test_validate_document_upload_rejected_xlsx_renamed_as_docx():
    # XLSX zip file containing xl/workbook.xml instead of word/document.xml
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("xl/workbook.xml", "<xml></xml>")
    xlsx_bytes = bio.getvalue()

    with pytest.raises(ValidationError):
        validate_document_upload("spreadsheet.docx", xlsx_bytes)
