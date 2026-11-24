from app import pdf_font_check


def test_embedded_font_names_drop_subset_prefix_and_decode_spaces():
    pdf = (b"<< /Type /Font /Subtype /Type0 /BaseFont /ABCDEF+Poppins#20Medium >>\n"
           b"<< /Type /Font /BaseFont /ABCDEF+Poppins#20Medium /FontDescriptor 9 0 R >>\n"
           b"<< /Type /Font /BaseFont/GHIJKL+Carlito >>")
    assert pdf_font_check.embedded_font_names(pdf) == ["Carlito", "Poppins Medium"]


def test_substituted_and_missing_fonts_are_reported(monkeypatch):
    monkeypatch.setattr(pdf_font_check, "installed_faces", lambda: {("Poppins", "Regular"), ("DejaVu Sans", "Book")})

    class FakeHTML:
        def __init__(self, string):
            pass

        def write_pdf(self, uncompressed_pdf):
            assert uncompressed_pdf is True
            return b"/BaseFont /ABCDEF+Poppins /BaseFont /GHIJKL+DejaVu#20Sans"

    import sys
    import types
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=FakeHTML))
    found = pdf_font_check.problems()
    assert found[0].startswith("fonts not installed: Carlito Bold, Carlito Regular, Poppins Bold, Poppins Medium")
    assert found[1] == "WeasyPrint used other fonts: DejaVu Sans"
