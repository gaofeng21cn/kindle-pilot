from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .models import CompanionError


DEFAULT_MTP_CANDIDATES = (
    Path("/Applications/OpenMTP.app/Contents/Resources/bin/mtp-cli"),
    Path("/Applications/OpenMTP 3.3.0-arm64.app/Contents/Resources/bin/mtp-cli"),
)


def quote_batch_arg(value: str | Path) -> str:
    """Quote one OpenMTP batch argument without invoking a shell."""
    text = str(value)
    if not text:
        return '""'
    if not re.search(r"[\s\"'\\]", text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass(frozen=True)
class MtpResult:
    command: str
    output: str
    returncode: int

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(
            line
            for line in self.output.splitlines()
            if re.search(r"StoreFull|SendObjectInfo|invalid response|^error:", line, re.I)
        )


def find_mtp_cli(candidates: Iterable[Path] = DEFAULT_MTP_CANDIDATES) -> Path:
    configured = os.environ.get("KINDLE_MTP_CLI")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path
        raise CompanionError("MTP_CLI_NOT_FOUND", f"KINDLE_MTP_CLI does not exist: {path}")
    for path in candidates:
        if path.is_file():
            return path
    raise CompanionError(
        "MTP_CLI_NOT_FOUND",
        "OpenMTP mtp-cli was not found; install OpenMTP or set KINDLE_MTP_CLI",
    )


def parse_storage_info(output: str) -> dict[str, int]:
    match = re.search(
        r"used\s+(\d+)\s+\(\d+%\),\s+free\s+(\d+)\s+bytes\s+of\s+(\d+)",
        output,
    )
    if not match:
        raise CompanionError("MTP_STORAGE_PARSE", "storage-info output was not recognized")
    return {
        "used_bytes": int(match.group(1)),
        "free_bytes": int(match.group(2)),
        "capacity_bytes": int(match.group(3)),
    }


def parse_listing(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        match = re.match(r"^\d+\s+\S+\s+\S+\s+\S+\s+\S+\s+(.+?)\s*$", line)
        if match:
            names.append(match.group(1))
    return names


class MtpClient:
    """Single-session OpenMTP batch wrapper.

    A caller should create one client for a transfer plan. Each invocation gets
    an isolated input file, which prevents another process from sharing the
    same MTP connection accidentally. Batch output is treated as failed when
    any transfer error appears, even if mtp-cli returns zero.
    """

    def __init__(
        self,
        executable: Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.executable = executable or find_mtp_cli()
        self.runner = runner

    def run(self, commands: Iterable[str], timeout: int = 1800) -> MtpResult:
        command_text = "\n".join(commands) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mtp.batch", prefix="kindle-pilot-", delete=False
        ) as handle:
            handle.write(command_text)
            batch_path = Path(handle.name)
        try:
            result = self.runner(
                [str(self.executable), "--batch", "--input-file", str(batch_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CompanionError("MTP_CLI_NOT_FOUND", str(self.executable)) from exc
        except subprocess.TimeoutExpired as exc:
            raise CompanionError("MTP_TIMEOUT", "MTP batch session timed out") from exc
        finally:
            batch_path.unlink(missing_ok=True)
        output = (result.stdout or "") + (result.stderr or "")
        mtp_result = MtpResult(command=command_text, output=output, returncode=result.returncode)
        if result.returncode != 0 or mtp_result.errors:
            detail = "; ".join(mtp_result.errors[:3]) or f"exit={result.returncode}"
            raise CompanionError("MTP_TRANSFER_FAILED", detail)
        return mtp_result

    def storage_info(self) -> dict[str, int]:
        result = self.run(("storage-info 65537", "exit"))
        return parse_storage_info(result.output)

    def list_path(self, path: str = "/") -> list[str]:
        result = self.run((f"lsext {quote_batch_arg(path)}", "exit"))
        return parse_listing(result.output)

    def delete_paths(self, paths: Iterable[str]) -> MtpResult:
        commands = ["cd /"] + [f"rm {quote_batch_arg(path)}" for path in paths] + ["exit"]
        return self.run(commands)

    def mkdir(self, path: str) -> MtpResult:
        return self.run((f"mkpath {quote_batch_arg(path)}", "exit"))

    def put(self, local_path: Path, remote_dir: str) -> MtpResult:
        if not local_path.is_file():
            raise CompanionError("LOCAL_ASSET_MISSING", f"local file not found: {local_path}")
        return self.run(
            (f"put {quote_batch_arg(local_path)} {quote_batch_arg(remote_dir)}", "exit")
        )
