"""Unit and integration tests for Precalculated Coverage Engine."""

import sys
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eurogeocov.geodatabase import GeoDatabase
from eurogeocov.api.app import app


class TestCoveragePrecalc(unittest.TestCase):
    """Test suite for precalculated coverage database and API."""

    @classmethod
    def setUpClass(cls):
        cls._client_cm = TestClient(app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._client_cm.__exit__(None, None, None)

    def test_01_geodatabase_has_coverage_table(self):
        db = GeoDatabase(read_only=True)
        tables = [t[0] for t in db.conn.execute("SHOW TABLES").fetchall()]
        self.assertIn("facility_coverage", tables)
        
        # Verify radars are already precalculated
        cnt = db.conn.execute("SELECT count(*) FROM facility_coverage WHERE category = 'RADAR'").fetchone()[0]
        self.assertGreaterEqual(cnt, 100)
        db.close()

    def test_02_get_coverage_api_radar_ids(self):
        # Query precalculated coverage for a radar
        res = self.client.get("/api/facilities/coverage?ids=radar_RAD_333_333&flight_level_ft=10000")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["stations_count"], 1)
        st = data["stations"][0]
        self.assertEqual(st["category"], "RADAR")
        self.assertIn("radial_lines", st)
        self.assertIn("jagged_perimeter", st)
        self.assertGreater(len(st["radial_lines"]), 10)
        self.assertGreater(len(st["jagged_perimeter"]), 10)
        self.assertGreater(st["metrics"]["coverage_area_sq_km"], 1000.0)

    def test_03_get_coverage_api_by_country(self):
        # Query precalculated coverage for Danish radars
        res = self.client.get("/api/facilities/coverage?country=DK&category=RADAR&flight_level_ft=15000")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(data["stations_count"], 5)
        for st in data["stations"]:
            self.assertEqual(st["country"], "DK")
            self.assertEqual(st["category"], "RADAR")
            self.assertGreater(len(st["radial_lines"]), 0)

    def test_04_get_coverage_fallback_uncalculated(self):
        # Query with an unknown or fallback station to verify graceful handling
        res = self.client.get("/api/facilities/coverage?ids=radar_RAD_333_333,peak_00001&flight_level_ft=10000")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(data["stations_count"], 1)

    def test_05_dynamic_fl600_evaluation(self):
        # Query coverage at FL600 (60,000 ft AMSL)
        res = self.client.get("/api/facilities/coverage?ids=radar_RAD_333_333&flight_level_ft=60000")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        st = data["stations"][0]
        self.assertEqual(st["flight_level_ft"], 60000.0)
        # Horizon reach at FL600 should be substantial (> 500 km)
        self.assertGreaterEqual(st["fl600_horizon_km"], 500.0)
        # Radial lines should have reaches extending up to the horizon
        max_reach = max(r["reach_km"] for r in st["radial_lines"])
        self.assertGreater(max_reach, 400.0)

    def test_06_custom_max_range_clipping(self):
        # Query with custom range capping of 120 km
        res = self.client.get("/api/facilities/coverage?ids=radar_RAD_333_333&flight_level_ft=30000&max_range_km=120")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        st = data["stations"][0]
        for r in st["radial_lines"]:
            self.assertLessEqual(r["reach_km"], 120.1)

    def test_07_horizon_profiles_stored_all_facilities(self):
        db = GeoDatabase(read_only=True)
        count = db.conn.execute("SELECT count(*) FROM facility_horizon_profiles").fetchone()[0]
        self.assertEqual(count, 1001)
        db.close()


if __name__ == "__main__":
    unittest.main()
