from __future__ import annotations

from dataclasses import dataclass

from .models import Asset, CompatibilityManifest, CompanionError, DeviceIdentity, Route


PRODUCT_CODES = (
    ("Kindle Colorsoft", "CS"),
    ("Kindle Paperwhite 12", "PW6"),
    ("Kindle Paperwhite 11", "PW5"),
    ("Kindle Scribe", "KS"),
    ("Kindle 11th gen 2024", "KT6"),
    ("Kindle 11th gen 2022", "KT5"),
)


def product_code(product: str) -> str | None:
    lowered = product.lower()
    for label, code in PRODUCT_CODES:
        if label.lower() in lowered:
            return code
    return None


def version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            raise CompanionError("INVALID_VERSION", f"invalid firmware version: {version!r}")
        parts.append(int(digits))
    return tuple(parts)


def _pad(values: tuple[int, ...], length: int) -> tuple[int, ...]:
    return values + (0,) * (length - len(values))


def compare_versions(left: str, right: str) -> int:
    lkey = version_key(left)
    rkey = version_key(right)
    width = max(len(lkey), len(rkey))
    lp = _pad(lkey, width)
    rp = _pad(rkey, width)
    return (lp > rp) - (lp < rp)


def route_firmware_status(route: Route, firmware: str) -> str:
    if compare_versions(firmware, route.firmware_min) < 0:
        return "below_minimum"
    if compare_versions(firmware, route.firmware_max) > 0:
        return "above_maximum"
    if route.firmwares and not any(
        compare_versions(firmware, listed) == 0 for listed in route.firmwares
    ):
        return "not_exact"
    return "supported"


def find_route(
    manifest: CompatibilityManifest,
    device: DeviceIdentity,
    firmware: str,
) -> Route:
    code = product_code(device.product)
    if not code:
        raise CompanionError(
            "DEVICE_UNSUPPORTED",
            f"unrecognized Kindle model: {device.product or 'unknown'}",
        )
    candidates = [route for route in manifest.routes if code in route.device_codes]
    if not candidates:
        raise CompanionError("ROUTE_UNSUPPORTED", f"no route for device code {code}")
    for route in candidates:
        if route_firmware_status(route, firmware) == "supported":
            return route
    ranges = ", ".join(f"{r.name} {r.firmware_min}-{r.firmware_max}" for r in candidates)
    raise CompanionError(
        "FIRMWARE_UNSUPPORTED",
        f"firmware {firmware} is not an exact supported route; candidates: {ranges}",
    )


def resolve_asset(route: Route, asset_name: str) -> Asset:
    for asset in route.assets:
        if asset.name == asset_name:
            return asset
    raise CompanionError(
        "ASSET_NOT_FOUND",
        f"asset {asset_name!r} is not declared for route {route.id}",
    )


@dataclass(frozen=True)
class RouteDecision:
    code: str
    route: Route | None
    firmware_status: str | None
    message: str

    @property
    def allowed(self) -> bool:
        return self.route is not None and self.firmware_status == "supported"

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "route": self.route.id if self.route else None,
            "firmware_status": self.firmware_status,
            "allowed": self.allowed,
            "message": self.message,
        }


def decide_route(
    manifest: CompatibilityManifest,
    device: DeviceIdentity,
    firmware: str,
) -> RouteDecision:
    code = product_code(device.product)
    if not code:
        return RouteDecision(
            "DEVICE_UNSUPPORTED",
            None,
            None,
            f"unrecognized Kindle model: {device.product or 'unknown'}",
        )
    candidates = [route for route in manifest.routes if code in route.device_codes]
    if not candidates:
        return RouteDecision(
            "ROUTE_UNSUPPORTED",
            None,
            None,
            f"no route for device code {code}",
        )
    route = candidates[0]
    status = route_firmware_status(route, firmware)
    if status == "supported":
        return RouteDecision("ROUTE_SUPPORTED", route, status, "exact supported route")
    if status == "not_exact":
        message = (
            f"firmware {firmware} is within {route.name}'s range but not an exact "
            "listed build; upstream does not guarantee this route"
        )
    elif status == "above_maximum":
        message = f"firmware {firmware} is newer than {route.name} supports"
    else:
        message = f"firmware {firmware} is older than {route.name} supports"
    return RouteDecision("FIRMWARE_UNSUPPORTED", route, status, message)
