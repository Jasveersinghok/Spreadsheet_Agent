import json
import logging
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "tool": getattr(record, "tool", "system"),
            "status": getattr(record, "status", ""),
            "duration_ms": getattr(record, "duration_ms", None),
            "message": record.getMessage(),
        }
        payload = {k: v for k, v in payload.items() if v is not None and v != ""}
        return json.dumps(payload)


def _build_logger(log_file: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger("agent")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(message)s")
    )
    logger.addHandler(console_handler)

    if log_file:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(JsonFormatter())
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("Could not open log file %s: %s", log_file, exc)

    return logger


_logger: Optional[logging.Logger] = None


def configure(log_file: Optional[str] = None) -> logging.Logger:
    global _logger
    _logger = _build_logger(log_file)
    return _logger


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = _build_logger()
    return _logger


def log_event(
    message: str,
    tool: str = "system",
    status: str = "",
    duration_ms: Optional[float] = None,
    level: str = "info",
) -> None:
    logger = get_logger()
    extra = {"tool": tool, "status": status, "duration_ms": duration_ms}
    getattr(logger, level.lower())(message, extra=extra)


@dataclass
class StepResult:
    step_name: str
    tool_name: str
    success: bool
    message: str
    duration_ms: float = 0.0
    data: Optional[Dict[str, Any]] = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class StepTracker:
    def __init__(self) -> None:
        self._steps: List[StepResult] = []
        self._active_steps: Dict[str, float] = {}

    def start(self, step_name: str, tool_name: str) -> None:
        self._active_steps[step_name] = time.monotonic()
        log_event(f"▶ Starting: {step_name}", tool=tool_name, status="started")

    def finish(self, step_name: str, tool_name: str, result: Dict[str, Any]) -> StepResult:
        elapsed = time.monotonic() - self._active_steps.pop(step_name, time.monotonic())
        duration_ms = elapsed * 1000

        step_result = StepResult(
            step_name=step_name,
            tool_name=tool_name,
            success=bool(result.get("success", False)),
            message=str(result.get("message", "")),
            duration_ms=round(duration_ms, 1),
            data=result.get("data"),
        )
        self._steps.append(step_result)

        icon = "✅" if step_result.success else "❌"
        log_event(
            f"{icon} {step_name}: {step_result.message}",
            tool=tool_name,
            status="success" if step_result.success else "failure",
            duration_ms=round(duration_ms, 1),
        )
        return step_result

    def get_steps(self) -> List[StepResult]:
        return list(self._steps)

    def print_report(self) -> None:
        print("\n" + "=" * 60)
        print("  AGENT EXECUTION REPORT")
        print("=" * 60)
        for step in self._steps:
            icon = "✅" if step.success else "❌"
            print(f"  {icon}  {step.step_name:<35} {step.duration_ms:>7.0f} ms")
            print(f"      {step.message}")
        print("=" * 60)
        total = len(self._steps)
        passed = sum(1 for s in self._steps if s.success)
        print(f"  Result: {passed}/{total} steps succeeded")
        print("=" * 60 + "\n")
