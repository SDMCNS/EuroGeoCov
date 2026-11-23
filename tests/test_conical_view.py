"""Unit and integration tests for Conical Coverage Slice and Vertical FL Ladder."""

import sys
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eurogeocov.dem_reader import DEMReader
from eurogeocov.propagation import PropagationEngine
from eurogeocov.airspace_grid import AirspaceCoverageEngine
from eurogeocov.api.app import app


class TestConicalAirspace(unittest.TestCase):
    """Test suite for conical slice coverage and side FL elevation views."""

    @classmethod
    def setUpClass(cls):
        cls.dem_reader = DEMReader()
        cls.prop_engine = PropagationEngine(dem_reader=cls.dem_reader)
        cls.airspace_engine = AirspaceCoverageEngine(dem_reader=cls.dem_reader, prop_engine=cls.prop_engine)
        cls._client_cm = TestClient(app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._client_cm.__exit__(None, None, None)
        if cls.dem_reader:
            cls.dem_reader.close()

    def test_01_conical_coverage_computation(self):
        """Test conical coverage slice calculation at FL200."""
        # Station at Mont Blanc
        res = self.airspace_engine.evaluate_conical_coverage(
            tx_lat=45.8326,
            tx_lon=6.8652,
            tx_alt_m=25.0,
            tx_is_agl=True,
            flight_level_ft=20000.0,
            max_range_km=100.0,
            cone_of_silence_deg=60.0,
            num_radials=36
        )

        self.assertEqual(res["flight_level_ft"], 20000.0)
        self.assertEqual(res["max_range_km"], 100.0)
        self.assertGreater(res["cone_of_silence_radius_km"], 0.0)
        self.assertGreater(len(res["boundary_polygon"]), 30)
        self.assertGreater(len(res["inner_cone_circle"]), 10)
        self.assertGreater(res["coverage_area_sq_km"], 1000.0)

    def test_02_conical_coverage_endpoint(self):
        """Test REST API endpoint for conical coverage slice."""
        payload = {
            "tx_lat": 45.8326,
            "tx_lon": 6.8652,
            "tx_alt_m": 25.0,
            "tx_is_agl": True,
            "flight_level_ft": 15000.0,
            "max_range_km": 80.0,
            "cone_of_silence_deg": 60.0,
            "frequency_hz": 1090000000.0,
            "num_radials": 36
        }
        res = self.client.post("/api/airspace/conical-coverage", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("boundary_polygon", data)
        self.assertIn("inner_cone_circle", data)
        self.assertIn("coverage_area_sq_km", data)
        self.assertEqual(data["flight_level_ft"], 15000.0)


if __name__ == "__main__":
    unittest.main()
