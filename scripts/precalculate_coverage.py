"""CLI Script to precalculate coverage for all ECAC Radars and Navaids (VOR and DME).

Computes Line of Sight (LoS) radial cuts, terrain shadows, and jagged perimeters
against the 24GB EU-DEM GeoTIFF and stores the results in DuckDB for instant frontend loading.
"""

import sys
import time
import argparse
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eurogeocov.coverage_precalculator import CoveragePrecalculator, DEFAULT_FLIGHT_LEVELS_FT


def main():
    parser = argparse.ArgumentParser(description="Precalculate coverage for ECAC Radars and Navaids.")
    parser.add_argument("--category", default="ALL", choices=["ALL", "RADAR", "NAVAID"], help="Facility category to precalculate")
    parser.add_argument("--country", default=None, help="Filter by country code (e.g. 'FR', 'DE')")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of facilities to precalculate")
    parser.add_argument("--batch-size", type=int, default=25, help="Batch size for database writes")
    parser.add_argument("--flight-levels", default=None, help="Comma-separated flight levels in feet (e.g. '1000,5000,10000,15000,20000,30000,40000')")

    args = parser.parse_args()

    fl_list = DEFAULT_FLIGHT_LEVELS_FT
    if args.flight_levels:
        fl_list = [float(x.strip()) for x in args.flight_levels.split(",") if x.strip()]

    print(f"\n=======================================================")
    print(f"🛰️  EuroGeoCov Coverage Precalculation Pipeline")
    print(f"   Category: {args.category}")
    print(f"   Country: {args.country or 'All ECAC'}")
    print(f"   Flight Levels: {len(fl_list)} levels ({', '.join(f'FL{int(fl/100)}' for fl in fl_list)})")
    print(f"=======================================================\n")

    t0 = time.time()
    last_print = [time.time()]

    def on_progress(current, total, name):
        now = time.time()
        if now - last_print[0] >= 3.0 or current == total or current == 1:
            pct = (current / total) * 100.0
            elapsed = now - t0
            rate = current / max(0.1, elapsed)
            remaining = (total - current) / max(0.1, rate)
            print(f"[{current:4d}/{total}] ({pct:5.1f}%) Processing {name:<20} | Elapsed: {elapsed:5.1f}s | Est. Remaining: {remaining:5.1f}s")
            last_print[0] = now

    with CoveragePrecalculator() as calc:
        total_cov, total_prof = calc.precalculate_all_facilities(
            flight_levels_ft=fl_list,
            category=args.category,
            country=args.country,
            limit=args.limit,
            batch_size=args.batch_size,
            progress_callback=on_progress
        )

    duration = time.time() - t0
    print(f"\n=======================================================")
    print(f"✅ Precalculation complete! Stored {total_cov} coverage records and {total_prof} FL600 horizon profiles in {duration:.1f}s.")
    print(f"=======================================================\n")


if __name__ == "__main__":
    main()
