"""Comprehensive unit and integration test suite for EuroGeoCov."""

import sys
import unittest
from pathlib import Path
import numpy as np

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eurogeocov.projection import wgs84_to_laea, laea_to_wgs84
from eurogeocov.dem_reader import DEMReader
from eurogeocov.peaks_loader import PeaksLoader
from eurogeocov.geodatabase import GeoDatabase
from eurogeocov.propagation import PropagationEngine
from eurogeocov.airspace_grid import AirspaceCoverageEngine, AirspaceCube
from eurogeocov.config import SPEED_OF_LIGHT, DEFAULT_FREQUENCIES


class TestEuroGeoCov(unittest.TestCase):
    """Test suite for EuroGeoCov core library."""

    @classmethod
    def setUpClass(cls):
        cls.dem_reader = DEMReader()
        cls.prop_engine = PropagationEngine(dem_reader=cls.dem_reader)
        cls.airspace_engine = AirspaceCoverageEngine(dem_reader=cls.dem_reader, prop_engine=cls.prop_engine)

    @classmethod
    def tearDownClass(cls):
        if cls.dem_reader:
            cls.dem_reader.close()

    def test_01_projection_accuracy_and_analytical_fallback(self):
        """Test EPSG:3035 coordinate transformation with both pyproj and analytical math."""
        # Test coordinates: Munich (approx 11.582° E, 48.135° N)
        lon, lat = 11.582, 48.135

        # With pyproj
        x_proj, y_proj = wgs84_to_laea(lon, lat, use_analytical=False)
        # With pure analytical Snyder formulas
        x_math, y_math = wgs84_to_laea(lon, lat, use_analytical=True)

        # Difference between pyproj and analytical formulas should be under 0.05 meters!
        self.assertAlmostEqual(x_proj, x_math, delta=0.05)
        self.assertAlmostEqual(y_proj, y_math, delta=0.05)

        # Test inverse transformation
        inv_lon, inv_lat = laea_to_wgs84(x_proj, y_proj, use_analytical=True)
        self.assertAlmostEqual(lon, inv_lon, delta=1e-5)
        self.assertAlmostEqual(lat, inv_lat, delta=1e-5)

    def test_02_dem_reader_sampling_and_bounds(self):
        """Test sampling elevation from EU-DEM GeoTIFF."""
        # Mont Blanc (approx 6.865° E, 45.833° N)
        elev = self.dem_reader.get_elevation_wgs84(6.8652, 45.8326)
        # Mont Blanc summit elevation in EU-DEM should be > 4700m
        self.assertGreater(elev, 4700.0)
        self.assertLess(elev, 4900.0)

        # Test out-of-bounds point (e.g. North Pacific)
        oob_elev = self.dem_reader.get_elevation_wgs84(-140.0, 30.0)
        self.assertEqual(oob_elev, 0.0)

    def test_03_dem_profile_extraction(self):
        """Test profile cross-section between two points."""
        # Mont Blanc to Matterhorn (approx 60 km)
        prof = self.dem_reader.get_elevation_profile(
            lon1=6.8652, lat1=45.8326,
            lon2=7.7285, lat2=45.9384,
            num_points=100
        )
        self.assertEqual(len(prof["elevations_m"]), 100)
        self.assertEqual(len(prof["distances_m"]), 100)
        self.assertGreater(prof["total_distance_m"], 50000.0)  # > 50 km
        self.assertLess(prof["total_distance_m"], 80000.0)

    def test_04_peaks_loader(self):
        """Test scanning and parsing European peaks from GeoJSON."""
        loader = PeaksLoader()
        peaks = list(loader.scan_peaks())
        self.assertGreater(len(peaks), 900)
        self.assertEqual(len(peaks), 928)

        # Check fields of a sample peak
        sample = peaks[0]
        self.assertIn("name", sample)
        self.assertIn("country", sample)
        self.assertIsNotNone(sample["latitude"])
        self.assertIsNotNone(sample["longitude"])
        self.assertIsNotNone(sample["x_laea"])
        self.assertIsNotNone(sample["y_laea"])

    def test_05_geodatabase_operations(self):
        """Test geodatabase initialization, search, and spatial queries."""
        db = GeoDatabase(read_only=True)
        count = db.conn.execute("SELECT count(*) FROM peaks").fetchone()[0]
        self.assertEqual(count, 928)

        # Search by name
        results = db.search_peaks(query="Blanc", limit=5)
        self.assertGreater(len(results), 0)
        self.assertIn("Blanc", results[0]["name"])

        # Search by country
        french_peaks = db.search_peaks(country="France", limit=10)
        self.assertGreater(len(french_peaks), 0)
        for p in french_peaks:
            self.assertEqual(p["country"], "France")

        # Top peaks
        top = db.get_top_peaks(limit=5)
        self.assertEqual(len(top), 5)
        self.assertGreaterEqual(top[0]["meters"], top[1]["meters"])

        # Nearest peaks lookup
        nearest = db.find_nearest_peaks(lat=45.83, lon=6.86, limit=3)
        self.assertEqual(len(nearest), 3)

        db.close()

    def test_06_rf_propagation_and_fresnel(self):
        """Test RF propagation physics (Fresnel radius, Earth bulge, path loss)."""
        # Test Fresnel radius calculation
        # At midpoint of 10 km link at 1090 MHz (lambda = 0.275m)
        d1 = 5000.0
        d2 = 5000.0
        f_hz = 1090e6
        r1 = self.prop_engine.compute_fresnel_radius(d1, d2, f_hz)
        # r1 = sqrt(lambda * d1 * d2 / (d1 + d2)) = sqrt(0.275 * 25e6 / 10000) = sqrt(687.5) ≈ 26.22 m
        self.assertAlmostEqual(r1, 26.22, delta=0.5)

        # Earth bulge at midpoint of 100 km link with k = 4/3 (R_e ≈ 8494.6 km)
        # h = (d1 * d2) / (2 * Re) = (50000 * 50000) / (2 * 8494666) ≈ 147.15 m
        bulge = self.prop_engine.compute_earth_bulge(50000.0, 50000.0)
        self.assertAlmostEqual(bulge, 147.15, delta=1.0)

        # Free space path loss for 10 km at 1090 MHz
        fspl = self.prop_engine.compute_fspl_db(10000.0, 1090e6)
        # FSPL ≈ 20*log10(10000) + 20*log10(1.09e9) - 147.55 ≈ 80 + 180.75 - 147.55 = 113.2 dB
        self.assertAlmostEqual(fspl, 113.18, delta=0.5)

    def test_07_point_to_point_los_evaluation(self):
        """Test full LoS evaluation between summit and airborne receiver."""
        # Tx at Mont Blanc (mast height 20m), Rx at high altitude 35,000 ft (10,668m AMSL) 50 km away
        eval_res = self.prop_engine.evaluate_los(
            tx_lon=6.8652, tx_lat=45.8326, tx_alt_m=20.0, tx_is_agl=True,
            rx_lon=7.2, rx_lat=46.0, rx_alt_m=10668.0, rx_is_agl=False,
            frequency_hz=1090e6,
            num_points=100,
            dem_reader=self.dem_reader
        )
        self.assertTrue(eval_res["has_los"])
        self.assertTrue(eval_res["has_fresnel_clearance"])
        self.assertEqual(eval_res["status"], "CLEAR")
        self.assertGreater(eval_res["min_fresnel_clearance_m"], 0.0)

    def test_08_airspace_1000ft_cube_assessment(self):
        """Test evaluation of a 1000-ft airspace voxel."""
        cube = AirspaceCube(center_lat=46.0, center_lon=7.0, center_alt_ft=20000.0)
        self.assertEqual(cube.size_ft, 1000.0)
        self.assertEqual(cube.alt_floor_ft, 19500.0)
        self.assertEqual(cube.alt_ceiling_ft, 20500.0)

        stations = [
            {"name": "Mont Blanc", "latitude": 45.8326, "longitude": 6.8652, "meters": 4808.0, "is_agl": True}
        ]

        assessment = self.airspace_engine.evaluate_cube_coverage(cube, stations, frequency_hz=1090e6)
        self.assertIn("is_covered", assessment)
        self.assertIn("redundancy_level", assessment)
        self.assertEqual(assessment["stations_evaluated"], 1)

    def test_09_cone_of_silence(self):
        """Test overhead antenna null / Cone of Silence detection."""
        # Target directly above Mont Blanc (very small horizontal offset, high altitude)
        eval_res = self.prop_engine.evaluate_los(
            tx_lon=6.8652, tx_lat=45.8326, tx_alt_m=20.0, tx_is_agl=True,
            rx_lon=6.8660, rx_lat=45.8330, rx_alt_m=10668.0,  # ~100m away horizontally, 6000m vertical
            frequency_hz=1090e6,
            num_points=50,
            cone_of_silence_deg=60.0,
            dem_reader=self.dem_reader
        )
        self.assertTrue(eval_res["in_cone_of_silence"])
        self.assertGreater(eval_res["elevation_angle_deg"], 60.0)
        self.assertEqual(eval_res["status"], "CONE_OF_SILENCE")

    def test_10_max_useful_flight_levels(self):
        """Test service ceiling / maximum useful flight level enforcement."""
        # Aircraft at 70,000 ft (FL700), beyond standard FL600 service volume
        eval_res = self.prop_engine.evaluate_los(
            tx_lon=6.8652, tx_lat=45.8326, tx_alt_m=20.0, tx_is_agl=True,
            rx_lon=7.5, rx_lat=46.0, rx_alt_m=21336.0,  # 70,000 ft AMSL
            frequency_hz=1090e6,
            num_points=50,
            max_flight_level_ft=60000.0,
            dem_reader=self.dem_reader
        )
        self.assertTrue(eval_res["exceeds_max_flight_level"])
        self.assertEqual(eval_res["status"], "EXCEEDS_MAX_FL")

    def test_11_earth_curvature_drop(self):
        """Test Earth curvature drop and bulge calculations."""
        # 100 km path with standard 4/3 refraction (Re ≈ 8494.6 km)
        d_total = 100000.0
        bulge_mid = self.prop_engine.compute_earth_bulge(50000.0, 50000.0)
        drop_end = (d_total ** 2) / (2.0 * self.prop_engine.effective_earth_radius)

        # Drop at 100 km: (100,000)^2 / (2 * 8,494,666) ≈ 588.6 m
        self.assertAlmostEqual(drop_end, 588.6, delta=2.0)
        # Midpoint bulge is exactly 1/4 of total drop: 588.6 / 4 ≈ 147.15 m
        self.assertAlmostEqual(bulge_mid, drop_end / 4.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
