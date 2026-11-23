"""Unit tests for ECAC Navaids (VOR/DME), Radars, and Multi-Station Radial Coverage."""

import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from eurogeocov.navaids_loader import NavaidsAndRadarsLoader, ECAC_COUNTRIES
from eurogeocov.geodatabase import GeoDatabase
from eurogeocov.dem_reader import DEMReader
from eurogeocov.airspace_grid import AirspaceCoverageEngine
from eurogeocov.propagation import PropagationEngine
from eurogeocov.api.app import app


class TestNavaidsAndRadars(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = GeoDatabase(read_only=True)
        try:
            cls.dem = DEMReader()
            cls.prop = PropagationEngine(dem_reader=cls.dem)
            cls.airspace = AirspaceCoverageEngine(dem_reader=cls.dem, prop_engine=cls.prop)
        except Exception:
            cls.dem = None
            cls.prop = None
            cls.airspace = None

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        if cls.dem:
            cls.dem.close()

    def test_navaids_loader_filtering(self):
        """Verify only VOR and DME in ECAC are loaded with correct power ranges."""
        loader = NavaidsAndRadarsLoader()
        navaids = loader.load_ecac_navaids(dem_reader=None)
        self.assertGreaterEqual(len(navaids), 800)

        # Ensure no NDBs or ILS localizers were included
        for n in navaids[:50]:
            self.assertTrue(any(t in n["type"] for t in ["VOR", "DME"]), f"Unexpected type: {n['type']}")
            self.assertIn(n["country"], ECAC_COUNTRIES)

        # Test power range distinction: Low TMA vs High Enroute
        low_dmes = [n for n in navaids if n["service_category"] == "TMA"]
        high_dmes = [n for n in navaids if n["service_category"] == "ENROUTE"]

        self.assertGreater(len(low_dmes), 0)
        self.assertGreater(len(high_dmes), 0)

        # Low power is airport TMA only (<= 40 NM)
        for l in low_dmes[:10]:
            self.assertLessEqual(l["range_nm"], 40.0)

        # High power is enroute (~130 NM)
        for h in high_dmes[:10]:
            self.assertGreaterEqual(h["range_nm"], 100.0)

    def test_radars_loader(self):
        """Verify ECAC surveillance radars are parsed with ranges and angle limits."""
        loader = NavaidsAndRadarsLoader()
        radars = loader.load_ecac_radars(dem_reader=None)
        self.assertGreaterEqual(len(radars), 180)

        r0 = radars[0]
        self.assertIn("range_nm", r0)
        self.assertIn("range_km", r0)
        self.assertIn("azimuth_start_deg", r0)
        self.assertIn("elevation_min_deg", r0)
        self.assertIn("mode_s", r0)

    def test_geodatabase_navaids_and_radars_queries(self):
        """Verify database search methods for navaids and radars."""
        # Search by country
        nav_fr = self.db.search_navaids(country="FR", limit=20)
        self.assertGreater(len(nav_fr), 0)
        for n in nav_fr:
            self.assertEqual(n["country"], "FR")

        # Search radars by mode_s
        rad_all = self.db.search_radars(limit=10)
        self.assertGreater(len(rad_all), 0)

        # Fetch by unique ID
        nav_id = nav_fr[0]["id"]
        fac = self.db.get_facility_by_id(nav_id)
        self.assertIsNotNone(fac)
        self.assertEqual(fac["id"], nav_id)

    def test_station_radials_cut_and_broken_perimeter(self):
        """Verify radial lines stop at obstacle cut points and create a jagged perimeter."""
        if not self.airspace or not self.dem:
            self.skipTest("DEM raster not available")

        # Test with an Alpine VOR/DME facility
        sample_nav = {
            "id": "nav_test_dvl",
            "ident": "DVL",
            "name": "Deauville Test",
            "category": "NAVAID",
            "type": "VOR-DME",
            "latitude": 45.83, # Near Alps
            "longitude": 6.86,
            "range_km": 150.0,
            "range_nm": 81.0,
            "mast_height_m": 25.0,
            "service_category": "ENROUTE"
        }

        res = self.airspace.evaluate_station_radials(
            station=sample_nav,
            flight_level_ft=8000.0, # Moderate altitude in mountain region should cause cuts
            num_radials=36,
            samples_per_radial=20
        )

        self.assertIn("radial_lines", res)
        self.assertIn("jagged_perimeter", res)
        self.assertIn("metrics", res)
        self.assertEqual(len(res["radial_lines"]), 36)

        # Check that radial lines contain start and end points and stop when cut
        cut_radials = [r for r in res["radial_lines"] if r["is_cut"]]
        self.assertGreater(len(cut_radials), 0, "Expected some radials to be cut in Alpine terrain at FL080")

        for r in cut_radials:
            self.assertLess(r["reach_km"], res["range_km"], "Cut radial should stop short of full range")
            self.assertIsNotNone(r["obstacle_elev_m"])
            self.assertEqual(len(r["line_coords"]), 2)

    def test_multi_station_radials_evaluation(self):
        """Verify multi-station simultaneous radial evaluation."""
        if not self.airspace or not self.dem:
            self.skipTest("DEM raster not available")

        stations = [
            {
                "id": "nav_1",
                "ident": "STA1",
                "name": "Station 1",
                "category": "NAVAID",
                "type": "VOR-DME",
                "latitude": 46.0,
                "longitude": 7.0,
                "range_km": 80.0,
            },
            {
                "id": "radar_1",
                "ident": "RAD1",
                "name": "Radar 1",
                "category": "RADAR",
                "type": "ENR-MDS",
                "latitude": 46.5,
                "longitude": 7.5,
                "range_km": 100.0,
            }
        ]

        res = self.airspace.evaluate_multi_station_radials(
            stations=stations,
            flight_level_ft=12000.0,
            num_radials=24,
            samples_per_radial=15
        )

        self.assertEqual(res["flight_level_ft"], 12000.0)
        self.assertEqual(len(res["stations"]), 2)
        self.assertIn("jagged_perimeter", res["stations"][0])
        self.assertIn("jagged_perimeter", res["stations"][1])

    def test_api_navaids_and_radars_endpoints(self):
        """Verify REST API routes for navaids, radars, unified facilities, and multi-station coverage."""
        with TestClient(app) as client:
            # 1. GET /api/navaids
            r_nav = client.get("/api/navaids?limit=5")
            self.assertEqual(r_nav.status_code, 200)
            navs = r_nav.json()
            self.assertGreater(len(navs), 0)

            # 2. GET /api/radars
            r_rad = client.get("/api/radars?limit=5")
            self.assertEqual(r_rad.status_code, 200)
            rads = r_rad.json()
            self.assertGreater(len(rads), 0)

            # 3. GET /api/facilities
            r_fac = client.get("/api/facilities?category=ALL&limit=10")
            self.assertEqual(r_fac.status_code, 200)
            facs = r_fac.json()
            self.assertGreater(len(facs), 0)

            # 4. POST /api/airspace/multi-station-radials
            post_payload = {
                "station_ids": [navs[0]["id"]],
                "flight_level_ft": 10000.0,
                "num_radials": 24,
                "samples_per_radial": 15
            }
            r_multi = client.post("/api/airspace/multi-station-radials", json=post_payload)
            self.assertEqual(r_multi.status_code, 200)
            multi_res = r_multi.json()
            self.assertIn("stations", multi_res)
            self.assertGreater(len(multi_res["stations"]), 0)


if __name__ == "__main__":
    unittest.main()
