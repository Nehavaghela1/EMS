"""
Shared Docx Styling Helper for EMS Pro Technical Documentation.
Provides consistent styling, headers, callouts, tables, and page setup.
"""
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

# Color Palette
COLOR_PRIMARY_HEX = "1E3A8A"      # Deep Navy
COLOR_SECONDARY_HEX = "0D9488"    # Teal Accent
COLOR_DARK_TEXT_HEX = "0F172A"    # Slate 900
COLOR_MUTED_TEXT_HEX = "475569"   # Slate 600
COLOR_LIGHT_BG_HEX = "F8FAFC"     # Slate 50
COLOR_BORDER_HEX = "CBD5E1"       # Slate 300

COLOR_PRIMARY = RGBColor(0x1E, 0x3A, 0x8A)
COLOR_SECONDARY = RGBColor(0x0D, 0x94, 0x88)
COLOR_DARK_TEXT = RGBColor(0x0F, 0x17, 0x2A)
COLOR_MUTED = RGBColor(0x47, 0x55, 0x69)

def create_styled_document():
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)
        section.header_distance = Inches(0.5)
        section.footer_distance = Inches(0.5)

    # Base Normal Style
    normal_style = doc.styles['Normal']
    normal_style.font.name = 'Arial'
    normal_style.font.size = Pt(10)
    normal_style.font.color.rgb = COLOR_DARK_TEXT
    normal_style.paragraph_format.line_spacing = 1.15
    normal_style.paragraph_format.space_after = Pt(4)

    return doc

def add_cover_page(doc, title, subtitle, doc_type, version="2.0.0", date_str="September 2026"):
    p_pre = doc.add_paragraph()
    p_pre.paragraph_format.space_before = Pt(36)
    r_tag = p_pre.add_run("EMS PRO PLATFORM TECHNICAL DOCUMENTATION")
    r_tag.font.bold = True
    r_tag.font.size = Pt(11)
    r_tag.font.color.rgb = COLOR_SECONDARY

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(12)
    p_title.paragraph_format.space_after = Pt(8)
    r_title = p_title.add_run(title)
    r_title.font.bold = True
    r_title.font.size = Pt(28)
    r_title.font.color.rgb = COLOR_PRIMARY

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(24)
    r_sub = p_sub.add_run(subtitle)
    r_sub.font.size = Pt(13)
    r_sub.font.color.rgb = COLOR_MUTED

    # Meta Table
    tbl = doc.add_table(rows=5, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_rows = [
        ("Document Classification", doc_type),
        ("Platform Version", version),
        ("Target Audience", "Engineering, DevOps, QA, Product & Architecture Teams"),
        ("Author / Organization", "Infiria Systems - Core Engineering Team"),
        ("Publication Date", date_str),
    ]
    for idx, (label, val) in enumerate(meta_rows):
        r = tbl.rows[idx]
        c0, c1 = r.cells[0], r.cells[1]
        c0.width = Inches(2.2)
        c1.width = Inches(4.3)
        p0 = c0.paragraphs[0]
        r0 = p0.add_run(label)
        r0.font.bold = True
        r0.font.size = Pt(9.5)
        r0.font.color.rgb = COLOR_PRIMARY
        p1 = c1.paragraphs[0]
        r1 = p1.add_run(val)
        r1.font.size = Pt(9.5)
        # Background shading
        shd0 = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{COLOR_LIGHT_BG_HEX}"/>')
        c0._tc.get_or_add_tcPr().append(shd0)
        shd1 = parse_xml(f'<w:shd {nsdecls("w")} w:fill="FFFFFF"/>')
        c1._tc.get_or_add_tcPr().append(shd1)
        set_cell_padding(c0, 100, 140, 100, 140)
        set_cell_padding(c1, 100, 140, 100, 140)

    doc.add_page_break()

def add_header_1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(18)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.font.name = 'Arial'
    r.font.bold = True
    r.font.size = Pt(16)
    r.font.color.rgb = COLOR_PRIMARY
    return p

def add_header_2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.font.name = 'Arial'
    r.font.bold = True
    r.font.size = Pt(12.5)
    r.font.color.rgb = COLOR_SECONDARY
    return p

def add_header_3(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.font.name = 'Arial'
    r.font.bold = True
    r.font.size = Pt(10.5)
    r.font.color.rgb = COLOR_DARK_TEXT
    return p

def add_callout(doc, text, title="NOTE"):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    cell.width = Inches(6.5)
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{COLOR_LIGHT_BG_HEX}"/>')
    cell._tc.get_or_add_tcPr().append(shd)
    # Left border highlight
    borders = parse_xml(f'<w:tcBorders {nsdecls("w")}><w:left w:val="single" w:sz="24" w:space="0" w:color="{COLOR_SECONDARY_HEX}"/><w:top w:val="none"/><w:right w:val="none"/><w:bottom w:val="none"/></w:tcBorders>')
    cell._tc.get_or_add_tcPr().append(borders)
    set_cell_padding(cell, 120, 180, 120, 180)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r_t = p.add_run(f"[{title}] ")
    r_t.font.bold = True
    r_t.font.size = Pt(9.5)
    r_t.font.color.rgb = COLOR_SECONDARY
    r_body = p.add_run(text)
    r_body.font.size = Pt(9.5)
    r_body.font.color.rgb = COLOR_DARK_TEXT
    p_spacer = doc.add_paragraph()
    p_spacer.paragraph_format.space_after = Pt(4)

def set_cell_padding(cell, top=100, bottom=100, left=140, right=140):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)

def add_styled_table(doc, headers, data, col_widths=None):
    tbl = doc.add_table(rows=len(data) + 1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    # Format header row
    hdr_row = tbl.rows[0]
    # cantSplit & tblHeader
    trPr = hdr_row._tr.get_or_add_trPr()
    trPr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))

    for col_idx, text in enumerate(headers):
        cell = hdr_row.cells[col_idx]
        if col_widths and col_idx < len(col_widths):
            cell.width = col_widths[col_idx]
        shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{COLOR_PRIMARY_HEX}"/>')
        cell._tc.get_or_add_tcPr().append(shd)
        set_cell_padding(cell, 120, 120, 140, 140)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(text)
        r.font.name = 'Arial'
        r.font.bold = True
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    # Format data rows
    for row_idx, row_vals in enumerate(data, start=1):
        row = tbl.rows[row_idx]
        bg_hex = COLOR_LIGHT_BG_HEX if row_idx % 2 == 1 else "FFFFFF"
        for col_idx, val in enumerate(row_vals):
            cell = row.cells[col_idx]
            if col_widths and col_idx < len(col_widths):
                cell.width = col_widths[col_idx]
            shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_hex}"/>')
            cell._tc.get_or_add_tcPr().append(shd)
            # Soft gray border
            borders = parse_xml(f'<w:tcBorders {nsdecls("w")}><w:bottom w:val="single" w:sz="4" w:space="0" w:color="{COLOR_BORDER_HEX}"/><w:top w:val="none"/><w:left w:val="none"/><w:right w:val="none"/></w:tcBorders>')
            cell._tc.get_or_add_tcPr().append(borders)
            set_cell_padding(cell, 80, 80, 120, 120)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(str(val))
            r.font.name = 'Arial'
            r.font.size = Pt(8.5)
            r.font.color.rgb = COLOR_DARK_TEXT

    p_post = doc.add_paragraph()
    p_post.paragraph_format.space_after = Pt(4)
    return tbl
