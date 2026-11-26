# ruff: noqa: E501
"""PDF generation for payslips, tax computation worksheets, and salary certificates.

Generates standard A4 PDF documents matching official payroll layouts using ReportLab.
"""

import io
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _fmt_inr(val: Any) -> str:
    if val is None or val == "":
        return "₹0.00"
    try:
        d = Decimal(str(val))
        return f"₹{d:,.2f}"
    except Exception:
        return f"₹{val}"


def generate_payslip_pdf(
    company_name: str,
    company_address: str,
    company_city_pin: str,
    period_title: str,
    employee_details: list[tuple[str, str]],
    net_payable: str,
    paid_days: str,
    lop_days: str,
    earnings: list[tuple[str, str]],
    deductions: list[tuple[str, str]],
    reimbursements: str,
    net_pay_words: str,
) -> bytes:
    """Renders a single-page official Payslip PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()

    header_title_style = ParagraphStyle(
        "HeaderTitle",
        parent=styles["Normal"],
        fontSize=15,
        leading=18,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    header_sub_style = ParagraphStyle(
        "HeaderSub",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
        fontName="Helvetica",
        textColor=colors.HexColor("#64748b"),
    )
    period_style = ParagraphStyle(
        "PeriodStyle",
        parent=styles["Normal"],
        alignment=2,  # Right align
        fontSize=9,
        leading=13,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    period_sub_style = ParagraphStyle(
        "PeriodSubStyle",
        parent=styles["Normal"],
        alignment=2,
        fontSize=7.5,
        leading=10,
        fontName="Helvetica",
        textColor=colors.HexColor("#64748b"),
    )
    label_style = ParagraphStyle(
        "LabelStyle",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        fontName="Helvetica",
        textColor=colors.HexColor("#64748b"),
    )
    val_style = ParagraphStyle(
        "ValStyle",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    table_th_style = ParagraphStyle(
        "TableTH",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#334155"),
    )
    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        fontName="Helvetica",
        textColor=colors.HexColor("#1e293b"),
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    table_num_style = ParagraphStyle(
        "TableNum",
        parent=styles["Normal"],
        alignment=2,
        fontSize=8,
        leading=11,
        fontName="Helvetica",
        textColor=colors.HexColor("#1e293b"),
    )
    table_num_bold = ParagraphStyle(
        "TableNumBold",
        parent=styles["Normal"],
        alignment=2,
        fontSize=8,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    footer_style = ParagraphStyle(
        "FooterStyle",
        parent=styles["Normal"],
        alignment=1,
        fontSize=7.5,
        leading=10,
        fontName="Helvetica-Oblique",
        textColor=colors.HexColor("#94a3b8"),
    )

    story: list[Any] = []

    # 1. Company Header
    header_data = [
        [
            Paragraph(f"<b>{company_name}</b>", header_title_style),
            Paragraph("PAYSLIP FOR THE MONTH", period_sub_style),
        ],
        [
            Paragraph(
                f"{company_address}<br/>{company_city_pin}".strip(),
                header_sub_style,
            ),
            Paragraph(f"<b>{period_title}</b>", period_style),
        ],
    ]
    header_table = Table(header_data, colWidths=[340, 183])
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#cbd5e1")))
    story.append(Spacer(1, 10))

    # 2. Employee Summary & Net Pay callout box
    # Left: 2 columns of employee details (label : val)
    # Right: Big net pay box
    half_count = (len(employee_details) + 1) // 2
    left_details = employee_details[:half_count]
    right_details = employee_details[half_count:]

    emp_table_rows = []
    max_rows = max(len(left_details), len(right_details))
    for i in range(max_rows):
        l_label, l_val = left_details[i] if i < len(left_details) else ("", "")
        r_label, r_val = right_details[i] if i < len(right_details) else ("", "")
        emp_table_rows.append(
            [
                Paragraph(l_label, label_style),
                Paragraph(f": {l_val}" if l_val else "", val_style),
                Paragraph(r_label, label_style),
                Paragraph(f": {r_val}" if r_val else "", val_style),
            ]
        )

    emp_details_table = Table(emp_table_rows, colWidths=[90, 100, 75, 95])
    emp_details_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    # Net Pay Callout
    net_box_data = [
        [
            Paragraph(
                f"<font size='14' color='#16a34a'><b>{net_payable}</b></font><br/>"
                "<font size='7.5' color='#64748b'>TOTAL NET PAY</font>",
                ParagraphStyle("NetPayCallout", alignment=1, leading=15),
            )
        ],
        [
            Paragraph(
                f"<font size='7.5' color='#334155'>Paid Days: <b>{paid_days}</b> &nbsp;|&nbsp; LOP: <b>{lop_days}</b></font>",
                ParagraphStyle("NetPayDays", alignment=1, leading=10),
            )
        ],
    ]
    net_box_table = Table(net_box_data, colWidths=[150])
    net_box_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#bbf7d0")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    summary_row = [[emp_details_table, net_box_table]]
    summary_table = Table(summary_row, colWidths=[365, 158])
    summary_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 14))

    # 3. Earnings & Deductions Tables (Side by Side)
    # Total Gross Earnings & Total Deductions
    total_earnings_val = sum(
        (Decimal(str(amt).replace("₹", "").replace(",", "")) for _, amt in earnings),
        Decimal("0.00"),
    )
    total_deductions_val = sum(
        (Decimal(str(amt).replace("₹", "").replace(",", "")) for _, amt in deductions),
        Decimal("0.00"),
    )

    earn_rows: list[list[Any]] = [
        [
            Paragraph("EARNINGS", table_th_style),
            Paragraph("AMOUNT", ParagraphStyle("THNum", parent=table_th_style, alignment=2)),
        ]
    ]
    for code, amt in earnings:
        earn_rows.append([Paragraph(code, table_cell_style), Paragraph(amt, table_num_style)])
    earn_rows.append(
        [
            Paragraph("<b>Gross Earnings</b>", table_cell_bold),
            Paragraph(f"<b>{_fmt_inr(total_earnings_val)}</b>", table_num_bold),
        ]
    )

    ded_rows: list[list[Any]] = [
        [
            Paragraph("DEDUCTIONS", table_th_style),
            Paragraph("AMOUNT", ParagraphStyle("THNum2", parent=table_th_style, alignment=2)),
        ]
    ]
    for code, amt in deductions:
        ded_rows.append([Paragraph(code, table_cell_style), Paragraph(amt, table_num_style)])
    ded_rows.append(
        [
            Paragraph("<b>Total Deductions</b>", table_cell_bold),
            Paragraph(f"<b>{_fmt_inr(total_deductions_val)}</b>", table_num_bold),
        ]
    )

    # Pad the shorter list with empty rows so tables are aligned
    diff = len(earn_rows) - len(ded_rows)
    if diff > 0:
        for _ in range(diff):
            ded_rows.insert(-1, [Paragraph("", table_cell_style), Paragraph("", table_num_style)])
    elif diff < 0:
        for _ in range(-diff):
            earn_rows.insert(-1, [Paragraph("", table_cell_style), Paragraph("", table_num_style)])

    earn_table = Table(earn_rows, colWidths=[175, 80])
    earn_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f8fafc")),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#e2e8f0")),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e2e8f0")),
            ]
        )
    )

    ded_table = Table(ded_rows, colWidths=[175, 80])
    ded_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f8fafc")),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#e2e8f0")),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e2e8f0")),
            ]
        )
    )

    breakdown_table = Table([[earn_table, ded_table]], colWidths=[261, 262])
    breakdown_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(breakdown_table)
    story.append(Spacer(1, 12))

    # Reimbursement note if present
    try:
        reimb_dec = Decimal(str(reimbursements).replace("₹", "").replace(",", ""))
    except Exception:
        reimb_dec = Decimal("0.00")
    if reimb_dec > 0:
        reimb_p = Paragraph(
            f"<font color='#16a34a'>+ Reimbursed Expenses (Tax-exempt): <b>{_fmt_inr(reimb_dec)}</b></font>",
            table_cell_bold,
        )
        story.append(reimb_p)
        story.append(Spacer(1, 8))

    # 4. Total Net Payable Banner
    banner_data = [
        [
            Paragraph(
                "<b>TOTAL NET PAYABLE</b><br/><font size='7.5' color='#64748b'>Gross Earnings - Total Deductions + Approved Reimbursements</font>",
                val_style,
            ),
            Paragraph(
                f"<font size='13' color='#0f172a'><b>{net_payable}</b></font>",
                ParagraphStyle("BannerNum", parent=val_style, alignment=2, leading=16),
            ),
        ]
    ]
    banner_table = Table(banner_data, colWidths=[360, 163])
    banner_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(banner_table)
    story.append(Spacer(1, 8))

    if net_pay_words:
        story.append(
            Paragraph(
                f"<b>Amount In Words :</b> {net_pay_words}",
                ParagraphStyle(
                    "WordsStyle",
                    parent=styles["Normal"],
                    fontSize=8,
                    textColor=colors.HexColor("#475569"),
                ),
            )
        )
        story.append(Spacer(1, 16))

    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "— This is a computer-generated payroll document and requires no signature. —",
            footer_style,
        )
    )

    doc.build(story)
    return buf.getvalue()


def generate_tax_worksheet_pdf(
    company_name: str,
    company_address: str,
    company_city_pin: str,
    period_title: str,
    financial_year: str,
    regime: str,
    employee_name: str,
    designation: str,
    pan: str,
    gross_income_rows: list[tuple[str, str]],
    net_taxable_income: str,
    tax_liability_rows: list[tuple[str, str]],
    total_tax_payable: str,
    monthly_tds: str,
) -> bytes:
    """Renders a single-page official Tax Computation Worksheet PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()

    header_title_style = ParagraphStyle(
        "HeaderTitle",
        parent=styles["Normal"],
        fontSize=15,
        leading=18,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    header_sub_style = ParagraphStyle(
        "HeaderSub",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
        fontName="Helvetica",
        textColor=colors.HexColor("#64748b"),
    )
    period_style = ParagraphStyle(
        "PeriodStyle",
        parent=styles["Normal"],
        alignment=2,
        fontSize=9,
        leading=13,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    period_sub_style = ParagraphStyle(
        "PeriodSubStyle",
        parent=styles["Normal"],
        alignment=2,
        fontSize=7.5,
        leading=10,
        fontName="Helvetica",
        textColor=colors.HexColor("#64748b"),
    )
    section_title = ParagraphStyle(
        "SectionTitle",
        parent=styles["Normal"],
        fontSize=9.5,
        leading=13,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    cell_label = ParagraphStyle(
        "CellLabel",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        fontName="Helvetica",
        textColor=colors.HexColor("#334155"),
    )
    cell_label_bold = ParagraphStyle(
        "CellLabelBold",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    cell_num = ParagraphStyle(
        "CellNum",
        parent=styles["Normal"],
        alignment=2,
        fontSize=8,
        leading=11,
        fontName="Helvetica",
        textColor=colors.HexColor("#1e293b"),
    )
    cell_num_bold = ParagraphStyle(
        "CellNumBold",
        parent=styles["Normal"],
        alignment=2,
        fontSize=8,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    footer_style = ParagraphStyle(
        "FooterStyle",
        parent=styles["Normal"],
        alignment=1,
        fontSize=7.5,
        leading=10,
        fontName="Helvetica-Oblique",
        textColor=colors.HexColor("#94a3b8"),
    )

    story: list[Any] = []

    # 1. Header
    header_data = [
        [
            Paragraph(f"<b>{company_name}</b>", header_title_style),
            Paragraph("INCOME TAX COMPUTATION", period_sub_style),
        ],
        [
            Paragraph(f"{company_address}<br/>{company_city_pin}".strip(), header_sub_style),
            Paragraph(
                f"<b>{period_title} &bull; FY {financial_year}</b><br/>{regime}", period_style
            ),
        ],
    ]
    header_table = Table(header_data, colWidths=[320, 203])
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#cbd5e1")))
    story.append(Spacer(1, 10))

    # 2. Employee Details
    emp_info_data = [
        [
            Paragraph("<b>Employee Name</b>", cell_label),
            Paragraph(f": {employee_name}", cell_label_bold),
            Paragraph("<b>PAN</b>", cell_label),
            Paragraph(f": {pan}", cell_label_bold),
        ],
        [
            Paragraph("<b>Designation</b>", cell_label),
            Paragraph(f": {designation}", cell_label_bold),
            Paragraph("<b>Tax Regime</b>", cell_label),
            Paragraph(f": {regime}", cell_label_bold),
        ],
    ]
    emp_table = Table(emp_info_data, colWidths=[100, 160, 100, 163])
    emp_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(emp_table)
    story.append(Spacer(1, 12))

    # 3. Gross Income & Exemption Breakdown
    story.append(Paragraph("<b>Gross Income & Exemption Breakdown</b>", section_title))
    story.append(Spacer(1, 4))
    gi_table_rows = []
    for label, val in gross_income_rows:
        gi_table_rows.append([Paragraph(label, cell_label), Paragraph(val, cell_num)])
    gi_table_rows.append(
        [
            Paragraph("<b>Net Taxable Income</b>", cell_label_bold),
            Paragraph(f"<b>{net_taxable_income}</b>", cell_num_bold),
        ]
    )
    gi_table = Table(gi_table_rows, colWidths=[383, 140])
    gi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -2), colors.HexColor("#f8fafc")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eff6ff")),
                ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#93c5fd")),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#93c5fd")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e2e8f0")),
            ]
        )
    )
    story.append(gi_table)
    story.append(Spacer(1, 12))

    # 4. Tax Liability Calculation
    story.append(Paragraph("<b>Tax Liability Calculation</b>", section_title))
    story.append(Spacer(1, 4))
    tax_rows = []
    for label, val in tax_liability_rows:
        tax_rows.append([Paragraph(label, cell_label), Paragraph(val, cell_num)])
    tax_rows.append(
        [
            Paragraph("<b>Total Annual Tax Payable</b>", cell_label_bold),
            Paragraph(f"<b>{total_tax_payable}</b>", cell_num_bold),
        ]
    )
    tax_rows.append(
        [
            Paragraph("<b>Monthly TDS Deduction</b>", cell_label_bold),
            Paragraph(f"<b>{monthly_tds}</b>", cell_num_bold),
        ]
    )
    tax_table = Table(tax_rows, colWidths=[383, 140])
    tax_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -3), colors.HexColor("#f8fafc")),
                ("BACKGROUND", (0, -2), (-1, -1), colors.HexColor("#fef2f2")),
                ("LINEABOVE", (0, -2), (-1, -2), 1, colors.HexColor("#fca5a5")),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e2e8f0")),
            ]
        )
    )
    story.append(tax_table)
    story.append(Spacer(1, 16))

    story.append(
        Paragraph(
            "— This is a system-generated official tax worksheet based on your payroll earnings and statutory tax slabs. —",
            footer_style,
        )
    )

    doc.build(story)
    return buf.getvalue()


def generate_salary_certificate_pdf(
    company_name: str,
    company_address: str,
    company_city_pin: str,
    issued_date: str,
    employee_name: str,
    employee_code: str,
    designation: str,
    date_of_joining: str,
    residential_address: str,
    annual_ctc: str,
    monthly_gross: str,
    components: list[tuple[str, str, str]],
    signatory_name: str,
    signatory_title: str,
) -> bytes:
    """Renders a single-page official Salary Certificate PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    styles = getSampleStyleSheet()

    header_title_style = ParagraphStyle(
        "CertHeaderTitle",
        parent=styles["Normal"],
        fontSize=16,
        leading=20,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
        alignment=1,
    )
    header_sub_style = ParagraphStyle(
        "CertHeaderSub",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
        fontName="Helvetica",
        textColor=colors.HexColor("#64748b"),
        alignment=1,
    )
    cert_title = ParagraphStyle(
        "CertTitle",
        parent=styles["Normal"],
        fontSize=12,
        leading=16,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1e293b"),
        alignment=1,
    )
    body_style = ParagraphStyle(
        "CertBody",
        parent=styles["Normal"],
        fontSize=9,
        leading=14,
        fontName="Helvetica",
        textColor=colors.HexColor("#334155"),
    )
    table_th = ParagraphStyle(
        "CertTH",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#334155"),
    )
    table_cell = ParagraphStyle(
        "CertCell",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        fontName="Helvetica",
        textColor=colors.HexColor("#1e293b"),
    )
    table_num = ParagraphStyle(
        "CertNum",
        parent=styles["Normal"],
        alignment=2,
        fontSize=8,
        leading=11,
        fontName="Helvetica",
        textColor=colors.HexColor("#1e293b"),
    )
    footer_style = ParagraphStyle(
        "CertFooter",
        parent=styles["Normal"],
        alignment=1,
        fontSize=7.5,
        leading=10,
        fontName="Helvetica-Oblique",
        textColor=colors.HexColor("#94a3b8"),
    )

    story: list[Any] = []

    # 1. Company Header centered
    story.append(Paragraph(f"<b>{company_name}</b>", header_title_style))
    story.append(Spacer(1, 2))
    story.append(
        Paragraph(
            f"{company_address}, {company_city_pin}".strip(" ,"),
            header_sub_style,
        )
    )
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0f172a")))
    story.append(Spacer(1, 12))

    # 2. Date & Title
    date_p = Paragraph(
        f"<b>Date:</b> {issued_date}", ParagraphStyle("CertDate", parent=body_style, alignment=2)
    )
    story.append(date_p)
    story.append(Spacer(1, 8))
    story.append(Paragraph("<u>TO WHOMSOEVER IT MAY CONCERN</u>", cert_title))
    story.append(Spacer(1, 12))

    # 3. Certification prose
    prose = (
        f"This is to certify that <b>{employee_name}</b> (Employee ID: <b>{employee_code}</b>) is currently "
        f"employed with <b>{company_name}</b> as <b>{designation}</b> since <b>{date_of_joining}</b>. "
        f"The employee's current annual Cost to Company (CTC) is <b>{_fmt_inr(annual_ctc)}</b>, with a monthly gross "
        f"salary of <b>{_fmt_inr(monthly_gross)}</b>. The detailed salary component breakdown is outlined below:"
    )
    story.append(Paragraph(prose, body_style))
    story.append(Spacer(1, 12))

    # 4. Component Table
    comp_rows = [
        [
            Paragraph("Salary Component", table_th),
            Paragraph("Monthly Amount", ParagraphStyle("THM", parent=table_th, alignment=2)),
            Paragraph("Annual Amount", ParagraphStyle("THA", parent=table_th, alignment=2)),
        ]
    ]
    for c_name, m_amt, a_amt in components:
        comp_rows.append(
            [
                Paragraph(c_name, table_cell),
                Paragraph(_fmt_inr(m_amt), table_num),
                Paragraph(_fmt_inr(a_amt), table_num),
            ]
        )
    comp_rows.append(
        [
            Paragraph(
                "<b>Total Gross Salary</b>",
                ParagraphStyle("TCB", parent=table_cell, fontName="Helvetica-Bold"),
            ),
            Paragraph(
                f"<b>{_fmt_inr(monthly_gross)}</b>",
                ParagraphStyle("TNB1", parent=table_num, fontName="Helvetica-Bold"),
            ),
            Paragraph(
                f"<b>{_fmt_inr(annual_ctc)}</b>",
                ParagraphStyle("TNB2", parent=table_num, fontName="Helvetica-Bold"),
            ),
        ]
    )

    comp_table = Table(comp_rows, colWidths=[275, 120, 120])
    comp_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#cbd5e1")),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e2e8f0")),
            ]
        )
    )
    story.append(comp_table)
    story.append(Spacer(1, 24))

    # 5. Signatory Box
    sig_data = [
        [
            Paragraph(
                f"For <b>{company_name}</b><br/><br/><br/>"
                f"<b>{signatory_name}</b><br/>"
                f"<font color='#64748b'>{signatory_title}</font>",
                body_style,
            )
        ]
    ]
    sig_table = Table(sig_data, colWidths=[250])
    sig_table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(sig_table)
    story.append(Spacer(1, 20))

    story.append(
        Paragraph("— This is an official digitally-issued salary certificate. —", footer_style)
    )

    doc.build(story)
    return buf.getvalue()
