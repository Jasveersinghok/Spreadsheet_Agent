
import re
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build  # type: ignore[import]
from googleapiclient.errors import HttpError  # type: ignore[import]

SCOPES: List[str] = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _retry(
    func: Any,
    *args: Any,
    max_attempts: int = 4,
    backoff_base: float = 2.0,
    **kwargs: Any,
) -> Any:
    last_exc: Exception = RuntimeError("No attempt made")
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except HttpError as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise
            wait = backoff_base ** attempt
            time.sleep(wait)
    raise last_exc


def _get_user_credentials():
    from google.oauth2.credentials import Credentials as UserCredentials
    from google.auth.transport.requests import Request

    agent_dir = Path(__file__).parent.parent
    token_path = agent_dir / "token.json"
    if not token_path.is_file():
        token_path = Path(__file__).parent / "token.json"
    if not token_path.is_file():
        return None

    creds = UserCredentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return creds if (creds and creds.valid) else None


def create_google_sheet(
    title: str,
    credentials_path: str,
    share_email: Optional[str] = None,
    max_attempts: int = 5,
    backoff_base: float = 2.0,
) -> Dict[str, Any]:
    from config import GOOGLE_CREDENTIALS_PATH, GOOGLE_SHEET_SHARE_EMAIL, GOOGLE_DRIVE_FOLDER_ID

    if not GOOGLE_DRIVE_FOLDER_ID:
        return {
            "success": False,
            "message": (
                "GOOGLE_DRIVE_FOLDER_ID is missing from .env.\n"
                "Create a folder in Google Drive, share it with your service account "
                "as Editor, and put the folder ID in .env as GOOGLE_DRIVE_FOLDER_ID."
            ),
            "data": None,
        }

    folder_id = GOOGLE_DRIVE_FOLDER_ID
    _url_match = re.search(r"/folders/([a-zA-Z0-9_-]+)", folder_id)
    if _url_match:
        folder_id = _url_match.group(1)

    try:
        creds = _get_user_credentials()

        if creds is None:
            return {
                "success": False,
                "message": (
                    "token.json not found. Run 'python oauth_login.py' once to authorise "
                    "the agent to create Google Sheets under your account."
                ),
                "data": None,
            }

        drive_service  = build("drive",  "v3", credentials=creds, cache_discovery=False)
        sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)

        file_metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": [folder_id],
        }
        response = _retry(
            drive_service.files()
            .create(body=file_metadata, fields="id")
            .execute,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )
        spreadsheet_id = response["id"]
        spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

        if GOOGLE_SHEET_SHARE_EMAIL:
            try:
                _retry(
                    drive_service.permissions()
                    .create(
                        fileId=spreadsheet_id,
                        body={
                            "type": "user",
                            "role": "writer",
                            "emailAddress": GOOGLE_SHEET_SHARE_EMAIL,
                        },
                        sendNotificationEmail=False,
                    )
                    .execute,
                    max_attempts=max_attempts,
                    backoff_base=backoff_base,
                )
            except Exception:  # noqa: BLE001
                pass  # non-fatal — sheet still created

        return {
            "success": True,
            "message": f"Google Sheet created: {title} ({spreadsheet_id})",
            "data": {
                "spreadsheet_id": spreadsheet_id,
                "spreadsheet_url": spreadsheet_url,
                "shared_with": GOOGLE_SHEET_SHARE_EMAIL,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "message": f"Failed to create Google Sheet: {exc}",
            "data": None,
        }


def write_csv_to_sheet(
    spreadsheet_id: str,
    csv_path: str,
    credentials_path: str,
    sheet_name: str = "Sheet1",
    max_attempts: int = 4,
    backoff_base: float = 2.0,
) -> Dict[str, Any]:
    import csv as _csv

    try:
        creds = _get_user_credentials()
        if creds is None:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=SCOPES
            )

        sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)

        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = _csv.reader(fh)
            values = list(reader)

        if not values:
            return {
                "success": False,
                "message": "CSV file is empty — nothing to write.",
                "data": None,
            }

        body = {"values": values}
        range_notation = f"{sheet_name}!A1"

        result = _retry(
            sheets_service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueInputOption="RAW",
                body=body,
            )
            .execute,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )

        updated_cells = result.get("updatedCells", 0)
        return {
            "success": True,
            "message": (
                f"Wrote {len(values) - 1} rows ({updated_cells} cells) "
                f"to Google Sheet {spreadsheet_id}"
            ),
            "data": {
                "spreadsheet_id": spreadsheet_id,
                "rows_written": len(values) - 1,
                "updated_cells": updated_cells,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "message": f"Failed to write data to Google Sheet: {exc}",
            "data": None,
        }


def import_csv_to_google_sheets(
    csv_path: str,
    sheet_title: str = "Employee Data",
) -> Dict[str, Any]:
    from config import (
        GOOGLE_CREDENTIALS_PATH,
        GOOGLE_SHEET_SHARE_EMAIL,
        GOOGLE_API_RETRIES,
        GOOGLE_API_BACKOFF_BASE,
    )

    create_result = create_google_sheet(
        title=sheet_title,
        credentials_path=GOOGLE_CREDENTIALS_PATH,
        share_email=GOOGLE_SHEET_SHARE_EMAIL or None,
        max_attempts=GOOGLE_API_RETRIES,
        backoff_base=GOOGLE_API_BACKOFF_BASE,
    )

    if not create_result["success"]:
        return create_result

    spreadsheet_id: str = create_result["data"]["spreadsheet_id"]
    spreadsheet_url: str = create_result["data"]["spreadsheet_url"]

    write_result = write_csv_to_sheet(
        spreadsheet_id=spreadsheet_id,
        csv_path=csv_path,
        credentials_path=GOOGLE_CREDENTIALS_PATH,
        max_attempts=GOOGLE_API_RETRIES,
        backoff_base=GOOGLE_API_BACKOFF_BASE,
    )

    if not write_result["success"]:
        return {
            "success": False,
            "message": (
                f"Sheet created ({spreadsheet_id}) but data write failed: "
                f"{write_result['message']}"
            ),
            "data": {"spreadsheet_id": spreadsheet_id, "spreadsheet_url": spreadsheet_url},
        }

    try:
        webbrowser.open(spreadsheet_url)
    except Exception:  # noqa: BLE001
        pass

    return {
        "success": True,
        "message": (
            f"Google Sheet created and populated. "
            f"URL: {spreadsheet_url}"
        ),
        "data": {
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_url": spreadsheet_url,
            "rows_written": write_result["data"]["rows_written"],
            "shared_with": GOOGLE_SHEET_SHARE_EMAIL or None,
        },
    }
