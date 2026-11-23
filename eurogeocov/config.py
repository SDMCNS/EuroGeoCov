"""Configuration and default constants for EuroGeoCov."""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DEM_TIFF_DEFAULT = BASE_DIR / "DEMTIFF" / "eudem_dem_3035_europe.tif"
PEAKS_DIR_DEFAULT = BASE_DIR / "peaks" / "data-master"
PEAKS_EUROPE_DIR = BASE_DIR / "peaks" / "data-master" / "europe"
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH_DEFAULT = DATA_DIR / "euro_geodatabase.duckdb"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Physical and Geodetic Constants
SPEED_OF_LIGHT = 299792458.0  # m/s
EARTH_RADIUS_WGS84_A = 6378137.0  # semi-major axis (m)
EARTH_RADIUS_WGS84_B = 6356752.314245  # semi-minor axis (m)
EARTH_MEAN_RADIUS = 6371000.0  # m
STANDARD_K_FACTOR = 4.0 / 3.0  # Standard atmospheric refraction factor

# Airspace Standards
FT_TO_METERS = 0.3048
METERS_TO_FT = 1.0 / FT_TO_METERS
AIRSPACE_CUBE_DEFAULT_FT = 1000.0  # Standard 1000ft airspace cube
AIRSPACE_CUBE_DEFAULT_M = AIRSPACE_CUBE_DEFAULT_FT * FT_TO_METERS  # 304.8m

# Aviation Operational Limits & Antenna Parameters
DEFAULT_CONE_OF_SILENCE_ANGLE_DEG = 60.0  # Elevation angle threshold (degrees) where antenna null occurs
DEFAULT_MAX_FLIGHT_LEVEL_FT = 60000.0    # FL600 (60,000 ft AMSL) maximum useful airspace service ceiling
DEFAULT_MAX_OPERATIONAL_RANGE_KM = 370.4 # 200 Nautical Miles maximum designated operational range (DOC)

# Common Radio Frequencies (Hz)
DEFAULT_FREQUENCIES = {
    "VHF_AIRBAND_COMM": 121.5e6,     # 121.5 MHz VHF Airband Emergency / Comm
    "VHF_VOR_NAV": 114.0e6,          # 114.0 MHz VHF Omni-directional Range
    "UHF_MIL_AIR": 243.0e6,          # 243.0 MHz Military Air Emergency
    "UHF_DME_TACAN": 1025.0e6,       # 1025 MHz Distance Measuring Equipment
    "SSR_ADSB_RECEIVE": 1090.0e6,    # 1090 MHz Mode S / ADS-B Transponder
    "MICROWAVE_LINK_5G": 5.8e9,      # 5.8 GHz Backhaul Microwave Link
    "SATELLITE_C_BAND": 4.0e9,       # 4.0 GHz C-band
    "SATELLITE_KU_BAND": 12.0e9,     # 12.0 GHz Ku-band
}
