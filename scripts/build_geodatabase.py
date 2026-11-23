"""CLI script to build and enrich the European Peaks Geodatabase with EU-DEM elevations."""

import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eurogeocov.geodatabase import GeoDatabase
from eurogeocov.dem_reader import DEMReader


def main():
    print("=" * 60)
    print("Building EuroGeoCov European Geodatabase...")
    print("=" * 60)

    start_time = time.time()
    db = GeoDatabase()

    print("[1/3] Parsing European peaks from GeoJSON dataset...")
    print("[2/3] Linking and sampling elevations from EU-DEM 25m GeoTIFF...")
    total_peaks = db.build_database(rebuild=True, enrich_dem=True)

    print("\n[3/3] Parsing & filtering ECAC Navaids (VOR, DME) and Radars...")
    cnt_nav, cnt_rad = db.build_navaids_and_radars(rebuild=True)

    elapsed = time.time() - start_time
    print(f"\nCompleted in {elapsed:.2f}s!")
    print(f"Total European peaks stored and indexed: {total_peaks}")
    print(f"Total ECAC VOR/DME navaids stored: {cnt_nav}")
    print(f"Total ECAC Surveillance Radars stored: {cnt_rad}")

    # Display sample top 5 peaks
    print("\nTop 5 Highest Peaks with Sampled EU-DEM Elevation:")
    top_peaks = db.get_top_peaks(limit=5)
    for idx, p in enumerate(top_peaks, 1):
        print(f"  {idx}. {p['name']} ({p['country']}): Reported {p['meters']}m | DEM {p['dem_meters']}m | Diff {p['diff_m']}m")

    # Display sample navaids
    print("\nSample ECAC Navaids (VOR / DME):")
    sample_navs = db.search_navaids(limit=5)
    for idx, n in enumerate(sample_navs, 1):
        print(f"  {idx}. {n['ident']} ({n['name']}) [{n['type']}] - Power: {n['power']}, Range: {n['range_nm']} NM ({n['range_km']} km), Country: {n['country']}")

    # Display sample radars
    print("\nSample ECAC Radars:")
    sample_rads = db.search_radars(limit=5)
    for idx, r in enumerate(sample_rads, 1):
        print(f"  {idx}. {r['name']} ({r['ident']}) [{r['type']}] - Range: {r['range_nm']} NM ({r['range_km']} km), Mode-S: {r['mode_s']}")


    # Display countries breakdown
    print("\nPeaks count by country:")
    countries = db.get_countries_summary()
    for c in countries[:10]:
        print(f"  - {c['country']}: {c['count']} peaks (Highest: {c['max_meters']}m)")

    db.close()
    print("=" * 60)


if __name__ == "__main__":
    main()
