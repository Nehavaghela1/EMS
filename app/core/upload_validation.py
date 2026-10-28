import io
import zipfile

from app.core.exceptions import ValidationError
from app.core.filenames import sanitize_filename

ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "docx"}

CANONICAL_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def validate_document_upload(filename: str, data: bytes) -> tuple[str, str, str]:
    """Validates filename and file bytes against allowed document types.
    Allowed extensions: pdf, jpg, jpeg, png, docx.
    Magic bytes:
      - PDF starts with b"%PDF-"
      - PNG starts with b"\\x89PNG\\r\\n\\x1a\\n"
      - JPEG starts with b"\\xff\\xd8\\xff"
      - DOCX starts with b"PK\\x03\\x04" AND zipfile.ZipFile(BytesIO(data)).namelist()
        contains "word/document.xml" (read names only, never extract).
    Extension and content must agree.
    Returns (clean_name, extension, content_type).
    """
    if not data or len(data) == 0:
        raise ValidationError("File content cannot be empty.")

    clean_name = sanitize_filename(filename)
    if "." not in clean_name:
        raise ValidationError("File has no extension or invalid format.")

    ext = clean_name.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file extension '.{ext}'. Allowed types are PDF, JPG, JPEG, PNG, DOCX."
        )

    # Magic bytes check & extension agreement
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            raise ValidationError("File content does not match a valid PDF document.")
    elif ext in ("jpg", "jpeg"):
        if not data.startswith(b"\xff\xd8\xff"):
            raise ValidationError("File content does not match a valid JPEG image.")
    elif ext == "png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValidationError("File content does not match a valid PNG image.")
    elif ext == "docx":
        if not data.startswith(b"PK\x03\x04"):
            raise ValidationError("File content does not match a valid DOCX archive.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                namelist = zf.namelist()
                if "word/document.xml" not in namelist:
                    raise ValidationError("DOCX file is missing 'word/document.xml'.")
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError("Invalid or corrupted DOCX file.") from e

    content_type = CANONICAL_CONTENT_TYPES[ext]
    return clean_name, ext, content_type
