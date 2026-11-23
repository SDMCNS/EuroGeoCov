"""Airspace 1000-ft Voxel and Coverage Assessment Engine.

Evaluates Line of Sight and radio coverage for 1000-ft cubes throughout the airspace
from single or distributed networks of mountain peak ground stations / transmitters.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from eurogeocov.config import (
    FT_TO_METERS,
    METERS_TO_FT,
    AIRSPACE_CUBE_DEFAULT_FT,
    DEFAULT_FREQUENCIES,
    DEFAULT_CONE_OF_SILENCE_ANGLE_DEG,
)
from eurogeocov.dem_reader import DEMReader
from eurogeocov.propagation import PropagationEngine
from eurogeocov.projection import wgs84_to_laea, laea_to_wgs84


@dataclass
class AirspaceCube:
    """Represents a discrete 1000-ft airspace voxel."""
    center_lat: float
    center_lon: float
    center_alt_ft: float
    size_ft: float = AIRSPACE_CUBE_DEFAULT_FT

    @property
    def alt_floor_ft(self) -> float:
        return self.center_alt_ft - (self.size_ft / 2.0)

    @property
    def alt_ceiling_ft(self) -> float:
        return self.center_alt_ft + (self.size_ft / 2.0)

    @property
    def center_alt_m(self) -> float:
        return self.center_alt_ft * FT_TO_METERS


class AirspaceCoverageEngine:
    """Assesses radio and optical coverage across 1000-ft airspace cubes."""

    def __init__(self, dem_reader: DEMReader, prop_engine: Optional[PropagationEngine] = None):
        self.dem_reader = dem_reader
        self.prop_engine = prop_engine or PropagationEngine(dem_reader=self.dem_reader)

    def evaluate_cube_coverage(
        self,
        cube: AirspaceCube,
        stations: List[Dict[str, Any]],
        frequency_hz: float = DEFAULT_FREQUENCIES["SSR_ADSB_RECEIVE"],
        num_profile_points: int = 150
    ) -> Dict[str, Any]:
        """Assess radio coverage at a specific 1000-ft airspace cube from a list of stations.

        Args:
            cube: AirspaceCube definition.
            stations: List of station dictionaries containing keys:
                      {'id', 'name', 'latitude', 'longitude', 'alt_m' or 'meters', optional 'is_agl'}.
            frequency_hz: Carrier frequency in Hz.
            num_profile_points: Sampling density along each ray path.

        Returns:
            Coverage assessment dictionary including station visibility breakdown,
            total station count, redundancy classification, and best signal path.
        """
        station_results = []
        visible_count = 0
        fresnel_visible_count = 0
        best_fspl = float("inf")
        best_station = None

        for st in stations:
            st_lat = float(st.get("latitude") or st.get("lat"))
            st_lon = float(st.get("longitude") or st.get("lon"))

            # Determine transmitter elevation AMSL and mast height AGL
            if st.get("tx_amsl_m") is not None:
                st_alt = float(st["tx_amsl_m"])
                st_agl = False
            elif st.get("dem_elev_m") is not None:
                st_alt = float(st["dem_elev_m"]) + float(st.get("mast_height_m") or (25.0 if st.get("category") == "RADAR" else 15.0))
                st_agl = False
            elif st.get("reported_elev_m") is not None:
                st_alt = float(st["reported_elev_m"]) + float(st.get("mast_height_m") or 15.0)
                st_agl = False
            else:
                st_alt = float(st.get("dem_meters") or st.get("meters") or st.get("alt_m") or 0.0)
                st_agl = bool(st.get("is_agl", False))

            st_name = st.get("name", "Unknown Station")
            st_id = st.get("id", str(st_name))
            st_cat = str(st.get("category", "")).upper()
            st_type = str(st.get("type", "")).upper()
            default_min_el = 30.0 if ("DME" in st_type and "VOR" not in st_type) else 0.5
            default_max_el = 34.0 if st_cat == "RADAR" else 60.0
            min_el_deg = float(st.get("elevation_min_deg") if st.get("elevation_min_deg") is not None else default_min_el)
            cone_deg = float(st.get("elevation_max_deg") or st.get("cone_of_silence_deg") or default_max_el)
            max_range_km = float(st.get("range_km") or st.get("doc_range_km") or st.get("max_operational_range_km") or 400.0)
            st_freq = float(st.get("frequency_hz") or (float(st.get("frequency_khz")) * 1000.0 if st.get("frequency_khz") else frequency_hz))

            los_eval = self.prop_engine.evaluate_los(
                tx_lon=st_lon,
                tx_lat=st_lat,
                tx_alt_m=st_alt,
                rx_lon=cube.center_lon,
                rx_lat=cube.center_lat,
                rx_alt_m=cube.center_alt_m,
                frequency_hz=st_freq,
                num_points=num_profile_points,
                tx_is_agl=st_agl,
                rx_is_agl=False,
                elevation_min_deg=min_el_deg,
                cone_of_silence_deg=cone_deg,
                max_operational_range_km=max_range_km,
                dem_reader=self.dem_reader
            )

            is_opt_los = los_eval["has_los"]
            is_fresnel = los_eval["has_fresnel_clearance"]
            in_cone = los_eval["in_cone_of_silence"]
            below_beam = los_eval.get("below_min_elevation", False)
            exceeds_fl = los_eval["exceeds_max_flight_level"]
            exceeds_range = los_eval["exceeds_operational_range"]
            fspl = los_eval["total_path_loss_db"]

            # Effective radio coverage requires Fresnel clearance, within elevation beam window,
            # not inside Cone of Silence, within useful flight level, and within designated operational range
            is_usable_coverage = is_fresnel and not in_cone and not below_beam and not exceeds_fl and not exceeds_range

            # Diagnostic classification
            if in_cone:
                diag_status = "CONE_OF_SILENCE"
            elif below_beam:
                diag_status = "BELOW_BEAM_MIN"
            elif exceeds_range:
                diag_status = "OUT_OF_RANGE"
            elif exceeds_fl:
                diag_status = "EXCEEDS_CEILING"
            elif not is_opt_los:
                diag_status = "TERRAIN_BLOCKED"
            elif not is_fresnel:
                diag_status = "DIFFRACTED"
            else:
                diag_status = "CLEAR"

            if is_opt_los:
                visible_count += 1
            if is_usable_coverage:
                fresnel_visible_count += 1
                if fspl < best_fspl:
                    best_fspl = fspl
                    best_station = st_name

            station_results.append({
                "station_id": st_id,
                "station_name": st_name,
                "ident": st.get("ident") or str(st_name)[:5],
                "category": st.get("category", "STATION"),
                "type": st.get("type", "GENERIC"),
                "distance_km": los_eval["total_distance_km"],
                "elevation_angle_deg": los_eval["elevation_angle_deg"],
                "in_cone_of_silence": in_cone,
                "below_min_elevation": below_beam,
                "elevation_min_deg": min_el_deg,
                "elevation_max_deg": cone_deg,
                "exceeds_max_fl": exceeds_fl,
                "exceeds_range": exceeds_range,
                "has_los": is_opt_los,
                "has_fresnel": is_fresnel,
                "is_usable_coverage": is_usable_coverage,
                "status": los_eval["status"],
                "detailed_status": diag_status,
                "min_clearance_m": los_eval["min_fresnel_clearance_m"],
                "path_loss_db": fspl,
            })

        # Redundancy tier
        if fresnel_visible_count == 0:
            redundancy = "NO_COVERAGE"
        elif fresnel_visible_count == 1:
            redundancy = "SINGLE_COVERAGE"
        elif fresnel_visible_count == 2:
            redundancy = "DUAL_REDUNDANT"
        else:
            redundancy = "MULTILATERATION_READY"

        return {
            "cube": {
                "center_lat": cube.center_lat,
                "center_lon": cube.center_lon,
                "center_alt_ft": cube.center_alt_ft,
                "center_alt_m": round(cube.center_alt_m, 1),
                "alt_floor_ft": cube.alt_floor_ft,
                "alt_ceiling_ft": cube.alt_ceiling_ft,
                "size_ft": cube.size_ft,
            },
            "is_covered": fresnel_visible_count > 0,
            "has_optical_los": visible_count > 0,
            "visible_stations_count": fresnel_visible_count,
            "optical_stations_count": visible_count,
            "redundancy_level": redundancy,
            "best_station": best_station,
            "best_path_loss_db": round(best_fspl, 2) if best_station else None,
            "stations_evaluated": len(stations),
            "station_details": station_results,
        }

    def evaluate_vertical_column(
        self,
        lat: float,
        lon: float,
        stations: List[Dict[str, Any]],
        min_alt_ft: float = 1000.0,
        max_alt_ft: float = 45000.0,
        step_ft: float = 1000.0,
        frequency_hz: float = DEFAULT_FREQUENCIES["SSR_ADSB_RECEIVE"],
    ) -> Dict[str, Any]:
        """Evaluate a vertical stack of 1000-ft cubes over a ground coordinate.

        Determines the lowest altitude where Line-of-Sight is established (Coverage Floor).
        """
        ground_elev_m = self.dem_reader.get_elevation_wgs84(lon, lat)
        ground_elev_ft = ground_elev_m * METERS_TO_FT

        altitudes = np.arange(min_alt_ft, max_alt_ft + step_ft, step_ft)
        cube_results = []
        coverage_floor_ft = None

        for alt_ft in altitudes:
            cube = AirspaceCube(center_lat=lat, center_lon=lon, center_alt_ft=float(alt_ft))
            res = self.evaluate_cube_coverage(cube, stations, frequency_hz=frequency_hz, num_profile_points=100)
            primary = res["station_details"][0] if res.get("station_details") else {}
            details = res.get("station_details", [])

            covering_stations = [s for s in details if s.get("is_usable_coverage")]
            covering_idents = [
                (s.get("ident") or s.get("station_name", "STA"))[:3].upper()
                for s in covering_stations
            ]
            covering_names = [
                f"{(s.get('ident') or s.get('station_name', 'STA'))[:3].upper()} ({s.get('type') or s.get('category') or 'STA'})"
                for s in covering_stations
            ]
            station_breakdown = [
                {
                    "ident": (s.get("ident") or s.get("station_name", "STA"))[:3].upper(),
                    "name": s.get("station_name"),
                    "is_covered": s.get("is_usable_coverage", False),
                    "status": s.get("detailed_status", "UNKNOWN"),
                    "distance_km": s.get("distance_km"),
                    "path_loss_db": s.get("path_loss_db"),
                }
                for s in details
            ]

            cube_results.append({
                "alt_ft": float(alt_ft),
                "is_covered": res["is_covered"],
                "visible_stations": res["visible_stations_count"],
                "covering_count": len(covering_stations),
                "covering_idents": covering_idents,
                "covering_names": covering_names,
                "station_breakdown": station_breakdown,
                "best_station": res["best_station"],
                "path_loss_db": res["best_path_loss_db"],
                "status": primary.get("status", "UNKNOWN"),
                "detailed_status": primary.get("detailed_status", "UNKNOWN"),
                "distance_km": primary.get("distance_km"),
                "elevation_angle_deg": primary.get("elevation_angle_deg"),
                "min_clearance_m": primary.get("min_clearance_m"),
                "in_cone_of_silence": primary.get("in_cone_of_silence", False),
                "below_min_elevation": primary.get("below_min_elevation", False),
                "elevation_min_deg": primary.get("elevation_min_deg", 0.5),
                "elevation_max_deg": primary.get("elevation_max_deg", 60.0),
                "exceeds_range": primary.get("exceeds_range", False),
            })
            if coverage_floor_ft is None and res["is_covered"]:
                coverage_floor_ft = float(alt_ft)

        return {
            "lat": lat,
            "lon": lon,
            "ground_elevation_m": round(ground_elev_m, 1),
            "ground_elevation_ft": round(ground_elev_ft, 1),
            "coverage_floor_ft": coverage_floor_ft,
            "coverage_floor_m": round(coverage_floor_ft * FT_TO_METERS, 1) if coverage_floor_ft else None,
            "column_samples": cube_results,
            "evaluated_stations": [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "ident": s.get("ident") or str(s.get("name", ""))[:5],
                    "category": s.get("category", "STATION"),
                    "type": s.get("type", "GENERIC"),
                    "lat": float(s.get("latitude") or s.get("lat") or 0.0),
                    "lon": float(s.get("longitude") or s.get("lon") or 0.0),
                }
                for s in stations
            ]
        }

    def evaluate_airspace_slice(
        self,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        altitude_ft: float,
        stations: List[Dict[str, Any]],
        grid_dim: int = 15,
        frequency_hz: float = DEFAULT_FREQUENCIES["SSR_ADSB_RECEIVE"],
    ) -> Dict[str, Any]:
        """Evaluate a horizontal 2D slice of 1000-ft airspace cubes at a given flight altitude.

        Args:
            min_lon, min_lat, max_lon, max_lat: Geographic bounding box.
            altitude_ft: Center altitude in feet (e.g. 10000 ft).
            stations: List of mountain peak transmitters.
            grid_dim: Number of grid voxels along each axis.
            frequency_hz: Radio frequency in Hz.

        Returns:
            Coverage grid containing visibility matrices, coverage percentages, and coordinates.
        """
        lons = np.linspace(min_lon, max_lon, grid_dim)
        lats = np.linspace(min_lat, max_lat, grid_dim)

        visibility_matrix = np.zeros((grid_dim, grid_dim), dtype=int)
        min_path_loss_matrix = np.full((grid_dim, grid_dim), 999.0)

        total_voxels = grid_dim * grid_dim
        covered_voxels = 0

        for r, lat in enumerate(lats):
            for c, lon in enumerate(lons):
                cube = AirspaceCube(center_lat=float(lat), center_lon=float(lon), center_alt_ft=altitude_ft)
                eval_res = self.evaluate_cube_coverage(
                    cube, stations, frequency_hz=frequency_hz, num_profile_points=80
                )
                vis_count = eval_res["visible_stations_count"]
                visibility_matrix[r, c] = vis_count
                if eval_res["best_path_loss_db"] is not None:
                    min_path_loss_matrix[r, c] = eval_res["best_path_loss_db"]

                if vis_count > 0:
                    covered_voxels += 1

        coverage_percent = round((covered_voxels / total_voxels) * 100.0, 1)

        return {
            "altitude_ft": altitude_ft,
            "bounds": {"min_lon": min_lon, "min_lat": min_lat, "max_lon": max_lon, "max_lat": max_lat},
            "grid_dim": grid_dim,
            "total_cubes": total_voxels,
            "covered_cubes": covered_voxels,
            "coverage_percentage": coverage_percent,
            "lats": lats.tolist(),
            "lons": lons.tolist(),
            "visibility_grid": visibility_matrix.tolist(),
            "path_loss_grid": np.where(min_path_loss_matrix == 999.0, None, min_path_loss_matrix).tolist(),
        }

    def evaluate_conical_coverage(
        self,
        tx_lat: float,
        tx_lon: float,
        tx_alt_m: float,
        tx_is_agl: bool = True,
        flight_level_ft: float = 10000.0,
        max_range_km: float = 150.0,
        cone_of_silence_deg: float = DEFAULT_CONE_OF_SILENCE_ANGLE_DEG,
        frequency_hz: float = DEFAULT_FREQUENCIES["SSR_ADSB_RECEIVE"],
        num_radials: int = 72,
        samples_per_radial: int = 25
    ) -> Dict[str, Any]:
        """Compute the horizontal 2D conical slice coverage at a given Flight Level up to max_range_km.

        Accounts for:
        1. Inner boundary: Overhead Cone of Silence (antenna null blind spot).
        2. Outer boundary: User selected range or radio horizon.
        3. Mountain terrain shadow cutoffs along 360-degree radial azimuths from EU-DEM.
        """
        import math

        # 1. Transmitter ground elevation and AMSL
        ground_elev = self.dem_reader.get_elevation_wgs84(tx_lon, tx_lat)
        tx_amsl = (ground_elev + tx_alt_m) if tx_is_agl else tx_alt_m
        target_amsl = flight_level_ft * FT_TO_METERS

        # 2. Inner Cone of Silence radius at target altitude
        delta_h = target_amsl - tx_amsl
        if delta_h > 0 and 0 < cone_of_silence_deg < 90:
            cone_angle_rad = math.radians(cone_of_silence_deg)
            r_cone_m = delta_h / math.tan(cone_angle_rad)
        else:
            r_cone_m = 0.0

        r_cone_km = round(r_cone_m / 1000.0, 2)
        r_max_m = max_range_km * 1000.0

        # Center in LAEA (EPSG:3035)
        x0, y0 = wgs84_to_laea(tx_lon, tx_lat)

        # 3. Outer boundary polygon & radial calculation
        azimuths = np.linspace(0.0, 360.0, num_radials, endpoint=False)
        boundary_coords_latlng = []
        radials_info = []

        # Prepare all coordinates to sample efficiently
        radial_data = []
        all_sample_coords_laea = []

        step_dists = np.linspace(max(100.0, r_cone_m), r_max_m, samples_per_radial)

        for az in azimuths:
            rad = math.radians(az)
            ux = math.sin(rad)
            uy = math.cos(rad)

            xs = x0 + step_dists * ux
            ys = y0 + step_dists * uy

            start_idx = len(all_sample_coords_laea)
            all_sample_coords_laea.extend(zip(xs, ys))
            radial_data.append({
                "azimuth": float(az),
                "ux": ux, "uy": uy,
                "start_idx": start_idx,
                "end_idx": start_idx + len(step_dists)
            })

        # Batch sample DEM for all radials in one call
        all_elevations = self.dem_reader.sample_xy(all_sample_coords_laea)

        effective_radius = self.prop_engine.effective_earth_radius
        total_covered_radials = 0

        for r_item in radial_data:
            az = r_item["azimuth"]
            elevs = np.array(all_elevations[r_item["start_idx"]:r_item["end_idx"]])

            # Ray AMSL along radial
            t = step_dists / r_max_m
            ray_amsl = tx_amsl + t * (target_amsl - tx_amsl)

            # Earth bulge along radial
            d1 = step_dists
            d2 = r_max_m - step_dists
            bulge = (d1 * d2) / (2.0 * effective_radius)

            curved_terrain = elevs + bulge

            # Fresnel zone 60%
            r1 = self.prop_engine.compute_fresnel_radius(d1, d2, frequency_hz)
            fresnel_60 = 0.6 * r1

            # Check for blockage along radial
            clearance = ray_amsl - curved_terrain - fresnel_60
            blocked_indices = np.where(clearance < 0.0)[0]

            if len(blocked_indices) > 0:
                first_blocked = blocked_indices[0]
                reach_dist = float(step_dists[first_blocked])
                is_blocked = True
                obst_elev = float(elevs[first_blocked])
            else:
                reach_dist = r_max_m
                is_blocked = False
                obst_elev = None

            reach_x = x0 + reach_dist * r_item["ux"]
            reach_y = y0 + reach_dist * r_item["uy"]
            lon_deg, lat_deg = laea_to_wgs84(reach_x, reach_y)

            boundary_coords_latlng.append([round(float(lat_deg), 5), round(float(lon_deg), 5)])

            if reach_dist > r_cone_m + 500.0:
                total_covered_radials += 1

            radials_info.append({
                "azimuth_deg": round(az, 1),
                "reach_km": round(reach_dist / 1000.0, 1),
                "is_blocked": is_blocked,
                "obstacle_elev_m": obst_elev,
                "lat": round(float(lat_deg), 5),
                "lon": round(float(lon_deg), 5)
            })

        # Close polygon
        if boundary_coords_latlng:
            boundary_coords_latlng.append(boundary_coords_latlng[0])

        # 4. Generate Inner Cone of Silence circle coordinates
        cone_circle_coords_latlng = []
        if r_cone_m > 50.0:
            for az in np.linspace(0.0, 360.0, 36, endpoint=True):
                rad = math.radians(az)
                cx = x0 + r_cone_m * math.sin(rad)
                cy = y0 + r_cone_m * math.cos(rad)
                clon, clat = laea_to_wgs84(cx, cy)
                cone_circle_coords_latlng.append([round(float(clat), 5), round(float(clon), 5)])

        # Estimated coverage area (approximate sum of radial triangles minus cone area)
        avg_reach_km = float(np.mean([r["reach_km"] for r in radials_info]))
        total_outer_area = math.pi * (avg_reach_km ** 2)
        cone_area = math.pi * (r_cone_km ** 2)
        effective_coverage_area = max(0.0, total_outer_area - cone_area)

        return {
            "flight_level_ft": flight_level_ft,
            "flight_level_m": round(target_amsl, 1),
            "max_range_km": max_range_km,
            "cone_of_silence_deg": cone_of_silence_deg,
            "cone_of_silence_radius_km": r_cone_km,
            "tx": {
                "lat": tx_lat,
                "lon": tx_lon,
                "ground_elev_m": round(ground_elev, 1),
                "amsl_m": round(tx_amsl, 1),
            },
            "boundary_polygon": boundary_coords_latlng,
            "inner_cone_circle": cone_circle_coords_latlng,
            "coverage_area_sq_km": round(effective_coverage_area, 1),
            "radials_count": num_radials,
            "radials": radials_info,
        }

    def evaluate_station_radials(
        self,
        station: Dict[str, Any],
        flight_level_ft: float = 10000.0,
        override_range_km: Optional[float] = None,
        num_radials: int = 72,
        samples_per_radial: int = 25,
        frequency_hz: Optional[float] = None
    ) -> Dict[str, Any]:
        """Compute radial lines of sight and jagged broken-edged perimeter for a specific station (VOR, DME, Radar, or Peak).

        Accounts for:
        1. Low-powered DME (TMA ~25 NM) vs High-powered enroute DME/VOR (~130 NM) vs Radar (~200 NM).
        2. Supported transmission/reception azimuth sectors.
        3. Supported elevation beam angles (e.g. 0.5° minimum, radar ceiling or cone of silence maximum).
        4. Radial lines that STOP at the exact point where terrain cuts Line-of-Sight.
        5. The resulting jagged and broken-edged circle view.
        """
        import math

        lat = float(station.get("latitude") or station.get("lat"))
        lon = float(station.get("longitude") or station.get("lon"))

        # Elevation: DEM elevation or reported
        dem_elev = station.get("dem_elev_m") or station.get("dem_meters")
        if dem_elev is None:
            dem_elev = self.dem_reader.get_elevation_wgs84(lon, lat)
        ground_elev = float(dem_elev)

        mast_h = float(station.get("mast_height_m") or 25.0)
        tx_amsl = ground_elev + mast_h

        # Operational range: high vs low DME / radar
        base_range_km = float(station.get("range_km") or 100.0)
        max_range_km = override_range_km if override_range_km is not None else base_range_km
        r_max_m = max_range_km * 1000.0

        # Frequency: default by category if not given
        cat = station.get("category", "NAVAID")
        if frequency_hz is None:
            if cat == "RADAR":
                frequency_hz = 1090e6
            elif "VOR" in str(station.get("type", "")):
                frequency_hz = (station.get("frequency_khz") or 115000.0) * 1000.0
            elif "DME" in str(station.get("type", "")):
                frequency_hz = 1025e6
            else:
                frequency_hz = 1090e6

        # Target Flight Level
        target_amsl = flight_level_ft * FT_TO_METERS

        # Angular limits: Elevation & Azimuth
        st_cat = str(station.get("category", "")).upper()
        st_type = str(station.get("type", "")).upper()
        default_min_el = 30.0 if ("DME" in st_type and "VOR" not in st_type) else 0.5
        default_max_el = 34.0 if st_cat == "RADAR" else 60.0
        elev_min_deg = float(station.get("elevation_min_deg") if station.get("elevation_min_deg") is not None else default_min_el)
        elev_max_deg = float(station.get("elevation_max_deg") if station.get("elevation_max_deg") is not None else default_max_el)
        az_start = float(station.get("azimuth_start_deg") or 0.0)
        az_end = float(station.get("azimuth_end_deg") or 360.0)

        # Cone of silence inner radius at target altitude
        delta_h = target_amsl - tx_amsl
        if delta_h > 0 and 0 < elev_max_deg < 90:
            cone_angle_rad = math.radians(elev_max_deg)
            r_cone_m = delta_h / math.tan(cone_angle_rad)
        else:
            r_cone_m = 0.0
        r_cone_km = round(r_cone_m / 1000.0, 2)

        # Lower elevation cutoff outer limit (e.g. DME 30-degree window)
        if delta_h > 0 and elev_min_deg > 0.5:
            beam_outer_limit_m = delta_h / math.tan(math.radians(elev_min_deg))
            r_max_m = min(r_max_m, beam_outer_limit_m)

        # Station center in EPSG:3035
        x0, y0 = wgs84_to_laea(lon, lat)

        azimuths = np.linspace(0.0, 360.0, num_radials, endpoint=False)
        step_dists = np.linspace(max(100.0, r_cone_m), r_max_m, samples_per_radial)

        radial_lines = []
        jagged_perimeter = []
        all_sample_coords = []
        radial_meta = []

        # Check if azimuth is in supported transmission sector
        def is_azimuth_supported(az):
            if az_start <= az_end:
                return az_start <= az <= az_end
            else:
                # Wrap-around across 360/0
                return az >= az_start or az <= az_end

        for az in azimuths:
            supported = is_azimuth_supported(az)
            rad = math.radians(az)
            ux = math.sin(rad)
            uy = math.cos(rad)

            if not supported:
                radial_meta.append({"azimuth": az, "supported": False, "ux": ux, "uy": uy, "start_idx": -1, "end_idx": -1})
                continue

            xs = x0 + step_dists * ux
            ys = y0 + step_dists * uy

            start_idx = len(all_sample_coords)
            all_sample_coords.extend(zip(xs, ys))
            radial_meta.append({
                "azimuth": az,
                "supported": True,
                "ux": ux, "uy": uy,
                "start_idx": start_idx,
                "end_idx": start_idx + len(step_dists)
            })

        # Batch sample DEM
        elevations = self.dem_reader.sample_xy(all_sample_coords) if all_sample_coords else []
        effective_radius = self.prop_engine.effective_earth_radius

        cut_count = 0
        clear_count = 0

        for r_item in radial_meta:
            az = r_item["azimuth"]
            ux, uy = r_item["ux"], r_item["uy"]

            if not r_item["supported"]:
                continue

            elevs = np.array(elevations[r_item["start_idx"]:r_item["end_idx"]])

            # Cumulative Horizon Angle Calculation (Earth curvature with k=4/3 refraction + terrain obstacles)
            # An obstacle at distance x with elevation h subtends angle:
            #   theta_obs(x) = (h - tx_amsl) / x - x / (2 * R_e)
            # The cumulative horizon angle from station up to distance x is:
            #   theta_horizon(x) = max_{s <= x} theta_obs(s)
            # An aircraft at distance d and flight level target_amsl has angle:
            #   theta_target(d) = (target_amsl - tx_amsl) / d - d / (2 * R_e)
            # Line of Sight is cut where theta_target(d) < theta_horizon(d)
            theta_obs = (elevs - tx_amsl) / step_dists - step_dists / (2.0 * effective_radius)
            theta_horizon = np.maximum.accumulate(theta_obs)
            theta_target = (target_amsl - tx_amsl) / step_dists - step_dists / (2.0 * effective_radius)

            blocked_indices = np.where(theta_target < theta_horizon)[0]

            if len(blocked_indices) > 0:
                first_blocked = blocked_indices[0]
                reach_dist = float(step_dists[first_blocked])
                is_cut = True
                cut_count += 1
                # Find the critical obstacle causing the horizon shadow
                obst_idx = int(np.argmax(theta_obs[:first_blocked + 1]))
                obst_elev = float(elevs[obst_idx])
                obst_d = float(step_dists[obst_idx])
            else:
                reach_dist = r_max_m
                is_cut = False
                clear_count += 1
                obst_elev = None
                obst_d = None

            # Start point (outside cone of silence)
            x_start = x0 + r_cone_m * ux
            y_start = y0 + r_cone_m * uy
            lon_start, lat_start = laea_to_wgs84(x_start, y_start)

            # End point (where line stops if cut, or full range if clear)
            x_end = x0 + reach_dist * ux
            y_end = y0 + reach_dist * uy
            lon_end, lat_end = laea_to_wgs84(x_end, y_end)

            start_pt = [round(float(lat_start), 5), round(float(lon_start), 5)]
            end_pt = [round(float(lat_end), 5), round(float(lon_end), 5)]

            radial_lines.append({
                "azimuth_deg": round(az, 1),
                "reach_km": round(reach_dist / 1000.0, 1),
                "is_cut": is_cut,
                "line_coords": [start_pt, end_pt],
                "obstacle_elev_m": obst_elev,
                "obstacle_dist_km": round(obst_d / 1000.0, 1) if obst_d else None
            })

            jagged_perimeter.append(end_pt)

        # Close perimeter
        if jagged_perimeter:
            jagged_perimeter.append(jagged_perimeter[0])

        # Inner cone circle
        inner_cone_circle = []
        if r_cone_m > 50.0:
            for az in np.linspace(0.0, 360.0, 36, endpoint=True):
                rad = math.radians(az)
                cx = x0 + r_cone_m * math.sin(rad)
                cy = y0 + r_cone_m * math.cos(rad)
                clon, clat = laea_to_wgs84(cx, cy)
                inner_cone_circle.append([round(float(clat), 5), round(float(clon), 5)])

        # Area calculation
        reaches = [r["reach_km"] for r in radial_lines]
        avg_r = float(np.mean(reaches)) if reaches else 0.0
        coverage_area = max(0.0, math.pi * (avg_r ** 2) - math.pi * (r_cone_km ** 2))

        return {
            "station_id": station.get("id"),
            "station_ident": station.get("ident") or station.get("name"),
            "station_name": station.get("name"),
            "station_type": station.get("type"),
            "category": cat,
            "service_category": station.get("service_category"),
            "tx_coords": [round(lat, 5), round(lon, 5)],
            "ground_elev_m": round(ground_elev, 1),
            "tx_amsl_m": round(tx_amsl, 1),
            "flight_level_ft": flight_level_ft,
            "flight_level_m": round(target_amsl, 1),
            "range_km": max_range_km,
            "range_nm": round(max_range_km / 1.852, 1),
            "inner_cone_radius_km": r_cone_km,
            "azimuth_sector": [az_start, az_end],
            "elevation_limits": [elev_min_deg, elev_max_deg],
            "radial_lines": radial_lines,
            "jagged_perimeter": jagged_perimeter,
            "inner_cone_circle": inner_cone_circle,
            "metrics": {
                "coverage_area_sq_km": round(coverage_area, 1),
                "total_radials": len(radial_lines),
                "cut_radials": cut_count,
                "clear_radials": clear_count,
                "cut_percentage": round((cut_count / max(1, len(radial_lines))) * 100.0, 1)
            }
        }

    def evaluate_multi_station_radials(
        self,
        stations: List[Dict[str, Any]],
        flight_level_ft: float = 10000.0,
        override_range_km: Optional[float] = None,
        num_radials: int = 72,
        samples_per_radial: int = 25,
        frequency_hz: Optional[float] = None
    ) -> Dict[str, Any]:
        """Evaluate jagged radial coverage for multiple user-selected stations (DME, VOR, Radars, Peaks)."""
        results = []
        for st in stations:
            res = self.evaluate_station_radials(
                station=st,
                flight_level_ft=flight_level_ft,
                override_range_km=override_range_km,
                num_radials=num_radials,
                samples_per_radial=samples_per_radial,
                frequency_hz=frequency_hz
            )
            results.append(res)

        return {
            "flight_level_ft": flight_level_ft,
            "flight_level_m": round(flight_level_ft * FT_TO_METERS, 1),
            "stations_count": len(stations),
            "stations": results
        }

