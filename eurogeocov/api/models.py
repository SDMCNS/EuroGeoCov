"""Pydantic schemas for the EuroGeoCov REST API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LOSRequest(BaseModel):
    tx_lat: float = Field(..., description="Transmitter latitude in degrees (-90 to 90)")
    tx_lon: float = Field(..., description="Transmitter longitude in degrees (-180 to 180)")
    tx_alt_m: float = Field(..., description="Transmitter altitude in meters")
    tx_is_agl: bool = Field(False, description="Whether tx_alt_m is above ground level (mast height)")
    rx_lat: float = Field(..., description="Receiver / Target latitude in degrees")
    rx_lon: float = Field(..., description="Receiver / Target longitude in degrees")
    rx_alt_m: float = Field(..., description="Receiver / Target altitude in meters")
    rx_is_agl: bool = Field(False, description="Whether rx_alt_m is above ground level")
    frequency_hz: float = Field(1090e6, description="Radio carrier frequency in Hz (default 1090 MHz ADS-B)")
    num_points: int = Field(200, ge=50, le=1000, description="Profile sampling points")
    cone_of_silence_deg: float = Field(60.0, description="Antenna elevation angle cutoff for overhead cone of silence")
    max_flight_level_ft: float = Field(60000.0, description="Maximum useful flight level service ceiling in feet (e.g. FL600)")
    max_operational_range_km: float = Field(370.4, description="Designated operational coverage range in km (e.g. 200 NM)")


class StationInput(BaseModel):
    id: Optional[str] = None
    name: str
    latitude: float
    longitude: float
    meters: Optional[float] = None
    alt_m: Optional[float] = None
    is_agl: bool = False


class AirspaceCubeRequest(BaseModel):
    lat: float
    lon: float
    altitude_ft: float = Field(10000.0, description="Altitude of cube center in feet")
    cube_size_ft: float = Field(1000.0, description="Airspace cube vertical/horizontal thickness in feet")
    frequency_hz: float = Field(1090e6, description="Radio frequency in Hz")
    facility_id: Optional[str] = Field(None, description="Optional facility ID (radar, navaid, custom, or peak)")
    station_ids: Optional[List[str]] = Field(None, description="Optional list of facility IDs")
    stations: Optional[List[StationInput]] = Field(None, description="Optional custom stations (defaults to top European peaks)")


class AirspaceColumnRequest(BaseModel):
    lat: float
    lon: float
    min_alt_ft: float = Field(1000.0, ge=500.0)
    max_alt_ft: float = Field(60000.0, le=60000.0)
    step_ft: float = Field(1000.0, ge=500.0)
    frequency_hz: float = Field(1090e6)
    facility_id: Optional[str] = Field(None, description="Optional facility ID (radar, navaid, custom, or peak)")
    station_ids: Optional[List[str]] = Field(None, description="Optional list of facility IDs")
    stations: Optional[List[StationInput]] = None


class AirspaceSliceRequest(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    altitude_ft: float = Field(10000.0)
    grid_dim: int = Field(15, ge=5, le=40)
    frequency_hz: float = Field(1090e6)
    stations: Optional[List[StationInput]] = None


class ConicalCoverageRequest(BaseModel):
    tx_lat: float = Field(..., description="Transmitter latitude in degrees")
    tx_lon: float = Field(..., description="Transmitter longitude in degrees")
    tx_alt_m: float = Field(..., description="Transmitter altitude in meters (summit or mast)")
    tx_is_agl: bool = Field(True, description="Whether transmitter altitude is mast height AGL")
    flight_level_ft: float = Field(10000.0, ge=1000.0, le=60000.0, description="Target flight level in feet AMSL (FL10 increments)")
    max_range_km: float = Field(150.0, ge=10.0, le=400.0, description="User-selected maximum horizontal range in km")
    cone_of_silence_deg: float = Field(60.0, ge=30.0, le=85.0, description="Antenna elevation angle cutoff for cone of silence")
    frequency_hz: float = Field(1090e6, description="Radio carrier frequency in Hz")
    num_radials: int = Field(72, ge=24, le=180, description="Number of radial azimuths around station (e.g. 72 = every 5°)")


class MultiStationRadialsRequest(BaseModel):
    station_ids: Optional[List[str]] = Field(None, description="List of facility IDs (nav_*, radar_*, or peak_*)")
    custom_stations: Optional[List[Dict[str, Any]]] = Field(None, description="Optional custom stations")
    flight_level_ft: float = Field(10000.0, ge=1000.0, le=60000.0, description="Flight Level in feet AMSL")
    override_range_km: Optional[float] = Field(None, ge=5.0, le=500.0, description="Optional range override in km")
    num_radials: int = Field(72, ge=24, le=180, description="Number of radial spoke rays (e.g. 72 = 5-degree increments)")
    samples_per_radial: int = Field(25, ge=10, le=100, description="Terrain samples per ray")
    frequency_hz: Optional[float] = Field(None, description="Optional radio frequency override in Hz")


class CustomFacilityCreateRequest(BaseModel):
    ident: str = Field(..., min_length=1, max_length=10, description="Facility identifier code (e.g. 'ALPS1', 'ZUR')")
    name: str = Field(..., min_length=1, max_length=100, description="Full facility name (e.g. 'Alpine Surveillance Node 1')")
    category: str = Field("RADAR", description="'RADAR', 'NAVAID', or 'CUSTOM'")
    type: str = Field("MODE-S", description="Specific equipment type ('PSR', 'SSR', 'MODE-S', 'VOR-DME', 'DME-ONLY', 'TACAN', 'TMA-DME')")
    service_category: str = Field("ENROUTE", description="'ENROUTE' or 'TMA'")
    country: str = Field("EU", max_length=5, description="Country code (e.g. 'FR', 'CH', 'DE', 'EU')")
    country_name: str = Field("Custom Facility", max_length=100)
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in WGS84 degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in WGS84 degrees")
    mast_height_m: float = Field(25.0, ge=0.0, le=300.0, description="Antenna mast height above ground in meters")
    range_nm: Optional[float] = Field(None, ge=1.0, le=350.0, description="Designated operational coverage range in NM")
    range_km: Optional[float] = Field(None, ge=1.0, le=650.0, description="Designated operational coverage range in km")
    azimuth_start_deg: float = Field(0.0, ge=0.0, le=360.0, description="Azimuth sector start (degrees true)")
    azimuth_end_deg: float = Field(360.0, ge=0.0, le=360.0, description="Azimuth sector end (degrees true)")
    elevation_min_deg: float = Field(0.5, ge=-5.0, le=30.0, description="Minimum elevation beam angle in degrees")
    elevation_max_deg: float = Field(45.0, ge=5.0, le=89.0, description="Maximum elevation cutoff / Cone of Silence angle in degrees")
    frequency_hz: Optional[float] = Field(None, description="Operating frequency in Hz")
    frequency_khz: Optional[float] = Field(None, description="Operating frequency in kHz")
    dme_channel: Optional[str] = Field(None, description="DME channel (e.g. '108X')")


class TemplateExportRequest(BaseModel):
    category: str = Field("RADAR", description="'RADAR' or 'NAVAID'")
    filename: Optional[str] = Field(None, description="Optional custom filename")
    facilities: List[Dict[str, Any]] = Field(..., description="List of facility objects to format into template CSV")


