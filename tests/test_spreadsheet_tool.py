"""
tests/test_spreadsheet_tool.py — Unit tests for tools/spreadsheet_tool.py.

The UNO bridge (pyuno / soffice.exe) is fully mocked so these tests run
on any machine without LibreOffice installed.

Tests cover:
  - Format → UNO FilterName mapping for xlsx, csv, ods
  - Default format (xlsx) when no format is specified
  - Successful import-and-save flow (UNO calls mocked)
  - Error handling when soffice.exe is not found
  - Error handling when UNO socket connection fails after retries
"""

import sys
import json
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Helpers to build a fake UNO environment
# ---------------------------------------------------------------------------

def _make_fake_doc():
    """Return a mock object that looks like a LibreOffice document."""
    doc = MagicMock()
    doc.storeToURL = MagicMock()
    doc.close = MagicMock()
    return doc


def _make_fake_desktop(doc):
    """Return a mock desktop that returns *doc* from loadComponentFromURL."""
    desktop = MagicMock()
    desktop.loadComponentFromURL = MagicMock(return_value=doc)
    return desktop


# ---------------------------------------------------------------------------
# Format-mapping tests (no mocking of LibreOffice needed)
# ---------------------------------------------------------------------------

class TestFormatMapping:
    """Verify the format → UNO FilterName mapping table."""

    def test_xlsx_filter(self):
        from tools.spreadsheet_tool import FORMAT_TO_FILTER
        assert FORMAT_TO_FILTER["xlsx"] == "Calc MS Excel 2007 XML"

    def test_csv_filter(self):
        from tools.spreadsheet_tool import FORMAT_TO_FILTER
        assert FORMAT_TO_FILTER["csv"] == "Text - txt - csv (StarCalc)"

    def test_ods_filter(self):
        from tools.spreadsheet_tool import FORMAT_TO_FILTER
        assert FORMAT_TO_FILTER["ods"] == "calc8"

    def test_all_formats_have_extension(self):
        from tools.spreadsheet_tool import FORMAT_TO_FILTER, FORMAT_TO_EXTENSION
        for fmt in FORMAT_TO_FILTER:
            assert fmt in FORMAT_TO_EXTENSION, f"Missing extension for format: {fmt}"

    def test_unknown_format_returns_failure(self, tmp_path):
        from tools.spreadsheet_tool import LibreOfficeAdapter
        import config

        adapter = LibreOfficeAdapter(
            soffice_path="fake_soffice.exe",
            connect_retries=1,
        )
        # Monkeypatch so we don't actually launch anything
        with patch.object(adapter, "_launch_soffice", return_value=None), \
             patch.object(adapter, "_connect_with_retry", return_value=MagicMock()):
            result = adapter.import_csv_and_save(
                csv_path=str(tmp_path / "dummy.csv"),
                output_format="pdf",  # type: ignore[arg-type]
            )
        assert result["success"] is False
        assert "pdf" in result["message"]


class TestDefaultFormat:
    """Verify that the default output format is xlsx."""

    def test_import_csv_to_spreadsheet_defaults_to_xlsx(self, tmp_path):
        """import_csv_to_spreadsheet should use xlsx by default."""
        from tools.spreadsheet_tool import import_csv_to_spreadsheet, FORMAT_TO_FILTER

        fake_doc = _make_fake_doc()
        fake_desktop = _make_fake_desktop(fake_doc)

        csv_file = tmp_path / "employees.csv"
        csv_file.write_text("a,b\n1,2\n")

        with patch("tools.spreadsheet_tool.LibreOfficeAdapter._launch_soffice"), \
             patch("tools.spreadsheet_tool.LibreOfficeAdapter._connect_with_retry",
                   return_value=fake_desktop), \
             patch("tools.spreadsheet_tool.LibreOfficeAdapter._open_csv",
                   return_value=fake_doc), \
             patch("tools.spreadsheet_tool.LibreOfficeAdapter._save_document") as mock_save, \
             patch("tools.spreadsheet_tool.LibreOfficeAdapter.close"):
            result = import_csv_to_spreadsheet(csv_path=str(csv_file))

        assert result["success"] is True
        assert result["data"]["output_format"] == "xlsx"


# ---------------------------------------------------------------------------
# LibreOfficeAdapter happy-path
# ---------------------------------------------------------------------------

class TestLibreOfficeAdapterHappyPath:

    @pytest.fixture()
    def csv_file(self, tmp_path):
        p = tmp_path / "test.csv"
        p.write_text("Employee ID,Name\nEMP001,Alice\n")
        return p

    def test_import_and_save_xlsx(self, tmp_path, csv_file):
        from tools.spreadsheet_tool import LibreOfficeAdapter

        fake_doc = _make_fake_doc()
        fake_desktop = _make_fake_desktop(fake_doc)
        adapter = LibreOfficeAdapter(soffice_path="fake_soffice.exe", connect_retries=1)

        save_path = tmp_path / "out.xlsx"

        with patch.object(adapter, "_launch_soffice"), \
             patch.object(adapter, "_connect_with_retry", return_value=fake_desktop), \
             patch.object(adapter, "_open_csv", return_value=fake_doc), \
             patch.object(adapter, "_save_document") as mock_save:
            result = adapter.import_csv_and_save(
                csv_path=str(csv_file),
                output_format="xlsx",
                output_path=str(save_path),
            )

        assert result["success"] is True
        assert result["data"]["output_format"] == "xlsx"
        mock_save.assert_called_once_with(fake_doc, save_path, "xlsx")
        fake_doc.close.assert_called_once()

    def test_import_and_save_ods(self, tmp_path, csv_file):
        from tools.spreadsheet_tool import LibreOfficeAdapter

        fake_doc = _make_fake_doc()
        fake_desktop = _make_fake_desktop(fake_doc)
        adapter = LibreOfficeAdapter(soffice_path="fake_soffice.exe", connect_retries=1)

        save_path = tmp_path / "out.ods"

        with patch.object(adapter, "_launch_soffice"), \
             patch.object(adapter, "_connect_with_retry", return_value=fake_desktop), \
             patch.object(adapter, "_open_csv", return_value=fake_doc), \
             patch.object(adapter, "_save_document") as mock_save:
            result = adapter.import_csv_and_save(
                csv_path=str(csv_file),
                output_format="ods",
                output_path=str(save_path),
            )

        assert result["success"] is True
        assert result["data"]["output_format"] == "ods"

    def test_import_and_save_csv_format(self, tmp_path, csv_file):
        from tools.spreadsheet_tool import LibreOfficeAdapter

        fake_doc = _make_fake_doc()
        fake_desktop = _make_fake_desktop(fake_doc)
        adapter = LibreOfficeAdapter(soffice_path="fake_soffice.exe", connect_retries=1)

        save_path = tmp_path / "out.csv"

        with patch.object(adapter, "_launch_soffice"), \
             patch.object(adapter, "_connect_with_retry", return_value=fake_desktop), \
             patch.object(adapter, "_open_csv", return_value=fake_doc), \
             patch.object(adapter, "_save_document") as mock_save:
            result = adapter.import_csv_and_save(
                csv_path=str(csv_file),
                output_format="csv",
                output_path=str(save_path),
            )

        assert result["success"] is True
        assert result["data"]["output_format"] == "csv"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestLibreOfficeAdapterErrors:

    def test_soffice_not_found(self, tmp_path):
        from tools.spreadsheet_tool import LibreOfficeAdapter

        adapter = LibreOfficeAdapter(
            soffice_path=str(tmp_path / "nonexistent_soffice.exe"),
            connect_retries=1,
        )
        csv_file = tmp_path / "t.csv"
        csv_file.write_text("a,b\n1,2\n")

        # _launch_soffice is called first; let it run for real (file won't exist)
        with patch("socket.socket") as mock_socket:
            mock_socket.return_value.__enter__.return_value.connect_ex.return_value = 1
            result = adapter.import_csv_and_save(
                csv_path=str(csv_file),
                output_format="xlsx",
                output_path=str(tmp_path / "out.xlsx"),
            )

        assert result["success"] is False
        assert "soffice" in result["message"].lower() or "not found" in result["message"].lower()

    def test_connection_failure_after_retries(self, tmp_path):
        from tools.spreadsheet_tool import LibreOfficeAdapter

        adapter = LibreOfficeAdapter(
            soffice_path="fake_soffice.exe",
            connect_retries=2,
            backoff_base=0.01,  # fast for tests
        )
        csv_file = tmp_path / "t.csv"
        csv_file.write_text("a,b\n1,2\n")

        with patch.object(adapter, "_launch_soffice"), \
             patch.object(adapter, "_connect_with_retry",
                          side_effect=ConnectionError("UNO socket refused")):
            result = adapter.import_csv_and_save(
                csv_path=str(csv_file),
                output_format="xlsx",
                output_path=str(tmp_path / "out.xlsx"),
            )

        assert result["success"] is False
        assert "failed" in result["message"].lower()

    def test_exception_from_open_csv(self, tmp_path):
        from tools.spreadsheet_tool import LibreOfficeAdapter

        adapter = LibreOfficeAdapter(soffice_path="fake_soffice.exe", connect_retries=1)
        csv_file = tmp_path / "t.csv"
        csv_file.write_text("a,b\n1,2\n")

        with patch.object(adapter, "_launch_soffice"), \
             patch.object(adapter, "_connect_with_retry", return_value=MagicMock()), \
             patch.object(adapter, "_open_csv", side_effect=RuntimeError("bad csv")):
            result = adapter.import_csv_and_save(
                csv_path=str(csv_file),
                output_format="xlsx",
                output_path=str(tmp_path / "out.xlsx"),
            )

        assert result["success"] is False
        assert "bad csv" in result["message"]


# ---------------------------------------------------------------------------
# SpreadsheetTool abstract interface
# ---------------------------------------------------------------------------

class TestSpreadsheetToolInterface:

    def test_abstract_class_cannot_be_instantiated(self):
        from tools.spreadsheet_tool import SpreadsheetTool
        with pytest.raises(TypeError):
            SpreadsheetTool()  # type: ignore[abstract]

    def test_libreoffice_adapter_is_subclass(self):
        from tools.spreadsheet_tool import SpreadsheetTool, LibreOfficeAdapter
        assert issubclass(LibreOfficeAdapter, SpreadsheetTool)

    def test_get_spreadsheet_tool_returns_libreoffice_adapter(self):
        from tools.spreadsheet_tool import get_spreadsheet_tool, LibreOfficeAdapter
        tool = get_spreadsheet_tool(soffice_path="fake.exe")
        assert isinstance(tool, LibreOfficeAdapter)
