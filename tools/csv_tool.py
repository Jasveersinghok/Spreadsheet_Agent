
import csv
import os
from datetime import date, timedelta
from pathlib import Path
from random import randint, uniform
from typing import Any, Dict, List, Optional

from faker import Faker

fake = Faker()

DEPARTMENTS: List[str] = [
    "Engineering",
    "Product",
    "Design",
    "Marketing",
    "Sales",
    "Finance",
    "HR",
    "Legal",
    "Operations",
    "Customer Success",
]

LOCATIONS: List[str] = [
    "New York",
    "San Francisco",
    "Austin",
    "Chicago",
    "Seattle",
    "Boston",
    "London",
    "Berlin",
    "Singapore",
    "Remote",
]

CSV_COLUMNS: List[str] = [
    "Employee ID",
    "Name",
    "Department",
    "Email",
    "Salary",
    "Hire Date",
    "Location",
]


def _writable_path(preferred: Path, fallback: Path) -> Optional[Path]:
    for candidate in (preferred, fallback):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            test_file = candidate / ".write_test"
            test_file.touch()
            test_file.unlink()
            return candidate
        except OSError:
            continue
    return None


def generate_employee_csv(
    num_rows: int = 20,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    from config import CSV_DEFAULT_NUM_ROWS, OUTPUT_DIR, FALLBACK_OUTPUT_DIR

    num_rows = max(num_rows, CSV_DEFAULT_NUM_ROWS)

    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        writable_dir = _writable_path(OUTPUT_DIR, FALLBACK_OUTPUT_DIR)
        if writable_dir is None:
            return {
                "success": False,
                "message": (
                    f"No writable output directory found. "
                    f"Tried: {OUTPUT_DIR} and {FALLBACK_OUTPUT_DIR}"
                ),
                "data": None,
            }
        target = writable_dir / "employees.csv"

    try:
        rows = _generate_rows(num_rows)
        _write_csv(target, rows)
        return {
            "success": True,
            "message": f"CSV generated successfully at {target} ({num_rows} rows)",
            "data": {"file_path": str(target), "num_rows": num_rows},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "message": f"CSV generation failed: {exc}",
            "data": None,
        }


def _generate_rows(num_rows: int) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    base_date = date(2015, 1, 1)
    for i in range(1, num_rows + 1):
        hire_date = base_date + timedelta(days=randint(0, 365 * 9))
        name = fake.name()
        department = fake.random_element(DEPARTMENTS)
        salary = round(uniform(45_000, 180_000), 2)
        rows.append(
            {
                "Employee ID": f"EMP{i:03d}",
                "Name": name,
                "Department": department,
                "Email": fake.email(),
                "Salary": f"{salary:.2f}",
                "Hire Date": hire_date.strftime("%Y-%m-%d"),
                "Location": fake.random_element(LOCATIONS),
            }
        )
    return rows


def _write_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(file_path: str) -> List[Dict[str, str]]:
    with open(file_path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
