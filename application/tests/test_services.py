import pytest
from application.services.export import ExportService


def test_filename_to_ext():
    filename = 'foo.pdfx'
    assert ExportService._extract_extension(filename) == 'pdfx'