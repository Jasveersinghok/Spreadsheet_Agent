# 📊 Autonomous Spreadsheet Import Agent

> **One command. CSV → LibreOffice Calc → Google Sheets. Fully autonomous.**

An AI-powered agent that generates realistic employee CSV data, imports it into a local spreadsheet application, and uploads it to Google Sheets — all from a single natural-language prompt. No Microsoft Excel license needed: this project uses **LibreOffice Calc** (free, open-source) which reads and writes `.xlsx`, `.csv`, and `.ods` files identically to Excel.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         USER (CLI)                                   │
│                    python main.py "your prompt"                      │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        main.py                                       │
│  • Pre-flight checks (API key, soffice.exe, credentials.json)        │
│  • Initialises SessionMemory + StepTracker                           │
│  • Calls planner.run_sync(prompt)                                    │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      planner.py (MCP Client)                         │
│                                                                      │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────────┐      │
│  │  PHASE 1    │    │   PHASE 2    │    │   PHASE 3           │      │
│  │  Planning   │───▶│  Execution   │───▶│   Final Report      │      │
│  │  (Groq LLM) │    │  (Tool Calls)│    │   (StepTracker)     │      │
│  └─────────────┘    └──────┬───────┘    └─────────────────────┘      │
│                            │ session.call_tool()                     │
│                            │ (MCP stdio transport)                   │
└────────────────────────────┼─────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                   mcp_server.py (FastMCP Server)                     │
│                                                                      │
│  Exposes 3 tools via @mcp.tool() over stdio transport:               │
│                                                                      │
│  ┌────────────────────────┐  ┌───────────────────────────────────┐   │
│  │  generate_employee_csv │  │  import_csv_to_libreoffice        │   │
│  │  (tools/csv_tool.py)   │  │  (tools/spreadsheet_tool.py)      │   │
│  │                        │  │                                    │   │
│  │  Faker → employees.csv │  │  soffice.exe → UNO bridge         │   │
│  └────────────────────────┘  │  → .xlsx / .csv / .ods             │   │
│                              └───────────────────────────────────┘   │
│  ┌────────────────────────────────────────────────┐                  │
│  │  import_csv_to_google_sheets                    │                  │
│  │  (tools/sheets_tool.py)                         │                  │
│  │                                                 │                  │
│  │  OAuth2 user creds → Sheets API + Drive API     │                  │
│  │  → creates sheet, writes data, opens in browser  │                  │
│  └────────────────────────────────────────────────┘                  │
└──────────────────────────────────────────────────────────────────────┘
```

### How the data flows

```
"Create employee CSV and import it"
          │
          ▼
   ┌──────────────┐     ┌───────────────────┐     ┌─────────────────────┐
   │  Faker        │────▶│  LibreOffice Calc  │────▶│  Google Sheets       │
   │  generates    │     │  (free, no Excel)  │     │  (Drive API)         │
   │  employees.csv│     │  saves .xlsx       │     │  creates + populates │
   └──────────────┘     │  opens in visible  │     │  opens in browser    │
                        │  Calc window       │     └─────────────────────┘
                        └───────────────────┘
```

---

## 💡 Design Decisions & Substitutions

### Why LibreOffice instead of Microsoft Excel?

I don't have a Microsoft Excel license (Office 365 is paid). **LibreOffice Calc is free, open-source, and works identically** — it reads and writes `.xlsx` files using the same XML-based format. The agent automates LibreOffice via its **UNO socket bridge** (the same API that Microsoft's COM/win32com provides for Excel), so the end result is identical: a properly formatted `.xlsx` spreadsheet file.

The `SpreadsheetTool` abstract base class (`spreadsheet_tool.py`) is designed so that swapping in a `win32com`-based `ExcelAdapter` in the future requires **zero changes** to any other module — just subclass `SpreadsheetTool` and update the factory function.

### MCP Server (Model Context Protocol)

The agent uses the **official MCP Python SDK** with `FastMCP` for tool registration. All three tools are exposed via `@mcp.tool()` decorators and served over **stdio transport** — the planner launches `mcp_server.py` as a subprocess and communicates via stdin/stdout.

This means any MCP-compatible client (Claude Desktop, Cursor, etc.) can connect to this tool server with zero extra code — just point it at `python mcp_server.py`.

**Why MCP over direct function calls?**
- Clean separation: tool logic never leaks into the planner
- Standard protocol: the tools are reusable by any MCP client
- Testability: mock the session, not the tool internals

### Planner (Plan-then-Execute Architecture)

The `Planner` class in `planner.py` implements a **two-phase architecture**:

1. **Planning phase** — sends the user prompt + all discovered tool schemas to Groq and asks it to output a structured JSON plan (ordered list of steps with tool names and arguments). No tools are called yet.
2. **Execution phase** — iterates through the plan step by step, asking Groq to issue `tool_call` messages. Each tool result is fed back into the conversation so the LLM can resolve placeholder arguments (e.g., the CSV path from step 1 is used in steps 2 and 3).

If Groq's planning response can't be parsed as JSON, a hardcoded **fallback plan** kicks in (generate CSV → import to LibreOffice → import to Google Sheets) so the agent never stalls.

### Session Memory

`SessionMemory` (`memory.py`) tracks the entire agent run in memory:
- Original user prompt
- The LLM-generated execution plan
- Each step's result (success/failure, timing, output data)
- Arbitrary metadata (preflight check results)

At the end of a run, it's serialised to a JSON file in `output/` for post-mortem analysis.

### Structured Logging

`logger.py` writes **JSON-structured log lines** to both:
- **Console** — human-readable `[INFO] message` format
- **Log file** (`output/agent.log`) — machine-parseable JSON objects with `timestamp`, `tool`, `status`, `duration_ms`, and `message` fields

The `StepTracker` class builds a **consolidated status report** printed at the end of every run, showing per-step success/failure, timing, and messages.

### Google Sheets — OAuth2 User Credentials (not Service Account)

The agent authenticates as **your Google account** (OAuth2 Desktop flow) instead of a service account. This is intentional:
- Service accounts on free-tier GCP projects have a **0-byte Drive quota** — they can create sheets but can't write data
- Running as the user means files land in **your Google Drive** under your 15 GB quota
- One-time setup: run `python oauth_login.py`, sign in once → `token.json` is saved and auto-refreshes forever

### UNO Socket Bridge (LibreOffice Automation)

LibreOffice is automated via its **UNO API over a TCP socket** (not command-line flags). The flow:
1. Launch `soffice.exe` with `--accept=socket,host=localhost,port=2002;urp;StarOffice.ServiceManager`
2. Connect using LibreOffice's built-in `python.exe` (which has the `uno` module)
3. Open the CSV via `desktop.loadComponentFromURL()`, save as `.xlsx` via `storeToURL()`
4. Re-open the output file with `Hidden=False` so the user sees it in a visible Calc window

The UNO script runs inside LibreOffice's own Python interpreter (not system Python) because the `uno` bridge module is only available there.

---

## ✅ Bonus Features Implemented

| Feature | Status | Details |
|---------|--------|---------|
| **AI-driven planning** | ✅ | Groq LLM generates a structured JSON plan before any tool is called (`planner.py`, `PLANNING_SYSTEM_PROMPT`) |
| **Retry logic with exponential backoff** | ✅ | UNO socket connection retries (configurable, default 8 attempts × 1.5s backoff). Google Sheets API retries (4 attempts × 2.0s backoff). Both configurable via `.env` |
| **Structured JSON logging** | ✅ | Every event logged as `{timestamp, tool, status, duration_ms, message}` to `output/agent.log` (`logger.py`) |
| **Multi-format output** | ✅ | LibreOffice saves as `.xlsx`, `.csv`, or `.ods` — controlled by `output_format` argument. Format → UNO FilterName mapping in `spreadsheet_tool.py` |
| **MCP tool server** | ✅ | Full FastMCP server (`mcp_server.py`) with 3 registered tools, stdio transport. Any MCP client can connect |
| **Unit tests** | ✅ | 4 test suites: `test_csv_tool.py`, `test_spreadsheet_tool.py`, `test_sheets_tool.py`, `test_planner.py` — all with mocked external dependencies (no real API keys or LibreOffice needed) |
| **Session memory** | ✅ | `SessionMemory` tracks prompt, plan, step results, metadata. Saved to JSON at end of run |
| **Pre-flight checks** | ✅ | Validates Groq API key, soffice.exe path, Google credentials before running |
| **Consolidated status report** | ✅ | `StepTracker.print_report()` prints a formatted table of all step outcomes with timing |
| **Google Sheets integration** | ✅ | Creates a new spreadsheet, writes all CSV data, shares with configured email, auto-opens in browser |

---

## 📋 Prerequisites

- **Windows 10/11** (tested on Windows; the UNO bridge and `soffice.exe` paths are Windows-specific)
- **Python 3.10+** (3.10, 3.11, 3.12 all work)
- **LibreOffice** installed (free download: https://www.libreoffice.org/download/)
  - Default path: `C:\Program Files\LibreOffice\program\soffice.exe`
  - If installed elsewhere, set `SOFFICE_PATH` in `.env`
- **Groq API key** (free: https://console.groq.com/keys)
- **Google Cloud project** with these APIs enabled:
  - Google Sheets API
  - Google Drive API
  - An OAuth 2.0 Desktop client ID (for `oauth_client.json`)

---

## 🚀 Setup Instructions

### 1. Clone / download the project

```powershell
git clone <repo-url>
cd Excel_agent/agent
```

### 2. Install Python dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure environment variables

```powershell
copy .env.example .env
```

Open `.env` in a text editor and fill in:

```env
# Required — get from https://console.groq.com/keys
GROQ_API_KEY=gsk_your_key_here

# Required for Google Sheets — your Drive folder ID
GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here

# Optional — email to share created sheets with
GOOGLE_SHEET_SHARE_EMAIL=you@gmail.com

# Optional — only if LibreOffice is installed in a non-default location
# SOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe
```

### 4. Set up Google Cloud (one-time)

See the [Google Cloud Setup](#-google-cloud-setup) section below.

### 5. Run the OAuth login (one-time)

```powershell
python oauth_login.py
```

This opens a browser → sign in with your Google account → paste the authorization code → `token.json` is saved. You never need to do this again — the token auto-refreshes.

### 6. Done! Run the agent

```powershell
python main.py "Create a sample employee CSV and import it into LibreOffice and Google Sheets"
```

---

## ☁️ Google Cloud Setup

### Step 1: Create a GCP project (or use existing)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one

### Step 2: Enable APIs

1. Go to **APIs & Services → Library**
2. Search for and enable:
   - **Google Sheets API**
   - **Google Drive API**

### Step 3: Create OAuth 2.0 credentials

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Name: `spreadsheet-agent` (or anything)
5. Click **Create**
6. Click **Download JSON**
7. Rename the downloaded file to `oauth_client.json`
8. Place it in the `agent/` folder (next to `main.py`)

### Step 4: Configure OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**
2. User type: **External** (or Internal if using Workspace)
3. Fill in app name, support email
4. Add scopes:
   - `https://www.googleapis.com/auth/spreadsheets`
   - `https://www.googleapis.com/auth/drive`
5. Add your Gmail as a **test user** (required while app is in "Testing" status)

### Step 5: Create a Drive folder for output

1. Go to [Google Drive](https://drive.google.com/)
2. Create a new folder (e.g., `Agent Output`)
3. Copy the folder ID from the URL: `https://drive.google.com/drive/folders/<THIS_IS_THE_ID>`
4. Paste it into `.env` as `GOOGLE_DRIVE_FOLDER_ID`

### Step 6: Run the OAuth login

```powershell
python oauth_login.py
```

Follow the on-screen instructions — open the URL, sign in, paste the code. Done!

---

## ▶️ How to Run

### Basic usage

```powershell
python main.py "Create a sample employee CSV with 20 rows and import it into LibreOffice and Google Sheets"
```

### Interactive mode (no prompt argument)

```powershell
python main.py
# Autonomous Spreadsheet Import Agent
# Enter your instruction (or press Ctrl-C to quit):
# > Create a CSV with 50 employees and save as xlsx
```

### Example output

```
============================================================
  PRE-FLIGHT CHECKS
============================================================
  ✅  Groq API key
       GROQ_API_KEY is set
  ✅  LibreOffice (soffice.exe)
       Found at C:\Program Files\LibreOffice\program\soffice.exe
  ✅  Google credentials
       Valid service account JSON at ./credentials.json
============================================================

🚀  Running agent for prompt: 'Create a sample employee CSV and import it into LibreOffice and Google Sheets'

============================================================
  EXECUTION PLAN
============================================================
  Step 1: Generate CSV
           Tool: generate_employee_csv
           Args: {"num_rows": 20}
  Step 2: Import to LibreOffice
           Tool: import_csv_to_libreoffice
           Args: {"csv_path": "<use result from step 1>", "output_format": "xlsx"}
  Step 3: Import to Google Sheets
           Tool: import_csv_to_google_sheets
           Args: {"csv_path": "<use result from step 1>"}
============================================================

[INFO] ▶ Starting: Generate CSV
[INFO] ✅ Generate CSV: CSV generated successfully at ...\output\employees.csv (20 rows)
[INFO] ▶ Starting: Import to LibreOffice
[INFO] ✅ Import to LibreOffice: CSV imported and saved as XLSX at ...\output\employees.xlsx
[INFO] ▶ Starting: Import to Google Sheets
[INFO] ✅ Import to Google Sheets: Google Sheet created and populated. URL: https://docs.google.com/spreadsheets/d/...

============================================================
  AGENT EXECUTION REPORT
============================================================
  ✅  Generate CSV                          1250 ms
      CSV generated successfully at ...\output\employees.csv (20 rows)
  ✅  Import to LibreOffice                 8420 ms
      CSV imported and saved as XLSX at ...\output\employees.xlsx
  ✅  Import to Google Sheets               3180 ms
      Google Sheet created and populated. URL: https://docs.google.com/spreadsheets/d/...
============================================================
  Result: 3/3 steps succeeded
============================================================

  Session log: ...\output\session_20260820T163000Z.json
```

### Run tests

```powershell
pytest tests/ -v
```

---

## 💬 Example Prompts

### Primary prompt *(used in the demo video)*

```
Create a sample employee CSV and import it into LibreOffice Calc and Google Sheets.
```

### Additional prompts the agent handles

These examples cover a range of instructions and edge cases to demonstrate how flexibly the agent interprets natural language:

| Prompt | What it tests |
|--------|---------------|
| `"Generate 25 rows of fake employee data, save it locally, and push it to Google Sheets."` | Row-count control + explicit local save + Sheets upload |
| `"Make an employee spreadsheet with department and salary columns, then sync it to my Google Sheet."` | Column awareness + Sheets sync wording |
| `"I need employee data in both LibreOffice Calc and Sheets — go ahead."` | Minimal prompt; agent infers all defaults |
| `"Just get some sample HR data into Google Sheets — no local file needed."` | Agent correctly skips the spreadsheet step when not requested |
| `"Create employee records and save them as an xlsx file."` | Format handling with no mention of Google Sheets |
| `"Build a CSV of 20 employees and open it in LibreOffice Calc."` | Agent does **not** push to Google Sheets unless explicitly asked |

---

## 📁 Project Structure

```
Excel_agent/
└── agent/
    ├── main.py                  # CLI entry point, pre-flight checks
    ├── planner.py               # Groq MCP client (plan-then-execute)
    ├── mcp_server.py            # FastMCP server (3 tools, stdio transport)
    ├── config.py                # Central config from .env
    ├── logger.py                # JSON structured logging + StepTracker
    ├── memory.py                # SessionMemory (prompt, plan, results)
    ├── oauth_login.py           # One-time Google OAuth2 setup
    ├── requirements.txt         # Python dependencies
    ├── .env                     # Environment variables (not committed)
    ├── credentials.json         # Google service account key
    ├── oauth_client.json        # Google OAuth2 Desktop client
    ├── token.json               # Saved OAuth2 token (auto-refreshes)
    ├── tools/
    │   ├── csv_tool.py          # Faker-based CSV generation
    │   ├── spreadsheet_tool.py  # LibreOffice UNO bridge (abstract + adapter)
    │   ├── sheets_tool.py       # Google Sheets + Drive API integration
    │   └── _uno_runner.py       # Standalone UNO script (used internally)
    ├── tests/
    │   ├── test_csv_tool.py     # CSV generation tests
    │   ├── test_spreadsheet_tool.py  # LibreOffice adapter tests (mocked UNO)
    │   ├── test_sheets_tool.py  # Google Sheets tests (mocked API)
    │   └── test_planner.py      # Planner plan+execute tests (mocked Groq + MCP)
    └── output/
        ├── employees.csv        # Generated CSV
        ├── employees.xlsx       # LibreOffice output
        ├── agent.log            # Structured JSON log
        └── session_*.json       # Session memory dumps
```

---

## 🔧 Configuration Reference

All values are set via environment variables in `.env`:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | ✅ | — | Groq API key for LLM calls |
| `GROQ_MODEL` | — | `openai/gpt-oss-120b` | LLM model identifier |
| `SOFFICE_PATH` | — | `C:\Program Files\LibreOffice\program\soffice.exe` | Path to LibreOffice |
| `UNO_HOST` | — | `localhost` | UNO socket host |
| `UNO_PORT` | — | `2002` | UNO socket port |
| `UNO_CONNECT_RETRIES` | — | `8` | Socket connection retry attempts |
| `UNO_CONNECT_BACKOFF_BASE` | — | `1.5` | Backoff multiplier (seconds) |
| `OUTPUT_DIR` | — | `./output` | Where CSV/XLSX files are saved |
| `GOOGLE_DRIVE_FOLDER_ID` | ✅* | — | Google Drive folder to create sheets in |
| `GOOGLE_SHEET_SHARE_EMAIL` | — | — | Email to share created sheets with |
| `GOOGLE_API_RETRIES` | — | `4` | Google API retry attempts |
| `GOOGLE_API_BACKOFF_BASE` | — | `2.0` | Google API backoff multiplier |

\* Required only if using the Google Sheets feature.

---

## 📜 License

This project was built as an assessment submission.
