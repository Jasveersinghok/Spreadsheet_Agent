import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SessionMemory:
    session_id: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    prompt: str = ""
    plan: List[Dict[str, Any]] = field(default_factory=list)
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def set_prompt(self, prompt: str) -> None:
        self.prompt = prompt

    def set_plan(self, plan: List[Dict[str, Any]]) -> None:
        self.plan = plan

    def add_step_result(self, step_name: str, tool_name: str, result: Dict[str, Any]) -> None:
        self.step_results.append(
            {
                "step_name": step_name,
                "tool_name": tool_name,
                "success": result.get("success"),
                "message": result.get("message", ""),
                "data": result.get("data"),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def last_result(self) -> Optional[Dict[str, Any]]:
        return self.step_results[-1] if self.step_results else None

    def succeeded_steps(self) -> List[str]:
        return [s["step_name"] for s in self.step_results if s.get("success")]

    def failed_steps(self) -> List[str]:
        return [s["step_name"] for s in self.step_results if not s.get("success")]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        file_path = directory / f"session_{self.session_id}.json"
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, default=str)
        return file_path

    @classmethod
    def load(cls, file_path: Path) -> "SessionMemory":
        with open(file_path, encoding="utf-8") as fh:
            data = json.load(fh)
        obj = cls.__new__(cls)
        obj.__dict__.update(data)
        return obj

    def summary(self) -> str:
        lines = [
            f"Session ID : {self.session_id}",
            f"Prompt     : {self.prompt!r}",
            f"Plan steps : {len(self.plan)}",
            f"Executed   : {len(self.step_results)}",
            f"Succeeded  : {len(self.succeeded_steps())}",
            f"Failed     : {len(self.failed_steps())}",
        ]
        return "\n".join(lines)
