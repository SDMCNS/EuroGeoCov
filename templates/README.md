# EuroGeoCov Data Templates

This folder contains CSV data templates for manually adding or modifying peaks, surveillance radars, and radio navigation aids (VOR / DME) into the European geodatabase and coverage precalculation pipeline.

---

## Template Files

| Template File | Target Dataset | Key Fields | Purpose |
| :--- | :--- | :--- | :--- |
| [`peaks_template.csv`](./peaks_template.csv) | European Mountain Summits | `name,latitude,longitude,meters,country` | Add mountain transmitters, relay sites, or summit obstacles. |
| [`radars_template.csv`](./radars_template.csv) | Surveillance Radars (PSR, SSR, Mode S) | `ident,name,country,latitude,longitude,mast_height_m,range_nm,azimuth_start_deg,azimuth_end_deg,elevation_min_deg,elevation_max_deg,type,mode_s` | Add primary/secondary surveillance radar facilities. |
| [`navaids_template.csv`](./navaids_template.csv) | Radio Navigation Aids (VOR & DME) | `ident,name,country,latitude,longitude,type,service_category,power,elevation_ft,frequency_khz,dme_channel,range_nm,elevation_max_deg` | Add low/high-power VOR and DME navigation facilities. |

---

## Ingesting Templates into the Geodatabase

To ingest filled CSV template files into the geodatabase and automatically compute their DEM elevations and FL600 over-the-horizon profiles:

```powershell
# Ingest custom peaks
python scripts/ingest_custom_data.py --file templates/peaks_template.csv --type PEAK

# Ingest custom radars
python scripts/ingest_custom_data.py --file templates/radars_template.csv --type RADAR

# Ingest custom navaids
python scripts/ingest_custom_data.py --file templates/navaids_template.csv --type NAVAID
```

The script:
1. Validates coordinate ranges (WGS84 decimal degrees).
2. Performs Snyder ETRS89-LAEA ellipsoidal projection (`EPSG:3035`).
3. Samples terrain elevations directly from the 24 GB EU-DEM GeoTIFF.
4. Generates 72-radial Line of Sight horizon profiles out to FL600.
5. Saves the records into DuckDB and/or `data/custom_facilities.json`.
