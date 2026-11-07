"""Payment files (5.8): one neutral payment list, many file formats.

A run's payment lines are turned into `PaymentLine` rows once; every format builds its file
from those rows alone. Version 1 registers only `csv`. A bank-specific layout is one more entry
in `PAYMENT_FILE_FORMATS` later. Nothing here reads the database or the clock, so exporting the
same rows twice gives the same bytes.
"""

import csv
import io
from dataclasses import astuple, dataclass, fields
from typing import Protocol

from app.core.csv_safety import csv_safe_cell


@dataclass(frozen=True)
class PaymentLine:
    """One payable employee. Every value is text, exactly as the file shows it."""

    payment_reference: str
    employee_code: str
    account_holder: str
    bank_name: str
    account_number: str
    ifsc: str
    amount: str
    currency: str
    payment_date: str
    narration: str


class PaymentFileFormat(Protocol):
    name: str
    content_type: str

    def filename(self, year: int, month: int) -> str: ...

    def build(self, lines: list[PaymentLine]) -> bytes: ...


class CsvPaymentFile:
    name = "csv"
    content_type = "text/csv; charset=utf-8"

    def filename(self, year: int, month: int) -> str:
        return f"payment-file-{year}{month:02d}.csv"

    def build(self, lines: list[PaymentLine]) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([f.name for f in fields(PaymentLine)])
        for line in lines:
            # A text value that starts with = + - @ tab or CR is prefixed with a quote, so a
            # spreadsheet never runs it as a formula.
            writer.writerow([csv_safe_cell(value) for value in astuple(line)])
        return buffer.getvalue().encode("utf-8")


PAYMENT_FILE_FORMATS: dict[str, PaymentFileFormat] = {"csv": CsvPaymentFile()}
