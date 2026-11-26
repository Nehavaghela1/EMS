# ruff: noqa: E501
"""SpreadsheetML (.xlsx) generation using Python's standard library zipfile.

Generates valid Microsoft Excel .xlsx workbooks containing:
- [Content_Types].xml
- _rels/.rels
- xl/_rels/workbook.xml.rels
- xl/workbook.xml
- xl/worksheets/sheet1.xml
- xl/styles.xml
"""

import io
import xml.sax.saxutils as saxutils
import zipfile


def _escape(text: str) -> str:
    return saxutils.escape(str(text))


def generate_annual_earnings_xlsx(
    company_name: str,
    employee_name: str,
    employee_code: str,
    financial_year: str,
    months: list[str],
    rows: list[
        dict
    ],  # list of {"group": str, "name": str, "values": list[str | None], "total": str}
) -> bytes:
    """Generates an .xlsx file for Annual Earnings statement.

    rows has:
      group: e.g. "Earnings", "Deductions", "Taxes", "Net Pay"
      name: component name or row label
      values: 12 string values (formatted with ₹ or blank/empty if None)
      total: YTD total formatted string
    """
    buf = io.BytesIO()

    # XML strings
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Annual Earnings" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="3">
    <font><name val="Calibri"/><sz val="11"/></font>
    <font><name val="Calibri"/><sz val="11"/><b val="true"/></font>
    <font><name val="Calibri"/><sz val="14"/><b val="true"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1">
    <border><left/><right/><top/><bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0"/>
  </cellXfs>
</styleSheet>"""

    # Build sheet1.xml
    sheet_rows: list[str] = []
    current_row = 1

    def make_cell(col_idx: int, row_idx: int, val: str, style_idx: int = 0) -> str:
        # Col letters: 1->A, 2->B, etc.
        col_letters = ""
        c = col_idx
        while c > 0:
            c, rem = divmod(c - 1, 26)
            col_letters = chr(65 + rem) + col_letters
        cell_ref = f"{col_letters}{row_idx}"
        escaped = _escape(val)
        return f'<c r="{cell_ref}" s="{style_idx}" t="inlineStr"><is><t>{escaped}</t></is></c>'

    # Title & Metadata
    sheet_rows.append(f'<row r="{current_row}">{make_cell(1, current_row, company_name, 2)}</row>')
    current_row += 1
    sheet_rows.append(
        f'<row r="{current_row}">{make_cell(1, current_row, f"Annual Earnings Statement — FY {financial_year}", 1)}</row>'
    )
    current_row += 1
    sheet_rows.append(
        f'<row r="{current_row}">{make_cell(1, current_row, f"Employee: {employee_name} ({employee_code})", 0)}</row>'
    )
    current_row += 2  # empty line

    # Table Header
    header_cells = [
        make_cell(1, current_row, "Component", 1),
    ]
    for i, m_name in enumerate(months, start=2):
        header_cells.append(make_cell(i, current_row, m_name, 1))
    header_cells.append(make_cell(len(months) + 2, current_row, "Total (YTD)", 1))
    sheet_rows.append(f'<row r="{current_row}">{"".join(header_cells)}</row>')
    current_row += 1

    # Table Data
    current_group = ""
    for r in rows:
        grp = r.get("group", "")
        if grp and grp != current_group:
            current_group = grp
            # Group separator
            sheet_rows.append(
                f'<row r="{current_row}">{make_cell(1, current_row, current_group.upper(), 1)}</row>'
            )
            current_row += 1

        is_bold = grp == "Net Pay" or r.get("name") in (
            "Gross Earnings",
            "Total Deductions",
            "Net Pay",
        )
        st_idx = 1 if is_bold else 0

        row_cells = [make_cell(1, current_row, r.get("name", ""), st_idx)]
        vals = r.get("values", [])
        for i in range(len(months)):
            v = vals[i] if i < len(vals) else ""
            display_val = "" if v is None else str(v)
            row_cells.append(make_cell(i + 2, current_row, display_val, st_idx))

        total_val = str(r.get("total", ""))
        row_cells.append(make_cell(len(months) + 2, current_row, total_val, st_idx))
        sheet_rows.append(f'<row r="{current_row}">{"".join(row_cells)}</row>')
        current_row += 1

    sheet1 = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {"".join(sheet_rows)}
  </sheetData>
</worksheet>"""

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/styles.xml", styles)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1)

    return buf.getvalue()
