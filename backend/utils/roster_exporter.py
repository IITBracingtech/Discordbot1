import csv
import io
from typing import Sequence
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def generate_roster_pdf(server_name: str, member_data: Sequence[tuple[str, str]], title_suffix: str = "") -> io.BytesIO:
    """Generates a PDF buffer containing team members and their assigned roles in 'Name - Roles' format."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'RosterTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'RosterSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569'),
        spaceAfter=14
    )
    cell_header_style = ParagraphStyle(
        'CellHeader',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        fontName='Helvetica-Bold',
        textColor=colors.white
    )
    cell_body_name = ParagraphStyle(
        'CellBodyName',
        parent=styles['Normal'],
        fontSize=9.5,
        leading=12.5,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0F172A')
    )
    cell_body_roles = ParagraphStyle(
        'CellBodyRoles',
        parent=styles['Normal'],
        fontSize=9.5,
        leading=12.5,
        textColor=colors.HexColor('#334155')
    )

    elements = []
    doc_title = f"IIT Bombay Racing — Team Roster{title_suffix}"
    elements.append(Paragraph(doc_title, title_style))
    elements.append(Paragraph(f"Server: {server_name}  •  Total Members: {len(member_data)}", subtitle_style))

    table_data = [[
        Paragraph("Member Name", cell_header_style),
        Paragraph("Assigned Roles / Tags (Name - Roles)", cell_header_style)
    ]]

    for name, roles in member_data:
        formatted_roles = roles if roles else "No Roles"
        table_data.append([
            Paragraph(name, cell_body_name),
            Paragraph(formatted_roles, cell_body_roles)
        ])

    col_widths = [190, 350]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
    ]))

    elements.append(t)
    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_roster_csv(member_data: Sequence[tuple[str, str]]) -> io.BytesIO:
    """Generates a CSV buffer containing team members and their assigned roles."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Member Name", "Roles", "Format (Name - Roles)"])
    for name, roles in member_data:
        role_str = roles if roles else "No Roles"
        writer.writerow([name, role_str, f"{name} - {role_str}"])

    bytes_buffer = io.BytesIO(buffer.getvalue().encode("utf-8"))
    bytes_buffer.seek(0)
    return bytes_buffer
