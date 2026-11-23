"""API integration tests for EuroGeoCov FastAPI endpoints."""

import sys
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eurogeocov.api.app import app


class TestAPI(unittest.TestCase):
    """Integration test suite for EuroGeoCov HTTP endpoints."""

    @classmethod
    def setUpClass(cls):
        cls._client_cm = TestClient(app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._client_cm.__exit__(None, None, None)

    def test_01_status_endpoint(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "online")
        self.assertTrue(data["dem_ready"])
        self.assertGreater(data["geodatabase"]["peaks_indexed"], 900)

    def test_02_peaks_search(self):
        res = self.client.get("/api/peaks?q=Matterhorn")
        self.assertEqual(res.status_code, 200)
        peaks = res.json()
        self.assertGreater(len(peaks), 0)
        self.assertIn("Matterhorn", peaks[0]["name"])

    def test_03_dem_elevation(self):
        # Mont Blanc coords
        res = self.client.get("/api/dem/elevation?lat=45.8326&lon=6.8652")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreater(data["elevation_m"], 4700.0)

    def test_04_los_profile_endpoint(self):
        payload = {
            "tx_lat": 45.8326,
            "tx_lon": 6.8652,
            "tx_alt_m": 25.0,
            "tx_is_agl": True,
            "rx_lat": 46.0,
            "rx_lon": 7.2,
            "rx_alt_m": 10000.0,
            "rx_is_agl": False,
            "frequency_hz": 1090000000.0,
            "num_points": 100
        }
        res = self.client.post("/api/los/profile", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("has_los", data)
        self.assertIn("has_fresnel_clearance", data)
        self.assertIn("total_path_loss_db", data)
        self.assertIn("profile", data)

    def test_05_airspace_cube_endpoint(self):
        payload = {
            "lat": 46.0,
            "lon": 7.0,
            "altitude_ft": 15000.0,
            "cube_size_ft": 1000.0,
            "frequency_hz": 1090000000.0
        }
        res = self.client.post("/api/airspace/cube", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("is_covered", data)
        self.assertIn("redundancy_level", data)
        self.assertIn("cube", data)

    def test_06_dependencies_endpoint(self):
        res = self.client.get("/api/dependencies")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("documentation", data)
        self.assertIn("Prototype Dependencies", data["documentation"])

    def test_07_facility_countries_summary(self):
        res = self.client.get("/api/facilities/countries")
        self.assertEqual(res.status_code, 200)
        countries = res.json()
        self.assertGreaterEqual(len(countries), 35)
        
        # Verify France, Germany, UK have counts
        fr = next((c for c in countries if c["country"] == "FR"), None)
        self.assertIsNotNone(fr)
        self.assertGreater(fr["vor_dme_count"], 50)
        self.assertGreater(fr["radar_count"], 15)

        de = next((c for c in countries if c["country"] == "DE"), None)
        self.assertIsNotNone(de)
        self.assertGreater(de["radar_count"], 20)

    def test_08_facilities_country_filter(self):
        # Query French facilities
        res = self.client.get("/api/facilities?country=FR&limit=100")
        self.assertEqual(res.status_code, 200)
        facs = res.json()
        self.assertGreater(len(facs), 20)
        for f in facs:
            self.assertEqual(f["country"], "FR")

    def test_09_multi_station_radials(self):
        # Get 2 German radars
        res_facs = self.client.get("/api/facilities?country=DE&category=RADAR&limit=2")
        self.assertEqual(res_facs.status_code, 200)
        rads = res_facs.json()
        self.assertEqual(len(rads), 2)

        payload = {
            "station_ids": [rads[0]["id"], rads[1]["id"]],
            "flight_level_ft": 15000.0,
            "num_radials": 36,
            "samples_per_radial": 20
        }
        res_cov = self.client.post("/api/airspace/multi-station-radials", json=payload)
        self.assertEqual(res_cov.status_code, 200)
        data = res_cov.json()
        self.assertEqual(len(data["stations"]), 2)
        self.assertIn("jagged_perimeter", data["stations"][0])
        self.assertIn("radial_lines", data["stations"][0])
        self.assertGreater(len(data["stations"][0]["radial_lines"]), 0)

    def test_10_airspace_column_with_facility_id(self):
        # Scan vertical 1,000-ft column cubes against a specific radar facility
        payload = {
            "lat": 48.0,
            "lon": 8.0,
            "min_alt_ft": 1000.0,
            "max_alt_ft": 30000.0,
            "step_ft": 1000.0,
            "facility_id": "radar_RAD_333_333"
        }
        res = self.client.post("/api/airspace/column", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("column_samples", data)
        self.assertGreater(len(data["column_samples"]), 10)
        sample = data["column_samples"][0]
        self.assertIn("status", sample)
        self.assertIn("detailed_status", sample)
        self.assertIn("distance_km", sample)

    def test_11_custom_facility_crud(self):
        # Create a custom station
        payload = {
            "ident": "TEST9",
            "name": "Integration Test Radar",
            "category": "RADAR",
            "type": "SSR",
            "service_category": "ENROUTE",
            "country": "DE",
            "country_name": "Germany",
            "latitude": 48.5,
            "longitude": 9.2,
            "mast_height_m": 25.0,
            "range_nm": 180.0,
            "elevation_max_deg": 45.0
        }
        res = self.client.post("/api/facilities/custom", json=payload)
        self.assertEqual(res.status_code, 200)
        created = res.json()
        self.assertEqual(created["ident"], "TEST9")
        fac_id = created["id"]
        self.assertTrue(fac_id.startswith("custom_"))

        # Verify it lists in custom facilities
        res_list = self.client.get("/api/facilities/custom")
        self.assertEqual(res_list.status_code, 200)
        customs = res_list.json()
        self.assertTrue(any(c["id"] == fac_id for c in customs))

        # Delete custom facility
        res_del = self.client.delete(f"/api/facilities/custom/{fac_id}")
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.json()["status"], "DELETED")

    def test_12_airspace_column_multi_station_covering_idents(self):
        payload = {
            "lat": 46.5,
            "lon": 7.5,
            "min_alt_ft": 10000.0,
            "max_alt_ft": 30000.0,
            "step_ft": 5000.0,
            "frequency_hz": 1090e6,
            "station_ids": ["radar_RAD_333_333", "radar_RAD_334_334"]
        }
        res = self.client.post("/api/airspace/column", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("column_samples", data)
        self.assertGreaterEqual(len(data["column_samples"]), 4)
        sample = data["column_samples"][0]
        self.assertIn("covering_count", sample)
        self.assertIn("covering_idents", sample)
        self.assertIsInstance(sample["covering_idents"], list)
        self.assertIn("station_breakdown", sample)
        self.assertIsInstance(sample["station_breakdown"], list)
        self.assertEqual(len(sample["station_breakdown"]), 2)

    def test_13_template_export_radars(self):
        payload = {
            "category": "RADAR",
            "filename": "radars_custom.csv",
            "facilities": [
                {
                    "ident": "RAD_ALPS",
                    "name": "Alps Surveillance Node",
                    "country": "CH",
                    "latitude": 46.5000,
                    "longitude": 8.0000,
                    "mast_height_m": 30.0,
                    "range_nm": 220.0,
                    "type": "MODE-S",
                    "mode_s": True
                }
            ]
        }
        res = self.client.post("/api/export/template", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "text/csv; charset=utf-8")
        text = res.text
        self.assertIn("ident,name,country,latitude,longitude,mast_height_m,range_nm", text)
        self.assertIn("RAD_ALPS,Alps Surveillance Node,CH,46.5000,8.0000,30.0,220.0,0.0,360.0,0.5,34.0,MODE-S,true", text)

    def test_14_template_export_navaids(self):
        payload = {
            "category": "NAVAID",
            "filename": "navaids_custom.csv",
            "facilities": [
                {
                    "ident": "GVA",
                    "name": "Geneve Cointrin",
                    "country": "CH",
                    "latitude": 46.2514,
                    "longitude": 6.1081,
                    "type": "VOR-DME",
                    "service_category": "TMA",
                    "power": "LOW",
                    "elevation_ft": 1410,
                    "frequency_khz": 115750,
                    "dme_channel": "104X",
                    "range_nm": 40.0
                }
            ]
        }
        res = self.client.post("/api/export/template", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "text/csv; charset=utf-8")
        text = res.text
        self.assertIn("ident,name,country,latitude,longitude,type,service_category,power,elevation_ft", text)
        self.assertIn("GVA,Geneve Cointrin,CH,46.2514,6.1081,VOR-DME,TMA,LOW,1410,115750,104X,40.0,30.0,150.0", text)

    def test_18_facility_volume_3d(self):
        # Existing station RAD_333
        res = self.client.get("/api/facilities/RAD_333/volume-3d?max_flight_level_ft=40000&num_slices=10")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["ident"], "RAD_333")
        self.assertEqual(data["ceiling_flight_level_ft"], 40000)
        self.assertGreater(data["total_volume_km3"], 100000.0)
        self.assertEqual(len(data["slices"]), 10)
        first_slice = data["slices"][0]
        self.assertIn("outer_radii_km", first_slice)
        self.assertIn("inner_radius_km", first_slice)
        self.assertEqual(len(first_slice["outer_radii_km"]), 72)
        self.assertIn("azimuths_deg", data)
        self.assertEqual(len(data["azimuths_deg"]), 72)

        # Non-existent facility returns 404
        res_404 = self.client.get("/api/facilities/NON_EXISTENT_9999/volume-3d")
        self.assertEqual(res_404.status_code, 404)


if __name__ == "__main__":
    unittest.main()
