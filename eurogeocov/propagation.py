"""Line of Sight (LoS) and RF propagation engine.

Calculates:
- Spherical Earth curvature and 4/3 atmospheric refraction
- Terrain elevation cross-sections from EU-DEM
- First Fresnel zone ellipsoids for arbitrary frequencies
- Overhead antenna Cone of Silence (elevation angle cutoff / null)
- Maximum Useful Flight Levels (ICAO/FAA service ceiling e.g. FL600)
- Maximum Designated Operational Coverage (DOC range e.g. 200 NM)
- Optical and Radio Line-of-Sight status
- Critical bottleneck obstacle detection
- Free-Space Path Loss (FSPL) and knife-edge diffraction loss
"""

import math
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from eurogeocov.config import (
    SPEED_OF_LIGHT,
    EARTH_MEAN_RADIUS,
    STANDARD_K_FACTOR,
    DEFAULT_FREQUENCIES,
    FT_TO_METERS,
    METERS_TO_FT,
    DEFAULT_CONE_OF_SILENCE_ANGLE_DEG,
    DEFAULT_MAX_FLIGHT_LEVEL_FT,
    DEFAULT_MAX_OPERATIONAL_RANGE_KM
)
from eurogeocov.dem_reader import DEMReader


class PropagationEngine:
    """Computes RF Line of Sight, Earth curvature, and airspace boundary clearances."""

    def __init__(self, dem_reader: Optional[DEMReader] = None, k_factor: float = STANDARD_K_FACTOR):
        self.dem_reader = dem_reader
        self.k_factor = k_factor
        self.effective_earth_radius = EARTH_MEAN_RADIUS * self.k_factor

    def compute_fresnel_radius(self, d1: Union[float, np.ndarray], d2: Union[float, np.ndarray], frequency_hz: float) -> Union[float, np.ndarray]:
        """Compute the radius of the first Fresnel zone (meters) at distance d1 from Tx and d2 from Rx."""
        if frequency_hz <= 0:
            raise ValueError("Frequency must be positive.")
        wavelength = SPEED_OF_LIGHT / frequency_hz
        total_d = d1 + d2
        denom = np.where(total_d <= 0, 1e-6, total_d)
        prod = (wavelength * d1 * d2) / denom
        prod = np.maximum(0.0, prod)
        return np.sqrt(prod)

    def compute_earth_bulge(self, d1: Union[float, np.ndarray], d2: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Compute apparent Earth bulge in meters along a path over a curved Earth with atmospheric refraction."""
        return (d1 * d2) / (2.0 * self.effective_earth_radius)

    def compute_fspl_db(self, distance_m: float, frequency_hz: float) -> float:
        """Calculate Free-Space Path Loss in decibels (dB)."""
        if distance_m <= 0 or frequency_hz <= 0:
            return 0.0
        return 20.0 * math.log10(distance_m) + 20.0 * math.log10(frequency_hz) - 147.552

    def compute_knife_edge_loss_db(self, v: float) -> float:
        """Approximation of Lee/ITU knife-edge diffraction loss (dB) from Fresnel diffraction parameter v."""
        if v <= -0.7:
            return 0.0
        elif v <= 0.0:
            return 6.0 + 9.0 * v
        elif v <= 1.0:
            return 6.0 + 9.0 * v - 1.27 * (v ** 2)
        elif v <= 2.4:
            return 13.0 + 20.0 * math.log10(v)
        else:
            return 16.0 + 20.0 * math.log10(v)

    def evaluate_los(
        self,
        tx_lon: float,
        tx_lat: float,
        tx_alt_m: float,
        rx_lon: float,
        rx_lat: float,
        rx_alt_m: float,
        frequency_hz: float = DEFAULT_FREQUENCIES["SSR_ADSB_RECEIVE"],
        num_points: int = 250,
        tx_is_agl: bool = False,
        rx_is_agl: bool = False,
        cone_of_silence_deg: float = DEFAULT_CONE_OF_SILENCE_ANGLE_DEG,
        max_flight_level_ft: float = DEFAULT_MAX_FLIGHT_LEVEL_FT,
        max_operational_range_km: float = DEFAULT_MAX_OPERATIONAL_RANGE_KM,
        dem_reader: Optional[DEMReader] = None,
    ) -> Dict[str, Any]:
        """Evaluate full Point-to-Point Line of Sight along terrain cross-section,
        accounting for:
        1. Earth curvature & 4/3 atmospheric refraction
        2. Fresnel zone ellipsoid clearances
        3. Antenna overhead Cone of Silence
        4. Maximum Useful Flight Levels & Designated Operational Coverage (DOC).

        Args:
            tx_lon, tx_lat: Transmitter WGS84 coordinates.
            tx_alt_m: Transmitter altitude (AMSL if tx_is_agl is False, mast height AGL if True).
            rx_lon, rx_lat: Receiver / Airspace target WGS84 coordinates.
            rx_alt_m: Receiver altitude (AMSL if rx_is_agl is False, AGL if True).
            frequency_hz: Carrier frequency in Hz (e.g. 1090 MHz ADS-B, 121.5 MHz VHF).
            num_points: Number of terrain profile sample slices.
            tx_is_agl: Whether tx_alt_m is above ground level.
            rx_is_agl: Whether rx_alt_m is above ground level.
            cone_of_silence_deg: Antenna elevation angle threshold above which overhead null occurs (default 60°).
            max_flight_level_ft: Maximum useful service flight level in feet (default FL600 / 60,000 ft).
            max_operational_range_km: Maximum useful operational range in km (default 200 NM / ~370.4 km).
            dem_reader: Optional override DEMReader instance.

        Returns:
            Dictionary containing LoS boolean results, clearances, Fresnel profile,
            Cone of Silence status, service ceiling status, and path loss.
        """
        reader = dem_reader or self.dem_reader
        if not reader:
            raise ValueError("A DEMReader must be provided to evaluate terrain LoS.")

        # 1. Sample profile from EU-DEM
        prof = reader.get_elevation_profile(tx_lon, tx_lat, rx_lon, rx_lat, num_points=num_points)

        distances = np.array(prof["distances_m"])
        terrain_elevations = np.array(prof["elevations_m"])
        total_dist = prof["total_distance_m"]
        total_dist_km = total_dist / 1000.0

        # 2. Adjust antenna heights if AGL
        tx_ground_elev = float(terrain_elevations[0])
        rx_ground_elev = float(terrain_elevations[-1])

        tx_amsl = (tx_ground_elev + tx_alt_m) if tx_is_agl else tx_alt_m
        rx_amsl = (rx_ground_elev + rx_alt_m) if rx_is_agl else rx_alt_m
        rx_amsl_ft = rx_amsl * METERS_TO_FT

        # 3. Direct Ray Line AMSL
        if total_dist <= 0:
            return {
                "has_los": True,
                "has_fresnel_clearance": True,
                "in_cone_of_silence": True,
                "exceeds_max_flight_level": False,
                "exceeds_operational_range": False,
                "elevation_angle_deg": 90.0,
                "status": "CONE_OF_SILENCE",
                "total_distance_m": 0.0,
                "total_distance_km": 0.0,
                "total_distance_nm": 0.0,
                "min_optical_clearance_m": 0.0,
                "min_fresnel_clearance_m": 0.0,
                "fspl_db": 0.0,
            }

        t = distances / total_dist
        ray_amsl = tx_amsl + t * (rx_amsl - tx_amsl)

        # 4. Earth Bulge & Curvature Drop (Spherical + 4/3 Refraction)
        d1 = distances
        d2 = total_dist - distances
        earth_bulge = self.compute_earth_bulge(d1, d2)
        curved_terrain = terrain_elevations + earth_bulge

        # 5. Antenna Elevation Angle & Cone of Silence Calculation
        # Elevation angle at Tx looking at Rx above the curved Earth horizon
        delta_h = rx_amsl - tx_amsl
        # Apparent curvature drop at distance D: D^2 / (2 * Re)
        curvature_drop = (total_dist ** 2) / (2.0 * self.effective_earth_radius)
        apparent_delta_h = delta_h - curvature_drop
        elevation_angle_rad = math.atan2(apparent_delta_h, total_dist)
        elevation_angle_deg = math.degrees(elevation_angle_rad)

        in_cone_of_silence = elevation_angle_deg > cone_of_silence_deg

        # 6. Service Volume Limits
        exceeds_max_fl = rx_amsl_ft > max_flight_level_ft
        exceeds_range = total_dist_km > max_operational_range_km

        # 7. Optical & Fresnel Clearance
        optical_clearance = ray_amsl - curved_terrain
        fresnel_r1 = self.compute_fresnel_radius(d1, d2, frequency_hz)
        fresnel_60 = 0.6 * fresnel_r1
        radio_clearance = optical_clearance - fresnel_60

        interior_slice = slice(1, -1) if len(distances) > 2 else slice(None)
        int_opt_clearance = optical_clearance[interior_slice]
        int_rad_clearance = radio_clearance[interior_slice]

        min_opt_clearance = float(np.min(int_opt_clearance)) if len(int_opt_clearance) > 0 else 0.0
        min_rad_clearance = float(np.min(int_rad_clearance)) if len(int_rad_clearance) > 0 else 0.0

        has_los = min_opt_clearance > 0.0
        has_fresnel = min_rad_clearance > 0.0

        # Critical bottleneck / obstacle
        worst_idx = int(np.argmin(int_rad_clearance)) + 1 if len(int_rad_clearance) > 0 else 0
        obstacle_info = {
            "distance_m": float(distances[worst_idx]),
            "lat": float(prof["lats"][worst_idx]),
            "lon": float(prof["lons"][worst_idx]),
            "terrain_elev_m": float(terrain_elevations[worst_idx]),
            "curved_terrain_m": float(curved_terrain[worst_idx]),
            "ray_height_m": float(ray_amsl[worst_idx]),
            "optical_clearance_m": float(optical_clearance[worst_idx]),
            "fresnel_clearance_m": float(radio_clearance[worst_idx]),
            "fresnel_radius_m": float(fresnel_r1[worst_idx]),
        }

        # 8. Path Loss & Diffraction
        fspl = self.compute_fspl_db(total_dist, frequency_hz)
        diffraction_loss = 0.0
        if not has_fresnel:
            h_penetration = -min_rad_clearance
            r1_at_worst = obstacle_info["fresnel_radius_m"]
            v = (h_penetration / (r1_at_worst + 1e-3)) * math.sqrt(2.0)
            diffraction_loss = self.compute_knife_edge_loss_db(v)

        # In Cone of Silence, apply typical antenna overhead null attenuation (-30 dB)
        cone_penalty_db = 30.0 if in_cone_of_silence else 0.0
        total_path_loss = fspl + diffraction_loss + cone_penalty_db

        # 9. Determine Status
        if in_cone_of_silence:
            status = "CONE_OF_SILENCE"
        elif exceeds_max_fl:
            status = "EXCEEDS_MAX_FL"
        elif exceeds_range:
            status = "OUT_OF_RANGE"
        elif not has_los:
            status = "OBSTRUCTED"
        elif not has_fresnel:
            status = "DIFFRACTED"
        else:
            status = "CLEAR"

        return {
            "has_los": bool(has_los),
            "has_fresnel_clearance": bool(has_fresnel),
            "in_cone_of_silence": bool(in_cone_of_silence),
            "exceeds_max_flight_level": bool(exceeds_max_fl),
            "exceeds_operational_range": bool(exceeds_range),
            "status": status,
            "elevation_angle_deg": round(elevation_angle_deg, 2),
            "cone_of_silence_deg": cone_of_silence_deg,
            "max_flight_level_ft": max_flight_level_ft,
            "max_operational_range_km": max_operational_range_km,
            "frequency_hz": frequency_hz,
            "wavelength_m": SPEED_OF_LIGHT / frequency_hz,
            "total_distance_m": float(total_dist),
            "total_distance_km": round(total_dist_km, 2),
            "total_distance_nm": round(total_dist / 1852.0, 2),
            "earth_curvature": {
                "k_factor": self.k_factor,
                "effective_earth_radius_km": round(self.effective_earth_radius / 1000.0, 1),
                "curvature_drop_at_rx_m": round(curvature_drop, 2),
                "max_path_bulge_m": round(float(np.max(earth_bulge)), 2) if len(earth_bulge) > 0 else 0.0,
            },
            "tx": {
                "lon": tx_lon, "lat": tx_lat,
                "ground_elev_m": tx_ground_elev,
                "amsl_m": tx_amsl,
                "amsl_ft": round(tx_amsl * METERS_TO_FT, 1),
            },
            "rx": {
                "lon": rx_lon, "lat": rx_lat,
                "ground_elev_m": rx_ground_elev,
                "amsl_m": rx_amsl,
                "amsl_ft": round(rx_amsl_ft, 1),
            },
            "min_optical_clearance_m": round(min_opt_clearance, 2),
            "min_fresnel_clearance_m": round(min_rad_clearance, 2),
            "fspl_db": round(fspl, 2),
            "diffraction_loss_db": round(diffraction_loss, 2),
            "total_path_loss_db": round(total_path_loss, 2),
            "obstacle": obstacle_info,
            "profile": {
                "distances_m": distances.tolist(),
                "terrain_m": terrain_elevations.tolist(),
                "curved_terrain_m": curved_terrain.tolist(),
                "ray_m": ray_amsl.tolist(),
                "fresnel_lower_m": (ray_amsl - fresnel_60).tolist(),
                "fresnel_upper_m": (ray_amsl + fresnel_60).tolist(),
                "lats": prof["lats"],
                "lons": prof["lons"],
            }
        }
