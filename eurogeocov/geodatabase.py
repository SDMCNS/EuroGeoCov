"""European Geodatabase engine backed by DuckDB.

Stores, indexes, and queries European mountain peaks linked to EU-DEM elevations.
Provides spatial bounding-box search, nearest-neighbor lookups, and metadata extraction.
"""

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import duckdb

from eurogeocov.config import DATABASE_PATH_DEFAULT
from eurogeocov.peaks_loader import PeaksLoader
from eurogeocov.navaids_loader import NavaidsAndRadarsLoader
from eurogeocov.dem_reader import DEMReader
from eurogeocov.projection import wgs84_to_laea


class GeoDatabase:
    """Manages spatial queries and storage for European peaks and DEM linkages."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None, read_only: bool = False):
        self.db_path = Path(db_path) if db_path else DATABASE_PATH_DEFAULT
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.read_only = read_only
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        self._lock = threading.RLock()

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            try:
                self._conn = duckdb.connect(str(self.db_path), read_only=self.read_only)
            except duckdb.IOException:
                # If database is locked by another process (e.g. running server), open as read-only
                self._conn = duckdb.connect(str(self.db_path), read_only=True)
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def build_database(self, rebuild: bool = False, enrich_dem: bool = True) -> int:
        """Parse peaks, link with DEM raster elevations, and populate the geodatabase."""
        # Check if table already exists
        if not rebuild:
            tables = self.conn.execute("SHOW TABLES").fetchall()
            table_names = [t[0] for t in tables]
            if "peaks" in table_names:
                count = self.conn.execute("SELECT count(*) FROM peaks").fetchone()[0]
                if count > 0:
                    return count

        loader = PeaksLoader()
        dem_reader = None
        if enrich_dem:
            try:
                dem_reader = DEMReader()
            except Exception:
                dem_reader = None

        peaks = loader.load_all_peaks(enrich_with_dem=enrich_dem, dem_reader=dem_reader)

        # Create table schema
        self.conn.execute("DROP TABLE IF EXISTS peaks")
        self.conn.execute("""
            CREATE TABLE peaks (
                id VARCHAR PRIMARY KEY,
                name VARCHAR,
                country VARCHAR,
                latitude DOUBLE,
                longitude DOUBLE,
                x_laea DOUBLE,
                y_laea DOUBLE,
                meters DOUBLE,
                feet DOUBLE,
                dem_meters DOUBLE,
                diff_m DOUBLE,
                regions VARCHAR,
                marker_size VARCHAR,
                file_path VARCHAR
            )
        """)

        # Insert records in batches
        insert_sql = """
            INSERT INTO peaks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                p["id"], p["name"], p["country"], p["latitude"], p["longitude"],
                p["x_laea"], p["y_laea"], p["meters"], p["feet"],
                p["dem_meters"], p["diff_m"], p["regions"],
                p["marker_size"], p["file_path"]
            )
            for p in peaks
        ]

        self.conn.executemany(insert_sql, rows)

        # Build index for fast spatial bounding box and elevation filtering
        self.conn.execute("CREATE INDEX idx_peaks_coords ON peaks (latitude, longitude)")
        self.conn.execute("CREATE INDEX idx_peaks_meters ON peaks (meters DESC)")
        self.conn.execute("CREATE INDEX idx_peaks_country ON peaks (country)")

        total = self.conn.execute("SELECT count(*) FROM peaks").fetchone()[0]

        # Also build navaids and radars tables
        self.build_navaids_and_radars(rebuild=rebuild, dem_reader=dem_reader)

        if dem_reader:
            try:
                dem_reader.close()
            except Exception:
                pass

        return total

    def build_navaids_and_radars(self, rebuild: bool = False, dem_reader: Optional[DEMReader] = None):
        """Parse and store ECAC VOR/DME navaids and surveillance radars."""
        tables = [t[0] for t in self.conn.execute("SHOW TABLES").fetchall()]
        has_navaids = "navaids" in tables
        has_radars = "radars" in tables

        if not rebuild and has_navaids and has_radars:
            cnt_nav = self.conn.execute("SELECT count(*) FROM navaids").fetchone()[0]
            cnt_rad = self.conn.execute("SELECT count(*) FROM radars").fetchone()[0]
            if cnt_nav > 0 and cnt_rad > 0:
                return cnt_nav, cnt_rad

        owns_reader = False
        reader = dem_reader
        if reader is None or (hasattr(reader, "dataset") and reader.dataset.closed):
            try:
                reader = DEMReader()
                owns_reader = True
            except Exception:
                reader = None

        try:
            loader = NavaidsAndRadarsLoader(dem_reader=reader)
            navaids = loader.load_ecac_navaids(dem_reader=reader)
            radars = loader.load_ecac_radars(dem_reader=reader)
        finally:
            if owns_reader and reader:
                reader.close()


        # 1. Build Navaids Table
        self.conn.execute("DROP TABLE IF EXISTS navaids")
        self.conn.execute("""
            CREATE TABLE navaids (
                id VARCHAR PRIMARY KEY,
                ident VARCHAR,
                name VARCHAR,
                type VARCHAR,
                category VARCHAR,
                service_category VARCHAR,
                country VARCHAR,
                country_name VARCHAR,
                latitude DOUBLE,
                longitude DOUBLE,
                x_laea DOUBLE,
                y_laea DOUBLE,
                reported_elev_ft DOUBLE,
                reported_elev_m DOUBLE,
                dem_elev_m DOUBLE,
                frequency_khz DOUBLE,
                dme_channel VARCHAR,
                power VARCHAR,
                usage_type VARCHAR,
                associated_airport VARCHAR,
                range_nm DOUBLE,
                range_km DOUBLE,
                doc_ceiling_ft DOUBLE,
                azimuth_start_deg DOUBLE,
                azimuth_end_deg DOUBLE,
                elevation_min_deg DOUBLE,
                elevation_max_deg DOUBLE
            )
        """)
        insert_nav = "INSERT INTO navaids VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        nav_rows = [
            (
                n["id"], n["ident"], n["name"], n["type"], n["category"], n["service_category"],
                n["country"], n.get("country_name", n["country"]), n["latitude"], n["longitude"], n["x_laea"], n["y_laea"],
                n["reported_elev_ft"], n["reported_elev_m"], n["dem_elev_m"], n["frequency_khz"],
                n["dme_channel"], n["power"], n["usage_type"], n["associated_airport"],
                n["range_nm"], n["range_km"], n["doc_ceiling_ft"],
                n["azimuth_start_deg"], n["azimuth_end_deg"], n["elevation_min_deg"], n["elevation_max_deg"]
            )
            for n in navaids
        ]
        self.conn.executemany(insert_nav, nav_rows)
        self.conn.execute("CREATE INDEX idx_nav_coords ON navaids (latitude, longitude)")
        self.conn.execute("CREATE INDEX idx_nav_ident ON navaids (ident)")
        self.conn.execute("CREATE INDEX idx_nav_type ON navaids (type)")
        self.conn.execute("CREATE INDEX idx_nav_country ON navaids (country)")

        # 2. Build Radars Table
        self.conn.execute("DROP TABLE IF EXISTS radars")
        self.conn.execute("""
            CREATE TABLE radars (
                id VARCHAR PRIMARY KEY,
                ident VARCHAR,
                name VARCHAR,
                type VARCHAR,
                category VARCHAR,
                service_category VARCHAR,
                country VARCHAR,
                country_name VARCHAR,
                latitude DOUBLE,
                longitude DOUBLE,
                x_laea DOUBLE,
                y_laea DOUBLE,
                dem_elev_m DOUBLE,
                mast_height_m DOUBLE,
                mode_s BOOLEAN,
                range_nm DOUBLE,
                range_km DOUBLE,
                doc_ceiling_ft DOUBLE,
                azimuth_start_deg DOUBLE,
                azimuth_end_deg DOUBLE,
                elevation_min_deg DOUBLE,
                elevation_max_deg DOUBLE,
                source VARCHAR
            )
        """)
        insert_rad = "INSERT INTO radars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        rad_rows = [
            (
                r["id"], r["ident"], r["name"], r["type"], r["category"], r["service_category"],
                r.get("country", "EU"), r.get("country_name", "Europe"),
                r["latitude"], r["longitude"], r["x_laea"], r["y_laea"],
                r["dem_elev_m"], r["mast_height_m"], r["mode_s"],
                r["range_nm"], r["range_km"], r["doc_ceiling_ft"],
                r["azimuth_start_deg"], r["azimuth_end_deg"], r["elevation_min_deg"], r["elevation_max_deg"],
                r["source"]
            )
            for r in radars
        ]
        self.conn.executemany(insert_rad, rad_rows)
        self.conn.execute("CREATE INDEX idx_rad_coords ON radars (latitude, longitude)")
        self.conn.execute("CREATE INDEX idx_rad_name ON radars (name)")
        self.conn.execute("CREATE INDEX idx_rad_country ON radars (country)")

        return len(navaids), len(radars)

    def _query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Thread-safe SQL query returning list of row dictionaries."""
        with self._lock:
            cur = self.conn.cursor()
            try:
                cursor = cur.execute(sql, params or [])
                cols = [desc[0] for desc in cursor.description]
                return [dict(zip(cols, row)) for row in cursor.fetchall()]
            finally:
                cur.close()

    def search_navaids(
        self,
        query: Optional[str] = None,
        country: Optional[str] = None,
        nav_type: Optional[str] = None,
        power: Optional[str] = None,
        service_cat: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Search ECAC VOR and DME navaids."""
        sql = "SELECT * FROM navaids WHERE 1=1"
        params: List[Any] = []
        if query:
            sql += " AND (lower(ident) LIKE lower(?) OR lower(name) LIKE lower(?))"
            q_pat = f"%{query.strip()}%"
            params.extend([q_pat, q_pat])
        if country:
            sql += " AND lower(country) = lower(?)"
            params.append(country.strip())
        if nav_type:
            sql += " AND type = ?"
            params.append(nav_type.strip())
        if power:
            sql += " AND power = ?"
            params.append(power.strip().upper())
        if service_cat:
            sql += " AND service_category = ?"
            params.append(service_cat.strip())
        sql += " ORDER BY ident ASC LIMIT ?"
        params.append(limit)

        return self._query(sql, params)

    def search_radars(
        self,
        query: Optional[str] = None,
        country: Optional[str] = None,
        mode_s: Optional[bool] = None,
        service_cat: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Search ECAC surveillance and ATC radars."""
        sql = "SELECT * FROM radars WHERE 1=1"
        params: List[Any] = []
        if query:
            sql += " AND (lower(name) LIKE lower(?) OR lower(ident) LIKE lower(?))"
            q_pat = f"%{query.strip()}%"
            params.extend([q_pat, q_pat])
        if country:
            sql += " AND lower(country) = lower(?)"
            params.append(country.strip())
        if mode_s is not None:
            sql += " AND mode_s = ?"
            params.append(mode_s)
        if service_cat:
            sql += " AND service_category = ?"
            params.append(service_cat.strip())
        sql += " ORDER BY name ASC LIMIT ?"
        params.append(limit)

        return self._query(sql, params)

    def get_facility_countries_summary(self) -> List[Dict[str, Any]]:
        """Summarize facilities (VOR/DME and Radars) counts by ECAC country."""
        sql = """
            WITH nav_counts AS (
                SELECT country, country_name, count(*) as vor_dme_count
                FROM navaids
                WHERE country IS NOT NULL AND country != ''
                GROUP BY country, country_name
            ),
            radar_counts AS (
                SELECT country, country_name, count(*) as radar_count
                FROM radars
                WHERE country IS NOT NULL AND country != ''
                GROUP BY country, country_name
            )
            SELECT 
                COALESCE(n.country, r.country) as country,
                COALESCE(n.country_name, r.country_name, r.country) as country_name,
                COALESCE(n.vor_dme_count, 0) as vor_dme_count,
                COALESCE(r.radar_count, 0) as radar_count,
                (COALESCE(n.vor_dme_count, 0) + COALESCE(r.radar_count, 0)) as total_facilities
            FROM nav_counts n
            FULL OUTER JOIN radar_counts r ON n.country = r.country
            ORDER BY country_name ASC
        """
        return self._query(sql)

    def get_facility_by_id(self, facility_id: str) -> Optional[Dict[str, Any]]:
        """Fetch facility from navaids, radars, custom facilities, or peaks by unique ID."""
        if facility_id.startswith("nav_"):
            rows = self._query("SELECT * FROM navaids WHERE id = ?", [facility_id])
            return rows[0] if rows else None
        elif facility_id.startswith("radar_"):
            rows = self._query("SELECT * FROM radars WHERE id = ?", [facility_id])
            return rows[0] if rows else None
        elif facility_id.startswith("custom_"):
            return self.get_custom_facility_by_id(facility_id)
        else:
            custom = self.get_custom_facility_by_id(facility_id)
            if custom:
                return custom
            return self.get_peak_by_id(facility_id)

    def get_custom_facilities(self) -> List[Dict[str, Any]]:
        """Retrieve all user-created custom facilities from JSON persistence."""
        custom_file = self.db_path.parent / "custom_facilities.json"
        if not custom_file.exists():
            return []
        try:
            with open(custom_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def get_custom_facility_by_id(self, facility_id: str) -> Optional[Dict[str, Any]]:
        """Find a custom facility by ID."""
        for fac in self.get_custom_facilities():
            if fac.get("id") == facility_id:
                return fac
        return None

    def save_custom_facility(self, facility: Dict[str, Any]) -> Dict[str, Any]:
        """Save or update a custom facility in JSON persistence."""
        custom_file = self.db_path.parent / "custom_facilities.json"
        facilities = self.get_custom_facilities()
        fac_id = facility.get("id")
        facilities = [f for f in facilities if f.get("id") != fac_id]
        facilities.append(facility)
        with open(custom_file, "w", encoding="utf-8") as f:
            json.dump(facilities, f, indent=2)
        return facility

    def delete_custom_facility(self, facility_id: str) -> bool:
        """Delete a custom facility by ID."""
        custom_file = self.db_path.parent / "custom_facilities.json"
        facilities = self.get_custom_facilities()
        filtered = [f for f in facilities if f.get("id") != facility_id]
        if len(filtered) < len(facilities):
            with open(custom_file, "w", encoding="utf-8") as f:
                json.dump(filtered, f, indent=2)
            return True
        return False

    def get_peak_by_id(self, peak_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a peak by unique ID."""
        rows = self._query("SELECT * FROM peaks WHERE id = ?", [peak_id])
        return rows[0] if rows else None

    def init_facility_coverage_table(self):
        """Create the precalculated facility coverage table and indexes."""
        with self._lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS facility_coverage (
                    facility_id VARCHAR,
                    facility_ident VARCHAR,
                    facility_name VARCHAR,
                    category VARCHAR,
                    type VARCHAR,
                    service_category VARCHAR,
                    country VARCHAR,
                    country_name VARCHAR,
                    flight_level_ft DOUBLE,
                    range_nm DOUBLE,
                    range_km DOUBLE,
                    tx_lat DOUBLE,
                    tx_lon DOUBLE,
                    tx_amsl_m DOUBLE,
                    ground_elev_m DOUBLE,
                    inner_cone_radius_km DOUBLE,
                    azimuth_start_deg DOUBLE,
                    azimuth_end_deg DOUBLE,
                    elevation_min_deg DOUBLE,
                    elevation_max_deg DOUBLE,
                    coverage_area_sq_km DOUBLE,
                    total_radials INTEGER,
                    cut_radials INTEGER,
                    clear_radials INTEGER,
                    cut_percentage DOUBLE,
                    radial_lines_json VARCHAR,
                    jagged_perimeter_json VARCHAR,
                    PRIMARY KEY (facility_id, flight_level_ft)
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_fc_fac_fl ON facility_coverage (facility_id, flight_level_ft)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_fc_country_fl ON facility_coverage (country, flight_level_ft)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_fc_cat_fl ON facility_coverage (category, flight_level_ft)")

            # Also ensure facility_horizon_profiles table exists
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS facility_horizon_profiles (
                    facility_id VARCHAR PRIMARY KEY,
                    ident VARCHAR,
                    name VARCHAR,
                    category VARCHAR,
                    type VARCHAR,
                    service_category VARCHAR,
                    country VARCHAR,
                    country_name VARCHAR,
                    latitude DOUBLE,
                    longitude DOUBLE,
                    x_laea DOUBLE,
                    y_laea DOUBLE,
                    tx_amsl_m DOUBLE,
                    ground_elev_m DOUBLE,
                    mast_height_m DOUBLE,
                    fl600_horizon_km DOUBLE,
                    fl600_horizon_nm DOUBLE,
                    doc_range_km DOUBLE,
                    doc_range_nm DOUBLE,
                    azimuth_start_deg DOUBLE,
                    azimuth_end_deg DOUBLE,
                    elevation_min_deg DOUBLE,
                    elevation_max_deg DOUBLE,
                    step_dists_json VARCHAR,
                    theta_horizon_matrix_json VARCHAR
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_fhp_country ON facility_horizon_profiles (country)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_fhp_cat ON facility_horizon_profiles (category)")

    def save_facility_horizon_profiles_batch(self, rows: List[Tuple]):
        """Insert or replace precalculated FL600 horizon profiles."""
        with self._lock:
            cur = self.conn.cursor()
            cur.executemany("""
                INSERT OR REPLACE INTO facility_horizon_profiles VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, rows)

    def get_facility_horizon_profiles(
        self,
        facility_ids: Optional[List[str]] = None,
        country: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Query precalculated FL600 horizon profiles."""
        sql = "SELECT * FROM facility_horizon_profiles WHERE 1=1"
        params: List[Any] = []

        if facility_ids:
            placeholders = ", ".join(["?"] * len(facility_ids))
            sql += f" AND facility_id IN ({placeholders})"
            params.extend(facility_ids)
        if country:
            sql += " AND lower(country) = lower(?)"
            params.append(country.strip())
        if category and category.upper() != "ALL":
            sql += " AND category = ?"
            params.append(category.strip().upper())

        sql += " ORDER BY category DESC, ident ASC LIMIT ?"
        params.append(limit)

        rows = self._query(sql, params)
        import json
        for r in rows:
            if r.get("step_dists_json"):
                try:
                    r["step_dists"] = json.loads(r["step_dists_json"])
                except Exception:
                    r["step_dists"] = []
            if r.get("theta_horizon_matrix_json"):
                try:
                    r["theta_horizon_matrix"] = json.loads(r["theta_horizon_matrix_json"])
                except Exception:
                    r["theta_horizon_matrix"] = []

        # Merge in custom facilities that have horizon profile data
        for c in self.get_custom_facilities():
            if not c.get("step_dists_json") or not c.get("theta_horizon_matrix_json"):
                continue
            if facility_ids and c.get("id") not in facility_ids:
                continue
            if country and (c.get("country") or "").lower() != country.strip().lower():
                continue
            if category and category.upper() != "ALL" and c.get("category", "").upper() != category.upper():
                continue

            try:
                sd = json.loads(c["step_dists_json"]) if isinstance(c["step_dists_json"], str) else c["step_dists_json"]
                th = json.loads(c["theta_horizon_matrix_json"]) if isinstance(c["theta_horizon_matrix_json"], str) else c["theta_horizon_matrix_json"]
            except Exception:
                continue

            rows.append({
                "facility_id": c["id"],
                "ident": c.get("ident"),
                "name": c.get("name"),
                "category": c.get("category", "CUSTOM"),
                "type": c.get("type", "CUSTOM"),
                "service_category": c.get("service_category", "ENROUTE"),
                "country": c.get("country", "EU"),
                "country_name": c.get("country_name", "Custom Facility"),
                "latitude": float(c.get("latitude") or 0.0),
                "longitude": float(c.get("longitude") or 0.0),
                "x_laea": float(c.get("x_laea") or 0.0),
                "y_laea": float(c.get("y_laea") or 0.0),
                "tx_amsl_m": float(c.get("tx_amsl_m") or 0.0),
                "ground_elev_m": float(c.get("ground_elev_m") or 0.0),
                "mast_height_m": float(c.get("mast_height_m") or 25.0),
                "fl600_horizon_km": float(c.get("fl600_horizon_km") or 600.0),
                "fl600_horizon_nm": float(c.get("fl600_horizon_nm") or 324.0),
                "doc_range_km": float(c.get("range_km") or 370.4),
                "doc_range_nm": float(c.get("range_nm") or 200.0),
                "azimuth_start_deg": float(c.get("azimuth_start_deg") or 0.0),
                "azimuth_end_deg": float(c.get("azimuth_end_deg") or 360.0),
                "elevation_min_deg": float(c.get("elevation_min_deg") or 0.5),
                "elevation_max_deg": float(c.get("elevation_max_deg") or 45.0),
                "step_dists": sd,
                "theta_horizon_matrix": th,
            })

        return rows

    def save_facility_coverage_batch(self, rows: List[Tuple]):
        """Insert or replace a batch of precalculated facility coverage records."""
        with self._lock:
            cur = self.conn.cursor()
            cur.executemany("""
                INSERT OR REPLACE INTO facility_coverage VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, rows)

    def get_facilities_coverage(
        self,
        facility_ids: Optional[List[str]] = None,
        country: Optional[str] = None,
        category: Optional[str] = None,
        flight_level_ft: float = 10000.0,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Query precalculated coverage for facilities by ID list, country, or category at flight level."""
        # Find closest precalculated flight level
        sql_levels = "SELECT DISTINCT flight_level_ft FROM facility_coverage"
        avail_levels = [row["flight_level_ft"] for row in self._query(sql_levels)]

        target_fl = flight_level_ft
        if avail_levels:
            target_fl = min(avail_levels, key=lambda fl: abs(fl - flight_level_ft))

        sql = "SELECT * FROM facility_coverage WHERE flight_level_ft = ?"
        params: List[Any] = [target_fl]

        if facility_ids:
            placeholders = ", ".join(["?"] * len(facility_ids))
            sql += f" AND facility_id IN ({placeholders})"
            params.extend(facility_ids)
        if country:
            sql += " AND lower(country) = lower(?)"
            params.append(country.strip())
        if category and category.upper() != "ALL":
            sql += " AND category = ?"
            params.append(category.strip().upper())

        sql += " ORDER BY category DESC, facility_ident ASC LIMIT ?"
        params.append(limit)

        rows = self._query(sql, params)
        import json
        for r in rows:
            if r.get("radial_lines_json"):
                try:
                    r["radial_lines"] = json.loads(r["radial_lines_json"])
                except Exception:
                    r["radial_lines"] = []
            if r.get("jagged_perimeter_json"):
                try:
                    r["jagged_perimeter"] = json.loads(r["jagged_perimeter_json"])
                except Exception:
                    r["jagged_perimeter"] = []
        return rows

    def search_peaks(
        self,
        query: Optional[str] = None,
        country: Optional[str] = None,
        min_meters: Optional[float] = None,
        max_meters: Optional[float] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,  # (min_lon, min_lat, max_lon, max_lat)
        limit: int = 100,
        order_by: str = "meters DESC"
    ) -> List[Dict[str, Any]]:
        """Search peaks with spatial and attribute filters."""
        sql = "SELECT * FROM peaks WHERE 1=1"
        params: List[Any] = []

        if query:
            sql += " AND lower(name) LIKE lower(?)"
            params.append(f"%{query.strip()}%")

        if country:
            sql += " AND lower(country) = lower(?)"
            params.append(country.strip())

        if min_meters is not None:
            sql += " AND meters >= ?"
            params.append(min_meters)

        if max_meters is not None:
            sql += " AND meters <= ?"
            params.append(max_meters)

        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            sql += " AND longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?"
            params.extend([min_lon, max_lon, min_lat, max_lat])

        sql += f" ORDER BY {order_by} LIMIT ?"
        params.append(limit)

        return self._query(sql, params)

    def get_top_peaks(self, limit: int = 25, country: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get highest European peaks (ideal candidates for communication relays/transmitters)."""
        return self.search_peaks(country=country, limit=limit, order_by="meters DESC")

    def get_countries_summary(self) -> List[Dict[str, Any]]:
        """Summarize peaks count and max elevations by country."""
        sql = """
            SELECT country, count(*) as count, max(meters) as max_meters, avg(meters) as avg_meters
            FROM peaks
            GROUP BY country
            ORDER BY count DESC
        """
        return self._query(sql)

    def find_nearest_peaks(self, lat: float, lon: float, limit: int = 5) -> List[Dict[str, Any]]:
        """Find peaks closest to a given coordinate using projected Euclidean distance."""
        x_target, y_target = wgs84_to_laea(lon, lat)
        sql = """
            SELECT *, sqrt(power(x_laea - ?, 2) + power(y_laea - ?, 2)) as distance_m
            FROM peaks
            WHERE x_laea IS NOT NULL
            ORDER BY distance_m ASC
            LIMIT ?
        """
        return self._query(sql, [x_target, y_target, limit])

    def export_geojson(self, min_meters: float = 0.0) -> Dict[str, Any]:
        """Export peaks as a GeoJSON FeatureCollection."""
        peaks = self.search_peaks(min_meters=min_meters, limit=5000)
        features = []
        for p in peaks:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [p["longitude"], p["latitude"]]
                },
                "properties": {
                    "id": p["id"],
                    "name": p["name"],
                    "country": p["country"],
                    "meters": p["meters"],
                    "feet": p["feet"],
                    "dem_meters": p["dem_meters"],
                    "diff_m": p["diff_m"],
                    "regions": p["regions"],
                }
            })
        return {
            "type": "FeatureCollection",
            "features": features
        }
