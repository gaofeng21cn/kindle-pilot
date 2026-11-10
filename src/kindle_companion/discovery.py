from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

from .models import CompanionError, DeviceIdentity


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run(command: list[str], runner: Runner) -> str:
    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        return ""
    except subprocess.TimeoutExpired as exc:
        raise CompanionError("DISCOVERY_TIMEOUT", f"timed out running {command[0]}") from exc
    return result.stdout or ""


def _serial(text: str) -> str:
    patterns = (
        r'"USB Serial Number"\s*=\s*"([A-Z0-9]+)"',
        r'"kUSBSerialNumberString"\s*=\s*"([A-Z0-9]+)"',
        r'"Serial Number"\s*=\s*"([A-Z0-9]+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def discover(
    runner: Runner = subprocess.run,
    product_output: str | None = None,
    ioreg_output: str | None = None,
) -> DeviceIdentity:
    if product_output is None:
        product_output = _run(
            ["system_profiler", "SPUSBDataType"],
            runner,
        )
    if ioreg_output is None:
        ioreg_output = _run(
            ["ioreg", "-p", "IOUSB", "-l", "-w", "0"],
            runner,
        )

    combined = f"{product_output}\n{ioreg_output}"
    products = (
        "Kindle Colorsoft Signature Edition",
        "Kindle Colorsoft",
        "Kindle Paperwhite 12",
        "Kindle Paperwhite 11",
        "Kindle Scribe",
        "Kindle 11th gen 2024",
        "Kindle 11th gen 2022",
        "Kindle",
    )
    product = next((name for name in products if name in combined), "")
    serial = _serial(combined)
    if not product:
        raise CompanionError(
            "DEVICE_NOT_FOUND",
            "Kindle is not visible to macOS USB discovery; unlock it and reconnect USB",
        )
    return DeviceIdentity(product=product, serial=serial)
