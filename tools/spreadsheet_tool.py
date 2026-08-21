
import os
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Literal, Optional

def _ensure_uno_path() -> None:
    try:
        from config import SOFFICE_PATH
        lo_program_dir = str(Path(SOFFICE_PATH).parent)
        if lo_program_dir not in sys.path:
            sys.path.insert(0, lo_program_dir)
    except Exception:  # noqa: BLE001
        pass

OutputFormat = Literal["xlsx", "csv", "ods"]

FORMAT_TO_FILTER: Dict[str, str] = {
    "xlsx": "Calc MS Excel 2007 XML",
    "csv": "Text - txt - csv (StarCalc)",
    "ods": "calc8",
}

FORMAT_TO_EXTENSION: Dict[str, str] = {
    "xlsx": ".xlsx",
    "csv": ".csv",
    "ods": ".ods",
}


class SpreadsheetTool(ABC):

    @abstractmethod
    def import_csv_and_save(
        self,
        csv_path: str,
        output_format: OutputFormat = "xlsx",
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    def close(self) -> None: ...


class LibreOfficeAdapter(SpreadsheetTool):

    def __init__(
        self,
        soffice_path: str,
        host: str = "localhost",
        port: int = 2002,
        connect_retries: int = 8,
        backoff_base: float = 1.5,
    ) -> None:
        self.soffice_path = soffice_path
        self.host = host
        self.port = port
        self.connect_retries = connect_retries
        self.backoff_base = backoff_base
        self._process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._desktop: Any = None


    def import_csv_and_save(
        self,
        csv_path: str,
        output_format: OutputFormat = "xlsx",
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        from config import OUTPUT_DIR, FALLBACK_OUTPUT_DIR

        if output_format not in FORMAT_TO_FILTER:
            return {
                "success": False,
                "message": (
                    f"Unknown output_format {output_format!r}. "
                    f"Supported: {list(FORMAT_TO_FILTER)}"
                ),
                "data": None,
            }

        if output_path:
            save_path = Path(output_path)
        else:
            ext = FORMAT_TO_EXTENSION[output_format]
            for candidate_dir in (OUTPUT_DIR, FALLBACK_OUTPUT_DIR):
                try:
                    candidate_dir.mkdir(parents=True, exist_ok=True)
                    save_path = candidate_dir / f"employees{ext}"
                    break
                except OSError:
                    continue
            else:
                return {
                    "success": False,
                    "message": "No writable output directory found for spreadsheet.",
                    "data": None,
                }

        try:
            self._launch_soffice()
            self._run_import_and_open(csv_path, str(save_path), FORMAT_TO_FILTER[output_format])
            return {
                "success": True,
                "message": (
                    f"CSV imported and saved as {output_format.upper()} "
                    f"at {save_path}"
                ),
                "data": {
                    "output_path": str(save_path),
                    "output_format": output_format,
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "message": f"LibreOffice import failed: {exc}",
                "data": None,
            }

    def close(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None


    def _launch_soffice(self) -> None:
        import socket as _socket

        # Check if something is already listening on the UNO port
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            already_up = s.connect_ex((self.host, self.port)) == 0

        if already_up:
            return

        if not Path(self.soffice_path).is_file():
            raise FileNotFoundError(
                f"soffice.exe not found at: {self.soffice_path}. "
                "Set SOFFICE_PATH in .env to the correct path."
            )

        accept_str = (
            f"socket,host={self.host},port={self.port};"
            "urp;StarOffice.ServiceManager"
        )
        cmd = [
            self.soffice_path,
            f"--accept={accept_str}",
            "--nofirststartwizard",
            "--calc",
        ]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )

        import socket as _socket2
        for _ in range(self.connect_retries):
            time.sleep(self.backoff_base)
            with _socket2.socket(_socket2.AF_INET, _socket2.SOCK_STREAM) as s:
                if s.connect_ex((self.host, self.port)) == 0:
                    break

    def _run_import_and_open(self, csv_path: str, save_path: str, filter_name: str) -> None:
        import tempfile
        Path(save_path).unlink(missing_ok=True)

        script_content = f"""
import sys
import uno
from com.sun.star.beans import PropertyValue
import time

def run():
    local_ctx = uno.getComponentContext()
    resolver = local_ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_ctx
    )
    ctx = None
    for _ in range({self.connect_retries}):
        try:
            ctx = resolver.resolve(
                "uno:socket,host={self.host},port={self.port};urp;StarOffice.ComponentContext"
            )
            break
        except Exception:
            time.sleep({self.backoff_base})
    if not ctx:
        print("FAILED: Could not connect to LibreOffice")
        sys.exit(1)

    desktop = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", ctx
    )
    url_in  = uno.systemPathToFileUrl(r"{csv_path}")
    url_out = uno.systemPathToFileUrl(r"{save_path}")

    # Step 1: open the CSV silently (Hidden=True)
    in_props = (
        PropertyValue(Name="FilterName",   Value="Text - txt - csv (StarCalc)"),
        PropertyValue(Name="FilterOptions", Value="44,34,76,1"),
        PropertyValue(Name="Hidden",        Value=True),
    )
    csv_doc = desktop.loadComponentFromURL(url_in, "_blank", 0, in_props)

    # Step 2: save as the requested format
    out_props = (
        PropertyValue(Name="FilterName", Value="{filter_name}"),
        PropertyValue(Name="Overwrite",  Value=True),
    )
    csv_doc.storeToURL(url_out, out_props)

    open_props = (
        PropertyValue(Name="Hidden", Value=False),
    )
    desktop.loadComponentFromURL(url_out, "_blank", 0, open_props)

    csv_doc.close(True)

if __name__ == '__main__':
    run()
"""
        python_exe = str(Path(self.soffice_path).parent / "python.exe")
        if not Path(python_exe).exists():
            raise FileNotFoundError(f"LibreOffice python not found at {python_exe}")

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(script_content)
            script_path = f.name

        try:
            result = subprocess.run(
                [python_exe, script_path],
                capture_output=True, text=True, check=True,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"UNO script failed:\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
            )
        finally:
            Path(script_path).unlink(missing_ok=True)



def get_spreadsheet_tool(
    soffice_path: str,
    host: str = "localhost",
    port: int = 2002,
    connect_retries: int = 8,
    backoff_base: float = 1.5,
) -> SpreadsheetTool:
    return LibreOfficeAdapter(
        soffice_path=soffice_path,
        host=host,
        port=port,
        connect_retries=connect_retries,
        backoff_base=backoff_base,
    )


def import_csv_to_spreadsheet(
    csv_path: str,
    output_format: OutputFormat = "xlsx",
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    from config import (
        SOFFICE_PATH,
        UNO_HOST,
        UNO_PORT,
        UNO_CONNECT_RETRIES,
        UNO_CONNECT_BACKOFF_BASE,
    )

    adapter = get_spreadsheet_tool(
        soffice_path=SOFFICE_PATH,
        host=UNO_HOST,
        port=UNO_PORT,
        connect_retries=UNO_CONNECT_RETRIES,
        backoff_base=UNO_CONNECT_BACKOFF_BASE,
    )
    return adapter.import_csv_and_save(
        csv_path=csv_path,
        output_format=output_format,
        output_path=output_path,
    )
