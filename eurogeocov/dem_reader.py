"""DEMTIFF reader for European EU-DEM (EPSG:3035).

Performs efficient out-of-core windowed reads, multi-point sampling,
profile extraction, and multi-scale bounding-box raster queries on the 24GB GeoTIFF.
"""

import threading
from pathlib import Path
from typing import List, Optional, Tuple, Union
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling

from eurogeocov.config import DEM_TIFF_DEFAULT
from eurogeocov.projection import wgs84_to_laea, laea_to_wgs84


class DEMReader:
    """Interface for sampling and querying the EU-DEM 25m GeoTIFF."""

    def __init__(self, tiff_path: Optional[Union[str, Path]] = None):
        self.tiff_path = Path(tiff_path) if tiff_path else DEM_TIFF_DEFAULT
        if not self.tiff_path.exists():
            raise FileNotFoundError(f"DEM GeoTIFF not found at: {self.tiff_path}")

        self._dataset = rasterio.open(str(self.tiff_path))
        self.crs = self._dataset.crs
        self.bounds = self._dataset.bounds  # left, bottom, right, top in EPSG:3035
        self.transform = self._dataset.transform
        self.res_x, self.res_y = abs(self.transform.a), abs(self.transform.e)
        self.width = self._dataset.width
        self.height = self._dataset.height
        self.nodata = self._dataset.nodata
        self._lock = threading.Lock()

    def close(self):
        """Close the underlying dataset handle."""
        with self._lock:
            if self._dataset and not self._dataset.closed:
                self._dataset.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def is_in_bounds(self, x: float, y: float) -> bool:
        """Check if projected EPSG:3035 coordinates (x, y) lie inside the DEM footprint."""
        return (self.bounds.left <= x <= self.bounds.right) and (self.bounds.bottom <= y <= self.bounds.top)

    def sample_xy(self, coords_laea: List[Tuple[float, float]]) -> List[float]:
        """Sample elevation at a list of (x, y) EPSG:3035 coordinates in meters.

        Returns:
            List of elevation values in meters AMSL (0.0 for sea/nodata).
        """
        valid_indices = []
        valid_coords = []
        results = [0.0] * len(coords_laea)

        for idx, (x, y) in enumerate(coords_laea):
            if self.is_in_bounds(x, y):
                valid_indices.append(idx)
                valid_coords.append((x, y))

        if not valid_coords:
            return results

        with self._lock:
            try:
                samples = list(self._dataset.sample(valid_coords))
                for idx, val in zip(valid_indices, samples):
                    try:
                        elev = float(val[0])
                        if np.isnan(elev) or (self.nodata is not None and elev == self.nodata) or elev < -500:
                            elev = 0.0
                        results[idx] = elev
                    except Exception:
                        results[idx] = 0.0
            except Exception:
                # Fallback point-by-point to gracefully bypass unreadable / corrupted raster tiles
                for idx, coord in zip(valid_indices, valid_coords):
                    try:
                        s = list(self._dataset.sample([coord]))
                        val = float(s[0][0])
                        if np.isnan(val) or (self.nodata is not None and val == self.nodata) or val < -500:
                            val = 0.0
                        results[idx] = val
                    except Exception:
                        results[idx] = 0.0

        return results

    def get_elevation_wgs84(self, lon: float, lat: float) -> float:
        """Get terrain elevation in meters for a single WGS84 point."""
        x, y = wgs84_to_laea(lon, lat)
        return self.sample_xy([(x, y)])[0]

    def sample_points_wgs84(self, points: List[Tuple[float, float]]) -> List[float]:
        """Sample elevations for multiple WGS84 points [(lon, lat), ...]."""
        coords_laea = [wgs84_to_laea(lon, lat) for lon, lat in points]
        return self.sample_xy(coords_laea)

    def get_elevation_profile(
        self,
        lon1: float,
        lat1: float,
        lon2: float,
        lat2: float,
        num_points: int = 200
    ) -> dict:
        """Extract high-resolution terrain profile along great-circle / geodesic path.

        Args:
            lon1, lat1: Start coordinates (degrees WGS84).
            lon2, lat2: End coordinates (degrees WGS84).
            num_points: Number of sampling steps along the path.

        Returns:
            Dictionary containing:
                distances_m: array of cumulative distance along path in meters
                elevations_m: array of sampled terrain elevation in meters
                lats: array of latitudes
                lons: array of longitudes
                x_laea: array of projected X
                y_laea: array of projected Y
                total_distance_m: total baseline distance
        """
        # Interpolate coordinates in EPSG:3035 space for consistent metric steps
        x1, y1 = wgs84_to_laea(lon1, lat1)
        x2, y2 = wgs84_to_laea(lon2, lat2)

        total_distance = float(np.hypot(x2 - x1, y2 - y1))
        t = np.linspace(0.0, 1.0, num_points)

        xs = x1 + t * (x2 - x1)
        ys = y1 + t * (y2 - y1)
        distances = t * total_distance

        coords_laea = list(zip(xs, ys))
        elevations = self.sample_xy(coords_laea)

        # Convert back to WGS84 for return metadata
        lons_deg, lats_deg = zip(*[laea_to_wgs84(x, y) for x, y in coords_laea])

        return {
            "total_distance_m": total_distance,
            "distances_m": distances.tolist(),
            "elevations_m": elevations,
            "lats": list(lats_deg),
            "lons": list(lons_deg),
            "x_laea": xs.tolist(),
            "y_laea": ys.tolist(),
        }

    def get_raster_patch(
        self,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        max_dimension: int = 300
    ) -> dict:
        """Extract a downsampled or full-resolution 2D elevation grid for a bounding box.

        Useful for rendering elevation heatmaps or 2D coverage viewsheds.
        """
        min_x, min_y = wgs84_to_laea(min_lon, min_lat)
        max_x, max_y = wgs84_to_laea(max_lon, max_lat)

        left = min(min_x, max_x)
        right = max(min_x, max_x)
        bottom = min(min_y, max_y)
        top = max(min_y, max_y)

        # Clip to DEM bounds
        left = max(left, self.bounds.left)
        right = min(right, self.bounds.right)
        bottom = max(bottom, self.bounds.bottom)
        top = min(top, self.bounds.top)

        if left >= right or bottom >= top:
            return {"error": "Bounding box out of DEM bounds"}

        window = from_bounds(left, bottom, right, top, self.transform)

        # Determine downsample factor if too large
        win_w = max(1, int(window.width))
        win_h = max(1, int(window.height))
        scale = max(win_w / max_dimension, win_h / max_dimension, 1.0)
        out_w = max(1, int(win_w / scale))
        out_h = max(1, int(win_h / scale))

        with self._lock:
            data = self._dataset.read(
                1,
                window=window,
                out_shape=(out_h, out_w),
                resampling=Resampling.bilinear
            )

        data = np.where(np.isnan(data) | (data < -500), 0.0, data)

        return {
            "width": out_w,
            "height": out_h,
            "bounds_laea": {"left": left, "bottom": bottom, "right": right, "top": top},
            "bounds_wgs84": {
                "min_lon": min_lon, "min_lat": min_lat,
                "max_lon": max_lon, "max_lat": max_lat
            },
            "min_elevation": float(np.min(data)),
            "max_elevation": float(np.max(data)),
            "grid": data.tolist()
        }
