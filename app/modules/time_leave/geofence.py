"""
Free GPS Geofencing via the Haversine formula — zero external dependencies.

All math is pure Python, running in-process on every check-in attempt.
The formula computes great-circle distance over a spherical Earth model;
for radii < 1 km this is accurate to within ~0.5 m, well within the
uncertainty of a phone's GPS fix anyway.

References:
  - Haversine formula: https://en.wikipedia.org/wiki/Haversine_formula
  - R = 6,371,000 m (mean Earth radius, WGS-84 "sphere" approximation)
"""

import math
import uuid
from typing import NamedTuple

from app.core.exceptions import AppError


# ── Earth mean radius (m) ────────────────────────────────────────────────────
_R_METERS = 6_371_000.0


class GeofenceViolationError(AppError):
    """Raised when the employee's GPS fix falls outside the office perimeter.

    The message deliberately tells the user *why* and *how far*, which is
    friendlier than a bare 403 and helps diagnose GPS drift issues.
    """

    status_code = 403
    code = "geofence_violation"

    def __init__(self, distance_m: float, radius_m: int) -> None:
        super().__init__(
            f"Check-in denied: you are {distance_m:.0f} m from the office "
            f"(allowed radius: {radius_m} m). Move closer or contact HR.",
            details={
                "distance_meters": round(distance_m, 1),
                "allowed_radius_meters": radius_m,
            },
        )


class GeolocationPermissionError(AppError):
    """Raised when the frontend reports that the user denied location access."""

    status_code = 400
    code = "geolocation_denied"

    def __init__(self) -> None:
        super().__init__(
            "Location access was denied. Please enable GPS in your browser "
            "or device settings and try again."
        )


def haversine_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Return the great-circle distance in metres between two WGS-84 points.

    Args:
        lat1, lon1: observer latitude/longitude in decimal degrees.
        lat2, lon2: office/target latitude/longitude in decimal degrees.

    Returns:
        Distance in metres (always ≥ 0).
    """
    # Convert degrees → radians
    φ1 = math.radians(lat1)
    φ2 = math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)

    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return _R_METERS * c


def verify_employee_geofence(
    *,
    emp_lat: float | None,
    emp_lon: float | None,
    office_lat: float | None,
    office_lon: float | None,
    radius_m: int,
    is_remote_exempt: bool,
) -> float | None:
    """Validate that the employee is within the office geofence.

    Design choices:
    - If the *office* has no GPS configured (office_lat/lon is None), the
      check is skipped — a graceful no-op so companies that haven't set
      up geofencing yet are unaffected.
    - If the *employee* sent no coords but the office has a fence configured,
      we raise GeolocationPermissionError so the frontend can prompt for
      permission rather than silently allowing ghost check-ins.
    - is_remote_exempt=True bypasses the fence (e.g., WFH-approved day).

    Returns:
        Distance in metres if a fence check was performed, else None.

    Raises:
        GeolocationPermissionError: coords missing but fence is configured.
        GeofenceViolationError: employee is outside the allowed radius.
    """
    # No office fence configured — nothing to enforce.
    if office_lat is None or office_lon is None:
        return None

    # Remote-exempt employee (e.g., approved WFH) bypasses fence.
    if is_remote_exempt:
        return None

    # Office has a fence but the client sent no coords.
    if emp_lat is None or emp_lon is None:
        raise GeolocationPermissionError()

    distance = haversine_distance_meters(emp_lat, emp_lon, office_lat, office_lon)

    if distance > radius_m:
        raise GeofenceViolationError(distance, radius_m)

    return distance
