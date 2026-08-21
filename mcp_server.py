import asyncio
import sys
from typing import Any, Dict, Literal, Optional

from mcp.server.fastmcp import FastMCP

from tools.csv_tool import generate_employee_csv as _generate_csv
from tools.spreadsheet_tool import import_csv_to_spreadsheet
from tools.sheets_tool import import_csv_to_google_sheets as _import_to_sheets

mcp = FastMCP(
    name="spreadsheet-import-agent",
    instructions=(
        "An agent that generates employee CSV data, imports it into "
        "LibreOffice Calc, and uploads it to Google Sheets. "
        "Use generate_employee_csv first to create the CSV, then call "
        "import_csv_to_libreoffice and import_csv_to_google_sheets with "
        "the returned file path."
    ),
)


@mcp.tool()
def generate_employee_csv(
    num_rows: int = 20,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a CSV file with realistic employee data using Faker."""
    return _generate_csv(num_rows=num_rows, output_path=output_path)


@mcp.tool()
def import_csv_to_libreoffice(
    csv_path: str,
    output_format: Literal["xlsx", "csv", "ods"] = "xlsx",
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Open a CSV in LibreOffice Calc and save it in the requested format."""
    return import_csv_to_spreadsheet(
        csv_path=csv_path,
        output_format=output_format,  # type: ignore[arg-type]
        output_path=output_path,
    )


@mcp.tool()
def import_csv_to_google_sheets(
    csv_path: str,
    sheet_title: str = "Employee Data",
) -> Dict[str, Any]:
    """Create a Google Spreadsheet and populate it with data from the CSV."""
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    final_title = f"{sheet_title} - {timestamp}"
    return _import_to_sheets(csv_path=csv_path, sheet_title=final_title)


if __name__ == "__main__":
    mcp.run(transport="stdio")
