"""EuroGeoCov: European Geodatabase, DEMTIFF, and Airspace Coverage Library."""

from eurogeocov.config import (
    DEM_TIFF_DEFAULT,
    PEAKS_EUROPE_DIR,
    DATABASE_PATH_DEFAULT,
    SPEED_OF_LIGHT,
    EARTH_MEAN_RADIUS,
    DEFAULT_FREQUENCIES,
    AIRSPACE_CUBE_DEFAULT_FT
)
from eurogeocov.projection import wgs84_to_laea, laea_to_wgs84
from eurogeocov.dem_reader import DEMReader
from eurogeocov.peaks_loader import PeaksLoader
from eurogeocov.geodatabase import GeoDatabase
from eurogeocov.propagation import PropagationEngine
from eurogeocov.airspace_grid import AirspaceCoverageEngine, AirspaceCube

__version__ = "0.1.0"
__all__ = [
    "DEMReader",
    "PeaksLoader",
    "GeoDatabase",
    "PropagationEngine",
    "AirspaceCoverageEngine",
    "AirspaceCube",
    "wgs84_to_laea",
    "laea_to_wgs84",
    "DEFAULT_FREQUENCIES",
]
