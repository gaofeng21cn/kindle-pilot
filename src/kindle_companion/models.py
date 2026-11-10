from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class CompanionError(RuntimeError):
    """An error that should be shown to an operator without a traceback."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DeviceIdentity:
    product: str
    serial: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SourceRecord:
    name: str
    url: str
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRecord":
        return cls(
            name=str(data["name"]),
            url=str(data["url"]),
            notes=str(data.get("notes", "")),
        )


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    sha256: str
    source: str
    required: bool = True
    redistribute: bool = False
    license: str = "unknown"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Asset":
        return cls(
            name=str(data["name"]),
            url=str(data["url"]),
            sha256=str(data["sha256"]).lower(),
            source=str(data["source"]),
            required=bool(data.get("required", True)),
            redistribute=bool(data.get("redistribute", False)),
            license=str(data.get("license", "unknown")),
        )


@dataclass(frozen=True)
class Route:
    id: str
    name: str
    device_codes: tuple[str, ...]
    firmware_min: str
    firmware_max: str
    firmwares: tuple[str, ...]
    jailbreak_url: str
    assets: tuple[Asset, ...]
    prerequisites: tuple[str, ...]
    manual_steps: tuple[str, ...]
    native_collections: dict[str, Any] | None = None
    wireless_maintenance: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Route":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            device_codes=tuple(str(v) for v in data["device_codes"]),
            firmware_min=str(data["firmware_min"]),
            firmware_max=str(data["firmware_max"]),
            firmwares=tuple(str(v) for v in data.get("firmwares", [])),
            jailbreak_url=str(data["jailbreak_url"]),
            assets=tuple(Asset.from_dict(v) for v in data.get("assets", [])),
            prerequisites=tuple(str(v) for v in data.get("prerequisites", [])),
            manual_steps=tuple(str(v) for v in data.get("manual_steps", [])),
            native_collections=data.get("native_collections"),
            wireless_maintenance=data.get("wireless_maintenance"),
        )


@dataclass(frozen=True)
class CompatibilityManifest:
    schema_version: int
    generated_at: str
    sources: dict[str, SourceRecord]
    routes: tuple[Route, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompatibilityManifest":
        if data.get("schema_version") != 1:
            raise CompanionError(
                "MANIFEST_SCHEMA",
                f"unsupported manifest schema: {data.get('schema_version')!r}",
            )
        return cls(
            schema_version=1,
            generated_at=str(data["generated_at"]),
            sources={
                str(key): SourceRecord.from_dict(value)
                for key, value in data.get("sources", {}).items()
            },
            routes=tuple(Route.from_dict(v) for v in data.get("routes", [])),
        )
