"""Coordinate Reference System (CRS) transformations.

Supports both:
1. PyProj Transformer (production-grade PROJ engine)
2. Analytical GRS80/WGS84 Lambert Azimuthal Equal Area (EPSG:3035) formulas
   for zero-dependency in-house migration.
"""

import math
from typing import Tuple, Union
import numpy as np

# EPSG:3035 (ETRS89-LAEA) definition:
# Ellipsoid: GRS80 (a = 6378137.0, 1/f = 298.257222101)
# Latitude of origin (phi_0): 52° N (0.907571211 rad)
# Longitude of origin (lambda_0): 10° E (0.174532925 rad)
# False Easting (x_0): 4321000.0 m
# False Northing (y_0): 3210000.0 m

LAEA_A = 6378137.0
LAEA_F = 1.0 / 298.257222101
LAEA_E2 = 2 * LAEA_F - LAEA_F * LAEA_F
LAEA_E = math.sqrt(LAEA_E2)
LAEA_PHI0 = math.radians(52.0)
LAEA_LAM0 = math.radians(10.0)
LAEA_X0 = 4321000.0
LAEA_Y0 = 3210000.0


try:
    from pyproj import Transformer
    _TRANSFORMER_TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    _TRANSFORMER_FROM_3035 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    _HAS_PYPROJ = True
except ImportError:
    _HAS_PYPROJ = False


def wgs84_to_laea(lon: Union[float, np.ndarray], lat: Union[float, np.ndarray], use_analytical: bool = False) -> Tuple[Union[float, np.ndarray], Union[float, np.ndarray]]:
    """Convert WGS84 Geographic (lon, lat) in degrees to ETRS89-LAEA (x, y) in meters (EPSG:3035).

    Args:
        lon: Longitude in decimal degrees.
        lat: Latitude in decimal degrees.
        use_analytical: If True, bypass pyproj and use pure mathematical formula.

    Returns:
        Tuple of (x, y) in meters (EPSG:3035).
    """
    if _HAS_PYPROJ and not use_analytical:
        return _TRANSFORMER_TO_3035.transform(lon, lat)

    # Pure analytical Snyder formulas for Lambert Azimuthal Equal Area (Ellipsoidal)
    return _analytical_wgs84_to_laea(lon, lat)


def laea_to_wgs84(x: Union[float, np.ndarray], y: Union[float, np.ndarray], use_analytical: bool = False) -> Tuple[Union[float, np.ndarray], Union[float, np.ndarray]]:
    """Convert ETRS89-LAEA (x, y) in meters to WGS84 Geographic (lon, lat) in degrees.

    Args:
        x: Easting in meters (EPSG:3035).
        y: Northing in meters (EPSG:3035).
        use_analytical: If True, bypass pyproj and use pure mathematical formula.

    Returns:
        Tuple of (lon, lat) in decimal degrees.
    """
    if _HAS_PYPROJ and not use_analytical:
        return _TRANSFORMER_FROM_3035.transform(x, y)

    return _analytical_laea_to_wgs84(x, y)


def _q_term(phi: float, e: float) -> float:
    """Compute authalic latitude auxiliary parameter q."""
    sin_phi = math.sin(phi)
    e_sin = e * sin_phi
    return (1.0 - e * e) * (sin_phi / (1.0 - e_sin * e_sin) - (1.0 / (2.0 * e)) * math.log((1.0 - e_sin) / (1.0 + e_sin)))


def _analytical_wgs84_to_laea(lon: float, lat: float) -> Tuple[float, float]:
    """Analytical ellipsoidal forward transformation to EPSG:3035."""
    phi = math.radians(lat)
    lam = math.radians(lon)

    q = _q_term(phi, LAEA_E)
    q0 = _q_term(LAEA_PHI0, LAEA_E)
    qp = _q_term(math.pi / 2.0, LAEA_E)

    beta = math.asin(q / qp)
    beta0 = math.asin(q0 / qp)

    m0 = math.cos(LAEA_PHI0) / math.sqrt(1.0 - LAEA_E2 * (math.sin(LAEA_PHI0) ** 2))
    rq = LAEA_A * math.sqrt(qp / 2.0)
    d = LAEA_A * m0 / (rq * math.cos(beta0))

    delta_lam = lam - LAEA_LAM0
    cos_dlam = math.cos(delta_lam)
    sin_dlam = math.sin(delta_lam)

    b = rq * math.sqrt(2.0 / (1.0 + math.sin(beta0) * math.sin(beta) + math.cos(beta0) * math.cos(beta) * cos_dlam))

    x = (b * d) * (math.cos(beta) * sin_dlam) + LAEA_X0
    y = (b / d) * (math.cos(beta0) * math.sin(beta) - math.sin(beta0) * math.cos(beta) * cos_dlam) + LAEA_Y0

    return x, y


def _analytical_laea_to_wgs84(x: float, y: float) -> Tuple[float, float]:
    """Analytical ellipsoidal inverse transformation from EPSG:3035."""
    qp = _q_term(math.pi / 2.0, LAEA_E)
    q0 = _q_term(LAEA_PHI0, LAEA_E)
    beta0 = math.asin(q0 / qp)

    m0 = math.cos(LAEA_PHI0) / math.sqrt(1.0 - LAEA_E2 * (math.sin(LAEA_PHI0) ** 2))
    rq = LAEA_A * math.sqrt(qp / 2.0)
    d = LAEA_A * m0 / (rq * math.cos(beta0))

    x_adj = (x - LAEA_X0) / d
    y_adj = (y - LAEA_Y0) * d
    rho = math.hypot(x_adj, y_adj)

    if rho < 1e-10:
        return math.degrees(LAEA_LAM0), math.degrees(LAEA_PHI0)

    c = 2.0 * math.asin(rho / (2.0 * rq))
    cos_c = math.cos(c)
    sin_c = math.sin(c)

    q = qp * (cos_c * math.sin(beta0) + (y_adj * sin_c * math.cos(beta0) / rho))

    # Iterative solution for phi from authalic q
    phi = math.asin(q / 2.0)
    for _ in range(5):
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        e_sin = LAEA_E * sin_phi
        denom = (1.0 - e_sin * e_sin) ** 2
        f = _q_term(phi, LAEA_E) - q
        f_prime = (2.0 * (1.0 - LAEA_E2) * cos_phi) / denom
        delta = f / f_prime
        phi -= delta
        if abs(delta) < 1e-12:
            break

    lam = LAEA_LAM0 + math.atan2(x_adj * sin_c, rho * math.cos(beta0) * cos_c - y_adj * math.sin(beta0) * sin_c)

    return math.degrees(lam), math.degrees(phi)
