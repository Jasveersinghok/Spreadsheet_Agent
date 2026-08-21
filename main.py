import sys
from pathlib import Path

_here = Path(__file__).parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    SOFFICE_PATH,
    GOOGLE_CREDENTIALS_PATH,
    LOG_FILE,
    OUTPUT_DIR,
)
from logger import configure, log_event
from memory import SessionMemory
from planner import run_sync


def preflight_checks() -> dict:
    checks = {}

    ok = bool(GROQ_API_KEY and GROQ_API_KEY.strip())
    checks["Groq API key"] = (ok, "GROQ_API_KEY is set" if ok else "GROQ_API_KEY is missing or empty — set it in .env")

    soffice_ok = Path(SOFFICE_PATH).is_file()
    checks["LibreOffice (soffice.exe)"] = (
        soffice_ok,
        f"Found at {SOFFICE_PATH}" if soffice_ok else
        f"Not found at {SOFFICE_PATH} — LibreOffice import will be skipped. "
        f"Set SOFFICE_PATH in .env if installed elsewhere.",
    )

    creds_path = Path(GOOGLE_CREDENTIALS_PATH)
    creds_ok = False
    creds_msg = ""
    if not creds_path.is_file():
        creds_msg = (
            f"credentials.json not found at {GOOGLE_CREDENTIALS_PATH} — "
            "Google Sheets import will be skipped."
        )
    else:
        try:
            import json
            with open(creds_path) as f:
                data = json.load(f)
            if data.get("type") == "service_account":
                creds_ok = True
                creds_msg = f"Valid service account JSON at {GOOGLE_CREDENTIALS_PATH}"
            else:
                creds_msg = "credentials.json does not appear to be a service account key."
        except Exception as exc:  # noqa: BLE001
            creds_msg = f"credentials.json could not be parsed: {exc}"
    checks["Google credentials"] = (creds_ok, creds_msg)

    return checks


def print_preflight(checks: dict) -> bool:
    print("\n" + "=" * 60)
    print("  PRE-FLIGHT CHECKS")
    print("=" * 60)
    groq_ok = True
    for name, (ok, reason) in checks.items():
        icon = "✅" if ok else "⚠️ "
        print(f"  {icon}  {name}")
        print(f"       {reason}")
        if not ok and name == "Groq API key":
            groq_ok = False
    print("=" * 60 + "\n")
    return groq_ok


def main() -> None:
    configure(log_file=LOG_FILE)

    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        print("Autonomous Spreadsheet Import Agent")
        print("Enter your instruction (or press Ctrl-C to quit):")
        try:
            prompt = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)

    if not prompt:
        print("Error: No prompt provided. Exiting.")
        sys.exit(1)

    log_event(f"Agent started. Prompt: {prompt!r}", tool="main", status="start")

    checks = preflight_checks()
    groq_ok = print_preflight(checks)

    if not groq_ok:
        print("ERROR: Cannot proceed without a valid Groq API key.")
        sys.exit(1)

    memory = SessionMemory()
    memory.set_prompt(prompt)
    memory.metadata["preflight"] = {k: {"ok": ok, "reason": r} for k, (ok, r) in checks.items()}

    print(f"\n🚀  Running agent for prompt: {prompt!r}\n")
    try:
        tracker = run_sync(prompt, memory=memory)
    except Exception as exc:  # noqa: BLE001
        log_event(f"Agent loop crashed: {exc}", tool="main", status="error", level="error")
        print(f"\n❌  Agent loop failed unexpectedly: {exc}")
        sys.exit(1)

    tracker.print_report()

    try:
        session_file = memory.save(OUTPUT_DIR)
        print(f"  Session log: {session_file}\n")
    except Exception as exc:  # noqa: BLE001
        print(f"  (Could not save session log: {exc})\n")

    log_event("Agent completed.", tool="main", status="done")


if __name__ == "__main__":
    main()
