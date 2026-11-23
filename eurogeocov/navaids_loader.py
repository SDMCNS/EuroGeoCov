"""Loader and parser for Aviation Navaids (VOR, DME) and Radars in the ECAC area.

Enriches each facility with EU-DEM elevations, determines operational ranges
(TMA low-powered vs Enroute high-powered), and assigns angular transmission/reception limits.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from eurogeocov.config import BASE_DIR
from eurogeocov.dem_reader import DEMReader
from eurogeocov.projection import wgs84_to_laea

logger = logging.getLogger(__name__)

# 44 European Civil Aviation Conference (ECAC) Member States
ECAC_COUNTRIES = {
    "AL", "AM", "AT", "AZ", "BE", "BA", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "GE", "DE", "GR", "HU", "IS", "IE", "IT", "LV", "LT", "LU", "MT", "MD", "MC", "ME",
    "NL", "MK", "NO", "PL", "PT", "RO", "SM", "RS", "SK", "SI", "ES", "SE", "CH", "TR",
    "UA", "GB"
}

ECAC_COUNTRY_NAMES = {
    "AL": "Albania", "AM": "Armenia", "AT": "Austria", "AZ": "Azerbaijan", "BE": "Belgium",
    "BA": "Bosnia and Herzegovina", "BG": "Bulgaria", "HR": "Croatia", "CY": "Cyprus",
    "CZ": "Czech Republic", "DK": "Denmark", "EE": "Estonia", "FI": "Finland", "FR": "France",
    "GE": "Georgia", "DE": "Germany", "GR": "Greece", "HU": "Hungary", "IS": "Iceland",
    "IE": "Ireland", "IT": "Italy", "LV": "Latvia", "LT": "Lithuania", "LU": "Luxembourg",
    "MT": "Malta", "MD": "Moldova", "MC": "Monaco", "ME": "Montenegro", "NL": "Netherlands",
    "MK": "North Macedonia", "NO": "Norway", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "SM": "San Marino", "RS": "Serbia", "SK": "Slovakia", "SI": "Slovenia", "ES": "Spain",
    "SE": "Sweden", "CH": "Switzerland", "TR": "Turkey", "UA": "Ukraine", "GB": "United Kingdom"
}

# Standard ICAO Designated Operational Coverage (DOC) ranges in Nautical Miles & km
# Low-powered DME / Terminal VOR: TMA / Airport approach
RANGE_TMA_LOW_NM = 25.0        # 25 NM ≈ 46.3 km
RANGE_TMA_LOW_KM = RANGE_TMA_LOW_NM * 1.852

RANGE_TMA_MED_NM = 40.0        # 40 NM ≈ 74.1 km
RANGE_TMA_MED_KM = RANGE_TMA_MED_NM * 1.852

# High-powered DME / Enroute VOR: High altitude enroute
RANGE_ENROUTE_HIGH_NM = 130.0  # 130 NM ≈ 240.8 km
RANGE_ENROUTE_HIGH_KM = RANGE_ENROUTE_HIGH_NM * 1.852

# Default Radar ranges
DEFAULT_ENROUTE_RADAR_NM = 200.0  # 200 NM ≈ 370.4 km
DEFAULT_ENROUTE_RADAR_KM = DEFAULT_ENROUTE_RADAR_NM * 1.852
DEFAULT_TERMINAL_RADAR_NM = 60.0  # 60 NM ≈ 111.1 km
DEFAULT_TERMINAL_RADAR_KM = DEFAULT_TERMINAL_RADAR_NM * 1.852


class NavaidsAndRadarsLoader:
    """Parses and enriches VOR/DME navaids and surveillance radars."""

    def __init__(
        self,
        navaids_csv_path: Optional[Union[str, Path]] = None,
        radars_json_path: Optional[Union[str, Path]] = None,
        dem_reader: Optional[DEMReader] = None
    ):
        base_data_dir = BASE_DIR / "radars and navaids"
        self.navaids_csv_path = Path(navaids_csv_path) if navaids_csv_path else base_data_dir / "navaids.csv"
        self.navaids_path = self.navaids_csv_path
        self.radars_json_path = Path(radars_json_path) if radars_json_path else base_data_dir / "radars.json"
        self.dem_reader = dem_reader

    def load_ecac_navaids(self, dem_reader: Optional[DEMReader] = None) -> List[Dict[str, Any]]:
        """Load only VOR and DME navigation aids within the ECAC European area."""
        reader = dem_reader or self.dem_reader
        if not self.navaids_csv_path.exists():
            logger.error("Navaids file not found: %s", self.navaids_csv_path)
            return []

        allowed_types = {"VOR", "DME", "VOR-DME", "VORTAC"}
        navaids = []

        with open(self.navaids_csv_path, mode="r", encoding="utf-8") as f:
            csv_reader = csv.DictReader(f)
            for row in csv_reader:
                nav_type = row.get("type", "").strip()
                country = row.get("iso_country", "").strip()

                if nav_type not in allowed_types or country not in ECAC_COUNTRIES:
                    continue

                try:
                    lat = float(row["latitude_deg"])
                    lon = float(row["longitude_deg"])
                except (ValueError, TypeError):
                    continue

                # Coordinate bounds check for Europe
                if not (-32.0 <= lon <= 50.0 and 32.0 <= lat <= 72.0):
                    continue

                power = row.get("power", "").strip().upper()
                usage = row.get("usageType", "").strip().upper()
                airport = row.get("associated_airport", "").strip()

                # Determine Operational Range based on power class & usage
                # Low powered DME is for airport TMA only; High is for en-route
                if power == "LOW" or usage == "TERMINAL":
                    service_category = "TMA"
                    range_nm = RANGE_TMA_LOW_NM
                    range_km = RANGE_TMA_LOW_KM
                    doc_ceiling_ft = 18000.0
                elif power == "MEDIUM" or usage == "LO":
                    service_category = "TMA"
                    range_nm = RANGE_TMA_MED_NM
                    range_km = RANGE_TMA_MED_KM
                    doc_ceiling_ft = 24000.0
                elif power == "HIGH" or usage in ("HI", "BOTH", "RNAV"):
                    service_category = "ENROUTE"
                    range_nm = RANGE_ENROUTE_HIGH_NM
                    range_km = RANGE_ENROUTE_HIGH_KM
                    doc_ceiling_ft = 60000.0
                else:
                    # Default: if associated with airport and no enroute tag, TMA
                    if airport:
                        service_category = "TMA"
                        range_nm = RANGE_TMA_LOW_NM
                        range_km = RANGE_TMA_LOW_KM
                        doc_ceiling_ft = 18000.0
                    else:
                        service_category = "ENROUTE"
                        range_nm = RANGE_ENROUTE_HIGH_NM
                        range_km = RANGE_ENROUTE_HIGH_KM
                        doc_ceiling_ft = 60000.0

                reported_elev_ft = None
                try:
                    if row.get("elevation_ft"):
                        reported_elev_ft = float(row["elevation_ft"])
                except ValueError:
                    pass

                # Projected coordinates
                x_laea, y_laea = wgs84_to_laea(lon, lat)

                freq_khz = None
                try:
                    if row.get("frequency_khz"):
                        freq_khz = float(row["frequency_khz"])
                except ValueError:
                    pass

                # Standard transmission/reception limits for VOR/DME:
                # - Min elevation angle: 0.5° (ground shielding)
                # - Max elevation angle: 60° (overhead cone of silence)
                # - Azimuth sector: 0° to 360° (omnidirectional unless sectored)
                record = {
                    "id": f"nav_{row['id']}",
                    "ident": row.get("ident", "").strip(),
                    "name": row.get("name", "").strip(),
                    "type": nav_type,
                    "category": "NAVAID",
                    "service_category": service_category,
                    "country": country,
                    "country_name": ECAC_COUNTRY_NAMES.get(country, country),
                    "latitude": lat,
                    "longitude": lon,
                    "x_laea": float(x_laea),
                    "y_laea": float(y_laea),
                    "reported_elev_ft": reported_elev_ft,
                    "reported_elev_m": round(reported_elev_ft * 0.3048, 1) if reported_elev_ft else None,
                    "dem_elev_m": None,
                    "frequency_khz": freq_khz,
                    "dme_channel": row.get("dme_channel", "").strip(),
                    "power": power or "UNKNOWN",
                    "usage_type": usage or "UNKNOWN",
                    "associated_airport": airport,
                    "range_nm": range_nm,
                    "range_km": round(range_km, 1),
                    "doc_ceiling_ft": doc_ceiling_ft,
                    "azimuth_start_deg": 0.0,
                    "azimuth_end_deg": 360.0,
                    "elevation_min_deg": 0.5,
                    "elevation_max_deg": 60.0,
                }
                navaids.append(record)

        # Batch sample DEM raster elevations if reader provided
        if reader and navaids:
            coords = [(n["x_laea"], n["y_laea"]) for n in navaids]
            sampled = reader.sample_xy(coords)
            for n, elev in zip(navaids, sampled):
                n["dem_elev_m"] = round(float(elev), 1)

        logger.info("Loaded %d ECAC VOR/DME navigation aids", len(navaids))
        return navaids

    def load_ecac_radars(self, dem_reader: Optional[DEMReader] = None) -> List[Dict[str, Any]]:
        """Load surveillance and ATC radars within the ECAC European area."""
        reader = dem_reader or self.dem_reader
        if not self.radars_json_path.exists():
            logger.error("Radars file not found: %s", self.radars_json_path)
            return []

        with open(self.radars_json_path, mode="r", encoding="utf-8") as f:
            data = json.load(f)

        # Pre-load navaid coordinate references to accurately resolve radar country by geographic proximity
        nav_coords = []
        if self.navaids_csv_path.exists():
            with open(self.navaids_csv_path, mode="r", encoding="utf-8-sig") as f_nav:
                for row in csv.DictReader(f_nav):
                    c = row.get("iso_country", "").strip().upper()
                    if c in ECAC_COUNTRIES:
                        try:
                            nav_coords.append((float(row["latitude_deg"]), float(row["longitude_deg"]), c))
                        except (ValueError, TypeError):
                            pass

        def resolve_radar_country(r_lat: float, r_lon: float) -> str:
            best_dist = 1e9
            best_country = "EU"
            for n_lat, n_lon, c in nav_coords:
                d = (n_lat - r_lat) ** 2 + (n_lon - r_lon) ** 2
                if d < best_dist:
                    best_dist = d
                    best_country = c
            return best_country

        features = data.get("features", [])
        radars = []

        for idx, feat in enumerate(features):
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates")
            if not coords or len(coords) < 2:
                continue

            lon, lat = float(coords[0]), float(coords[1])

            # Filter for ECAC / European geographic extent
            if not (-32.0 <= lon <= 50.0 and 34.0 <= lat <= 72.0):
                continue

            props = feat.get("properties", {})
            name = props.get("name") or f"Radar-{idx}"
            radar_id = props.get("id") or f"RAD_{idx}"
            radar_type = props.get("type", "ENR-MDS")
            mode_s = bool(props.get("mode_s", False))
            country = resolve_radar_country(lat, lon)
            country_name = ECAC_COUNTRY_NAMES.get(country, country)

            # Parse specified range (e.g. '200 NM', '120 NM', '250 NM')
            range_str = props.get("range", "")
            range_nm = None
            if range_str:
                parts = range_str.replace("NM", "").strip().split()
                try:
                    range_nm = float(parts[0])
                except (ValueError, IndexError):
                    pass

            if not range_nm:
                # Default by radar type
                if radar_type and ("TER" in radar_type or "ASR" in radar_type):
                    range_nm = DEFAULT_TERMINAL_RADAR_NM
                    service_category = "TERMINAL_RADAR"
                else:
                    range_nm = DEFAULT_ENROUTE_RADAR_NM
                    service_category = "ENROUTE_RADAR"
            else:
                service_category = "TERMINAL_RADAR" if range_nm <= 100.0 else "ENROUTE_RADAR"

            range_km = range_nm * 1.852

            x_laea, y_laea = wgs84_to_laea(lon, lat)

            # Radar beam transmission & reception angles:
            # - Primary/Secondary ATC radars: cosecant-squared elevation beam covering ~0.5° to 35°/40°
            # - Overhead null beyond 35°/40° (radar cone of silence)
            record = {
                "id": f"radar_{radar_id}_{idx}",
                "ident": str(radar_id),
                "name": name,
                "type": radar_type or "RADAR",
                "category": "RADAR",
                "service_category": service_category,
                "country": country,
                "country_name": country_name,
                "latitude": lat,
                "longitude": lon,
                "x_laea": float(x_laea),
                "y_laea": float(y_laea),
                "dem_elev_m": None,
                "mast_height_m": 25.0,  # Standard ATC radar tower height AGL
                "mode_s": mode_s,
                "range_nm": range_nm,
                "range_km": round(range_km, 1),
                "doc_ceiling_ft": 60000.0,
                "azimuth_start_deg": 0.0,
                "azimuth_end_deg": 360.0,
                "elevation_min_deg": 0.5,
                "elevation_max_deg": 35.0,
                "source": props.get("source", "")
            }
            radars.append(record)

        # Batch sample DEM raster elevations
        if reader and radars:
            coords = [(r["x_laea"], r["y_laea"]) for r in radars]
            sampled = reader.sample_xy(coords)
            for r, elev in zip(radars, sampled):
                r["dem_elev_m"] = round(float(elev), 1)

        logger.info("Loaded %d ECAC surveillance and ATC radars", len(radars))
        return radars
