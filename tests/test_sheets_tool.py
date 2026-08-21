"""
tests/test_sheets_tool.py — Unit tests for tools/sheets_tool.py.

The Google API client is fully mocked so these tests run without real
credentials or network access.

Tests cover:
  - create_google_sheet: success, missing credentials, API error
  - write_csv_to_sheet: success, empty CSV, API error with retry
  - import_csv_to_google_sheets: end-to-end happy path
  - Retry logic: verifies backoff on HttpError
"""

import sys
import json
import csv
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def creds_file(tmp_path) -> Path:
    """Write a minimal service-account JSON so the file-exists check passes."""
    path = tmp_path / "credentials.json"
    payload = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "key123",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n",
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    path.write_text(json.dumps(payload))
    return path


@pytest.fixture()
def csv_file(tmp_path) -> Path:
    """Write a minimal CSV to import."""
    path = tmp_path / "employees.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Employee ID", "Name", "Department"])
        for i in range(1, 6):
            writer.writerow([f"EMP{i:03d}", f"Person {i}", "Eng"])
    return path


@pytest.fixture()
def patch_config(monkeypatch, creds_file, tmp_path):
    """Point config at the test credentials and share email."""
    import config
    monkeypatch.setattr(config, "GOOGLE_CREDENTIALS_PATH", str(creds_file))
    monkeypatch.setattr(config, "GOOGLE_SHEET_SHARE_EMAIL", "user@example.com")
    monkeypatch.setattr(config, "GOOGLE_API_RETRIES", 3)
    monkeypatch.setattr(config, "GOOGLE_API_BACKOFF_BASE", 0.01)


# ---------------------------------------------------------------------------
# Helper: build a mock Sheets/Drive API chain
# ---------------------------------------------------------------------------

def _make_api_mocks(spreadsheet_id="sheet-abc-123", spreadsheet_url="https://docs.google.com/fake"):
    sheets_service = MagicMock()
    drive_service = MagicMock()

    # sheets.spreadsheets().create().execute()
    create_response = {
        "spreadsheetId": spreadsheet_id,
        "spreadsheetUrl": spreadsheet_url,
    }
    (sheets_service.spreadsheets.return_value
     .create.return_value.execute.return_value) = create_response

    # sheets.spreadsheets().values().update().execute()
    update_response = {"updatedCells": 15, "updatedRows": 6}
    (sheets_service.spreadsheets.return_value
     .values.return_value.update.return_value.execute.return_value) = update_response

    # drive.permissions().create().execute()
    (drive_service.permissions.return_value
     .create.return_value.execute.return_value) = {}

    return sheets_service, drive_service


# ---------------------------------------------------------------------------
# Tests: create_google_sheet
# ---------------------------------------------------------------------------

class TestCreateGoogleSheet:

    def test_success_without_sharing(self, creds_file):
        from tools.sheets_tool import create_google_sheet

        sheets_service, drive_service = _make_api_mocks()

        with patch("tools.sheets_tool._get_credentials", return_value=MagicMock()), \
             patch("tools.sheets_tool.build", side_effect=[sheets_service, drive_service]):
            result = create_google_sheet(
                title="Test Sheet",
                credentials_path=str(creds_file),
                share_email=None,
            )

        assert result["success"] is True
        assert result["data"]["spreadsheet_id"] == "sheet-abc-123"
        # Drive permission create should NOT have been called
        drive_service.permissions.return_value.create.assert_not_called()

    def test_success_with_sharing(self, creds_file):
        from tools.sheets_tool import create_google_sheet

        sheets_service, drive_service = _make_api_mocks()

        with patch("tools.sheets_tool._get_credentials", return_value=MagicMock()), \
             patch("tools.sheets_tool.build", side_effect=[sheets_service, drive_service]):
            result = create_google_sheet(
                title="Shared Sheet",
                credentials_path=str(creds_file),
                share_email="user@example.com",
            )

        assert result["success"] is True
        assert result["data"]["shared_with"] == "user@example.com"
        drive_service.permissions.return_value.create.assert_called_once()

    def test_missing_credentials_file(self, tmp_path):
        from tools.sheets_tool import create_google_sheet

        result = create_google_sheet(
            title="Test",
            credentials_path=str(tmp_path / "nonexistent.json"),
        )
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_api_error_returns_failure(self, creds_file):
        from tools.sheets_tool import create_google_sheet
        from googleapiclient.errors import HttpError

        sheets_service = MagicMock()
        (sheets_service.spreadsheets.return_value
         .create.return_value.execute.side_effect) = HttpError(
            resp=MagicMock(status=500), content=b"Server Error"
        )

        with patch("tools.sheets_tool._get_credentials", return_value=MagicMock()), \
             patch("tools.sheets_tool.build", return_value=sheets_service), \
             patch("tools.sheets_tool.time.sleep"):  # no real sleeping
            result = create_google_sheet(
                title="Test",
                credentials_path=str(creds_file),
                max_attempts=2,
                backoff_base=0.01,
            )

        assert result["success"] is False
        assert "failed" in result["message"].lower()


# ---------------------------------------------------------------------------
# Tests: write_csv_to_sheet
# ---------------------------------------------------------------------------

class TestWriteCsvToSheet:

    def test_success(self, creds_file, csv_file):
        from tools.sheets_tool import write_csv_to_sheet

        sheets_service, _ = _make_api_mocks()

        with patch("tools.sheets_tool._get_credentials", return_value=MagicMock()), \
             patch("tools.sheets_tool.build", return_value=sheets_service):
            result = write_csv_to_sheet(
                spreadsheet_id="sheet-abc-123",
                csv_path=str(csv_file),
                credentials_path=str(creds_file),
            )

        assert result["success"] is True
        assert result["data"]["rows_written"] == 5  # header + 5 data rows, minus header

    def test_empty_csv_returns_failure(self, creds_file, tmp_path):
        from tools.sheets_tool import write_csv_to_sheet

        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("")

        with patch("tools.sheets_tool._get_credentials", return_value=MagicMock()), \
             patch("tools.sheets_tool.build", return_value=MagicMock()):
            result = write_csv_to_sheet(
                spreadsheet_id="sheet-abc-123",
                csv_path=str(empty_csv),
                credentials_path=str(creds_file),
            )

        assert result["success"] is False
        assert "empty" in result["message"].lower()

    def test_api_retry_on_http_error(self, creds_file, csv_file):
        from tools.sheets_tool import write_csv_to_sheet
        from googleapiclient.errors import HttpError

        sheets_service = MagicMock()
        execute_mock = MagicMock()
        # Fail twice then succeed
        execute_mock.side_effect = [
            HttpError(resp=MagicMock(status=429), content=b"Rate limited"),
            HttpError(resp=MagicMock(status=429), content=b"Rate limited"),
            {"updatedCells": 10, "updatedRows": 6},
        ]
        (sheets_service.spreadsheets.return_value
         .values.return_value.update.return_value.execute) = execute_mock

        with patch("tools.sheets_tool._get_credentials", return_value=MagicMock()), \
             patch("tools.sheets_tool.build", return_value=sheets_service), \
             patch("tools.sheets_tool.time.sleep"):
            result = write_csv_to_sheet(
                spreadsheet_id="sheet-abc-123",
                csv_path=str(csv_file),
                credentials_path=str(creds_file),
                max_attempts=4,
                backoff_base=0.01,
            )

        assert result["success"] is True
        assert execute_mock.call_count == 3  # 2 failures + 1 success


# ---------------------------------------------------------------------------
# Tests: import_csv_to_google_sheets (end-to-end)
# ---------------------------------------------------------------------------

class TestImportCsvToGoogleSheets:

    def test_full_flow(self, patch_config, creds_file, csv_file):
        from tools.sheets_tool import import_csv_to_google_sheets

        sheets_service, drive_service = _make_api_mocks()

        with patch("tools.sheets_tool._get_credentials", return_value=MagicMock()), \
             patch("tools.sheets_tool.build", side_effect=[
                 sheets_service, drive_service,  # create_google_sheet
                 sheets_service,                  # write_csv_to_sheet
             ]):
            result = import_csv_to_google_sheets(csv_path=str(csv_file))

        assert result["success"] is True
        assert "spreadsheet_url" in result["data"]
        assert result["data"]["rows_written"] >= 1

    def test_create_fails_propagates(self, patch_config, creds_file, csv_file):
        from tools.sheets_tool import import_csv_to_google_sheets

        sheets_service = MagicMock()
        (sheets_service.spreadsheets.return_value
         .create.return_value.execute.side_effect) = Exception("quota exceeded")

        with patch("tools.sheets_tool._get_credentials", return_value=MagicMock()), \
             patch("tools.sheets_tool.build", return_value=sheets_service), \
             patch("tools.sheets_tool.time.sleep"):
            result = import_csv_to_google_sheets(csv_path=str(csv_file))

        assert result["success"] is False
        assert "quota" in result["message"].lower() or "failed" in result["message"].lower()
