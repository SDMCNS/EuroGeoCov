"""FastAPI application for EuroGeoCov.

Exposes REST endpoints for European geodatabase querying, DEM elevation profiles,
RF Line of Sight (LoS) calculations, and 1000-ft airspace coverage cubes.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from eurogeocov.config import BASE_DIR, DEM_TIFF_DEFAULT
from eurogeocov.geodatabase import GeoDatabase
from eurogeocov.dem_reader import DEMReader
from eurogeocov.propagation import PropagationEngine
from eurogeocov.airspace_grid import AirspaceCoverageEngine, AirspaceCube
from eurogeocov.api.models import (
    LOSRequest,
    AirspaceCubeRequest,
    AirspaceColumnRequest,
    AirspaceSliceRequest,
    ConicalCoverageRequest,
    MultiStationRadialsRequest,
    CustomFacilityCreateRequest,
)

# Global instances
g_db: Optional[GeoDatabase] = None
g_dem: Optional[DEMReader] = None
g_prop: Optional[PropagationEngine] = None
g_airspace: Optional[AirspaceCoverageEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global g_db, g_dem, g_prop, g_airspace
    try:
        # Check if database needs initial build
        db_path = BASE_DIR / "data" / "euro_geodatabase.duckdb"
        if not db_path.exists():
            builder = GeoDatabase(read_only=False)
            builder.build_database(rebuild=False, enrich_dem=True)
            builder.close()

        # Connect in read-only mode so multiple processes/threads can access simultaneously without locks
        g_db = GeoDatabase(read_only=True)
        peaks_count = g_db.conn.execute("SELECT count(*) FROM peaks").fetchone()[0]
        
        # Check navaids and radars counts
        tables = [t[0] for t in g_db.conn.execute("SHOW TABLES").fetchall()]
        nav_count = g_db.conn.execute("SELECT count(*) FROM navaids").fetchone()[0] if "navaids" in tables else 0
        rad_count = g_db.conn.execute("SELECT count(*) FROM radars").fetchone()[0] if "radars" in tables else 0
        
        print(f"[EuroGeoCov] Geodatabase ready: {peaks_count} peaks, {nav_count} ECAC VOR/DME, {rad_count} ECAC radars.")

    except Exception as e:
        print(f"[EuroGeoCov] Geodatabase init warning: {e}")

    try:
        g_dem = DEMReader()
        g_prop = PropagationEngine(dem_reader=g_dem)
        g_airspace = AirspaceCoverageEngine(dem_reader=g_dem, prop_engine=g_prop)
        print("[EuroGeoCov] DEM engine and RF propagation system initialized.")
    except Exception as e:
        print(f"[EuroGeoCov] DEM Reader init warning: {e}")

    yield

    if g_dem:
        g_dem.close()
    if g_db:
        g_db.close()


app = FastAPI(
    title="EuroGeoCov API",
    description="European Geodatabase, DEMTIFF, and 1000-ft Airspace Coverage Service",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    """Retrieve operational status, DEM metadata, and geodatabase stats."""
    peaks_count = 0
    if g_db:
        try:
            peaks_count = g_db.conn.execute("SELECT count(*) FROM peaks").fetchone()[0]
        except Exception:
            pass

    dem_ready = g_dem is not None
    dem_info = {}
    if dem_ready and g_dem:
        dem_info = {
            "crs": str(g_dem.crs),
            "width": g_dem.width,
            "height": g_dem.height,
            "resolution_m": [g_dem.res_x, g_dem.res_y],
            "bounds_laea": {
                "left": g_dem.bounds.left,
                "bottom": g_dem.bounds.bottom,
                "right": g_dem.bounds.right,
                "top": g_dem.bounds.top,
            }
        }

    return {
        "status": "online",
        "dem_ready": dem_ready,
        "dem_metadata": dem_info,
        "geodatabase": {
            "peaks_indexed": peaks_count,
            "database_path": str(g_db.db_path) if g_db else None,
        }
    }


@app.get("/api/peaks")
def search_peaks(
    q: Optional[str] = Query(None, description="Search by peak name"),
    country: Optional[str] = Query(None, description="Filter by country"),
    min_meters: Optional[float] = Query(None, description="Minimum elevation (m)"),
    max_meters: Optional[float] = Query(None, description="Maximum elevation (m)"),
    min_lon: Optional[float] = Query(None),
    min_lat: Optional[float] = Query(None),
    max_lon: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None),
    limit: int = Query(100, ge=1, le=2000),
) -> List[Dict[str, Any]]:
    """Search mountain peaks with spatial and attribute filters."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")

    bbox = None
    if all(v is not None for v in [min_lon, min_lat, max_lon, max_lat]):
        bbox = (min_lon, min_lat, max_lon, max_lat)

    return g_db.search_peaks(
        query=q,
        country=country,
        min_meters=min_meters,
        max_meters=max_meters,
        bbox=bbox,
        limit=limit
    )


@app.get("/api/peaks/top")
def get_top_peaks(
    limit: int = Query(25, ge=1, le=100),
    country: Optional[str] = Query(None)
) -> List[Dict[str, Any]]:
    """Retrieve highest candidate peaks for antenna / transmitter sites."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    return g_db.get_top_peaks(limit=limit, country=country)


@app.get("/api/peaks/countries")
def get_countries_summary() -> List[Dict[str, Any]]:
    """Summary of indexed peaks aggregated by European country."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    return g_db.get_countries_summary()


@app.get("/api/peaks/{peak_id}")
def get_peak(peak_id: str) -> Dict[str, Any]:
    """Retrieve individual peak details by unique ID."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    peak = g_db.get_peak_by_id(peak_id)
    if not peak:
        raise HTTPException(status_code=404, detail="Peak not found")
    return peak


@app.get("/api/peaks/geojson/all")
def get_peaks_geojson(min_meters: float = Query(0.0)) -> Dict[str, Any]:
    """Export peaks as a GeoJSON FeatureCollection."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    return g_db.export_geojson(min_meters=min_meters)


@app.get("/api/navaids")
def search_navaids(
    q: Optional[str] = Query(None, description="Search by ident (e.g. 'DVL') or name"),
    country: Optional[str] = Query(None, description="Filter by ECAC ISO country code (e.g. 'FRA', 'DEU')"),
    type: Optional[str] = Query(None, description="Filter by type ('VOR', 'DME', 'VOR-DME', 'VORTAC')"),
    power: Optional[str] = Query(None, description="Filter by power ('LOW', 'HIGH', 'MEDIUM')"),
    service_category: Optional[str] = Query(None, description="Service category ('TMA' or 'ENROUTE')"),
    limit: int = Query(100, ge=1, le=1000)
) -> List[Dict[str, Any]]:
    """Query ECAC Navigation Aids (VOR and DME)."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    return g_db.search_navaids(
        query=q,
        country=country,
        nav_type=type,
        power=power,
        service_cat=service_category,
        limit=limit
    )


@app.get("/api/radars")
def search_radars(
    q: Optional[str] = Query(None, description="Search by radar name or code"),
    country: Optional[str] = Query(None, description="Filter by ECAC country code (e.g. 'FR', 'DE')"),
    mode_s: Optional[bool] = Query(None, description="Filter by Mode-S capability"),
    service_category: Optional[str] = Query(None, description="Filter by category ('TERMINAL' or 'ENROUTE')"),
    limit: int = Query(100, ge=1, le=500)
) -> List[Dict[str, Any]]:
    """Query European Surveillance & ATC Radars."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    return g_db.search_radars(
        query=q,
        country=country,
        mode_s=mode_s,
        service_cat=service_category,
        limit=limit
    )


@app.get("/api/facilities")
def search_facilities(
    q: Optional[str] = Query(None, description="Search by ident or name"),
    country: Optional[str] = Query(None, description="Filter by ECAC country code (e.g. 'FR', 'DE')"),
    category: Optional[str] = Query(None, description="'ALL', 'NAVAID', 'RADAR', or 'PEAK'"),
    service_category: Optional[str] = Query(None, description="'TMA' or 'ENROUTE'"),
    limit: int = Query(2500, ge=1, le=5000)
) -> List[Dict[str, Any]]:
    """Unified search across Navaids, Radars, and mountain Peaks."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    
    results: List[Dict[str, Any]] = []
    cat = (category or "ALL").upper()

    # User-created Custom Facilities
    if cat in ("ALL", "RADAR", "NAVAID", "CUSTOM"):
        for c in g_db.get_custom_facilities():
            if cat not in ("ALL", "CUSTOM", c.get("category", "CUSTOM").upper()):
                continue
            if country and (c.get("country") or "").upper() != country.upper():
                continue
            if q:
                ql = q.lower()
                if ql not in c.get("ident", "").lower() and ql not in c.get("name", "").lower():
                    continue
            results.append({
                "id": c["id"],
                "ident": c["ident"],
                "name": c["name"],
                "category": c.get("category", "CUSTOM"),
                "type": c.get("type", "CUSTOM"),
                "service_category": c.get("service_category", "ENROUTE"),
                "latitude": c["latitude"],
                "longitude": c["longitude"],
                "country": c.get("country", "EU"),
                "country_name": c.get("country_name", "Custom Facility"),
                "range_nm": c.get("range_nm", 200.0),
                "range_km": c.get("range_km", 370.4),
                "elev_m": c.get("tx_amsl_m") or (float(c.get("ground_elev_m") or 0.0) + float(c.get("mast_height_m") or 25.0)),
                "mode_s": c.get("mode_s"),
                "azimuth_limits": [c.get("azimuth_start_deg", 0.0), c.get("azimuth_end_deg", 360.0)],
                "elevation_limits": [c.get("elevation_min_deg", 0.5), c.get("elevation_max_deg", 45.0)],
            })

    # Radars first so they always appear prominently
    if cat in ("ALL", "RADAR"):
        rads = g_db.search_radars(query=q, country=country, service_cat=service_category, limit=limit)
        for r in rads:
            results.append({
                "id": r["id"],
                "ident": r["ident"],
                "name": r["name"],
                "category": "RADAR",
                "type": r["type"],
                "service_category": r["service_category"],
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "country": r.get("country"),
                "country_name": r.get("country_name"),
                "range_nm": r["range_nm"],
                "range_km": r["range_km"],
                "elev_m": (r.get("dem_elev_m") or 0.0) + (r.get("mast_height_m") or 25.0),
                "mode_s": r.get("mode_s"),
                "azimuth_limits": [r.get("azimuth_start_deg", 0.0), r.get("azimuth_end_deg", 360.0)],
                "elevation_limits": [r.get("elevation_min_deg", 0.5), r.get("elevation_max_deg", 45.0)],
            })

    # Navaids
    if cat in ("ALL", "NAVAID"):
        navs = g_db.search_navaids(query=q, country=country, service_cat=service_category, limit=limit)
        for n in navs:
            results.append({
                "id": n["id"],
                "ident": n["ident"],
                "name": n["name"],
                "category": "NAVAID",
                "type": n["type"],
                "service_category": n["service_category"],
                "latitude": n["latitude"],
                "longitude": n["longitude"],
                "country": n.get("country"),
                "country_name": n.get("country_name"),
                "range_nm": n["range_nm"],
                "range_km": n["range_km"],
                "elev_m": n.get("dem_elev_m") or n.get("reported_elev_m") or 0.0,
                "power": n.get("power"),
                "frequency_khz": n.get("frequency_khz"),
                "dme_channel": n.get("dme_channel"),
                "azimuth_limits": [n.get("azimuth_start_deg", 0.0), n.get("azimuth_end_deg", 360.0)],
                "elevation_limits": [n.get("elevation_min_deg", 0.5), n.get("elevation_max_deg", 60.0)],
            })

    # Peaks
    if cat in ("ALL", "PEAK"):
        pks = g_db.search_peaks(query=q, country=country, limit=limit)
        for p in pks:
            results.append({
                "id": p["id"],
                "ident": p["name"][:5].upper(),
                "name": p["name"],
                "category": "PEAK",
                "type": "SUMMIT",
                "service_category": "ENROUTE",
                "latitude": p["latitude"],
                "longitude": p["longitude"],
                "country": p.get("country"),
                "country_name": p.get("country"),
                "range_nm": 81.0,
                "range_km": 150.0,
                "elev_m": p.get("dem_meters") or p.get("meters") or 0.0,
                "azimuth_limits": [0.0, 360.0],
                "elevation_limits": [0.5, 60.0],
            })

    return results[:limit]


@app.get("/api/facilities/countries")
def get_facility_countries() -> List[Dict[str, Any]]:
    """Retrieve breakdown of VOR/DME navaids and surveillance radars across ECAC countries."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    return g_db.get_facility_countries_summary()


@app.get("/api/facilities/coverage")
def get_facilities_coverage(
    ids: Optional[str] = Query(None, description="Comma-separated facility IDs (e.g. 'radar_RAD_333_333,nav_85184')"),
    country: Optional[str] = Query(None, description="Filter by ECAC country (e.g. 'FR', 'DE')"),
    category: Optional[str] = Query(None, description="'ALL', 'RADAR', or 'NAVAID'"),
    flight_level_ft: float = Query(10000.0, description="Flight Level in feet AMSL (up to FL600)"),
    max_range_km: Optional[float] = Query(None, description="Optional user max range filter in km"),
    use_doc_range: bool = Query(False, description="Whether to cap coverage to designated operational range (DOC)"),
    limit: int = Query(500, ge=1, le=1000)
) -> Dict[str, Any]:
    """Retrieve precalculated over-the-horizon coverage for selected facilities out to FL600."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")

    fac_ids = [i.strip() for i in ids.split(",") if i.strip()] if ids else None
    stations_data = []

    # 1. First check if FL600 horizon profiles exist for dynamic range and altitude viewing
    profiles = g_db.get_facility_horizon_profiles(
        facility_ids=fac_ids,
        country=country,
        category=category,
        limit=limit
    )

    from eurogeocov.coverage_precalculator import evaluate_coverage_dynamically

    if profiles:
        for p in profiles:
            cap_km = max_range_km
            if use_doc_range and p.get("doc_range_km"):
                cap_km = min(cap_km, p["doc_range_km"]) if cap_km else p["doc_range_km"]
            st = evaluate_coverage_dynamically(p, flight_level_ft=flight_level_ft, max_range_km=cap_km)
            stations_data.append(st)
    else:
        # Fallback to precalculated coverage table
        precalc = g_db.get_facilities_coverage(
            facility_ids=fac_ids,
            country=country,
            category=category,
            flight_level_ft=flight_level_ft,
            limit=limit
        )

        for r in precalc:
            stations_data.append({
                "station_id": r["facility_id"],
                "station_ident": r["facility_ident"],
                "station_name": r["facility_name"],
                "category": r["category"],
                "station_type": r["type"],
                "service_category": r["service_category"],
                "country": r["country"],
                "country_name": r["country_name"],
                "flight_level_ft": r["flight_level_ft"],
                "range_nm": r["range_nm"],
                "range_km": r["range_km"],
                "tx_coords": [r["tx_lat"], r["tx_lon"]],
                "tx_amsl_m": r["tx_amsl_m"],
                "ground_elev_m": r["ground_elev_m"],
                "inner_cone_radius_km": r["inner_cone_radius_km"],
                "azimuth_sector": [r["azimuth_start_deg"], r["azimuth_end_deg"]],
                "elevation_limits": [r["elevation_min_deg"], r["elevation_max_deg"]],
                "radial_lines": r.get("radial_lines", []),
                "jagged_perimeter": r.get("jagged_perimeter", []),
                "metrics": {
                    "coverage_area_sq_km": r["coverage_area_sq_km"],
                    "total_radials": r["total_radials"],
                    "cut_radials": r["cut_radials"],
                    "clear_radials": r["clear_radials"],
                    "cut_percentage": r["cut_percentage"]
                }
            })

    # 2. If specific facility IDs were requested but not in DB, fallback on-the-fly
    if fac_ids and g_airspace:
        found_ids = {s["station_id"] for s in stations_data}
        missing_ids = [fid for fid in fac_ids if fid not in found_ids]
        for mid in missing_ids:
            fac = g_db.get_facility_by_id(mid)
            if fac:
                try:
                    computed = g_airspace.evaluate_station_radials(
                        station=fac,
                        flight_level_ft=flight_level_ft,
                        override_range_km=max_range_km,
                        num_radials=72,
                        samples_per_radial=25
                    )
                    stations_data.append(computed)
                except Exception as e:
                    logger.warning("On-the-fly fallback failed for %s: %s", mid, e)

    return {
        "flight_level_ft": flight_level_ft,
        "flight_level_m": round(flight_level_ft * 0.3048, 1),
        "max_range_km": max_range_km,
        "stations_count": len(stations_data),
        "stations": stations_data
    }


@app.post("/api/facilities/custom")
def create_custom_facility(req: CustomFacilityCreateRequest) -> Dict[str, Any]:
    """Create a new custom station/facility, compute DEM elevation and FL600 horizon profile."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")

    from eurogeocov.projection import wgs84_to_laea
    import uuid
    import time
    import logging
    logger = logging.getLogger("eurogeocov.api")

    fac_id = f"custom_{req.ident.upper()}_{uuid.uuid4().hex[:6]}"
    x_laea, y_laea = wgs84_to_laea(req.longitude, req.latitude)

    # Get ground elevation from DEM
    ground_elev_m = 0.0
    if g_dem:
        try:
            ground_elev_m = g_dem.get_elevation_wgs84(req.longitude, req.latitude)
        except Exception as e:
            ground_elev_m = 0.0

    tx_amsl_m = ground_elev_m + req.mast_height_m

    # Default operational ranges
    rng_nm = req.range_nm
    rng_km = req.range_km
    if rng_nm is None and rng_km is None:
        if req.category.upper() == "RADAR":
            rng_nm = 200.0
            rng_km = 370.4
        elif req.service_category.upper() == "TMA":
            rng_nm = 40.0
            rng_km = 74.1
        else:
            rng_nm = 130.0
            rng_km = 240.8
    elif rng_nm is not None and rng_km is None:
        rng_km = round(rng_nm * 1.852, 1)
    elif rng_km is not None and rng_nm is None:
        rng_nm = round(rng_km / 1.852, 1)

    facility_dict = {
        "id": fac_id,
        "ident": req.ident.upper(),
        "name": req.name,
        "category": req.category.upper(),
        "type": req.type.upper(),
        "service_category": req.service_category.upper(),
        "country": req.country.upper(),
        "country_name": req.country_name,
        "latitude": req.latitude,
        "longitude": req.longitude,
        "x_laea": x_laea,
        "y_laea": y_laea,
        "ground_elev_m": round(ground_elev_m, 1),
        "mast_height_m": req.mast_height_m,
        "tx_amsl_m": round(tx_amsl_m, 1),
        "range_nm": rng_nm,
        "range_km": rng_km,
        "azimuth_start_deg": req.azimuth_start_deg,
        "azimuth_end_deg": req.azimuth_end_deg,
        "elevation_min_deg": req.elevation_min_deg,
        "elevation_max_deg": req.elevation_max_deg,
        "frequency_hz": req.frequency_hz,
        "frequency_khz": req.frequency_khz,
        "dme_channel": req.dme_channel,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # Precalculate FL600 horizon profile for instant dynamic view
    if g_dem:
        try:
            from eurogeocov.coverage_precalculator import CoveragePrecalculator
            calc = CoveragePrecalculator(dem_reader=g_dem, geodatabase=g_db)
            cov_rows, profile_row = calc.precalculate_station_coverage(
                station=facility_dict,
                flight_levels_ft=[1000, 5000, 10000, 15000, 20000, 30000, 40000, 50000, 60000],
                num_radials=72,
                samples_per_radial=50
            )
            facility_dict["fl600_horizon_km"] = profile_row[15]
            facility_dict["fl600_horizon_nm"] = profile_row[16]
            facility_dict["step_dists_json"] = profile_row[23]
            facility_dict["theta_horizon_matrix_json"] = profile_row[24]
        except Exception as e:
            logger.warning("Failed to precalculate horizon for custom station %s: %s", fac_id, e)

    g_db.save_custom_facility(facility_dict)
    return facility_dict


@app.get("/api/facilities/custom")
def list_custom_facilities() -> List[Dict[str, Any]]:
    """List all user-created custom facilities."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    return g_db.get_custom_facilities()


@app.delete("/api/facilities/custom/{facility_id}")
def delete_custom_facility(facility_id: str) -> Dict[str, Any]:
    """Delete a custom facility by ID."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    ok = g_db.delete_custom_facility(facility_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Custom facility {facility_id} not found")
    return {"status": "DELETED", "facility_id": facility_id}


@app.get("/api/facilities/{facility_id}")
def get_facility(facility_id: str) -> Dict[str, Any]:
    """Retrieve details for any facility (navaid, radar, or peak) by unique ID."""
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")
    fac = g_db.get_facility_by_id(facility_id)
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found")
    return fac


@app.post("/api/airspace/multi-station-radials")
def evaluate_multi_station_radials(req: MultiStationRadialsRequest) -> Dict[str, Any]:
    """Evaluate radial lines of sight and jagged broken-edged circle coverage for multiple facilities."""
    if not g_airspace:
        raise HTTPException(status_code=503, detail="Airspace engine not initialized")
    if not g_db:
        raise HTTPException(status_code=503, detail="Geodatabase not initialized")

    resolved_stations: List[Dict[str, Any]] = []

    # 1. Resolve by facility ID
    if req.station_ids:
        for fid in req.station_ids:
            fac = g_db.get_facility_by_id(fid)
            if fac:
                resolved_stations.append(fac)

    # 2. Add any custom stations
    if req.custom_stations:
        resolved_stations.extend(req.custom_stations)

    # 3. Fallback if empty: pick 2 prominent stations (e.g. 1 VOR, 1 Radar, or top peak)
    if not resolved_stations:
        sample_navs = g_db.search_navaids(power="HIGH", limit=2)
        resolved_stations.extend(sample_navs)
        sample_rads = g_db.search_radars(limit=1)
        resolved_stations.extend(sample_rads)

    try:
        return g_airspace.evaluate_multi_station_radials(
            stations=resolved_stations,
            flight_level_ft=req.flight_level_ft,
            override_range_km=req.override_range_km,
            num_radials=req.num_radials,
            samples_per_radial=req.samples_per_radial,
            frequency_hz=req.frequency_hz,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Coverage evaluation error: {e}")



@app.get("/api/dem/elevation")
def get_elevation_point(lat: float, lon: float) -> Dict[str, Any]:
    """Sample terrain elevation from the 24GB EU-DEM GeoTIFF."""
    if not g_dem:
        raise HTTPException(status_code=503, detail="DEM reader not initialized")
    elev = g_dem.get_elevation_wgs84(lon, lat)
    return {
        "lat": lat,
        "lon": lon,
        "elevation_m": round(elev, 2),
        "elevation_ft": round(elev * 3.28084, 1),
    }


@app.post("/api/los/profile")
def calculate_los(req: LOSRequest) -> Dict[str, Any]:
    """Calculate point-to-point Line of Sight, Fresnel zone, and terrain obstacles."""
    if not g_prop or not g_dem:
        raise HTTPException(status_code=503, detail="Propagation engine not initialized")

    try:
        return g_prop.evaluate_los(
            tx_lon=req.tx_lon,
            tx_lat=req.tx_lat,
            tx_alt_m=req.tx_alt_m,
            rx_lon=req.rx_lon,
            rx_lat=req.rx_lat,
            rx_alt_m=req.rx_alt_m,
            frequency_hz=req.frequency_hz,
            num_points=req.num_points,
            tx_is_agl=req.tx_is_agl,
            rx_is_agl=req.rx_is_agl,
            cone_of_silence_deg=req.cone_of_silence_deg,
            max_flight_level_ft=req.max_flight_level_ft,
            max_operational_range_km=req.max_operational_range_km,
            dem_reader=g_dem,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"LoS evaluation error: {e}")


def _resolve_stations(
    custom_stations: Optional[List[Any]] = None,
    facility_id: Optional[str] = None,
    station_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Helper to convert custom stations, resolve by facility ID (radar, navaid, custom), or load default top peaks."""
    if custom_stations:
        return [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in custom_stations]

    ids_to_resolve = []
    if facility_id:
        ids_to_resolve.append(facility_id)
    if station_ids:
        ids_to_resolve.extend(station_ids)

    if ids_to_resolve and g_db:
        resolved = []
        for fid in ids_to_resolve:
            fac = g_db.get_facility_by_id(fid)
            if fac:
                resolved.append(fac)
        if resolved:
            return resolved

    if g_db:
        return g_db.get_top_peaks(limit=10)
    return []


@app.post("/api/airspace/cube")
def evaluate_airspace_cube(req: AirspaceCubeRequest) -> Dict[str, Any]:
    """Assess radio coverage at any 1000-ft cube in the Earth's airspace."""
    if not g_airspace:
        raise HTTPException(status_code=503, detail="Airspace engine not initialized")

    stations = _resolve_stations(req.stations, facility_id=req.facility_id, station_ids=req.station_ids)
    cube = AirspaceCube(
        center_lat=req.lat,
        center_lon=req.lon,
        center_alt_ft=req.altitude_ft,
        size_ft=req.cube_size_ft,
    )
    return g_airspace.evaluate_cube_coverage(cube, stations, frequency_hz=req.frequency_hz)


@app.post("/api/airspace/column")
def evaluate_airspace_column(req: AirspaceColumnRequest) -> Dict[str, Any]:
    """Evaluate vertical stack of 1000-ft airspace cubes to identify the coverage floor."""
    if not g_airspace:
        raise HTTPException(status_code=503, detail="Airspace engine not initialized")

    stations = _resolve_stations(req.stations, facility_id=req.facility_id, station_ids=req.station_ids)
    return g_airspace.evaluate_vertical_column(
        lat=req.lat,
        lon=req.lon,
        stations=stations,
        min_alt_ft=req.min_alt_ft,
        max_alt_ft=req.max_alt_ft,
        step_ft=req.step_ft,
        frequency_hz=req.frequency_hz,
    )


@app.post("/api/airspace/slice")
def evaluate_airspace_slice(req: AirspaceSliceRequest) -> Dict[str, Any]:
    """Evaluate a horizontal 2D slice of 1000-ft airspace cubes at a flight altitude."""
    if not g_airspace:
        raise HTTPException(status_code=503, detail="Airspace engine not initialized")

    stations = _resolve_stations(req.stations)
    return g_airspace.evaluate_airspace_slice(
        min_lon=req.min_lon,
        min_lat=req.min_lat,
        max_lon=req.max_lon,
        max_lat=req.max_lat,
        altitude_ft=req.altitude_ft,
        stations=stations,
        grid_dim=req.grid_dim,
        frequency_hz=req.frequency_hz,
    )


@app.post("/api/airspace/conical-coverage")
def evaluate_conical_coverage(req: ConicalCoverageRequest) -> Dict[str, Any]:
    """Compute horizontal conical coverage slice at a given Flight Level with Cone of Silence & range."""
    if not g_airspace:
        raise HTTPException(status_code=503, detail="Airspace engine not initialized")

    return g_airspace.evaluate_conical_coverage(
        tx_lat=req.tx_lat,
        tx_lon=req.tx_lon,
        tx_alt_m=req.tx_alt_m,
        tx_is_agl=req.tx_is_agl,
        flight_level_ft=req.flight_level_ft,
        max_range_km=req.max_range_km,
        cone_of_silence_deg=req.cone_of_silence_deg,
        frequency_hz=req.frequency_hz,
        num_radials=req.num_radials
    )


@app.get("/api/dependencies")
def get_dependencies_ledger() -> Dict[str, Any]:
    """Return the prototype dependencies record and migration strategy."""
    doc_path = BASE_DIR / "PROTOTYPE_DEPENDENCIES.md"
    content = ""
    if doc_path.exists():
        content = doc_path.read_text(encoding="utf-8")
    return {
        "status": "active",
        "documentation": content
    }


# Mount static frontend
static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(str(static_dir / "index.html"))

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)
