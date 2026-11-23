"""CLI Script to ingest custom peaks, radars, and navaids CSV templates into the European Geodatabase.

Enriches stations with EU-DEM raster elevations, computes Snyder ETRS89-LAEA coordinates,
and precalculates FL600 over-the-horizon profiles for instant coverage visualization.
"""

import sys
import csv
import time
import argparse
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eurogeocov.geodatabase import GeoDatabase
from eurogeocov.dem_reader import DEMReader
from eurogeocov.projection import wgs84_to_laea
from eurogeocov.coverage_precalculator import CoveragePrecalculator


def ingest_file(file_path: Path, data_type: str):
    if not file_path.exists():
        print(f"❌ Error: File not found: {file_path}")
        sys.exit(1)

    print(f"\n=======================================================")
    print(f"📥 EuroGeoCov Custom Data Ingestion Pipeline")
    print(f"   Source File: {file_path.name}")
    print(f"   Target Type: {data_type.upper()}")
    print(f"=======================================================\n")

    # Read CSV lines ignoring comments
    rows = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader((line for line in f if not line.strip().startswith("#")))
        for r in reader:
            if r and any(v.strip() for v in r.values() if v):
                rows.append({k.strip(): v.strip() for k, v in r.items() if k})

    if not rows:
        print("⚠️ No valid data rows found in CSV.")
        return

    print(f"Found {len(rows)} record(s) to process.\n")

    db = GeoDatabase(read_only=True)
    dem = None
    calc = None
    try:
        dem = DEMReader()
        calc = CoveragePrecalculator(dem_reader=dem, geodatabase=db)
    except Exception as e:
        print(f"⚠️ Note: DEMReader could not be loaded ({e}). Ground elevations will use reported values.")

    ingested_count = 0

    for i, row in enumerate(rows, 1):
        try:
            lat = float(row.get("latitude") or row.get("lat"))
            lon = float(row.get("longitude") or row.get("lon"))
            name = row.get("name") or "Unnamed Station"
            country = (row.get("country") or "EU").upper()

            # ETRS89-LAEA Snyder coordinates
            x_laea, y_laea = wgs84_to_laea(lon, lat)

            # DEM elevation
            dem_elev = None
            if dem:
                try:
                    dem_elev = float(dem.get_elevation_wgs84(lon, lat))
                except Exception:
                    dem_elev = None

            if data_type.upper() == "PEAK":
                peak_id = f"custom_peak_{i:04d}_{int(time.time())}"
                meters = float(row.get("meters") or dem_elev or 0.0)
                dem_m = dem_elev if dem_elev is not None else meters
                try:
                    db.conn.execute("""
                        INSERT OR REPLACE INTO peaks (id, name, country, latitude, longitude, meters, dem_meters, x_laea, y_laea)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [peak_id, name, country, lat, lon, meters, dem_m, x_laea, y_laea])
                except Exception:
                    # Database is read-only, save as custom facility
                    db.save_custom_facility({
                        "id": peak_id,
                        "ident": name[:5].upper(),
                        "name": name,
                        "category": "PEAK",
                        "type": "SUMMIT",
                        "service_category": "ENROUTE",
                        "country": country,
                        "latitude": lat,
                        "longitude": lon,
                        "x_laea": x_laea,
                        "y_laea": y_laea,
                        "meters": meters,
                        "dem_meters": dem_m,
                        "tx_amsl_m": dem_m,
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
                    })
                print(f"  [{i}/{len(rows)}] Peak '{name}' ({country}) -> {meters}m AMSL (DEM: {dem_m:.1f}m)")

            else:
                # RADAR or NAVAID
                ident = (row.get("ident") or name[:5]).upper()
                fac_id = f"custom_{ident}_{int(time.time())}_{i}"
                cat = data_type.upper()
                fac_type = row.get("type", "MODE-S" if cat == "RADAR" else "VOR-DME").upper()
                service_cat = row.get("service_category", "ENROUTE").upper()
                mast_h = float(row.get("mast_height_m") or (25.0 if cat == "RADAR" else 15.0))
                ground_m = dem_elev if dem_elev is not None else float(row.get("elevation_ft", 0.0)) * 0.3048
                tx_amsl = ground_m + mast_h

                rng_nm = float(row.get("range_nm") or (200.0 if cat == "RADAR" else 130.0))
                rng_km = rng_nm * 1.852

                station_dict = {
                    "id": fac_id,
                    "ident": ident,
                    "name": name,
                    "category": cat,
                    "type": fac_type,
                    "service_category": service_cat,
                    "country": country,
                    "country_name": country,
                    "latitude": lat,
                    "longitude": lon,
                    "x_laea": x_laea,
                    "y_laea": y_laea,
                    "dem_elev_m": round(ground_m, 1),
                    "ground_elev_m": round(ground_m, 1),
                    "mast_height_m": mast_h,
                    "tx_amsl_m": round(tx_amsl, 1),
                    "range_nm": round(rng_nm, 1),
                    "range_km": round(rng_km, 1),
                    "azimuth_start_deg": float(row.get("azimuth_start_deg", 0.0)),
                    "azimuth_end_deg": float(row.get("azimuth_end_deg", 360.0)),
                    "elevation_min_deg": float(row.get("elevation_min_deg", 0.5)),
                    "elevation_max_deg": float(row.get("elevation_max_deg", 45.0 if cat == "RADAR" else 60.0)),
                    "frequency_hz": float(row.get("frequency_hz", 1090e6 if cat == "RADAR" else 115e6)),
                    "frequency_khz": float(row.get("frequency_khz", 115000.0)),
                    "dme_channel": row.get("dme_channel"),
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }

                # Precalculate FL600 horizon profile if DEM is available
                if calc:
                    try:
                        cov_rows, p_row = calc.precalculate_station_coverage(
                            station=station_dict,
                            flight_levels_ft=[1000, 5000, 10000, 15000, 20000, 30000, 40000, 50000, 60000],
                            num_radials=72,
                            samples_per_radial=50
                        )
                        station_dict["fl600_horizon_km"] = p_row[15]
                        station_dict["fl600_horizon_nm"] = p_row[16]
                        station_dict["step_dists_json"] = p_row[23]
                        station_dict["theta_horizon_matrix_json"] = p_row[24]
                    except Exception as e:
                        print(f"    Horizon precalc warning: {e}")

                db.save_custom_facility(station_dict)
                print(f"  [{i}/{len(rows)}] {cat} {ident} ({fac_type}, {country}) -> Antenna: {tx_amsl:.1f}m AMSL, Range: {rng_nm:.0f} NM")

            ingested_count += 1
        except Exception as e:
            print(f"  ❌ Error on row {i}: {e}")

    db.close()
    if dem:
        dem.close()

    print(f"\n=======================================================")
    print(f"✅ Ingested {ingested_count} / {len(rows)} records successfully!")
    print(f"=======================================================\n")


def main():
    parser = argparse.ArgumentParser(description="Ingest custom CSV templates into EuroGeoCov geodatabase.")
    parser.add_argument("--file", "-f", required=True, help="Path to CSV template file")
    parser.add_argument("--type", "-t", choices=["PEAK", "RADAR", "NAVAID"], default=None,
                        help="Data type (PEAK, RADAR, or NAVAID). Auto-detected if omitted.")
    args = parser.parse_args()

    file_path = Path(args.file)
    data_type = args.type
    if not data_type:
        fname = file_path.name.lower()
        if "peak" in fname:
            data_type = "PEAK"
        elif "radar" in fname:
            data_type = "RADAR"
        elif "nav" in fname:
            data_type = "NAVAID"
        else:
            print("❌ Error: Could not auto-detect data type. Please specify --type PEAK|RADAR|NAVAID.")
            sys.exit(1)

    ingest_file(file_path, data_type)


if __name__ == "__main__":
    main()
