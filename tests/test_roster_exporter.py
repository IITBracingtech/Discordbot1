import pytest
from backend.utils.roster_exporter import generate_roster_pdf, generate_roster_csv


def test_generate_roster_pdf():
    member_data = [
        ("Srikar", "Mech, DE"),
        ("Narayana Malla", "AMs, Manager"),
        ("Member Three", "No Roles")
    ]
    pdf_buf = generate_roster_pdf("Test Server", member_data, title_suffix=" (Test)")
    content = pdf_buf.getvalue()
    assert len(content) > 1000
    assert content.startswith(b"%PDF")


def test_generate_roster_csv():
    member_data = [
        ("Srikar", "Mech, DE"),
        ("Narayana Malla", "AMs, Manager")
    ]
    csv_buf = generate_roster_csv(member_data)
    content = csv_buf.getvalue().decode("utf-8")
    assert "Member Name,Roles,Format (Name - Roles)" in content
    assert "Srikar,\"Mech, DE\",\"Srikar - Mech, DE\"" in content
    assert "Narayana Malla,\"AMs, Manager\",\"Narayana Malla - AMs, Manager\"" in content
