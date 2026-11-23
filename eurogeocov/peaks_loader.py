"""Loader and parser for Open Peaks GeoJSON dataset.

Traverses continent and country folders, validates coordinates,
enriches peaks with projected EPSG:3035 coordinates, and queries
the DEM raster to calculate DEM elevation vs reported elevation.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Generator, List, Optional, Union
import numpy as np

from eurogeocov.config import PEAKS_EUROPE_DIR, PEAKS_DIR_DEFAULT
from eurogeocov.projection import wgs84_to_laea
from eurogeocov.dem_reader import DEMReader

logger = logging.getLogger(__name__)


class PeaksLoader:
    """Loads, validates, and enriches peaks GeoJSON data."""

    def __init__(self, peaks_dir: Optional[Union[str, Path]] = None):
        self.peaks_dir = Path(peaks_dir) if peaks_dir else PEAKS_EUROPE_DIR

    def scan_peaks(self, validate_coords: bool = True) -> Generator[Dict, None, None]:
        """Scan and parse all .geojson peak files under the directory."""
        if not self.peaks_dir.exists():
            logger.warning("Peaks directory %s does not exist", self.peaks_dir)
            return

        geojson_files = self.peaks_dir.rglob("*.geojson")

        for file_path in geojson_files:
            if file_path.name.startswith("_index"):
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.debug("Failed to read %s: %s", file_path, e)
                continue

            props = data.get("properties", {})
            geom = data.get("geometry", {})
            coords = geom.get("coordinates") if geom else None

            # Determine coordinates from geometry or properties
            lon, lat = None, None
            if coords and len(coords) >= 2 and coords[0] is not None and coords[1] is not None:
                lon = float(coords[0])
                lat = float(coords[1])
            elif props.get("longitude") is not None and props.get("latitude") is not None:
                lon = float(props["longitude"])
                lat = float(props["latitude"])

            if validate_coords:
                if lon is None or lat is None:
                    continue
                # Longitude / Latitude range validation
                if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                    continue
                # Skip 0,0 default / invalid placeholders
                if abs(lon) < 1e-4 and abs(lat) < 1e-4:
                    continue

            # Extract metadata
            name = props.get("name") or file_path.stem.replace("-", " ").title()
            feet = props.get("feet")
            meters = props.get("meters")

            if meters is None and feet is not None:
                meters = round(feet * 0.3048, 1)
            elif feet is None and meters is not None:
                feet = round(meters * 3.28084)

            # Determine country from folder structure if not in properties
            rel_parts = file_path.relative_to(self.peaks_dir).parts
            country = rel_parts[0].replace("-", " ").title() if len(rel_parts) > 1 else "Unknown"

            # Compute projected ETRS89-LAEA coordinates
            x_laea, y_laea = None, None
            if lon is not None and lat is not None:
                x_laea, y_laea = wgs84_to_laea(lon, lat)

            regions = props.get("regions", [])
            if isinstance(regions, list):
                regions_str = ", ".join(regions)
            else:
                regions_str = str(regions)

            record = {
                "id": f"{country.lower()}_{file_path.stem}",
                "name": name,
                "country": country,
                "latitude": lat,
                "longitude": lon,
                "x_laea": float(x_laea) if x_laea is not None else None,
                "y_laea": float(y_laea) if y_laea is not None else None,
                "meters": float(meters) if meters is not None else None,
                "feet": float(feet) if feet is not None else None,
                "dem_meters": None,  # Can be populated during enrichment
                "diff_m": None,
                "regions": regions_str,
                "marker_size": props.get("marker-size", "medium"),
                "file_path": str(file_path),
            }

            yield record

    def load_all_peaks(self, enrich_with_dem: bool = True, dem_reader: Optional[DEMReader] = None) -> List[Dict]:
        """Load all peaks into memory with optional DEM raster elevation enrichment."""
        peaks = list(self.scan_peaks(validate_coords=True))
        logger.info("Loaded %d valid peaks from %s", len(peaks), self.peaks_dir)

        if enrich_with_dem and peaks:
            created_reader = False
            if dem_reader is None:
                try:
                    dem_reader = DEMReader()
                    created_reader = True
                except Exception as e:
                    logger.warning("DEM reader could not be initialized for enrichment: %s", e)

            if dem_reader:
                logger.info("Enriching %d peaks with DEM raster elevations...", len(peaks))
                coords_laea = [(p["x_laea"], p["y_laea"]) for p in peaks]
                sampled_elevs = dem_reader.sample_xy(coords_laea)

                for p, elev in zip(peaks, sampled_elevs):
                    p["dem_meters"] = round(float(elev), 1)
                    if p["meters"] is not None:
                        p["diff_m"] = round(float(elev) - float(p["meters"]), 1)

                if created_reader:
                    dem_reader.close()

        return peaks
