# EuroGeoCov: European Geodatabase, DEMTIFF & Airspace Coverage Engine

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![DuckDB](https://img.shields.io/badge/DuckDB-Spatial-yellow.svg)](https://duckdb.org/)
[![Leaflet](https://img.shields.io/badge/Leaflet-1.9.4-brightgreen.svg)](https://leafletjs.com/)

**EuroGeoCov** is a high-performance geospatial and radio-frequency (RF) propagation library and web visualizer for Europe. It combines a 24 GB European Digital Elevation Model (EU-DEM 25m) with European mountain summits, ECAC surveillance radars, and radio navigation aids (VOR / DME) into an analytical geodatabase.

The system evaluates:
1. **Physical Line of Sight (LoS)**: True ellipsoidal Earth curvature with 4/3 tropospheric refraction ($k = 1.3333$) and $60\%$ First Fresnel Zone ($0.6 \cdot F_1$) clearance.
2. **Conical Airspace Coverage & Silence Cones**: Horizontal slice coverage with transmitter elevation beam cutoffs ($\theta_{max}$ overhead silence cone and $\theta_{min}$ horizon cutoff).
3. **Over-the-Horizon Precalculation to FL600**: 72-radial horizon angle profiles precalculated out to $600\text{--}700\text{ km}$ ($60,000\text{ ft} = 18,288\text{ m}$ AMSL), enabling sub-millisecond ($0.05\text{ ms}$) on-the-fly evaluation at any flight level and custom range limit.
4. **Client-Side Merged Airspace Boundaries**: Turf.js geometric polygon union of multiple facilities into a seamless merged coverage footprint with non-overlapping area calculation ($\text{km}^2$).
5. **Airspace 1000-ft Voxel Cubes**: Interactive vertical column ladder analysis from FL010 to FL600 over any ground point within a radar, VOR, or DME facility's coverage.
6. **Station Creator & Custom Geodatabase**: Built-in UI and CLI ingestion pipeline to create custom stations, auto-enrich ground elevations from the EU-DEM GeoTIFF, and calculate over-the-horizon coverage.
7. **Interactive 3D Airspace Coverage Volume**: WebGL 3D solid mesh modal of any site's airspace coverage volume powered by Three.js and OrbitControls. Features outer faceted terrain-cut shells across altitudes, inverted zenith silence cones, ground compass grid with range rings, antenna mast pin, variable vertical exaggeration (1x to 10x), material themes (Hologram Cyan, Radar Emerald, Sunset Amber, Tactical Wireframe), turntable auto-rotation, and integrated 3D volumetric calculations ($\text{km}^3$).

---

## Visualizer Overview

![EuroGeoCov Web Visualizer](screenshots/Main%20View.png)
*Figure 1: EuroGeoCov Web Visualizer — Multi-station ECAC surveillance radar and VOR/DME navigation aid coverage, 360° radial spoke ray casting, country filters, and real-time coverage metrics over European topography.*

---

## Architecture & Code vs. Data Separation

The project enforces strict separation between **immutable code logic** and **heavy datasets / binary databases**:

```
geodata/
├── eurogeocov/                   # CORE LIBRARY & LOGIC
│   ├── __init__.py               # Top-level exports
│   ├── config.py                 # Geodetic constants & directory configurations
│   ├── projection.py             # WGS84 (EPSG:4326) <-> ETRS89-LAEA (EPSG:3035) Snyder math
│   ├── dem_reader.py             # 24GB BigTIFF windowed reader & bilinear profile sampler
│   ├── peaks_loader.py           # World peaks GeoJSON loader & DEM enrichment
│   ├── navaids_loader.py         # ECAC VOR/DME navaids and surveillance radars parser
│   ├── geodatabase.py            # DuckDB spatial database & custom facilities persistence
│   ├── propagation.py            # Earth bulge, Fresnel ellipsoids, optical/radio LoS, FSPL
│   ├── airspace_grid.py          # 1000-ft airspace voxel coverage engine & column ladder
│   ├── coverage_precalculator.py # FL600 over-the-horizon profile engine
│   ├── api/
│   │   ├── app.py                # FastAPI REST service & static asset mounter
│   │   └── models.py             # Pydantic schemas for requests & responses
│   └── static/
│       ├── index.html            # Web Visualizer UI (OSM / OpenTopoMap, Leaflet, Turf.js)
│       ├── app.js                # Map controller, Turf union, Canvas profile chart
│       └── style.css             # Aerospace dark theme
├── scripts/                      # CLI RUNNERS & PIPELINES
│   ├── run_server.py             # Launches Uvicorn web server daemon
│   ├── precalculate_coverage.py  # Computes FL600 horizon profiles across all facilities
│   └── ingest_custom_data.py     # Ingests user CSV templates into the geodatabase
├── templates/                    # USER DATA INPUT TEMPLATES
│   ├── README.md                 # Guide to using templates
│   ├── peaks_template.csv        # Template for mountain summits / relay sites
│   ├── radars_template.csv       # Template for surveillance radars (PSR, SSR, Mode S)
│   └── navaids_template.csv      # Template for radio navigation aids (VOR & DME)
├── tests/                        # AUTOMATED TEST SUITE (40 tests)
├── data/                         # OUTPUT DATABASE & PRECALCULATED STATE (Git-ignored)
│   ├── euro_geodatabase.duckdb   # DuckDB database file
│   └── custom_facilities.json    # User-created stations
└── DEMTIFF/                      # RASTER ELEVATION DATA (Git-ignored)
    └── eu_dem_v11_E50N20.TIF     # 24 GB EU-DEM GeoTIFF
```

---

## Data Acquisition Guide

### 1. EU-DEM v1.1 Digital Elevation Model (24 GB)
- **Source**: Copernicus Land Monitoring Service (European Environment Agency - EEA).
- **Format**: Cloud-Optimized BigTIFF / GeoTIFF, horizontal resolution $25\text{ m} \times 25\text{ m}$, coordinate reference system `ETRS89-LAEA` (`EPSG:3035`).
- **Download**:
  1. Access the Copernicus Land Monitoring Service portal: [Copernicus EU-DEM v1.1](https://land.copernicus.eu/imagery-in-situ/eu-dem/eu-dem-v1.1).
  2. Download the full continental Europe mosaic or tile `E50N20`.
  3. Place the `.TIF` file inside the `DEMTIFF/` or `data/DEMTIFF/` directory:
     ```
     DEMTIFF/eu_dem_v11_E50N20.TIF
     ```
  4. The `DEMReader` automatically searches `DEMTIFF/` and `data/DEMTIFF/` for any `.tif` or `.tiff` file.

### 2. European Peaks Dataset
- **Source**: World Peaks dataset (GeoJSON).
- **Location**: Place source files in `peaks/` or use the provided template in `templates/peaks_template.csv`.
- Contains summit names, coordinates, and reported elevations across 40 European nations.

### 3. ECAC Surveillance Radars & Navaids
- **Source**: Eurocontrol Navigation Aids & Surveillance Infrastructure databases.
- **Location**: Included in `radars and navaids/`.
- Includes 816 European VOR/DME navaids and 185 enroute and terminal surveillance radars.

---

## Data Templates & Manual Ingestion

You can add custom mountain sites, surveillance radars, and navigation aids manually using the CSV templates in `templates/`:

### 1. Peaks Template (`templates/peaks_template.csv`)
```csv
name,latitude,longitude,meters,country
Mont Blanc,45.8326,6.8652,4808,FR
Matterhorn,45.9763,7.6586,4478,CH
Zugspitze,47.4211,10.9853,2962,DE
```

### 2. Surveillance Radars Template (`templates/radars_template.csv`)
```csv
ident,name,country,latitude,longitude,mast_height_m,range_nm,azimuth_start_deg,azimuth_end_deg,elevation_min_deg,elevation_max_deg,type,mode_s
RAD_PARIS_N,Paris Nord En-route Radar,FR,49.0097,2.5479,25.0,200.0,0.0,360.0,0.5,34.0,ENR-MDS,true
RAD_MUC_TMA,Munich Terminal Area Radar,DE,48.3538,11.7861,30.0,60.0,0.0,360.0,0.5,34.0,SSR,true
```

### 3. Navaids Template (`templates/navaids_template.csv`)
```csv
ident,name,country,latitude,longitude,type,service_category,power,elevation_ft,frequency_khz,dme_channel,range_nm,elevation_min_deg,elevation_max_deg
LAM,Lambourne,GB,51.6464,0.1517,VOR-DME,ENROUTE,HIGH,320,115600,103X,130.0,30.0,150.0
KLO,Kloten,CH,47.4583,8.5489,VOR-DME,TMA,LOW,1420,114850,95Y,40.0,30.0,150.0
```

### 4. Running the Ingestion CLI
To ingest your filled templates into the geodatabase:

```powershell
# Ingest custom peaks
python scripts/ingest_custom_data.py --file templates/peaks_template.csv --type PEAK

# Ingest custom radars (calculates FL600 horizon profile automatically)
python scripts/ingest_custom_data.py --file templates/radars_template.csv --type RADAR

# Ingest custom navaids
python scripts/ingest_custom_data.py --file templates/navaids_template.csv --type NAVAID
```

---

## Precalculation Pipeline to FL600

To eliminate on-the-fly raster sampling latencies in the web visualizer, coverage is precalculated across European airspace:

```powershell
# Precalculate over-the-horizon coverage and horizon profiles for all ECAC facilities
python scripts/precalculate_coverage.py --category ALL

# Precalculate for a specific country or category
python scripts/precalculate_coverage.py --country FR --category RADAR
```

### Physics of the FL600 Horizon
At flight level FL600 ($60,000\text{ ft} = 18,288\text{ m}$ AMSL), radio reach extends to the effective $4/3$ Earth radio horizon:
$$d_{FL600} = \sqrt{2 R_e \max(1, h_{tx})} + \sqrt{2 R_e h_{FL600}} \approx 580\text{--}700\text{ km} \quad (310\text{--}380\text{ NM})$$

The precalculator samples 72 radial azimuths with quadratic power spacing ($s_k = (t^{1.35}) \cdot d_{FL600}$), capturing high-resolution terrain obstacles close to the station where peaks subtend the steepest elevation angles. The resulting 72-radial horizon angle matrix $\theta_{horizon}(\phi, s)$ is stored in DuckDB. 

When queried, the API evaluates Line of Sight for **any custom flight level** (FL010 to FL600) and **any user-defined range cap** in **$\sim 0.05\text{ ms}$** per station!

---

## Running the Web Visualizer

Start the FastAPI application:

```powershell
python scripts/run_server.py --port 8000
```

Open your browser to:
- **Interactive Web Visualizer**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive OpenAPI Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Visualizer Features
1. **Radars & Navaids Coverage Tab**:
   - **Bulk Selection by Country**: Select all VOR/DME navaids or radars in any of the 40 ECAC countries with one click.
   - **Radial Cut Spokes**: Spokes stop at the exact terrain obstacle cut point, marked with red obstacle termination dots. Clicking any spoke or dot inspects the vertical airspace column at that location.
   - **Merged Coverage Footprint**: Turf.js merges individual facility perimeters into a unified coverage boundary (cyan dashed outline, translucent blue fill) and computes the total non-overlapping coverage area in $\text{km}^2$.
   - **Range Modes**:
     - *Over-the-Horizon (Full FL600)*: Reach out to the physical horizon (~600–700 km).
     - *Designated (DOC)*: Capped to official operational ranges (25–40 NM TMA, 130 NM VOR, 200 NM Radar).
     - *Custom Max Range Slider*: Dynamic range filter from 20 km to 700 km (10 to 380 NM).
   - **Flight Level Ladder**: Live dropdown and side elevation ladder stepping in FL10 (1,000 ft) increments up to FL600.
   - **Ray Azimuth Sweep & Rotation**:
     - Select any active station to inspect individual radial rays (72 or 120 radials).
     - **Slider & Steppers**: Scrub azimuth angles $0^\circ$ to $360^\circ$ with live map ray highlighting.
     - **Radar Sweep Animation (Play/Pause)**: 360° animated beam rotation around the station site.
     - **Synchronized Tri-Panel Inspection**: Each ray step highlights the ray on the map, plots the 2D terrain & Fresnel zone cross-section below, and updates the vertical 1,000-ft cube ladder at the side!
   - **Multi-Station 1,000-ft Airspace Column Inspection**:
     - Click any point on the map when a set of stations are selected (or use "📍 Click Map Point").
     - Displays the 1,000-ft vertical cube ladder from FL600 down to FL010.
     - For each flight level, shows coverage status, **number of covering stations**, and **3-letter ICAO station identifiers** (e.g. `[GVA, LYS, ZUR]`).

   ![VOR/DME Coverage at FL030 in NW Spain](screenshots/VOR_DMe%20FL030%20NW%20Spain.png)
   *Figure 2: Multi-station VOR/DME coverage at FL030 across Northwest Spain (Cantabrian Mountains). Radial spokes terminate at mountain terrain obstacles (red dots), generating broken, jagged coverage perimeters and merged airspace envelopes.*

2. **LoS & Fresnel Tab**:
   - Point-to-point ray casting with interactive draggable Tx/Rx markers.
   - 2D Canvas terrain elevation profile with Earth curvature bulge, LOS direct ray, 1st Fresnel zone clearance ellipsoid ($0.6 \cdot F_1$), and bottleneck obstacle marker.

   ![Elevation & Fresnel Zone Profile](screenshots/Evevation%20LoS%20view.png)
   *Figure 3: Elevation & Fresnel Zone Profile Drawer — Interactive 2D terrain cross section sampled from the 25m EU-DEM showing the curved Earth baseline ($k = 4/3$), direct Line-of-Sight ray, 60% First Fresnel zone clearance ellipsoid, and critical obstacle marker.*

3. **Airspace 1000ft Cubes Tab**:
   - **Load Facility Coverage**: Load any Radar, VOR, DME, or Custom Station to display its coverage boundary on the map.
   - **Click Any Point in Coverage**: Click on the map inside or around the facility's coverage to immediately evaluate the vertical column.
   - **Vertical 1000-ft Coverage Blocks (FL010 to FL600)**: Visual ladder of 60 vertical blocks color-coded by status:
     - <span style="color:#3fb950">●</span> **CLEAR**: Clear Line of Sight with Fresnel clearance.
     - <span style="color:#d29922">●</span> **DIFFRACTED**: Optical line of sight clear but Fresnel zone clipped by terrain.
     - <span style="color:#f85149">●</span> **TERRAIN_BLOCKED**: Ray path obstructed by mountain terrain.
     - <span style="color:#bc8cff">●</span> **CONE_OF_SILENCE**: Inside overhead antenna silence cone ($\theta > \theta_{max}$).
     - <span style="color:#8b949e">●</span> **OUT_OF_RANGE**: Beyond facility operational service volume.

   ![Vertical Airspace Column Profile](screenshots/vertical%20profile%201000ft3%20view.png)
   *Figure 4: Vertical Airspace Profile (1,000-ft Ladder) — Interactive voxel column from FL600 down to FL010 showing coverage state, number of covering ground sensors, and 3-letter ICAO station identifiers (e.g. `[GVA, LYS, ZUR]`).*
4. **Explainer & Scientific Concepts Tab (📖)**:
   - Comprehensive guide to the underlying physics and mathematics:
     - $4/3$ Earth Radius ($R' \approx 8,495\text{ km}$) and Earth bulge formula $\Delta h = \frac{d_1 d_2}{2 R'}$.
     - First Fresnel Zone ($F_1$) radius and the $60\%$ clearance criterion ($0.6 \cdot F_1$).
     - **Radar Zenith Cone of Silence ($\sim 34.0^\circ$)**: Surveillance radars possess an upper beam cutoff with an overhead zenith cone angle of $\sim 34^\circ$. Targets above this elevation angle are in the silent null, forming an inner dead radius $r_{\text{inner}} = \frac{\Delta h}{\tan(34.0^\circ)}$.
     - **DME $30^\circ\text{--}150^\circ$ ($120^\circ$ Vertical Slice) Window**: DME antenna coverage is physically bounded within a $30^\circ\text{--}150^\circ$ vertical plane window ($120^\circ$ vertical slice centered at zenith). Signals below $30^\circ$ elevation angle are not covered (`BELOW_BEAM_MIN`), creating a bounded vertical annulus $[r_{\text{inner}}, r_{\text{outer}}]$ where $r_{\text{outer}} = \min(R_{\text{DOC}}, \frac{\Delta h}{\tan(30^\circ)})$.
     - Friis Free Space Path Loss (FSPL) and ITU-R P.526 knife-edge obstacle diffraction loss $J(v)$.
     - Airspace voxelization, coverage floor, and multi-sensor redundancy tiers ($N$-Coverage).
5. **Dataset Builder & CLI Exporter Tab (🛠️)**:
   - **Interactive Map Site Placement**: Click anywhere on the map to place new candidate radar or VOR/DME sites, automatically extracting coordinates and EU-DEM ground elevations.
   - **One-Click Map Staging**: Add existing facilities directly from map popups ("➕ Add to Dataset Builder") or batch import all active selected stations.
   - **Live Network Overlay**: Visualizes the staged station network on the map with glowing radar (🎯) and navaid (📡) markers.
   - **CLI Template Downloads**: Download pre-formatted CSV template files (`radars_custom.csv` and `navaids_custom.csv`) matching standard CLI ingestion requirements.
   - **CLI Ingestion**: Copy and run the CLI command to enrich ground elevations and compute FL600 over-the-horizon profiles:
     ```powershell
     python scripts/ingest_custom_data.py --file templates/radars_custom.csv --type RADAR
     python scripts/ingest_custom_data.py --file templates/navaids_custom.csv --type NAVAID
     ```

---

## REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/facilities` | `GET` | List/search all radars, navaids, custom stations, and peaks with country and category filters. |
| `/api/facilities/coverage` | `GET` | Retrieve precalculated over-the-horizon coverage, radial cut spokes, and perimeters dynamically evaluated at any FL and range cap. |
| `/api/facilities/countries` | `GET` | Summary breakdown of radars and navaids across ECAC countries. |
| `/api/facilities/custom` | `GET` / `POST` | List or create custom user stations with automatic DEM enrichment and FL600 horizon precalc. |
| `/api/facilities/custom/{id}` | `DELETE` | Delete a custom facility. |
| `/api/export/template` | `POST` | Format and export a list of facilities as a CSV template ready for CLI ingestion. |
| `/api/airspace/cube` | `POST` | Assess radio coverage at any single 1,000-ft cube in Earth's airspace. |
| `/api/airspace/column` | `POST` | Scan a vertical stack of 1,000-ft cubes (FL010 to FL600) over a coordinate to find the coverage floor and diagnose blocking. |
| `/api/airspace/conical-coverage` | `POST` | On-the-fly conical horizontal slice coverage computation. |
| `/api/los/profile` | `POST` | High-resolution point-to-point Line of Sight, Earth curvature, Fresnel zone, and terrain profile. |
| `/api/peaks` | `GET` | Query European peaks by name, country, elevation range, or bounding box. |
| `/api/dependencies` | `GET` | Prototype dependencies ledger and roadmap for custom in-house implementations. |

---

## Verification & Automated Tests

Run the full test suite (42 unit and integration tests):

```powershell
python -m unittest discover tests
```

Tests cover:
- Snyder ellipsoidal LAEA projection round-trip accuracy.
- DEM windowed sampling and elevation extraction.
- RF Line of Sight, Earth curvature bulge, and Fresnel zone calculations.
- Overhead cone of silence and operational range cutoffs.
- DuckDB spatial queries, navaids/radars ingestion, and coverage precalculation tables.
- Dynamic FL600 evaluation and custom range clipping.
- Airspace cube evaluation and vertical column floor detection.
