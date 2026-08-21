import os
from pathlib import Path
from dotenv import load_dotenv

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=False)
load_dotenv(_here.parent / ".env", override=False)

GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL: str = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL: str = os.environ.get("GROQ_BASE_URL", "https://api.groq.com")

SOFFICE_PATH: str = os.environ.get(
    "SOFFICE_PATH",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
)
UNO_HOST: str = os.environ.get("UNO_HOST", "localhost")
UNO_PORT: int = int(os.environ.get("UNO_PORT", "2002"))

UNO_CONNECT_RETRIES: int = int(os.environ.get("UNO_CONNECT_RETRIES", "8"))
UNO_CONNECT_BACKOFF_BASE: float = float(os.environ.get("UNO_CONNECT_BACKOFF_BASE", "1.5"))

OUTPUT_DIR: Path = Path(os.environ.get("OUTPUT_DIR", str(_here / "output")))
FALLBACK_OUTPUT_DIR: Path = Path.home() / "Documents"

DEFAULT_SPREADSHEET_FORMAT: str = os.environ.get("DEFAULT_SPREADSHEET_FORMAT", "xlsx")

GOOGLE_CREDENTIALS_PATH: str = os.environ.get(
    "GOOGLE_CREDENTIALS_PATH",
    str(_here / "credentials.json"),
)
GOOGLE_SHEET_SHARE_EMAIL: str = os.environ.get("GOOGLE_SHEET_SHARE_EMAIL", "")
GOOGLE_DRIVE_FOLDER_ID: str = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

GOOGLE_API_RETRIES: int = int(os.environ.get("GOOGLE_API_RETRIES", "4"))
GOOGLE_API_BACKOFF_BASE: float = float(os.environ.get("GOOGLE_API_BACKOFF_BASE", "2.0"))

CSV_DEFAULT_NUM_ROWS: int = int(os.environ.get("CSV_DEFAULT_NUM_ROWS", "20"))

LOG_FILE: str = os.environ.get("LOG_FILE", str(_here / "output" / "agent.log"))
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
