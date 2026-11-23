# Prototype Dependencies & In-House Replacement Ledger

This document tracks all external open-source libraries, modules, and algorithms utilized for the rapid prototyping of the **EuroGeoCov** library, geodatabase, Line-of-Sight (LoS) RF engine, and airspace voxel coverage system.

Per project requirements, each component has a defined role, current upstream dependency, and an architectural replacement roadmap for migrating to a custom/in-house production implementation.

---

## Dependency & Replacement Matrix

| Subsystem | Prototype Component | Upstream Package & License | Purpose in Prototype | Production In-House Replacement Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Raster I/O & GeoTIFF** | `rasterio`, `affine` | BSD-3-Clause / Apache-2.0 (GDAL wrapper) | Reads the 24 GB `eudem_dem_3035_europe.tif` tiled BigTIFF, handles overview pyramid decimation, and windowed sub-array reads. | Implement custom memory-mapped (mmap) BigTIFF parser with pure C/Rust extension supporting Deflate/LZW compression, reading 256x256 tiles and overview tags directly without GDAL. |
| **Geodetic Projections** | `pyproj` | MIT (PROJ C-library wrapper) | Converts between geographic coordinates (WGS84 EPSG:4326) and European Terrestrial Reference System 1989 Lambert Azimuthal Equal Area (ETRS89-LAEA EPSG:3035). | Implement direct analytical forward and inverse transformation equations for Lambert Azimuthal Equal Area (Snyder 1987) on the GRS80/WGS84 ellipsoid. Formulas are ~50 lines of vectorized C/Python math with zero external C dependencies. |
| **Geodatabase & Spatial Queries** | `duckdb` | MIT | Ingestion, columnar storage, R-tree spatial indexing, and SQL queries for 1,500+ European peaks enriched with DEM elevations. | Transition to custom memory-mapped spatial index (KD-Tree or 2D/3D Morton Z-order linear quadtree) stored in flat binary format or an embedded SQLite instance with R*Tree extension. |
| **Vector Geometry** | `shapely` | BSD-3-Clause (GEOS wrapper) | Geometric bounding box queries, point-in-polygon containment, and geodesic line representation. | Implement direct lightweight 2D/3D spatial primitives (point, bbox, ray, segment) with bounding-box clipping and plane intersections. |
| **Numerical Math & Ray Casting** | `numpy`, `scipy` | BSD-3-Clause | Vectorized elevation profile sampling, Bresenham line generation, 1D linear interpolation along terrain rays, and Fresnel ellipsoid calculation. | Retain `numpy` for array primitives or compile an optimized SIMD C/Rust ray-marching kernel (`C-extension` or WebAssembly for frontend). |
| **REST API Server** | `fastapi`, `uvicorn`, `starlette` | MIT / BSD-3-Clause | Async HTTP server providing REST endpoints for peaks query, point-to-point LoS profile, and airspace coverage evaluation. | Can remain FastAPI for high-level microservice deployment, or replace with lightweight embedded HTTP router or gRPC service in C++/Go. |
| **Aeronautical Navaids & Radar Datasets** | Ingested open aeronautical databases (`navaids.csv`, `radars.json`) | Open Data | 816 ECAC VOR/DME navaids (Low TMA 25 NM vs High Enroute 130 NM) and 185 European Surveillance Radars with Mode-S, coverage ranges, and sector/elevation limits. | Standardized AIXM 5.1 / ARINC 424 XML binary parser for real-time Aeronautical Information Publication (AIP) ingestion. |
| **Data Validation** | `pydantic` | MIT | Request and response schema typing and serialization. | Retain Pydantic or replace with standard Python `dataclasses` / `struct` packing for ultra-low latency IPC. |
| **Frontend Map Visualizer** | `Leaflet.js` | BSD-2-Clause | Interactive 2D map visualization of European peaks, transmitter sites, ray paths, and airspace coverage grid overlays. | WebGL/WebGPU custom map canvas or CesiumJS / Deck.gl for full 3D Earth terrain rendering. |

---

## Scientific & RF Algorithms Implemented

1. **Earth Curvature & 4/3 Atmospheric Refraction Model**:
   - Standard radio atmospheric refraction bends electromagnetic waves toward Earth.
   - Model uses effective Earth radius $R_e = k \cdot R_0$, where $k = 4/3 \approx 1.3333$ (standard atmosphere) or configurable $k \in [0.5, 2.0]$.
   - Earth bulge correction at distance $d_1$ from Tx and $d_2$ from Rx:
     $$h_{bulge}(d_1) = \frac{d_1 \cdot d_2}{2 \cdot R_e}$$

2. **Fresnel Zone Clearance**:
   - First Fresnel zone radius at distance $d_1, d_2$ for frequency $f$:
     $$r_1(d_1, d_2) = \sqrt{\frac{c \cdot d_1 \cdot d_2}{f \cdot (d_1 + d_2)}}$$
   - Standard clearance threshold: $0.6 \cdot r_1$ (60% clearance ensures free space propagation without significant knife-edge diffraction).

3. **Free-Space Path Loss (FSPL)**:
   $$FSPL(dB) = 20 \log_{10}(d) + 20 \log_{10}(f) - 147.55$$ (for $d$ in meters, $f$ in Hz).

4. **1000-ft Airspace Voxelization**:
   - Voxel cube sizing: 1,000 ft vertical increments (Flight Levels) $\times$ customizable horizontal cell resolution ($1000\text{ ft} \approx 304.8\text{ m}$ or multi-voxel aggregates).
   - Visibility ray-marching from single/multiple mountain peak transmitters to assess airspace coverage completeness and redundant multi-station coverage.

---

## Deprecation & Replacement Phases

- **Phase 1 (Current Prototype)**: High-speed validation using `rasterio`, `pyproj`, `duckdb`, `fastapi`.
- **Phase 2 (Coordinate & RF Core Native)**: Replace `pyproj` with internal pure Python/C Snyder LAEA math; isolate RF propagation engine to zero-dependency C/Python core.
- **Phase 3 (DEM Storage Optimization)**: Replace GDAL/rasterio with native memory-mapped Cloud-Optimized GeoTIFF (COG) reader or quantized elevation tile format (.terrain / FlatGeobuf).
