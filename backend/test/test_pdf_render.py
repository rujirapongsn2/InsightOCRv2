from app.services.pdf_render import find_pdftoppm_page_png


def test_finds_zero_padded_poppler_page_output(tmp_path):
    output_prefix = str(tmp_path / "page")
    expected = tmp_path / "page-01.png"
    expected.write_bytes(b"png")

    assert find_pdftoppm_page_png(output_prefix, 1) == str(expected)


def test_finds_unpadded_poppler_page_output(tmp_path):
    output_prefix = str(tmp_path / "page")
    expected = tmp_path / "page-10.png"
    expected.write_bytes(b"png")

    assert find_pdftoppm_page_png(output_prefix, 10) == str(expected)


def test_ignores_different_page_numbers(tmp_path):
    output_prefix = str(tmp_path / "page")
    (tmp_path / "page-02.png").write_bytes(b"png")

    assert find_pdftoppm_page_png(output_prefix, 1) is None
