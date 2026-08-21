"""
tests/test_csv_tool.py — Unit tests for tools/csv_tool.py.

Tests run without LibreOffice, Google credentials, or network access.
"""

import csv
import os
import sys
from pathlib import Path

import pytest

# Make the agent package importable from the test directory
sys.path.insert(0, str(Path(__file__).parent.parent))

# Patch config before importing csv_tool so we don't need a real .env
import unittest.mock as mock

FAKE_OUTPUT_DIR = Path("/tmp/fake_output_csv_tests")
FAKE_FALLBACK_DIR = Path("/tmp/fake_fallback_csv_tests")


@pytest.fixture(autouse=True)
def patch_config(tmp_path, monkeypatch):
    """Redirect output dirs to tmp_path for every test."""
    import config
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "FALLBACK_OUTPUT_DIR", tmp_path / "fallback")
    monkeypatch.setattr(config, "CSV_DEFAULT_NUM_ROWS", 20)


def test_generate_csv_success(tmp_path):
    """CSV tool should generate a file with the correct number of rows and columns."""
    from tools.csv_tool import generate_employee_csv, CSV_COLUMNS

    out_path = tmp_path / "employees.csv"
    result = generate_employee_csv(num_rows=5, output_path=str(out_path))

    assert result["success"] is True
    assert Path(result["data"]["file_path"]).is_file()

    with open(result["data"]["file_path"], newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    # Even though we asked for 5, the minimum is 20
    assert len(rows) >= 20
    for col in CSV_COLUMNS:
        assert col in rows[0], f"Missing column: {col}"


def test_generate_csv_employee_id_format(tmp_path):
    """Employee IDs should follow the EMP001, EMP002... pattern."""
    from tools.csv_tool import generate_employee_csv

    out_path = tmp_path / "emp.csv"
    result = generate_employee_csv(num_rows=20, output_path=str(out_path))
    assert result["success"] is True

    with open(result["data"]["file_path"], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    for i, row in enumerate(rows, 1):
        assert row["Employee ID"] == f"EMP{i:03d}", (
            f"Row {i} has unexpected Employee ID: {row['Employee ID']}"
        )


def test_generate_csv_salary_range(tmp_path):
    """Salaries should be numeric and within the expected range."""
    from tools.csv_tool import generate_employee_csv

    out_path = tmp_path / "sal.csv"
    result = generate_employee_csv(num_rows=20, output_path=str(out_path))
    assert result["success"] is True

    with open(result["data"]["file_path"], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    for row in rows:
        salary = float(row["Salary"])
        assert 45_000 <= salary <= 180_000, f"Salary out of range: {salary}"


def test_generate_csv_default_location(tmp_path, monkeypatch):
    """When output_path is None, file should land in the configured output dir."""
    import config
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "auto_output")
    monkeypatch.setattr(config, "FALLBACK_OUTPUT_DIR", tmp_path / "fallback")

    from tools.csv_tool import generate_employee_csv

    result = generate_employee_csv()
    assert result["success"] is True
    file_path = Path(result["data"]["file_path"])
    assert file_path.exists()
    assert file_path.suffix == ".csv"


def test_generate_csv_fallback_dir(tmp_path, monkeypatch):
    """If primary output dir is not writable, should fall back gracefully."""
    import config
    import builtins
    import os

    # Make primary dir creation fail
    bad_dir = tmp_path / "no_permission"
    good_dir = tmp_path / "fallback_ok"

    monkeypatch.setattr(config, "OUTPUT_DIR", bad_dir)
    monkeypatch.setattr(config, "FALLBACK_OUTPUT_DIR", good_dir)

    # Patch _writable_path to simulate bad primary dir
    original_mkdir = Path.mkdir

    call_count = [0]

    def fake_mkdir(self, *args, **kwargs):
        call_count[0] += 1
        if str(self) == str(bad_dir) and call_count[0] == 1:
            raise OSError("Permission denied")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    from tools import csv_tool
    # Re-import to pick up the monkeypatched config
    result = csv_tool.generate_employee_csv()
    assert result["success"] is True


def test_generate_csv_no_writable_dir(tmp_path, monkeypatch):
    """When no directory is writable, return a clear failure."""
    import config

    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "bad1")
    monkeypatch.setattr(config, "FALLBACK_OUTPUT_DIR", tmp_path / "bad2")

    from tools.csv_tool import _writable_path
    # Both dirs are "unwritable" by patching mkdir globally
    with mock.patch.object(Path, "mkdir", side_effect=OSError("denied")):
        result = _writable_path(tmp_path / "bad1", tmp_path / "bad2")
    assert result is None


def test_read_csv(tmp_path):
    """read_csv should return a list of dicts matching the written data."""
    from tools.csv_tool import generate_employee_csv, read_csv

    out_path = tmp_path / "read_test.csv"
    generate_employee_csv(num_rows=20, output_path=str(out_path))
    rows = read_csv(str(out_path))
    assert isinstance(rows, list)
    assert len(rows) >= 20
    assert "Employee ID" in rows[0]
