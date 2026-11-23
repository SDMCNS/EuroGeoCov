/**
 * EuroGeoCov Interactive Frontend Application
 */

let map = null;
let txMarker = null;
let rxMarker = null;
let obstacleMarker = null;
let losPolyline = null;
let conicalLayerGroup = null;
let probeMarker = null;
let pickingMode = null; // 'tx', 'rx', 'cube', 'conical_probe'

let peaksData = [];
let countriesList = [];
let currentColumnData = null;
let currentConicalCenter = { lat: 45.8326, lon: 6.8652, alt: 4808, name: "Mont Blanc" };

// Multi-Station Facilities State
let allFacilities = [];
let allFacilityCountries = [];
let selectedFacilityIds = new Set();
let facilityCategoryFilter = "ALL";
let selectedCountryFilter = "";
const STATION_PALETTE = ['#39c5bb', '#bc8cff', '#ffa657', '#58a6ff', '#7ee787', '#f2cc60', '#ff7b72', '#26a69a', '#ab47bc'];

// Active Ray Sweep & Rotation State
let activeRayStationId = null;
let currentRayIndex = 0;
let rayRotationTimer = null;
let activeRayLayer = null;
let rayProfileCache = {};

// Dataset Builder & CLI Export State
let stagedDataset = [];
let datasetBuilderLayerGroup = null;

// Initialize Map & Application
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  loadTopPeaks();
  loadCountries();
  searchPeaks();
  loadDependencies();
  loadFacilities();
  switchTab('conical');

  // Initial calculation
  setTimeout(() => {
    runLoSEvaluation();
  }, 1000);

  // Resize canvas and map when window changes
  window.addEventListener("resize", () => {
    if (map) map.invalidateSize();
    drawProfileChart();
  });
});

function initMap() {
  // Center on the Alps / Central Europe
  map = L.map("map").setView([46.5, 9.5], 7);

  // Standard OpenStreetMap base layer (100% Free, No API key required)
  const osmLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors | EU-DEM Copernicus',
    maxZoom: 19,
  });

  // OpenTopoMap topographic layer (Free, No API key required)
  const topoLayer = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    attribution: 'Map: &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>, <a href="http://viewfinderpanoramas.org" target="_blank">SRTM</a> | Style: &copy; <a href="https://opentopomap.org" target="_blank">OpenTopoMap</a>',
    maxZoom: 17,
  });

  // Add default OSM layer
  osmLayer.addTo(map);

  // Add interactive base layer switcher
  const baseMaps = {
    "OpenStreetMap (Standard)": osmLayer,
    "OpenTopoMap (Topographic)": topoLayer
  };
  L.control.layers(baseMaps, null, { position: "topright" }).addTo(map);

  conicalLayerGroup = L.layerGroup().addTo(map);
  datasetBuilderLayerGroup = L.layerGroup().addTo(map);

  // Custom Icons
  const txIcon = L.divIcon({
    className: "custom-tx-icon",
    html: '<div style="background:#58a6ff; width:16px; height:16px; border-radius:50%; border:2px solid #fff; box-shadow:0 0 10px #58a6ff;"></div>',
    iconSize: [16, 16],
    iconAnchor: [8, 8]
  });

  const rxIcon = L.divIcon({
    className: "custom-rx-icon",
    html: '<div style="background:#3fb950; width:16px; height:16px; border-radius:3px; border:2px solid #fff; box-shadow:0 0 10px #3fb950;"></div>',
    iconSize: [16, 16],
    iconAnchor: [8, 8]
  });

  const txLat = parseFloat(document.getElementById("txLat").value);
  const txLon = parseFloat(document.getElementById("txLon").value);
  const rxLat = parseFloat(document.getElementById("rxLat").value);
  const rxLon = parseFloat(document.getElementById("rxLon").value);

  txMarker = L.marker([txLat, txLon], { icon: txIcon, draggable: true }).addTo(map);
  rxMarker = L.marker([rxLat, rxLon], { icon: rxIcon, draggable: true }).addTo(map);

  txMarker.on("dragend", (e) => {
    const latlng = e.target.getLatLng();
    document.getElementById("txLat").value = latlng.lat.toFixed(4);
    document.getElementById("txLon").value = latlng.lng.toFixed(4);
    runLoSEvaluation();
  });

  rxMarker.on("dragend", (e) => {
    const latlng = e.target.getLatLng();
    document.getElementById("rxLat").value = latlng.lat.toFixed(4);
    document.getElementById("rxLon").value = latlng.lng.toFixed(4);
    runLoSEvaluation();
  });

  map.on("click", (e) => {
    if (pickingMode === "tx") {
      document.getElementById("txLat").value = e.latlng.lat.toFixed(4);
      document.getElementById("txLon").value = e.latlng.lng.toFixed(4);
      txMarker.setLatLng(e.latlng);
      pickingMode = null;
      runLoSEvaluation();
    } else if (pickingMode === "rx") {
      document.getElementById("rxLat").value = e.latlng.lat.toFixed(4);
      document.getElementById("rxLon").value = e.latlng.lng.toFixed(4);
      rxMarker.setLatLng(e.latlng);
      pickingMode = null;
      runLoSEvaluation();
    } else if (pickingMode === "cube") {
      document.getElementById("cubeLat").value = e.latlng.lat.toFixed(4);
      document.getElementById("cubeLon").value = e.latlng.lng.toFixed(4);
      pickingMode = null;
      evaluateAirspaceCube();
    } else if (pickingMode === "builder") {
      document.getElementById("builderLat").value = e.latlng.lat.toFixed(4);
      document.getElementById("builderLon").value = e.latlng.lng.toFixed(4);
      fetch(`/api/dem/elevation?lat=${e.latlng.lat}&lon=${e.latlng.lng}`)
        .then(r => r.json())
        .then(d => {
          if (d && d.elevation_m !== undefined) {
            const ft = Math.round(d.elevation_m * 3.28084);
            const elevInput = document.getElementById("builderSiteElevFt");
            if (elevInput) elevInput.value = ft;
          }
        }).catch(() => {});
      pickingMode = null;
      const pickBtn = document.getElementById("btnPickBuilderMap");
      if (pickBtn) {
        pickBtn.textContent = "Click on Map";
        pickBtn.classList.remove("active");
      }
      map.getContainer().style.cursor = "";
    } else if (pickingMode === "conical_probe" || (document.getElementById("tab-conical") && document.getElementById("tab-conical").style.display !== "none")) {
      inspectAirspaceColumnAt(e.latlng.lat, e.latlng.lng);
      pickingMode = null;
    }
  });
}

function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach(b => {
    const fnAttr = b.getAttribute("onclick") || "";
    if (fnAttr.includes(`'${tabId}'`)) {
      b.classList.add("active");
    } else {
      b.classList.remove("active");
    }
  });
  document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");

  const content = document.getElementById(`tab-${tabId}`);
  if (content) content.style.display = "block";

  const sidePanel = document.getElementById("sideElevationPanel");

  if (tabId === "conical") {
    if (sidePanel) sidePanel.style.display = "flex";
    runMultiStationCoverage();
  } else if (tabId === "dataset-builder") {
    stopRayRotation();
    if (activeRayLayer) {
      map.removeLayer(activeRayLayer);
      activeRayLayer = null;
    }
    if (sidePanel) sidePanel.style.display = "none";
    if (conicalLayerGroup) conicalLayerGroup.clearLayers();
    renderDatasetBuilderMarkers();
  } else {
    // Stop any active ray rotation and clear active ray on map
    stopRayRotation();
    if (activeRayLayer) {
      map.removeLayer(activeRayLayer);
      activeRayLayer = null;
    }
    // Hide side panel in other tabs unless manually opened
    if (sidePanel && tabId !== "conical") sidePanel.style.display = "none";
    if (conicalLayerGroup) conicalLayerGroup.clearLayers();
  }

  if (map) {
    setTimeout(() => {
      map.invalidateSize();
    }, 150);
  }
}

function pickOnMap(mode) {
  pickingMode = mode;
  alert(`Click anywhere on the map to set the ${mode.toUpperCase()} position.`);
}

function syncRxAltMeters() {
  const ft = parseFloat(document.getElementById("rxAltFt").value);
  document.getElementById("rxAltM").value = (ft * 0.3048).toFixed(1);
}

function syncRxAltFeet() {
  const m = parseFloat(document.getElementById("rxAltM").value);
  document.getElementById("rxAltFt").value = Math.round(m * 3.28084);
}

function onFreqPresetChange(val) {
  const customGroup = document.getElementById("customFreqGroup");
  if (val === "custom") {
    customGroup.style.display = "block";
  } else {
    customGroup.style.display = "none";
  }
}

function getSelectedFrequencyHz() {
  const preset = document.getElementById("freqPreset").value;
  if (preset === "custom") {
    return parseFloat(document.getElementById("customFreqHz").value) || 1090000000;
  }
  return parseFloat(preset);
}

async function loadTopPeaks() {
  try {
    const res = await fetch("/api/peaks/top?limit=30");
    const peaks = await res.json();
    const select = document.getElementById("txPeakSelect");
    const conicalSelect = document.getElementById("conicalPeakSelect");

    select.innerHTML = '<option value="">-- Choose Mountain Peak --</option>';
    if (conicalSelect) {
      conicalSelect.innerHTML = '<option value="">-- Choose Mountain Peak --</option>';
    }

    peaks.forEach(p => {
      const valStr = JSON.stringify({
        lat: p.latitude,
        lon: p.longitude,
        alt: p.dem_meters || p.meters,
        name: p.name
      });
      const label = `${p.name} (${p.country}) - ${Math.round(p.dem_meters || p.meters)}m`;

      const opt1 = document.createElement("option");
      opt1.value = valStr;
      opt1.textContent = label;
      select.appendChild(opt1);

      if (conicalSelect) {
        const opt2 = document.createElement("option");
        opt2.value = valStr;
        opt2.textContent = label;
        conicalSelect.appendChild(opt2);
      }
    });

    if (peaks.length > 0) {
      currentConicalCenter = {
        lat: peaks[0].latitude,
        lon: peaks[0].longitude,
        alt: peaks[0].dem_meters || peaks[0].meters,
        name: peaks[0].name
      };
    }
  } catch (err) {
    console.warn("Failed to load top peaks:", err);
  }
}

function onTxPeakSelect(val) {
  if (!val) return;
  const p = JSON.parse(val);
  document.getElementById("txLat").value = p.lat.toFixed(4);
  document.getElementById("txLon").value = p.lon.toFixed(4);
  txMarker.setLatLng([p.lat, p.lon]);
  map.panTo([p.lat, p.lon]);
  runLoSEvaluation();
}

function onConicalPeakSelect(val) {
  if (!val) return;
  const p = JSON.parse(val);
  currentConicalCenter = p;
  map.panTo([p.lat, p.lon]);
  runConicalCoverage();
}

async function loadCountries() {
  try {
    const res = await fetch("/api/peaks/countries");
    const countries = await res.json();
    countriesList = countries;
    const select = document.getElementById("peakCountrySelect");
    select.innerHTML = '<option value="">All Countries</option>';
    countries.forEach(c => {
      const opt = document.createElement("option");
      opt.value = c.country;
      opt.textContent = `${c.country} (${c.count} peaks)`;
      select.appendChild(opt);
    });
  } catch (err) {
    console.warn("Failed to load countries:", err);
  }
}

let searchTimeout = null;
function debounceSearchPeaks() {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(searchPeaks, 300);
}

async function searchPeaks() {
  const q = document.getElementById("peakSearchQuery").value;
  const country = document.getElementById("peakCountrySelect").value;
  const minMeters = document.getElementById("peakMinMeters").value;

  let url = `/api/peaks?limit=50`;
  if (q) url += `&q=${encodeURIComponent(q)}`;
  if (country) url += `&country=${encodeURIComponent(country)}`;
  if (minMeters) url += `&min_meters=${minMeters}`;

  try {
    const res = await fetch(url);
    const peaks = await res.json();
    const tbody = document.getElementById("peaksTableBody");
    tbody.innerHTML = "";

    if (peaks.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">No peaks found matching criteria</td></tr>';
      return;
    }

    peaks.forEach(p => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-weight:600; color:#fff;">${p.name}</td>
        <td>${p.country}</td>
        <td>${Math.round(p.meters)}m</td>
        <td style="color:var(--accent-cyan);">${p.dem_meters ? Math.round(p.dem_meters) + 'm' : '--'}</td>
      `;
      tr.onclick = () => {
        document.getElementById("txLat").value = p.latitude.toFixed(4);
        document.getElementById("txLon").value = p.longitude.toFixed(4);
        txMarker.setLatLng([p.latitude, p.longitude]);
        map.panTo([p.latitude, p.longitude]);
        switchTab("los");
        runLoSEvaluation();
      };
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.warn("Failed to search peaks:", err);
  }
}

let currentProfileData = null;

async function runLoSEvaluation() {
  const txLat = parseFloat(document.getElementById("txLat").value);
  const txLon = parseFloat(document.getElementById("txLon").value);
  const txAlt = parseFloat(document.getElementById("txAlt").value);
  const txIsAgl = document.getElementById("txAltType").value === "AGL";

  const rxLat = parseFloat(document.getElementById("rxLat").value);
  const rxLon = parseFloat(document.getElementById("rxLon").value);
  const rxAltM = parseFloat(document.getElementById("rxAltM").value);
  const freqHz = getSelectedFrequencyHz();

  txMarker.setLatLng([txLat, txLon]);
  rxMarker.setLatLng([rxLat, rxLon]);

  const payload = {
    tx_lat: txLat,
    tx_lon: txLon,
    tx_alt_m: txAlt,
    tx_is_agl: txIsAgl,
    rx_lat: rxLat,
    rx_lon: rxLon,
    rx_alt_m: rxAltM,
    rx_is_agl: false,
    frequency_hz: freqHz,
    num_points: 250
  };

  try {
    const res = await fetch("/api/los/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    currentProfileData = data;

    // Update Stats
    document.getElementById("statDistance").textContent = `${data.total_distance_km} km (${data.total_distance_nm} NM)`;
    document.getElementById("statClearance").textContent = `${data.min_fresnel_clearance_m} m`;
    document.getElementById("statPathLoss").textContent = `${data.total_path_loss_db} dB`;

    if (document.getElementById("statElevationAngle")) {
      const coneText = data.in_cone_of_silence ? "⚠️ CONE OF SILENCE" : "Normal";
      document.getElementById("statElevationAngle").textContent = `${data.elevation_angle_deg}° (${coneText})`;
      document.getElementById("statElevationAngle").style.color = data.in_cone_of_silence ? "var(--accent-red)" : "var(--text-bright)";
    }

    if (document.getElementById("statCurvature") && data.earth_curvature) {
      document.getElementById("statCurvature").textContent = `${data.earth_curvature.max_path_bulge_m}m (Drop: ${data.earth_curvature.curvature_drop_at_rx_m}m)`;
    }

    const badge = document.getElementById("profileStatusBadge");
    if (data.status === "CLEAR") {
      badge.textContent = "CLEAR LOS (FRESNEL OK)";
      badge.className = "status-badge status-clear";
    } else if (data.status === "DIFFRACTED") {
      badge.textContent = "OPTICAL LOS (FRESNEL GRAZED)";
      badge.className = "status-badge status-diffracted";
    } else if (data.status === "CONE_OF_SILENCE") {
      badge.textContent = "CONE OF SILENCE (ANTENNA NULL)";
      badge.className = "status-badge status-obstructed";
    } else if (data.status === "EXCEEDS_MAX_FL") {
      badge.textContent = "EXCEEDS MAX FL (> FL600)";
      badge.className = "status-badge status-diffracted";
    } else if (data.status === "OUT_OF_RANGE") {
      badge.textContent = "OUT OF RANGE (> 200 NM)";
      badge.className = "status-badge status-diffracted";
    } else {
      badge.textContent = "OBSTRUCTED (TERRAIN BLOCKED)";
      badge.className = "status-badge status-obstructed";
    }

    // Obstacle stat
    if (data.obstacle && !data.has_fresnel_clearance) {
      document.getElementById("statObstacle").textContent = `${Math.round(data.obstacle.terrain_elev_m)}m @ ${(data.obstacle.distance_m / 1000).toFixed(1)}km`;
    } else {
      document.getElementById("statObstacle").textContent = "Clear";
    }

    // Map Polyline
    if (losPolyline) map.removeLayer(losPolyline);
    const lineColor = data.status === "CLEAR" ? "#3fb950" : (data.status === "DIFFRACTED" ? "#d29922" : "#f85149");
    losPolyline = L.polyline([[txLat, txLon], [rxLat, rxLon]], { color: lineColor, weight: 3, dashArray: data.status === "OBSTRUCTED" ? "6, 6" : null }).addTo(map);

    // Obstacle pin
    if (obstacleMarker) map.removeLayer(obstacleMarker);
    if (data.obstacle && !data.has_los) {
      obstacleMarker = L.circleMarker([data.obstacle.lat, data.obstacle.lon], {
        radius: 6,
        color: "#f85149",
        fillColor: "#f85149",
        fillOpacity: 0.8
      }).addTo(map).bindPopup(`<b>Critical Obstacle</b><br>Elevation: ${Math.round(data.obstacle.terrain_elev_m)}m AMSL`);
    }

    // Draw Cross Section
    drawProfileChart();

  } catch (err) {
    console.error("LoS calculation error:", err);
  }
}

function drawProfileChart() {
  if (!currentProfileData || !currentProfileData.profile) return;

  const canvas = document.getElementById("profileChartCanvas");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;

  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;

  const prof = currentProfileData.profile;
  const distances = prof.distances_m;
  const terrain = prof.curved_terrain_m;
  const ray = prof.ray_m;
  const fresnelLower = prof.fresnel_lower_m;
  const fresnelUpper = prof.fresnel_upper_m;

  const maxDist = currentProfileData.total_distance_m;
  const allElevs = [...terrain, ...ray, ...fresnelUpper];
  const minElev = Math.max(0, Math.min(...allElevs) - 200);
  const maxElev = Math.max(...allElevs) + 300;

  const padding = { top: 20, right: 30, bottom: 25, left: 50 };
  const plotW = w - padding.left - padding.right;
  const plotH = h - padding.top - padding.bottom;

  function toX(d) {
    return padding.left + (d / maxDist) * plotW;
  }
  function toY(elev) {
    return padding.top + plotH - ((elev - minElev) / (maxElev - minElev)) * plotH;
  }

  // Clear
  ctx.clearRect(0, 0, w, h);

  // Grid Lines
  ctx.strokeStyle = "#21262d";
  ctx.lineWidth = 1;
  const numYGrid = 4;
  ctx.fillStyle = "#8b949e";
  ctx.font = "10px sans-serif";
  for (let i = 0; i <= numYGrid; i++) {
    const yVal = minElev + (i / numYGrid) * (maxElev - minElev);
    const yPx = toY(yVal);
    ctx.beginPath();
    ctx.moveTo(padding.left, yPx);
    ctx.lineTo(w - padding.right, yPx);
    ctx.stroke();
    ctx.fillText(`${Math.round(yVal)}m`, 8, yPx + 3);
  }

  // Distance X labels
  const numXGrid = 5;
  for (let i = 0; i <= numXGrid; i++) {
    const dVal = (i / numXGrid) * maxDist;
    const xPx = toX(dVal);
    ctx.beginPath();
    ctx.moveTo(xPx, padding.top);
    ctx.lineTo(xPx, h - padding.bottom);
    ctx.stroke();
    ctx.fillText(`${(dVal / 1000).toFixed(0)}km`, xPx - 10, h - 8);
  }

  // 1. Draw Fresnel Zone Ellipsoid (Shaded)
  ctx.beginPath();
  ctx.moveTo(toX(distances[0]), toY(fresnelUpper[0]));
  for (let i = 1; i < distances.length; i++) {
    ctx.lineTo(toX(distances[i]), toY(fresnelUpper[i]));
  }
  for (let i = distances.length - 1; i >= 0; i--) {
    ctx.lineTo(toX(distances[i]), toY(fresnelLower[i]));
  }
  ctx.closePath();
  ctx.fillStyle = "rgba(88, 166, 255, 0.12)";
  ctx.fill();

  ctx.strokeStyle = "rgba(88, 166, 255, 0.4)";
  ctx.lineWidth = 1;
  ctx.stroke();

  // 2. Draw Terrain (Curved Earth Baseline)
  ctx.beginPath();
  ctx.moveTo(toX(distances[0]), toY(terrain[0]));
  for (let i = 1; i < distances.length; i++) {
    ctx.lineTo(toX(distances[i]), toY(terrain[i]));
  }
  ctx.lineTo(toX(maxDist), toY(minElev));
  ctx.lineTo(toX(0), toY(minElev));
  ctx.closePath();
  ctx.fillStyle = "#1e242c";
  ctx.fill();

  ctx.strokeStyle = "#8b949e";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(toX(distances[0]), toY(terrain[0]));
  for (let i = 1; i < distances.length; i++) {
    ctx.lineTo(toX(distances[i]), toY(terrain[i]));
  }
  ctx.stroke();

  // 3. Draw Direct Line-of-Sight Ray
  ctx.beginPath();
  ctx.moveTo(toX(distances[0]), toY(ray[0]));
  ctx.lineTo(toX(distances[distances.length - 1]), toY(ray[ray.length - 1]));
  ctx.strokeStyle = currentProfileData.status === "CLEAR" ? "#3fb950" : (currentProfileData.status === "DIFFRACTED" ? "#d29922" : "#f85149");
  ctx.lineWidth = 2;
  ctx.stroke();

  // 4. Mark Antennas
  ctx.fillStyle = "#58a6ff";
  ctx.beginPath();
  ctx.arc(toX(0), toY(ray[0]), 4, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = "#3fb950";
  ctx.beginPath();
  ctx.arc(toX(maxDist), toY(ray[ray.length - 1]), 4, 0, Math.PI * 2);
  ctx.fill();

  // 5. Mark Bottleneck Obstacle
  if (currentProfileData.obstacle && !currentProfileData.has_fresnel_clearance) {
    const ox = toX(currentProfileData.obstacle.distance_m);
    const oy = toY(currentProfileData.obstacle.curved_terrain_m);
    ctx.fillStyle = "#f85149";
    ctx.beginPath();
    ctx.arc(ox, oy, 5, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = "#f85149";
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(ox, oy);
    ctx.lineTo(ox, toY(currentProfileData.obstacle.ray_height_m));
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

async function evaluateAirspaceCube() {
  const lat = parseFloat(document.getElementById("cubeLat").value);
  const lon = parseFloat(document.getElementById("cubeLon").value);
  const altFt = parseFloat(document.getElementById("cubeAltSelect").value);
  const freqHz = getSelectedFrequencyHz();

  const payload = {
    lat: lat,
    lon: lon,
    altitude_ft: altFt,
    cube_size_ft: 1000.0,
    frequency_hz: freqHz
  };

  try {
    const res = await fetch("/api/airspace/cube", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    const container = document.getElementById("airspaceCubeResult");
    const content = document.getElementById("cubeResultContent");
    container.style.display = "block";

    const badgeColor = data.is_covered ? "var(--accent-green)" : "var(--accent-red)";
    content.innerHTML = `
      <div style="margin-bottom:8px;">
        <b>Cube Altitude:</b> ${data.cube.center_alt_ft} ft (${data.cube.center_alt_m}m AMSL)<br>
        <b>Voxel Layer:</b> ${data.cube.alt_floor_ft} - ${data.cube.alt_ceiling_ft} ft<br>
        <b>Coverage Status:</b> <span style="color:${badgeColor}; font-weight:700;">${data.redundancy_level}</span><br>
        <b>Visible Mountain Stations:</b> ${data.visible_stations_count} / ${data.stations_evaluated}<br>
        <b>Best Relay Station:</b> ${data.best_station || 'None'}<br>
        <b>Signal Path Loss:</b> ${data.best_path_loss_db ? data.best_path_loss_db + ' dB' : 'N/A'}
      </div>
      <div style="border-top:1px solid var(--border-color); padding-top:6px; font-size:11px;">
        ${data.station_details.map(s => `
          <div style="display:flex; justify-content:space-between; margin-bottom:3px;">
            <span>${s.station_name} (${s.distance_km}km)</span>
            <span style="color:${s.has_fresnel ? 'var(--accent-green)' : 'var(--accent-red)'}">${s.status}</span>
          </div>
        `).join('')}
      </div>
    `;

    // Drop circle marker on map for cube
    L.circle([lat, lon], {
      radius: 1500,
      color: data.is_covered ? "#3fb950" : "#f85149",
      fillColor: data.is_covered ? "#3fb950" : "#f85149",
      fillOpacity: 0.3
    }).addTo(map).bindPopup(`<b>1000ft Airspace Cube</b><br>Altitude: ${altFt} ft<br>Status: ${data.redundancy_level}`);

  } catch (err) {
    console.error("Airspace cube evaluation failed:", err);
  }
}

async function evaluateVerticalColumn() {
  const lat = parseFloat(document.getElementById("cubeLat").value);
  const lon = parseFloat(document.getElementById("cubeLon").value);
  const freqHz = getSelectedFrequencyHz();

  const payload = {
    lat: lat,
    lon: lon,
    min_alt_ft: 1000.0,
    max_alt_ft: 45000.0,
    step_ft: 1000.0,
    frequency_hz: freqHz
  };

  try {
    const res = await fetch("/api/airspace/column", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    const container = document.getElementById("airspaceColumnResult");
    const content = document.getElementById("columnResultContent");
    container.style.display = "block";

    content.innerHTML = `
      <div style="margin-bottom:8px;">
        <b>Terrain Elevation:</b> ${data.ground_elevation_m}m (${Math.round(data.ground_elevation_ft)} ft)<br>
        <b>Airspace Coverage Floor:</b> <span style="color:var(--accent-cyan); font-weight:700;">${data.coverage_floor_ft ? data.coverage_floor_ft + ' ft AMSL' : 'No Coverage'}</span>
      </div>
      <table style="width:100%; font-size:11px;">
        <thead><tr><th>Altitude</th><th>Covered</th><th>Stations</th><th>Best Link</th></tr></thead>
        <tbody>
          ${data.column_samples.map(s => `
            <tr>
              <td>FL${Math.round(s.alt_ft / 100)} (${s.alt_ft}ft)</td>
              <td style="color:${s.is_covered ? 'var(--accent-green)' : 'var(--accent-red)'}">${s.is_covered ? 'YES' : 'DARK'}</td>
              <td>${s.visible_stations}</td>
              <td>${s.best_station || '--'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    console.error("Vertical column evaluation failed:", err);
  }
}

async function loadDependencies() {
  try {
    const res = await fetch("/api/dependencies");
    const data = await res.json();
    const container = document.getElementById("dependenciesContainer");

    const components = [
      {
        name: "rasterio / GDAL",
        license: "BSD-3-Clause",
        role: "Tiled BigTIFF window reads and overview sampling on 24GB EU-DEM.",
        replace: "Custom memory-mapped COG BigTIFF tile decoder in C/Rust with Deflate decompression."
      },
      {
        name: "pyproj / PROJ",
        license: "MIT",
        role: "ETRS89-LAEA EPSG:3035 and WGS84 EPSG:4326 geodetic transformations.",
        replace: "Built-in pure analytical Snyder LAEA ellipsoidal mathematical engine (already verified in eurogeocov.projection)."
      },
      {
        name: "DuckDB",
        license: "MIT",
        role: "Spatial indexing, bounding box SQL searches, and columnar storage of European peaks.",
        replace: "Custom FlatGeobuf / SQLite R*Tree memory index or KD-Tree file format."
      },
      {
        name: "NumPy & SciPy",
        license: "BSD-3-Clause",
        role: "Vectorized ray-casting, Bresenham interpolation, and Fresnel zone calculations.",
        replace: "Can be compiled to a standalone SIMD C-extension or pure WebAssembly kernel."
      },
      {
        name: "FastAPI / Uvicorn",
        license: "MIT",
        role: "Asynchronous REST API service for peak queries and LoS ray evaluations.",
        replace: "Ultra-lightweight embedded C++ / Rust HTTP/gRPC server."
      },
      {
        name: "Leaflet.js",
        license: "BSD-2-Clause",
        role: "Interactive map visualization of European peaks and Line of Sight rays.",
        replace: "Custom WebGL / CesiumJS 3D Earth terrain globe."
      }
    ];

    container.innerHTML = components.map(c => `
      <div class="dep-card">
        <div class="dep-header">
          <span class="dep-title">${c.name}</span>
          <span class="dep-license">${c.license}</span>
        </div>
        <div style="font-size:12px; color:var(--text-bright);">${c.role}</div>
        <div class="dep-replace"><b>Replacement Plan:</b> ${c.replace}</div>
      </div>
    `).join('');

  } catch (err) {
    console.warn("Failed to load dependencies:", err);
  }
}

// -------------------------------------------------------------
// Conical Coverage Slice & Side FL10 Elevation Ladder Functions
// -------------------------------------------------------------

// -------------------------------------------------------------
// Navaids & Radars Multi-Facility Coverage & Radial LoS Lines
// -------------------------------------------------------------

async function loadFacilities() {
  const container = document.getElementById("facilitySelectContainer");
  if (container) {
    container.innerHTML = `<div style="display:flex; align-items:center; justify-content:center; gap:8px; padding:15px; color:var(--accent-cyan); font-size:11px;"><span class="spinner"></span> Loading European surveillance & navigation facilities...</div>`;
  }

  try {
    const [facRes, countriesRes] = await Promise.all([
      fetch("/api/facilities?limit=2500"),
      fetch("/api/facilities/countries")
    ]);
    if (!facRes.ok) {
      throw new Error(`HTTP ${facRes.status}: ${facRes.statusText}`);
    }
    allFacilities = await facRes.json();
    if (countriesRes.ok) {
      allFacilityCountries = await countriesRes.json();
      populateCountrySelect();
    }

    const countBadge = document.getElementById("facilitiesCountBadge");
    if (countBadge) {
      const navs = allFacilities.filter(f => f.category === "NAVAID").length;
      const rads = allFacilities.filter(f => f.category === "RADAR").length;
      countBadge.textContent = `${allFacilities.length} Loaded (${rads} Radars, ${navs} VOR/DME)`;
    }

    // Default select 2 prominent facilities: 1 High VOR/DME and 1 Radar
    const defNav = allFacilities.find(f => f.category === "NAVAID" && f.range_nm >= 100);
    const defRad = allFacilities.find(f => f.category === "RADAR");
    if (defNav) selectedFacilityIds.add(defNav.id);
    if (defRad) selectedFacilityIds.add(defRad.id);

    updateCountryBulkCard();
    renderFacilityList();
    updateSelectedChips();
    populateBuilderEcacSelect();

    // Trigger initial multi-station coverage
    runMultiStationCoverage();
  } catch (err) {
    console.error("Failed to load facilities:", err);
    if (container) {
      container.innerHTML = `<div style="color:var(--accent-red); font-size:11px; text-align:center; padding:12px;">Failed to load facilities: ${err.message}. <button class="btn-link" onclick="loadFacilities()">Retry</button></div>`;
    }
  }
}

function populateCountrySelect() {
  const sel = document.getElementById("facilityCountrySelect");
  const statsBadge = document.getElementById("countryStatsBadge");
  if (!sel) return;

  if (statsBadge && allFacilityCountries.length > 0) {
    statsBadge.textContent = `${allFacilityCountries.length} ECAC Countries`;
  }

  let html = `<option value="">All ECAC Countries (40 countries, 1,001 facilities)</option>`;
  const sorted = [...allFacilityCountries].sort((a, b) => (a.country_name || a.country).localeCompare(b.country_name || b.country));
  html += sorted.map(c => `
    <option value="${c.country}">${c.country_name || c.country} (${c.country}) — ${c.radar_count} Radars, ${c.vor_dme_count} VOR/DME</option>
  `).join("");

  sel.innerHTML = html;
  if (selectedCountryFilter) {
    sel.value = selectedCountryFilter;
  }
}

function onFacilityCountryChange(val) {
  selectedCountryFilter = val || "";
  updateCountryBulkCard();
  renderFacilityList();

  if (selectedCountryFilter) {
    const countryFacs = allFacilities.filter(f => f.country === selectedCountryFilter);
    if (countryFacs.length > 0) {
      const bounds = L.latLngBounds(countryFacs.map(f => [f.latitude, f.longitude]));
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 8 });
      }
    }
  }
}

function updateCountryBulkCard() {
  const targetName = document.getElementById("targetCountryName");
  const targetTotals = document.getElementById("targetCountryTotals");
  const vorCountSpan = document.getElementById("countryVorCount");
  const radarCountSpan = document.getElementById("countryRadarCount");
  const totalCountSpan = document.getElementById("countryTotalCount");

  if (!selectedCountryFilter) {
    if (targetName) targetName.textContent = "All ECAC Countries";
    const totalNavs = allFacilities.filter(f => f.category === "NAVAID").length;
    const totalRads = allFacilities.filter(f => f.category === "RADAR").length;
    if (targetTotals) targetTotals.textContent = `${totalNavs} Navs · ${totalRads} Radars`;
    if (vorCountSpan) vorCountSpan.textContent = totalNavs;
    if (radarCountSpan) radarCountSpan.textContent = totalRads;
    if (totalCountSpan) totalCountSpan.textContent = (totalNavs + totalRads);
    return;
  }

  const c = allFacilityCountries.find(x => x.country === selectedCountryFilter);
  const cName = c ? `${c.country_name} (${c.country})` : selectedCountryFilter;
  const vorC = c ? c.vor_dme_count : allFacilities.filter(f => f.country === selectedCountryFilter && f.category === "NAVAID").length;
  const radC = c ? c.radar_count : allFacilities.filter(f => f.country === selectedCountryFilter && f.category === "RADAR").length;
  const totC = c ? c.total_facilities : (vorC + radC);

  if (targetName) targetName.textContent = cName;
  if (targetTotals) targetTotals.textContent = `${vorC} Navs · ${radC} Radars`;
  if (vorCountSpan) vorCountSpan.textContent = vorC;
  if (radarCountSpan) radarCountSpan.textContent = radC;
  if (totalCountSpan) totalCountSpan.textContent = totC;
}

function bulkSelectByCountry(type) {
  const matching = allFacilities.filter(f => {
    if (selectedCountryFilter && f.country !== selectedCountryFilter) return false;
    if (type === "VOR_DME") return f.category === "NAVAID";
    if (type === "RADAR") return f.category === "RADAR";
    if (type === "ALL") return f.category === "NAVAID" || f.category === "RADAR";
    return true;
  });

  if (matching.length === 0) {
    alert(`No ${type} facilities found for ${selectedCountryFilter || 'selected filter'}.`);
    return;
  }

  matching.forEach(f => selectedFacilityIds.add(f.id));

  const latlngs = matching.map(f => [f.latitude, f.longitude]);
  if (latlngs.length > 0) {
    const bounds = L.latLngBounds(latlngs);
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 8 });
    }
  }

  renderFacilityList();
  updateSelectedChips();
  runMultiStationCoverage();
}

function bulkDeselectByCountry() {
  if (selectedCountryFilter) {
    allFacilities
      .filter(f => f.country === selectedCountryFilter)
      .forEach(f => selectedFacilityIds.delete(f.id));
  } else {
    selectedFacilityIds.clear();
  }
  renderFacilityList();
  updateSelectedChips();
  if (selectedFacilityIds.size === 0) {
    if (conicalLayerGroup) conicalLayerGroup.clearLayers();
    const statsBox = document.getElementById("multiStationStatsContent");
    if (statsBox) {
      statsBox.innerHTML = `<div>No facilities selected. Select 1 or more to view coverage.</div>`;
    }
  } else {
    runMultiStationCoverage();
  }
}

function getFilteredFacilities() {
  const query = (document.getElementById("facilitySearchInput")?.value || "").toLowerCase().trim();
  return allFacilities.filter(f => {
    // Country filter
    if (selectedCountryFilter && f.country !== selectedCountryFilter) return false;

    // Category match
    if (facilityCategoryFilter === "RADAR" && f.category !== "RADAR") return false;
    if (facilityCategoryFilter === "ENROUTE" && !(f.category === "NAVAID" && f.service_category === "ENROUTE")) return false;
    if (facilityCategoryFilter === "TMA" && !(f.category === "NAVAID" && f.service_category === "TMA")) return false;
    if (facilityCategoryFilter === "PEAK" && f.category !== "PEAK") return false;

    // Search query match
    if (query) {
      const matchIdent = (f.ident || "").toLowerCase().includes(query);
      const matchName = (f.name || "").toLowerCase().includes(query);
      const matchCountry = (f.country || "").toLowerCase().includes(query);
      const matchCountryName = (f.country_name || "").toLowerCase().includes(query);
      const matchType = (f.type || "").toLowerCase().includes(query);
      if (!matchIdent && !matchName && !matchCountry && !matchCountryName && !matchType) return false;
    }
    return true;
  });
}

function renderFacilityList() {
  const container = document.getElementById("facilitySelectContainer");
  const countText = document.getElementById("visibleFacilityCountText");
  if (!container) return;

  const filtered = getFilteredFacilities();
  if (countText) {
    countText.textContent = `Showing ${Math.min(filtered.length, 150)} of ${filtered.length} matching (${allFacilities.length} total)`;
  }

  if (filtered.length === 0) {
    container.innerHTML = `<div style="color:var(--text-muted); font-size:11px; text-align:center; padding:12px;">No matching facilities found.</div>`;
    return;
  }

  const displaySlice = filtered.slice(0, 150);
  let html = displaySlice.map(f => {
    const isChecked = selectedFacilityIds.has(f.id);
    let metaClass = "meta-enroute";
    let metaLabel = `${f.type} ${f.range_nm}NM`;
    if (f.category === "RADAR") {
      metaClass = "meta-radar";
      metaLabel = `RADAR ${f.range_nm}NM`;
    } else if (f.category === "NAVAID" && f.service_category === "TMA") {
      metaClass = "meta-tma";
      metaLabel = `TMA DME ${f.range_nm}NM`;
    } else if (f.category === "PEAK") {
      metaClass = "meta-peak";
      metaLabel = `${Math.round(f.elev_m)}m PEAK`;
    }

    return `
      <div class="facility-item ${isChecked ? 'selected' : ''}" onclick="toggleFacility('${f.id}')">
        <div class="facility-left">
          <input type="checkbox" ${isChecked ? 'checked' : ''} onclick="event.stopPropagation(); toggleFacility('${f.id}')">
          <span class="facility-ident">${f.ident || '--'}</span>
          <span class="facility-name" title="${f.name}">${f.name}</span>
          ${f.country ? `<span style="color:var(--text-muted); font-size:10px;">(${f.country})</span>` : ''}
        </div>
        <div>
          <span class="facility-meta-badge ${metaClass}">${metaLabel}</span>
        </div>
      </div>
    `;
  }).join("");

  if (filtered.length > 150) {
    html += `<div style="text-align:center; padding:6px; color:var(--text-muted); font-size:10px; border-top:1px dashed var(--border-color); margin-top:4px;">Showing first 150 of ${filtered.length}. Use search box above to find any specific facility.</div>`;
  }

  container.innerHTML = html;
}

function toggleFacility(id) {
  if (selectedFacilityIds.has(id)) {
    selectedFacilityIds.delete(id);
  } else {
    selectedFacilityIds.add(id);
  }
  renderFacilityList();
  updateSelectedChips();
  debounceMultiStationCoverage();
}

function selectAllFilteredFacilities() {
  const filtered = getFilteredFacilities().slice(0, 15); // Safety limit up to 15 at once
  filtered.forEach(f => selectedFacilityIds.add(f.id));
  renderFacilityList();
  updateSelectedChips();
  runMultiStationCoverage();
}

function clearSelectedFacilities() {
  selectedFacilityIds.clear();
  renderFacilityList();
  updateSelectedChips();
  if (conicalLayerGroup) conicalLayerGroup.clearLayers();
  document.getElementById("multiStationStatsContent").innerHTML = `<div>No facilities selected. Select 1 or more to view coverage.</div>`;
}

function updateSelectedChips() {
  const box = document.getElementById("selectedChipsBox");
  const countBadge = document.getElementById("selectedCountBadge");
  if (!box) return;

  const selectedList = allFacilities.filter(f => selectedFacilityIds.has(f.id));
  if (countBadge) countBadge.textContent = `${selectedList.length} Selected`;

  const bCount = document.getElementById("btnStageCoverageCount");
  if (bCount) bCount.textContent = selectedFacilityIds.size;
  const impCount = document.getElementById("importCheckedCount");
  if (impCount) impCount.textContent = selectedFacilityIds.size;

  if (selectedList.length === 0) {
    box.innerHTML = `<span style="font-size:11px; color:var(--text-muted); font-style:italic;">No facility selected yet. Check boxes above or click presets.</span>`;
    return;
  }

  box.innerHTML = selectedList.map((f, idx) => {
    const color = STATION_PALETTE[idx % STATION_PALETTE.length];
    return `
      <div class="station-chip" title="${f.name} (${f.type})">
        <span class="station-chip-color" style="background:${color};"></span>
        <span style="font-weight:700; color:#fff;">${f.ident || f.name.slice(0, 5)}</span>
        <span style="font-size:10px; color:var(--text-muted);">${f.range_nm}NM</span>
        <span class="station-chip-del" onclick="event.stopPropagation(); toggleFacility('${f.id}')">&times;</span>
      </div>
    `;
  }).join("");
}

function setFacilityFilter(cat) {
  facilityCategoryFilter = cat;
  document.querySelectorAll(".facility-filter-chips .filter-chip").forEach(c => {
    if (c.dataset.cat === cat) c.classList.add("active");
    else c.classList.remove("active");
  });
  renderFacilityList();
}

function onFacilitySearchInput() {
  renderFacilityList();
}

function loadPresetFacilities(preset) {
  selectedFacilityIds.clear();
  if (preset === "major_radars") {
    // Pick 3-4 major European radars
    const rads = allFacilities.filter(f => f.category === "RADAR").slice(0, 3);
    rads.forEach(r => selectedFacilityIds.add(r.id));
  } else if (preset === "enroute_dme") {
    // Alps / Central Europe VOR-DMEs
    const dmes = allFacilities.filter(f => f.category === "NAVAID" && f.service_category === "ENROUTE" && ["FR", "CH", "IT", "DE"].includes(f.country)).slice(0, 4);
    dmes.forEach(d => selectedFacilityIds.add(d.id));
  } else if (preset === "tma_london_paris") {
    // London and Paris TMA DMEs
    const tmas = allFacilities.filter(f => f.category === "NAVAID" && f.service_category === "TMA" && ["GB", "FR"].includes(f.country)).slice(0, 4);
    tmas.forEach(t => selectedFacilityIds.add(t.id));
  }
  renderFacilityList();
  updateSelectedChips();
  runMultiStationCoverage();
}

function onRangeModeChange() {
  const isCustom = document.getElementById("rangeModeCustom")?.checked;
  const isDoc = document.getElementById("rangeModeDoc")?.checked;

  const group = document.getElementById("rangeCustomGroup");
  const label = document.getElementById("rangeModeLabel");

  if (group) group.style.display = isCustom ? "block" : "none";
  if (label) {
    if (isCustom) {
      const km = document.getElementById("conicalRangeSlider")?.value || 200;
      label.textContent = `Custom (${km} km / ${Math.round(km / 1.852)} NM)`;
    } else if (isDoc) {
      label.textContent = "Designated (DOC)";
    } else {
      label.textContent = "Over-the-Horizon (FL600)";
    }
  }
  debounceMultiStationCoverage();
}

function onRangeSliderChange(val) {
  const km = parseFloat(val);
  const nm = Math.round(km / 1.852);
  const disp = document.getElementById("rangeValueDisplay");
  const label = document.getElementById("rangeModeLabel");
  if (disp) disp.textContent = `${km} km (${nm} NM)`;
  if (label && document.getElementById("rangeModeCustom")?.checked) {
    label.textContent = `Custom (${km} km / ${nm} NM)`;
  }
  debounceMultiStationCoverage();
}

let multiStationTimeout = null;
let lastCoverageData = null;

function debounceMultiStationCoverage() {
  clearTimeout(multiStationTimeout);
  multiStationTimeout = setTimeout(runMultiStationCoverage, 200);
}

function refreshConicalRender() {
  if (lastCoverageData) {
    renderMultiStationCoverage(lastCoverageData);
  }
}

async function runMultiStationCoverage() {
  if (selectedFacilityIds.size === 0) {
    if (conicalLayerGroup) conicalLayerGroup.clearLayers();
    lastCoverageData = null;
    const statsBox = document.getElementById("multiStationStatsContent");
    if (statsBox) {
      statsBox.innerHTML = `<div>No facilities selected. Select 1 or more above or use bulk buttons to view coverage.</div>`;
    }
    return;
  }

  const flSelect = document.getElementById("conicalFlSelect");
  const flFt = flSelect ? parseFloat(flSelect.value) : 10000.0;
  const idsParam = Array.from(selectedFacilityIds).join(",");

  const isCustom = document.getElementById("rangeModeCustom")?.checked;
  const isDoc = document.getElementById("rangeModeDoc")?.checked;
  const rangeSlider = document.getElementById("conicalRangeSlider");

  let rangeQuery = "";
  if (isCustom && rangeSlider) {
    rangeQuery = `&max_range_km=${rangeSlider.value}`;
  } else if (isDoc) {
    rangeQuery = `&use_doc_range=true`;
  }
  // Otherwise default: full over-the-horizon reach out to FL600!

  const statsBox = document.getElementById("multiStationStatsContent");
  if (statsBox) {
    statsBox.innerHTML = `
      <div style="display:flex; align-items:center; gap:8px; color:var(--accent-cyan); padding:8px 0; font-size:12px;">
        <span class="spinner"></span>
        <span>Loading coverage for ${selectedFacilityIds.size} facility/facilities at FL${Math.round(flFt / 100)}...</span>
      </div>
    `;
  }

  const t0 = performance.now();
  try {
    const url = `/api/facilities/coverage?ids=${encodeURIComponent(idsParam)}&flight_level_ft=${flFt}${rangeQuery}`;
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    const data = await res.json();
    data.loadTimeMs = Math.round(performance.now() - t0);
    lastCoverageData = data;

    renderMultiStationCoverage(data);
    highlightLadderFL(flFt);

  } catch (err) {
    console.error("Multi-station coverage loading failed:", err);
    if (statsBox) {
      statsBox.innerHTML = `
        <div style="color:var(--accent-red); font-size:12px; margin-bottom:6px;">
          Failed to load coverage: ${err.message}
        </div>
        <button class="btn btn-secondary" style="width:auto; padding:4px 10px; font-size:11px;" onclick="runMultiStationCoverage()">🔄 Retry Loading Coverage</button>
      `;
    }
  }
}

function renderMultiStationCoverage(data) {
  if (!conicalLayerGroup) conicalLayerGroup = L.layerGroup().addTo(map);
  conicalLayerGroup.clearLayers();

  const stations = data.stations || [];
  if (stations.length === 0) return;

  const showRadials = document.getElementById("toggleShowRadials") ? document.getElementById("toggleShowRadials").checked : true;
  const mergeCoverage = document.getElementById("toggleMergeCoverage") ? document.getElementById("toggleMergeCoverage").checked : true;
  const showPerimeters = document.getElementById("toggleShowPerimeters") ? document.getElementById("toggleShowPerimeters").checked : true;
  const flFt = data.flight_level_ft || 10000.0;

  let boundsToFit = [];

  // 1. Render Each Station Marker, Radials, and Individual Perimeters
  stations.forEach((station, idx) => {
    const color = STATION_PALETTE[idx % STATION_PALETTE.length];
    const tx = station.tx_coords;
    boundsToFit.push(tx);

    // Station Center Marker
    const ident = station.station_ident || "STA";
    const markerHtml = `
      <div class="station-radar-marker" style="background:${color}; width:22px; height:22px;">
        ${ident.slice(0, 3)}
      </div>
    `;
    const stationIcon = L.divIcon({
      className: "custom-station-icon",
      html: markerHtml,
      iconSize: [22, 22],
      iconAnchor: [11, 11]
    });

    const stMarker = L.marker(tx, { icon: stationIcon }).addTo(conicalLayerGroup);
    stMarker.bindPopup(`
      <div style="font-size:12px;">
        <b style="color:${color}; font-size:13px;">${station.station_ident} &middot; ${station.station_name}</b><br>
        <b>Type:</b> ${station.station_type} (${station.category})<br>
        <b>Country:</b> ${station.country_name || station.country || '--'}<br>
        <b>Designated Range:</b> ${station.range_nm} NM (${station.range_km} km)<br>
        <b>Antenna Altitude:</b> ${station.tx_amsl_m}m AMSL (Ground: ${station.ground_elev_m}m)<br>
        <b>Flight Level:</b> FL${Math.round(flFt / 100)} (${flFt} ft AMSL)<br>
        <b>Effective Area:</b> ${(station.metrics?.coverage_area_sq_km || 0).toLocaleString()} km&sup2;<br>
        <b>Terrain Cut Radials:</b> ${station.metrics?.cut_radials || 0} / ${station.metrics?.total_radials || 0} (${station.metrics?.cut_percentage || 0}%)
        <div style="margin-top:8px; border-top:1px solid #30363d; padding-top:6px; display:flex; flex-direction:column; gap:4px;">
          <button class="btn btn-primary" style="font-size:11px; padding:3px 8px; width:100%; cursor:pointer; background: #1f6feb;" onclick="openCoverage3DModal('${station.station_id}')">
            🧊 3D Coverage Volume
          </button>
          <button class="btn btn-secondary" style="font-size:11px; padding:3px 8px; width:100%; cursor:pointer;" onclick="addFacilityToDatasetBuilder('${station.station_id}')">
            ➕ Add to Dataset Builder
          </button>
        </div>
      </div>
    `);

    // Individual Radial Lines of Sight (stopping at cut points)
    if (showRadials) {
      const radials = station.radial_lines || [];
      radials.forEach(r => {
        const lineCoords = r.line_coords;
        if (!lineCoords || lineCoords.length < 2) return;
        boundsToFit.push(lineCoords[1]);

        const spoke = L.polyline(lineCoords, {
          color: color,
          weight: r.is_cut ? 1.4 : 1.1,
          opacity: r.is_cut ? 0.75 : 0.4,
          dashArray: r.is_cut ? "3, 2" : null
        }).addTo(conicalLayerGroup);

        const tooltipMsg = r.is_cut
          ? `<span style="color:#f85149; font-weight:700;">⚠ Cut by Terrain</span> at ${r.reach_km} km`
          : `<span style="color:#3fb950; font-weight:700;">✓ Clear Line of Sight</span> to ${r.reach_km} km`;

        spoke.bindTooltip(`
          <b>${station.station_ident} &middot; Radial ${r.azimuth_deg}&deg;</b><br>
          ${tooltipMsg}<br>
          <i>Click to inspect vertical FL column</i>
        `, { sticky: true });

        spoke.on("click", (e) => {
          inspectAirspaceColumnAt(e.latlng.lat, e.latlng.lng);
        });

        // Obstacle termination dot if cut
        if (r.is_cut) {
          const cutPt = lineCoords[1];
          const cutDot = L.circleMarker(cutPt, {
            radius: 2.5,
            color: "#f85149",
            fillColor: "#f85149",
            fillOpacity: 0.9,
            weight: 1
          }).addTo(conicalLayerGroup);
          cutDot.on("click", () => {
            inspectAirspaceColumnAt(cutPt[0], cutPt[1]);
          });
        }
      });
    }

    // Individual Jagged Perimeter Outline
    if (showPerimeters && station.jagged_perimeter && station.jagged_perimeter.length > 2) {
      const jaggedPoly = L.polygon(station.jagged_perimeter, {
        color: color,
        weight: 1.8,
        fillColor: color,
        fillOpacity: mergeCoverage ? 0.08 : 0.16,
      }).addTo(conicalLayerGroup);

      jaggedPoly.bindPopup(`
        <div style="font-size:12px;">
          <b style="color:${color};">${station.station_ident} Jagged Coverage Perimeter</b><br>
          <b>Flight Level:</b> FL${Math.round(flFt / 100)} (${flFt} ft AMSL)<br>
          <b>Effective Area:</b> ${(station.metrics?.coverage_area_sq_km || 0).toLocaleString()} km&sup2;<br>
          <b>Radials Cut:</b> ${station.metrics?.cut_radials || 0} / ${station.metrics?.total_radials || 0} (${station.metrics?.cut_percentage || 0}%)
          <div style="margin-top:6px; border-top:1px solid #30363d; padding-top:4px;">
            <button class="btn btn-primary" style="font-size:11px; padding:3px 8px; width:100%; cursor:pointer; background: #1f6feb;" onclick="openCoverage3DModal('${station.station_id}')">
              🧊 3D Coverage Volume
            </button>
          </div>
        </div>
      `);
    }

    // Inner Cone of Silence Circle
    if (station.inner_cone_radius_km > 0.1) {
      L.circle(tx, {
        radius: station.inner_cone_radius_km * 1000.0,
        color: "#f85149",
        weight: 1.2,
        dashArray: "3, 3",
        fillColor: "#f85149",
        fillOpacity: 0.25
      }).addTo(conicalLayerGroup).bindTooltip(`Cone of Silence (Radius: ${station.inner_cone_radius_km} km)`);
    }
  });

  // 2. Client-Side Merged Coverage Layer (Turf.js Union)
  let mergedAreaKm2 = 0;
  if (mergeCoverage && stations.length > 0) {
    if (window.turf && stations.length > 1) {
      try {
        const polyFeatures = [];
        stations.forEach(s => {
          if (s.jagged_perimeter && s.jagged_perimeter.length > 3) {
            const ring = s.jagged_perimeter.map(pt => [pt[1], pt[0]]);
            if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) {
              ring.push(ring[0]);
            }
            polyFeatures.push(turf.polygon([ring]));
          }
        });

        if (polyFeatures.length > 1) {
          let unionResult = polyFeatures[0];
          for (let i = 1; i < polyFeatures.length; i++) {
            try {
              const u = turf.union(unionResult, polyFeatures[i]);
              if (u) unionResult = u;
            } catch (e) {
              // Ignore degenerate polygon intersections gracefully
            }
          }

          if (unionResult) {
            const mergedLayer = L.geoJSON(unionResult, {
              style: {
                color: "#38bdf8",
                weight: 2.8,
                dashArray: "5, 4",
                fillColor: "#0284c7",
                fillOpacity: 0.18
              }
            }).addTo(conicalLayerGroup);

            try {
              mergedAreaKm2 = Math.round(turf.area(unionResult) / 1000000.0);
            } catch (e) { }

            mergedLayer.bindTooltip(`
              <b>Combined / Merged Airspace Coverage</b><br>
              ${stations.length} Facilities Unified<br>
              ${mergedAreaKm2.toLocaleString()} km&sup2; Non-Overlapping Area
            `, { sticky: true });
          }
        }
      } catch (turfErr) {
        console.warn("Client-side Turf merge fallback:", turfErr);
      }
    }

    if (!mergedAreaKm2) {
      mergedAreaKm2 = Math.round(stations.reduce((acc, s) => acc + (s.metrics?.coverage_area_sq_km || 0), 0));
    }
  }

  // Fit map viewport to show the coverage of selected stations
  if (boundsToFit.length > 0 && map) {
    try {
      map.fitBounds(boundsToFit, { padding: [40, 40], maxZoom: 9 });
    } catch (e) {
      console.warn("fitBounds error:", e);
    }
  }

  // 3. Render Combined Statistics Panel
  renderCombinedCoverageStats(data, mergedAreaKm2);

  // 4. Populate Ray Elevation & Fresnel Profile Station Selector
  populateRayStationSelector(data);
}

function renderCombinedCoverageStats(data, mergedAreaKm2) {
  const container = document.getElementById("multiStationStatsContent");
  if (!container) return;

  const stations = data.stations || [];
  if (stations.length === 0) {
    container.innerHTML = `<div>No stations evaluated.</div>`;
    return;
  }

  const flFt = data.flight_level_ft || 10000.0;
  let totalSumArea = 0;
  let totalCutRadials = 0;
  let totalRadials = 0;

  stations.forEach(s => {
    totalSumArea += (s.metrics?.coverage_area_sq_km || 0);
    totalCutRadials += (s.metrics?.cut_radials || 0);
    totalRadials += (s.metrics?.total_radials || 0);
  });

  const overallCutPct = totalRadials > 0 ? ((totalCutRadials / totalRadials) * 100).toFixed(1) : 0;
  const loadTimeBadge = data.loadTimeMs ? `<span class="badge" style="font-size:9px; background:rgba(63,185,80,0.2); color:var(--accent-green);">⚡ Loaded in ${data.loadTimeMs}ms</span>` : "";

  let html = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; padding-bottom:6px; border-bottom:1px solid var(--border-color);">
      <div>
        <b>FL${Math.round(flFt / 100)}</b> (${flFt} ft AMSL) &middot; ${stations.length} Station(s)<br>
        <span style="font-size:11px; color:var(--accent-cyan); font-weight:600;">Merged Area: ~${(mergedAreaKm2 || totalSumArea).toLocaleString()} km&sup2;</span>
      </div>
      <div style="text-align:right;">
        ${loadTimeBadge}<br>
        <span style="color:${overallCutPct > 30 ? 'var(--accent-red)' : 'var(--accent-green)'}; font-weight:700; font-size:11px;">${overallCutPct}% Cut LoS</span>
      </div>
    </div>
  `;

  stations.forEach((s, idx) => {
    const color = STATION_PALETTE[idx % STATION_PALETTE.length];
    html += `
      <div class="station-stat-card">
        <div class="station-stat-header">
          <span style="color:${color}; font-weight:700;">${s.station_ident} &middot; ${s.station_name}</span>
          <span class="badge" style="font-size:9px;">${s.range_nm} NM</span>
        </div>
        <div style="font-size:11px; color:var(--text-muted); display:flex; justify-content:space-between;">
          <span>${s.category} &middot; ${s.station_type}</span>
          <span>Cone: ${s.inner_cone_radius_km} km</span>
        </div>
        <div style="font-size:11px; margin-top:3px; display:flex; justify-content:space-between;">
          <span>Coverage: <b>${(s.metrics?.coverage_area_sq_km || 0).toLocaleString()} km&sup2;</b></span>
          <span style="color:${(s.metrics?.cut_percentage || 0) > 25 ? 'var(--accent-yellow)' : 'var(--accent-green)'};">
            Cut: <b>${s.metrics?.cut_radials || 0} / ${s.metrics?.total_radials || 0} (${s.metrics?.cut_percentage || 0}%)</b>
          </span>
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

function enableMapProbe() {
  pickingMode = "conical_probe";
  alert("Click ANY location on the map to inspect its vertical airspace elevation profile in FL10 (1000 ft) increments.");
}

async function inspectAirspaceColumnAt(lat, lon, isRayTip = false) {
  const sidePanel = document.getElementById("sideElevationPanel");
  if (sidePanel) sidePanel.style.display = "flex";

  // Drop or move probe marker on map if not a silent ray tip update
  if (!isRayTip) {
    if (!probeMarker) {
      const probeIcon = L.divIcon({
        className: "custom-probe-icon",
        html: '<div style="background:#bc8cff; width:14px; height:14px; border-radius:50%; border:2px solid #fff; box-shadow:0 0 10px #bc8cff;"></div>',
        iconSize: [14, 14],
        iconAnchor: [7, 7]
      });
      probeMarker = L.marker([lat, lon], { icon: probeIcon }).addTo(map);
    } else {
      probeMarker.setLatLng([lat, lon]);
    }
  }

  const probeLoc = document.getElementById("sideProbeLocation");
  const staCount = selectedFacilityIds.size;
  if (probeLoc) {
    probeLoc.innerHTML = `Loading vertical column at <b>${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E</b> (${staCount > 0 ? staCount + ' stations' : 'Standard'})...`;
  }

  const freqHz = getSelectedFrequencyHz();
  const payload = {
    lat: lat,
    lon: lon,
    min_alt_ft: 1000.0,
    max_alt_ft: 60000.0,
    step_ft: 1000.0,
    frequency_hz: freqHz
  };

  if (isRayTip && activeRayStationId) {
    payload.station_ids = [activeRayStationId];
  } else if (selectedFacilityIds.size > 0) {
    payload.station_ids = Array.from(selectedFacilityIds);
  } else if (currentConicalCenter) {
    payload.stations = [{
      name: currentConicalCenter.name || "Station",
      latitude: currentConicalCenter.lat,
      longitude: currentConicalCenter.lon,
      meters: currentConicalCenter.alt || 25.0,
      is_agl: true
    }];
  }

  try {
    const res = await fetch("/api/airspace/column", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const columnData = await res.json();
    currentColumnData = columnData;

    const evalCount = columnData.evaluated_stations ? columnData.evaluated_stations.length : selectedFacilityIds.size;
    if (probeLoc) {
      probeLoc.innerHTML = `
        <b>Probe:</b> ${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E &middot; <b>Stations Evaluated:</b> ${evalCount}<br>
        <b>Terrain Elevation:</b> ${columnData.ground_elevation_m}m (${Math.round(columnData.ground_elevation_ft)} ft)<br>
        <b>Coverage Floor:</b> <span style="color:var(--accent-cyan); font-weight:700;">${columnData.coverage_floor_ft ? 'FL' + Math.round(columnData.coverage_floor_ft / 100) + ' (' + columnData.coverage_floor_ft.toLocaleString() + 'ft)' : 'No Coverage (Shadow)'}</span>
      `;
    }

    const currentFlSelect = document.getElementById("conicalFlSelect");
    const activeFl = currentFlSelect ? parseFloat(currentFlSelect.value) : 10000.0;
    renderFlLadder(columnData, activeFl);

  } catch (err) {
    console.error("Column probe failed:", err);
  }
}

function renderFlLadder(columnData, selectedFlFt) {
  const ladderList = document.getElementById("flLadderList");
  if (!ladderList || !columnData || !columnData.column_samples) return;

  ladderList.innerHTML = "";
  const samples = columnData.column_samples;
  const groundM = columnData.ground_elevation_m;

  // Render from FL600 downwards to FL010 (top-down vertical profile)
  const sortedSamples = [...samples].sort((a, b) => b.alt_ft - a.alt_ft);

  sortedSamples.forEach(s => {
    const altFt = s.alt_ft;
    const flNum = Math.round(altFt / 100);
    const flLabel = flNum < 100 ? `FL0${flNum}` : `FL${flNum}`;
    const altM = Math.round(altFt * 0.3048);
    const isSelected = Math.abs(altFt - selectedFlFt) < 500;

    let statusClass = "fl-status-shadow";
    let statusLabel = "Shadow";
    let countBadge = "";
    let pillsHtml = "";

    const coveringCount = (s.covering_count !== undefined) ? s.covering_count : (s.is_covered ? 1 : 0);
    const idents = s.covering_idents || [];

    if (altM <= groundM) {
      statusClass = "fl-status-ground";
      statusLabel = "Terrain";
      countBadge = `<span class="fl-station-count-badge count-zero">Ground</span>`;
      pillsHtml = `<div style="font-size:9px; color:#8b949e;">Below Ground (${groundM}m)</div>`;
    } else if (coveringCount > 0) {
      statusClass = "fl-status-clear";
      statusLabel = s.path_loss_db ? `${s.path_loss_db} dB` : "Clear";
      const badgeCls = coveringCount > 1 ? "count-multi" : "count-single";
      countBadge = `<span class="fl-station-count-badge ${badgeCls}">✓ ${coveringCount} Station${coveringCount > 1 ? "s" : ""}</span>`;

      if (idents.length > 0) {
        pillsHtml = `<div class="fl-station-pills">` +
          idents.map(id => `<span class="fl-station-pill pill-covered">${id}</span>`).join("") +
          `</div>`;
      }
    } else if (s.in_cone_of_silence) {
      statusClass = "fl-status-cone";
      statusLabel = "Cone Null";
      countBadge = `<span class="fl-station-count-badge count-zero">Cone of Silence</span>`;
      pillsHtml = `<div style="font-size:9px; color:#d29922;">Above Antenna Max Elevation (~34&deg; Radar)</div>`;
    } else if (s.below_min_elevation) {
      statusClass = "fl-status-cone";
      statusLabel = "Below Beam";
      countBadge = `<span class="fl-station-count-badge count-zero">Below Min Elev</span>`;
      pillsHtml = `<div style="font-size:9px; color:#d29922;">Outside 30&deg;&ndash;150&deg; DME Window</div>`;
    } else {
      statusClass = "fl-status-shadow";
      statusLabel = "Blocked";
      countBadge = `<span class="fl-station-count-badge count-zero">0 Stations</span>`;
      pillsHtml = `<div style="font-size:9px; color:#ff7b72;">Terrain Shadow</div>`;
    }

    // Build hover tooltip with full station breakdown
    let tooltipLines = [`${flLabel} (${altFt.toLocaleString()} ft AMSL) - ${coveringCount} covering station(s)`];
    if (s.station_breakdown && s.station_breakdown.length > 0) {
      s.station_breakdown.forEach(st => {
        const mark = st.is_covered ? "✓" : "✗";
        tooltipLines.push(`${mark} ${st.ident} (${st.name || ""}): ${st.status} [${st.distance_km || "--"} km]`);
      });
    }

    const item = document.createElement("div");
    item.className = `fl-ladder-item ${statusClass} ${isSelected ? 'selected-fl' : ''}`;
    item.dataset.altFt = altFt;
    item.title = tooltipLines.join("\n");
    item.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:2px; flex:1;">
        <div style="display:flex; align-items:center; gap:6px;">
          <span style="font-weight:700; width:46px;">${flLabel}</span>
          <span style="font-size:10px; color:var(--text-muted); width:52px;">${altFt.toLocaleString()}ft</span>
          ${countBadge}
        </div>
        ${pillsHtml}
      </div>
      <div style="text-align:right; margin-left:8px;">
        <div style="font-weight:600; font-size:10px;">${statusLabel}</div>
      </div>
    `;

    item.onclick = () => {
      selectLadderFl(altFt);
    };

    ladderList.appendChild(item);
  });
}

function selectLadderFl(flFt) {
  const flSelect = document.getElementById("conicalFlSelect");
  if (flSelect) {
    let options = Array.from(flSelect.options).map(o => parseFloat(o.value));
    let closest = options.reduce((prev, curr) => Math.abs(curr - flFt) < Math.abs(prev - flFt) ? curr : prev);
    flSelect.value = closest;
  }
  highlightLadderFL(flFt);
  runMultiStationCoverage();
}

function highlightLadderFL(flFt) {
  document.querySelectorAll(".fl-ladder-item").forEach(item => {
    const itemFt = parseFloat(item.dataset.altFt);
    if (Math.abs(itemFt - flFt) < 500) {
      item.classList.add("selected-fl");
    } else {
      item.classList.remove("selected-fl");
    }
  });
}

function closeSidePanel() {
  const sidePanel = document.getElementById("sideElevationPanel");
  if (sidePanel) sidePanel.style.display = "none";
  if (probeMarker) {
    map.removeLayer(probeMarker);
    probeMarker = null;
  }
  if (map) {
    setTimeout(() => { map.invalidateSize(); }, 100);
  }
}

// ==========================================================================
// Ray Elevation & Fresnel Profile Sweep & Rotation System
// ==========================================================================

function populateRayStationSelector(data) {
  const select = document.getElementById("rayStationSelect");
  if (!select) return;
  rayProfileCache = {};
  rayColumnCache = {};
  const stations = data?.stations || [];
  if (stations.length === 0) {
    select.innerHTML = '<option value="">-- No active stations --</option>';
    stopRayRotation();
    return;
  }

  const optionsHtml = stations.map((st, idx) => {
    const ident = st.station_ident || st.station_id || `STA_${idx}`;
    const name = st.station_name || ident;
    const type = st.station_type || st.category || "FACILITY";
    const radCount = st.radial_lines ? st.radial_lines.length : 72;
    return `<option value="${st.station_id}">[${ident}] ${name} (${type} &middot; ${radCount} rays)</option>`;
  }).join("");
  select.innerHTML = optionsHtml;

  const exists = stations.some(s => s.station_id === activeRayStationId);
  if (!exists) {
    activeRayStationId = stations[0].station_id;
  }
  select.value = activeRayStationId;
  onRayStationSelect(activeRayStationId);
}

function onRayStationSelect(stationId) {
  activeRayStationId = stationId;
  const station = (lastCoverageData?.stations || []).find(s => s.station_id === stationId);
  const slider = document.getElementById("rayAzimuthSlider");
  if (!station || !station.radial_lines || station.radial_lines.length === 0) {
    if (slider) { slider.max = 0; slider.value = 0; }
    return;
  }

  // Ensure side elevation panel is visible for vertical profile ladder
  const sidePanel = document.getElementById("sideElevationPanel");
  if (sidePanel) sidePanel.style.display = "flex";
  if (map) setTimeout(() => map.invalidateSize(), 50);

  const radials = station.radial_lines;
  if (slider) {
    slider.max = radials.length - 1;
    slider.value = 0;
  }
  currentRayIndex = 0;
  inspectRayByIndex(0);
}

function onRaySliderInput(val) {
  currentRayIndex = parseInt(val, 10);
  inspectRayByIndex(currentRayIndex);
}

function stepRay(delta) {
  const station = (lastCoverageData?.stations || []).find(s => s.station_id === activeRayStationId);
  if (!station || !station.radial_lines || station.radial_lines.length === 0) return;
  const radials = station.radial_lines;
  currentRayIndex = (currentRayIndex + delta + radials.length) % radials.length;
  const slider = document.getElementById("rayAzimuthSlider");
  if (slider) slider.value = currentRayIndex;
  inspectRayByIndex(currentRayIndex);
}

function toggleRayRotation() {
  if (rayRotationTimer) {
    stopRayRotation();
  } else {
    startRayRotation();
  }
}

function startRayRotation() {
  const speedEl = document.getElementById("rayRotationSpeed");
  const speedMs = speedEl ? parseInt(speedEl.value, 10) : 350;
  const icon = document.getElementById("playIcon");
  const text = document.getElementById("playText");
  const btn = document.getElementById("btnPlayRays");
  if (icon) icon.textContent = "⏸";
  if (text) text.textContent = "Pause Sweep";
  if (btn) btn.style.background = "#d29922";

  // Ensure side panel is visible when sweep starts
  const sidePanel = document.getElementById("sideElevationPanel");
  if (sidePanel) sidePanel.style.display = "flex";
  if (map) setTimeout(() => map.invalidateSize(), 50);

  rayRotationTimer = setInterval(() => {
    stepRay(1);
  }, speedMs);
}

function stopRayRotation() {
  if (rayRotationTimer) {
    clearInterval(rayRotationTimer);
    rayRotationTimer = null;
  }
  const icon = document.getElementById("playIcon");
  const text = document.getElementById("playText");
  const btn = document.getElementById("btnPlayRays");
  if (icon) icon.textContent = "▶";
  if (text) text.textContent = "Play Rotation Sweep";
  if (btn) btn.style.background = "";
}

function synthesizeColumnFromProfile(profData, station, selectedFlFt) {
  if (!profData || !profData.profile) return null;
  const rxGroundM = (profData.rx && profData.rx.ground_elev_m !== undefined) ? profData.rx.ground_elev_m : 0;
  const txAmslM = (profData.tx && profData.tx.amsl_m !== undefined) ? profData.tx.amsl_m : (station.tx_amsl_m || 25);
  const distM = profData.total_distance_m || 1000;
  const distKm = distM / 1000.0;
  const cDistances = profData.profile.distances_m || [];
  const cCurvedTerrain = profData.profile.curved_terrain_m || [];
  const numPts = cDistances.length;

  const minElevDeg = (station.elevation_limits && station.elevation_limits[0] !== undefined)
    ? station.elevation_limits[0]
    : (station.elevation_min_deg !== undefined ? station.elevation_min_deg : 0.5);
  const maxElevDeg = (station.elevation_limits && station.elevation_limits[1] !== undefined)
    ? station.elevation_limits[1]
    : (station.elevation_max_deg !== undefined ? station.elevation_max_deg : (station.category === "RADAR" ? 34.0 : 60.0));
  const maxRangeKm = station.range_km || (station.range_nm ? station.range_nm * 1.852 : 370.4);

  const rawIdent = station.station_ident || station.ident || "STA";
  const ident = rawIdent.slice(0, 3).toUpperCase();
  const name = station.station_name || station.name || ident;

  const freqHz = getSelectedFrequencyHz();
  const wavelength = 3e8 / freqHz;

  const samples = [];
  let coverageFloorFt = null;

  for (let altFt = 1000; altFt <= 60000; altFt += 1000) {
    const altM = altFt * 0.3048;
    const deltaH = altM - txAmslM;
    const elevAngleDeg = (Math.atan2(deltaH, distM) * 180.0) / Math.PI;

    const inCone = elevAngleDeg > maxElevDeg;
    const belowMin = elevAngleDeg < minElevDeg;
    const exceedsRange = distKm > maxRangeKm;

    let isOptBlocked = false;
    let isDiffracted = false;

    if (altM <= rxGroundM) {
      isOptBlocked = true;
    } else if (!inCone && !belowMin && !exceedsRange && numPts > 0) {
      for (let i = 0; i < numPts; i++) {
        const s = cDistances[i];
        if (s <= 0 || s >= distM) continue;
        const rayH = txAmslM + (s / distM) * deltaH;
        const curvedH = cCurvedTerrain[i];
        const clearance = rayH - curvedH;

        if (clearance < 0) {
          isOptBlocked = true;
          break;
        }

        const d1 = s;
        const d2 = distM - s;
        const f1 = Math.sqrt((wavelength * d1 * d2) / distM);
        if (clearance < 0.6 * f1) {
          isDiffracted = true;
        }
      }
    }

    const isCovered = (!isOptBlocked && !isDiffracted && !inCone && !belowMin && !exceedsRange);

    if (isCovered && coverageFloorFt === null) {
      coverageFloorFt = altFt;
    }

    let status = "CLEAR";
    if (altM <= rxGroundM) status = "TERRAIN";
    else if (inCone) status = "CONE_OF_SILENCE";
    else if (belowMin) status = "BELOW_BEAM_MIN";
    else if (exceedsRange) status = "OUT_OF_RANGE";
    else if (isOptBlocked) status = "TERRAIN_BLOCKED";
    else if (isDiffracted) status = "DIFFRACTED";

    const fsplDb = isCovered ? Math.round(20 * Math.log10(distKm) + 20 * Math.log10(freqHz / 1e6) + 32.44) : null;

    samples.push({
      alt_ft: altFt,
      is_covered: isCovered,
      covering_count: isCovered ? 1 : 0,
      covering_idents: isCovered ? [ident] : [],
      covering_names: isCovered ? [`${ident} (${station.station_type || station.category || 'STA'})`] : [],
      in_cone_of_silence: inCone,
      below_min_elevation: belowMin,
      distance_km: Math.round(distKm * 10) / 10,
      elevation_angle_deg: Math.round(elevAngleDeg * 10) / 10,
      path_loss_db: fsplDb,
      status: status,
      detailed_status: status,
      station_breakdown: [{
        ident: ident,
        name: name,
        is_covered: isCovered,
        status: status,
        distance_km: Math.round(distKm * 10) / 10,
        path_loss_db: fsplDb
      }]
    });
  }

  return {
    ground_elevation_m: Math.round(rxGroundM * 10) / 10,
    ground_elevation_ft: Math.round(rxGroundM * 3.28084),
    coverage_floor_ft: coverageFloorFt,
    column_samples: samples
  };
}

async function inspectRayByIndex(rayIndex) {
  const station = (lastCoverageData?.stations || []).find(s => s.station_id === activeRayStationId);
  if (!station || !station.radial_lines || station.radial_lines.length === 0) return;

  const radials = station.radial_lines;
  if (rayIndex < 0 || rayIndex >= radials.length) return;
  const r = radials[rayIndex];

  // Ensure side elevation panel is visible for vertical profile ladder
  const sidePanel = document.getElementById("sideElevationPanel");
  if (sidePanel && sidePanel.style.display !== "flex") {
    sidePanel.style.display = "flex";
    if (map) setTimeout(() => map.invalidateSize(), 50);
  }

  // 1. Update text & badges
  const angleDisplay = document.getElementById("rayAngleDisplay");
  if (angleDisplay) {
    angleDisplay.textContent = `${r.azimuth_deg.toFixed(1)}° (Ray ${rayIndex + 1} / ${radials.length})`;
  }
  const azimuthBadge = document.getElementById("rayAzimuthBadge");
  if (azimuthBadge) {
    azimuthBadge.textContent = `Az: ${r.azimuth_deg.toFixed(1)}°`;
  }

  const summary = document.getElementById("activeRaySummary");
  if (summary) {
    summary.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:3px;">
        <b style="color:#fff;">[${station.station_ident || "STA"}] ${station.station_name || "Station"}</b>
        <span style="color:var(--accent-cyan); font-weight:700;">${r.azimuth_deg}&deg; True</span>
      </div>
      <div style="font-size:11px; color:var(--text-muted);">
        <b>Reach:</b> ${r.reach_km} km (${Math.round(r.reach_km / 1.852)} NM) &middot;
        <b>Line Status:</b> ${r.is_cut ? '<span style="color:var(--accent-red); font-weight:700;">⚠ Cut by Mountain Peak</span>' : '<span style="color:var(--accent-green); font-weight:700;">✓ Clear Horizon LoS</span>'}
      </div>
    `;
  }

  // 2. Highlight Ray on Map
  if (activeRayLayer) {
    map.removeLayer(activeRayLayer);
    activeRayLayer = null;
  }

  const coords = r.line_coords;
  if (coords && coords.length >= 2) {
    activeRayLayer = L.layerGroup().addTo(map);

    // Glowing halo line
    L.polyline(coords, {
      color: "#f0883e",
      weight: 6,
      opacity: 0.5,
    }).addTo(activeRayLayer);

    // Sharp bright core line
    L.polyline(coords, {
      color: "#ffffff",
      weight: 2.2,
      opacity: 1.0,
      dashArray: r.is_cut ? "6, 3" : null
    }).addTo(activeRayLayer);

    // Ray Tip / Termination Target Marker
    const tipMarker = L.circleMarker(coords[1], {
      radius: 6,
      color: "#ffd700",
      fillColor: r.is_cut ? "#f85149" : "#3fb950",
      fillOpacity: 1.0,
      weight: 2.5
    }).addTo(activeRayLayer);

    tipMarker.bindTooltip(`
      <b>${station.station_ident} &middot; Azimuth ${r.azimuth_deg}&deg;</b><br>
      Reach: ${r.reach_km} km &middot; ${r.is_cut ? "Terrain Cut" : "Clear"}
    `, { permanent: false, sticky: true });
  }

  // 3. Update Elevation & Fresnel Profile (bottom) AND Vertical Profile (side ladder) synchronously
  const flFt = lastCoverageData?.flight_level_ft || 10000.0;
  const cacheKey = `${station.station_id}_${flFt}_${rayIndex}`;

  function applyProfileAndColumn(profData) {
    currentProfileData = profData;
    updateProfileStatsCards(profData);
    drawProfileChart();

    // Update Vertical 1000-ft Column Ladder immediately!
    const colData = synthesizeColumnFromProfile(profData, station, flFt);
    if (colData) {
      currentColumnData = colData;
      const probeLoc = document.getElementById("sideProbeLocation");
      if (probeLoc) {
        probeLoc.innerHTML = `
          <b>Ray Sweep:</b> ${r.azimuth_deg.toFixed(1)}° True &middot; <b>Station:</b> ${station.station_ident || "STA"}<br>
          <b>Terrain Elevation:</b> ${colData.ground_elevation_m}m (${colData.ground_elevation_ft} ft)<br>
          <b>Coverage Floor:</b> <span style="color:var(--accent-cyan); font-weight:700;">${colData.coverage_floor_ft ? 'FL' + Math.round(colData.coverage_floor_ft / 100) + ' (' + colData.coverage_floor_ft.toLocaleString() + 'ft)' : 'No Coverage (Shadow)'}</span>
        `;
      }
      renderFlLadder(colData, flFt);
    }
  }

  if (rayProfileCache[cacheKey]) {
    applyProfileAndColumn(rayProfileCache[cacheKey]);
  } else {
    try {
      const payload = {
        tx_lon: station.tx_coords[1],
        tx_lat: station.tx_coords[0],
        tx_alt_m: station.tx_amsl_m || 25.0,
        rx_lon: coords[1][1],
        rx_lat: coords[1][0],
        rx_alt_m: flFt * 0.3048,
        frequency_hz: getSelectedFrequencyHz(),
        num_points: 100,
        tx_is_agl: false,
        rx_is_agl: false
      };
      const res = await fetch("/api/los/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const profData = await res.json();
        rayProfileCache[cacheKey] = profData;
        applyProfileAndColumn(profData);
      }
    } catch (e) {
      console.warn("Ray profile evaluate error:", e);
    }
  }
}

function updateProfileStatsCards(data) {
  if (!data) return;
  const statusBadge = document.getElementById("profileStatusBadge");
  if (statusBadge) {
    statusBadge.className = `status-badge status-${(data.status || "clear").toLowerCase()}`;
    statusBadge.textContent = `${data.status || "CLEAR"} LOS`;
  }
  const statDist = document.getElementById("statDistance");
  if (statDist) statDist.textContent = `${data.total_distance_km || (data.total_distance_m / 1000).toFixed(1)} km`;
  const statClear = document.getElementById("statClearance");
  if (statClear) statClear.textContent = `${data.min_fresnel_clearance_m ?? "--"} m`;
  const statElev = document.getElementById("statElevationAngle");
  if (statElev) statElev.textContent = `${data.elevation_angle_deg ?? "--"}°`;
  const statCurv = document.getElementById("statCurvature");
  if (statCurv) statCurv.textContent = `${data.curvature_bulge_m ?? "--"} m (k=4/3)`;
  const statPath = document.getElementById("statPathLoss");
  if (statPath) statPath.textContent = `${data.total_path_loss_db ?? data.free_space_path_loss_db ?? "--"} dB`;
  const statObst = document.getElementById("statObstacle");
  if (statObst) statObst.textContent = data.obstacle ? `${data.obstacle.curved_terrain_m}m @ ${(data.obstacle.distance_m / 1000).toFixed(1)}km` : "None";
}

/* ==========================================================================
   Dataset Builder & CLI Template Exporter
   ========================================================================== */

function populateBuilderEcacSelect() {
  const sel = document.getElementById("builderEcacSelect");
  if (!sel || !allFacilities || allFacilities.length === 0) return;

  const sorted = [...allFacilities].sort((a, b) => (a.ident || a.name).localeCompare(b.ident || b.name));
  let html = `<option value="">-- Choose ECAC VOR/DME or Radar to add (${sorted.length} available) --</option>`;
  sorted.forEach(f => {
    const cat = f.category === "RADAR" ? "RADAR" : "VOR/DME";
    html += `<option value="${f.id}">[${cat}] ${f.ident} - ${f.name} (${f.country || 'EU'}, ${f.type}, ${f.range_nm}NM)</option>`;
  });
  sel.innerHTML = html;
}

function onBuilderCategoryChange() {
  const cat = document.querySelector('input[name="builderCategory"]:checked')?.value || "RADAR";
  const radFields = document.getElementById("builderRadarFields");
  const navFields = document.getElementById("builderNavaidFields");
  if (cat === "RADAR") {
    if (radFields) radFields.style.display = "block";
    if (navFields) navFields.style.display = "none";
  } else {
    if (radFields) radFields.style.display = "none";
    if (navFields) navFields.style.display = "block";
  }
}

function onBuilderNavaidTypeChange() {
  const type = document.getElementById("builderNavaidType")?.value || "VOR-DME";
  const catSelect = document.getElementById("builderServiceCat");
  const minEl = document.getElementById("builderNavaidMinElev");
  const maxEl = document.getElementById("builderNavaidMaxElev");

  if (type.includes("DME")) {
    if (minEl) minEl.value = "30.0";
    if (maxEl) maxEl.value = "150.0";
  } else {
    if (minEl) minEl.value = "0.5";
    if (maxEl) maxEl.value = "60.0";
  }

  if (type === "DME" || type.includes("TMA")) {
    if (catSelect) catSelect.value = "TMA";
    onBuilderServiceCatChange();
  }
}

function onBuilderServiceCatChange() {
  const sCat = document.getElementById("builderServiceCat")?.value || "ENROUTE";
  const pwr = document.getElementById("builderPower");
  const rng = document.getElementById("builderNavaidRange");
  if (sCat === "TMA") {
    if (pwr) pwr.value = "LOW";
    if (rng) rng.value = 40;
  } else {
    if (pwr) pwr.value = "HIGH";
    if (rng) rng.value = 130;
  }
}

function enableBuilderMapPick() {
  const btn = document.getElementById("btnPickBuilderMap");
  if (pickingMode === "builder") {
    pickingMode = null;
    if (btn) {
      btn.textContent = "Click on Map";
      btn.classList.remove("active");
    }
    map.getContainer().style.cursor = "";
  } else {
    pickingMode = "builder";
    if (btn) {
      btn.textContent = "Click map point... (Cancel)";
      btn.classList.add("active");
    }
    map.getContainer().style.cursor = "crosshair";
  }
}

function addCustomSiteToBuilder() {
  const cat = document.querySelector('input[name="builderCategory"]:checked')?.value || "RADAR";
  const ident = (document.getElementById("builderIdent")?.value || "").trim().toUpperCase();
  const name = (document.getElementById("builderName")?.value || "").trim() || `${ident} Station`;
  const country = (document.getElementById("builderCountry")?.value || "EU").trim().toUpperCase().slice(0, 2);
  const lat = parseFloat(document.getElementById("builderLat")?.value);
  const lon = parseFloat(document.getElementById("builderLon")?.value);

  if (!ident) {
    alert("Please enter a facility Ident / Code (e.g. RAD_01 or GVA).");
    return;
  }
  if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    alert("Please enter valid latitude (-90 to 90) and longitude (-180 to 180).");
    return;
  }

  // Check for duplicates
  if (stagedDataset.some(s => s.ident.toUpperCase() === ident)) {
    if (!confirm(`A station with ident '${ident}' already exists in your staged dataset. Add another?`)) {
      return;
    }
  }

  let site = null;
  if (cat === "RADAR") {
    const rType = document.getElementById("builderRadarType")?.value || "MODE-S";
    const mastH = parseFloat(document.getElementById("builderMastHeight")?.value) || 25.0;
    const rng = parseFloat(document.getElementById("builderRadarRange")?.value) || 200.0;
    const modeS = document.getElementById("builderModeS")?.value === "true";
    const minEl = parseFloat(document.getElementById("builderRadarMinElev")?.value) || 0.5;
    const maxEl = parseFloat(document.getElementById("builderRadarMaxElev")?.value) || 34.0;
    const azS = parseFloat(document.getElementById("builderRadarAzStart")?.value) || 0.0;
    const azE = parseFloat(document.getElementById("builderRadarAzEnd")?.value) || 360.0;

    site = {
      id: `custom_rad_${ident}_${Date.now()}`,
      ident: ident,
      name: name,
      category: "RADAR",
      type: rType,
      country: country,
      latitude: lat,
      longitude: lon,
      mast_height_m: mastH,
      range_nm: rng,
      range_km: Math.round(rng * 1.852 * 10) / 10,
      mode_s: modeS,
      azimuth_start_deg: azS,
      azimuth_end_deg: azE,
      elevation_min_deg: minEl,
      elevation_max_deg: maxEl
    };
  } else {
    // NAVAID
    const nType = document.getElementById("builderNavaidType")?.value || "VOR-DME";
    const sCat = document.getElementById("builderServiceCat")?.value || "ENROUTE";
    const pwr = document.getElementById("builderPower")?.value || (sCat === "TMA" ? "LOW" : "HIGH");
    const rng = parseFloat(document.getElementById("builderNavaidRange")?.value) || (sCat === "TMA" ? 40.0 : 130.0);
    const elevFt = parseInt(document.getElementById("builderSiteElevFt")?.value) || 1000;
    const freqKhz = parseInt(document.getElementById("builderFreqKhz")?.value) || 115000;
    const dmeCh = (document.getElementById("builderDmeChan")?.value || "95X").trim().toUpperCase();
    const isDme = nType.includes("DME");
    const minEl = parseFloat(document.getElementById("builderNavaidMinElev")?.value) || (isDme ? 30.0 : 0.5);
    const maxEl = parseFloat(document.getElementById("builderNavaidMaxElev")?.value) || (isDme ? 150.0 : 60.0);

    site = {
      id: `custom_nav_${ident}_${Date.now()}`,
      ident: ident,
      name: name,
      category: "NAVAID",
      type: nType,
      service_category: sCat,
      power: pwr,
      country: country,
      latitude: lat,
      longitude: lon,
      elevation_ft: elevFt,
      ground_elev_m: Math.round(elevFt * 0.3048),
      range_nm: rng,
      range_km: Math.round(rng * 1.852 * 10) / 10,
      frequency_khz: freqKhz,
      dme_channel: dmeCh,
      elevation_min_deg: minEl,
      elevation_max_deg: maxEl
    };
  }

  stagedDataset.push(site);
  updateDatasetBuilderUI();

  // Reset ident for convenience
  const nextNum = stagedDataset.length + 1;
  const identInput = document.getElementById("builderIdent");
  if (identInput) identInput.value = cat === "RADAR" ? `RAD_${nextNum < 10 ? '0' : ''}${nextNum}` : `NAV_${nextNum < 10 ? '0' : ''}${nextNum}`;
}

function addEcacStationToBuilder() {
  const sel = document.getElementById("builderEcacSelect");
  if (!sel || !sel.value) {
    alert("Please choose an ECAC station from the dropdown.");
    return;
  }
  addFacilityToDatasetBuilder(sel.value);
}

function addFacilityToDatasetBuilder(stationId) {
  let fac = allFacilities.find(f => f.id === stationId);
  if (!fac && conicalData && conicalData.stations) {
    const cSt = conicalData.stations.find(s => s.station_id === stationId);
    if (cSt) {
      fac = {
        id: cSt.station_id,
        ident: cSt.station_ident,
        name: cSt.station_name,
        category: cSt.category,
        type: cSt.station_type,
        service_category: cSt.service_category,
        country: cSt.country,
        country_name: cSt.country_name,
        latitude: cSt.tx_coords[0],
        longitude: cSt.tx_coords[1],
        range_nm: cSt.range_nm,
        range_km: cSt.range_km,
        mast_height_m: 25.0,
        ground_elev_m: cSt.ground_elev_m,
        dem_elev_m: cSt.ground_elev_m
      };
    }
  }

  if (!fac) {
    alert(`Facility ${stationId} details not found.`);
    return;
  }

  const ident = (fac.ident || fac.name.slice(0, 5)).toUpperCase();
  if (stagedDataset.some(s => (s.id && s.id === fac.id) || s.ident === ident)) {
    alert(`Station ${ident} is already in the staged dataset.`);
    return;
  }

  const isRadar = (fac.category === "RADAR" || (fac.type && fac.type.includes("RADAR")));
  const site = {
    id: fac.id || `staged_${Date.now()}`,
    ident: ident,
    name: fac.name || "Station",
    category: isRadar ? "RADAR" : "NAVAID",
    type: fac.type || (isRadar ? "MODE-S" : "VOR-DME"),
    service_category: fac.service_category || (fac.type && fac.type.includes("TMA") ? "TMA" : "ENROUTE"),
    power: fac.power || (fac.service_category === "TMA" ? "LOW" : "HIGH"),
    country: (fac.country || "EU").toUpperCase().slice(0, 2),
    latitude: Number(fac.latitude || 0),
    longitude: Number(fac.longitude || 0),
    mast_height_m: fac.mast_height_m || 25.0,
    ground_elev_m: fac.ground_elev_m || fac.dem_elev_m || 0.0,
    elevation_ft: fac.elevation_ft || Math.round((fac.ground_elev_m || fac.dem_elev_m || 0.0) * 3.28084),
    range_nm: fac.range_nm || (isRadar ? 200.0 : 130.0),
    range_km: fac.range_km || (isRadar ? 370.4 : 240.8),
    mode_s: fac.mode_s !== undefined ? fac.mode_s : true,
    frequency_khz: fac.frequency_khz || 115000,
    dme_channel: fac.dme_channel || "95X",
    azimuth_start_deg: fac.azimuth_limits ? fac.azimuth_limits[0] : 0.0,
    azimuth_end_deg: fac.azimuth_limits ? fac.azimuth_limits[1] : 360.0,
    elevation_min_deg: fac.elevation_limits ? fac.elevation_limits[0] : (isRadar ? 0.5 : ((fac.type && fac.type.includes("DME")) ? 30.0 : 0.5)),
    elevation_max_deg: fac.elevation_limits ? fac.elevation_limits[1] : (isRadar ? 34.0 : ((fac.type && fac.type.includes("DME")) ? 150.0 : 60.0))
  };

  stagedDataset.push(site);
  updateDatasetBuilderUI();

  // Subtle alert / feedback
  const toast = document.createElement("div");
  toast.style.cssText = "position:fixed; bottom:20px; right:20px; background:#1f6feb; color:#fff; padding:10px 16px; border-radius:6px; font-size:12px; font-weight:600; z-index:9999; box-shadow:0 4px 12px rgba(0,0,0,0.4);";
  toast.textContent = `✓ Staged ${site.ident} (${site.name}) — Total ${stagedDataset.length} site(s)`;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2500);
}

function importCheckedCoverageStationsToBuilder() {
  if (selectedFacilityIds.size === 0) {
    alert("No facilities are currently checked in the Conical Coverage view.");
    return;
  }

  let addedCount = 0;
  selectedFacilityIds.forEach(id => {
    const fac = allFacilities.find(f => f.id === id);
    if (!fac) return;
    const ident = (fac.ident || fac.name.slice(0, 5)).toUpperCase();
    if (stagedDataset.some(s => s.id === fac.id || s.ident === ident)) return;

    const isRadar = (fac.category === "RADAR" || (fac.type && fac.type.includes("RADAR")));
    const site = {
      id: fac.id,
      ident: ident,
      name: fac.name || "Station",
      category: isRadar ? "RADAR" : "NAVAID",
      type: fac.type || (isRadar ? "MODE-S" : "VOR-DME"),
      service_category: fac.service_category || (fac.type && fac.type.includes("TMA") ? "TMA" : "ENROUTE"),
      power: fac.power || (fac.service_category === "TMA" ? "LOW" : "HIGH"),
      country: (fac.country || "EU").toUpperCase().slice(0, 2),
      latitude: Number(fac.latitude || 0),
      longitude: Number(fac.longitude || 0),
      mast_height_m: fac.mast_height_m || 25.0,
      ground_elev_m: fac.ground_elev_m || fac.dem_elev_m || 0.0,
      elevation_ft: fac.elevation_ft || Math.round((fac.ground_elev_m || fac.dem_elev_m || 0.0) * 3.28084),
      range_nm: fac.range_nm || (isRadar ? 200.0 : 130.0),
      range_km: fac.range_km || (isRadar ? 370.4 : 240.8),
      mode_s: fac.mode_s !== undefined ? fac.mode_s : true,
      frequency_khz: fac.frequency_khz || 115000,
      dme_channel: fac.dme_channel || "95X",
      azimuth_start_deg: fac.azimuth_limits ? fac.azimuth_limits[0] : 0.0,
      azimuth_end_deg: fac.azimuth_limits ? fac.azimuth_limits[1] : 360.0,
      elevation_min_deg: fac.elevation_limits ? fac.elevation_limits[0] : (isRadar ? 0.5 : ((fac.type && fac.type.includes("DME")) ? 30.0 : 0.5)),
      elevation_max_deg: fac.elevation_limits ? fac.elevation_limits[1] : (isRadar ? 34.0 : ((fac.type && fac.type.includes("DME")) ? 150.0 : 60.0))
    };
    stagedDataset.push(site);
    addedCount++;
  });

  updateDatasetBuilderUI();
  alert(`Imported ${addedCount} checked station(s) into the Dataset Builder (Total: ${stagedDataset.length}).`);
}

function removeStagedSite(index) {
  if (index >= 0 && index < stagedDataset.length) {
    stagedDataset.splice(index, 1);
    updateDatasetBuilderUI();
  }
}

function clearStagedDataset() {
  if (stagedDataset.length === 0) return;
  if (confirm(`Remove all ${stagedDataset.length} staged sites from your dataset?`)) {
    stagedDataset = [];
    updateDatasetBuilderUI();
  }
}

function updateDatasetBuilderUI() {
  const radarCount = stagedDataset.filter(s => s.category === "RADAR").length;
  const navaidCount = stagedDataset.filter(s => s.category === "NAVAID").length;
  const totalCount = stagedDataset.length;

  const rCountEl = document.getElementById("builderRadarCount");
  if (rCountEl) rCountEl.textContent = radarCount;
  const nCountEl = document.getElementById("builderNavaidCount");
  if (nCountEl) nCountEl.textContent = navaidCount;
  const tCountEl = document.getElementById("builderTotalCount");
  if (tCountEl) tCountEl.textContent = totalCount;
  const totalBadge = document.getElementById("stagedTotalBadge");
  if (totalBadge) totalBadge.textContent = `${totalCount} Staged`;
  const listCount = document.getElementById("stagedListCount");
  if (listCount) listCount.textContent = totalCount;

  // Coverage Tab Stage Buttons
  const bCoverageCount = document.getElementById("btnStageCoverageCount");
  if (bCoverageCount) bCoverageCount.textContent = selectedFacilityIds.size;
  const impCoverageCount = document.getElementById("importCheckedCount");
  if (impCoverageCount) impCoverageCount.textContent = selectedFacilityIds.size;

  // Download buttons state
  const btnRad = document.getElementById("btnDownloadRadars");
  if (btnRad) {
    btnRad.disabled = radarCount === 0;
    btnRad.title = radarCount === 0 ? "No radars in dataset" : `Download ${radarCount} radars as CSV`;
  }
  const btnNav = document.getElementById("btnDownloadNavaids");
  if (btnNav) {
    btnNav.disabled = navaidCount === 0;
    btnNav.title = navaidCount === 0 ? "No VOR/DME in dataset" : `Download ${navaidCount} VOR/DME as CSV`;
  }

  // Render Table List
  const container = document.getElementById("stagedTableContainer");
  if (container) {
    if (totalCount === 0) {
      container.innerHTML = `
        <div style="color:var(--text-muted); font-size:11px; text-align:center; padding:12px;">
          No sites staged yet. Click on the map, select existing stations, or click "➕ Add to Dataset Builder" in any station popup.
        </div>
      `;
    } else {
      let html = "";
      stagedDataset.forEach((s, idx) => {
        const isRadar = s.category === "RADAR";
        const badgeClass = isRadar ? "staged-badge-radar" : "staged-badge-navaid";
        const metaDetail = isRadar
          ? `Mast: ${s.mast_height_m || 25}m AGL &middot; Range: ${s.range_nm}NM &middot; ${s.type} ${s.mode_s ? "(Mode S)" : ""}`
          : `Elev: ${s.elevation_ft || 0}ft &middot; Range: ${s.range_nm}NM &middot; ${s.type} (${s.service_category || "ENROUTE"}) &middot; ${s.frequency_khz ? (s.frequency_khz / 1000).toFixed(2) + "MHz" : ""}`;

        html += `
          <div class="staged-item-card">
            <div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span class="${badgeClass}">${isRadar ? "RADAR" : "VOR/DME"}</span>
                <span style="font-weight:700; color:#fff; font-size:12px;">${s.ident}</span>
                <span style="color:var(--text-bright); font-size:12px;">${s.name}</span>
                <span style="color:var(--text-muted); font-size:10px;">(${s.country || "EU"})</span>
              </div>
              <div class="staged-item-meta">
                ${s.latitude.toFixed(4)}&deg;N, ${s.longitude.toFixed(4)}&deg;E &middot; ${metaDetail}
              </div>
            </div>
            <button class="btn-icon-delete" onclick="removeStagedSite(${idx})" title="Remove ${s.ident} from dataset">&times;</button>
          </div>
        `;
      });
      container.innerHTML = html;
    }
  }

  // Update CLI command preview
  const cliBox = document.getElementById("cliCommandBox");
  if (cliBox) {
    let cmd = "# 1. Download your template files above\n# 2. Ingest into geodatabase (enriches with 25m EU-DEM & precalculates FL600 horizon):\n";
    if (radarCount > 0) {
      cmd += "python scripts/ingest_custom_data.py --file templates/radars_custom.csv --type RADAR\n";
    }
    if (navaidCount > 0) {
      cmd += "python scripts/ingest_custom_data.py --file templates/navaids_custom.csv --type NAVAID\n";
    }
    if (radarCount === 0 && navaidCount === 0) {
      cmd += "python scripts/ingest_custom_data.py --file templates/radars_template.csv --type RADAR\n";
      cmd += "python scripts/ingest_custom_data.py --file templates/navaids_template.csv --type NAVAID\n";
    }
    cliBox.textContent = cmd.trim();
  }

  // Render Map Markers
  renderDatasetBuilderMarkers();
}

function renderDatasetBuilderMarkers() {
  if (!datasetBuilderLayerGroup) return;
  datasetBuilderLayerGroup.clearLayers();

  if (stagedDataset.length === 0) return;

  const bounds = [];
  stagedDataset.forEach((s, idx) => {
    const isRadar = s.category === "RADAR";
    const color = isRadar ? "#d29922" : "#1f6feb";
    const iconSymbol = isRadar ? "🎯" : "📡";

    const customIcon = L.divIcon({
      className: "custom-builder-marker",
      html: `
        <div class="builder-marker-pin" style="background:${color};" title="${s.ident} (${s.name})">
          ${iconSymbol}
        </div>
      `,
      iconSize: [26, 26],
      iconAnchor: [13, 13]
    });

    const marker = L.marker([s.latitude, s.longitude], { icon: customIcon }).addTo(datasetBuilderLayerGroup);
    bounds.push([s.latitude, s.longitude]);

    marker.bindPopup(`
      <div style="font-size:12px;">
        <b style="color:${color}; font-size:13px;">[${s.category}] ${s.ident} &middot; ${s.name}</b><br>
        <b>Country:</b> ${s.country || "EU"}<br>
        <b>Type:</b> ${s.type}<br>
        <b>Coordinates:</b> ${s.latitude.toFixed(4)}&deg;N, ${s.longitude.toFixed(4)}&deg;E<br>
        <b>Range:</b> ${s.range_nm} NM (${s.range_km || Math.round(s.range_nm * 1.852)} km)<br>
        <b>${isRadar ? "Mast Height" : "Elevation"}:</b> ${isRadar ? (s.mast_height_m || 25) + "m AGL" : (s.elevation_ft || 0) + "ft AMSL"}<br>
        <div style="margin-top:8px; border-top:1px solid #30363d; padding-top:6px;">
          <button class="btn btn-secondary" style="font-size:11px; padding:3px 8px; width:100%; color:var(--accent-red);" onclick="removeStagedSite(${idx})">
            ✕ Remove from Dataset
          </button>
        </div>
      </div>
    `);
  });

  // Fit bounds if in dataset builder tab
  const builderTab = document.getElementById("tab-dataset-builder");
  if (builderTab && builderTab.style.display !== "none" && bounds.length > 0) {
    const latLngBounds = L.latLngBounds(bounds);
    if (latLngBounds.isValid()) {
      map.fitBounds(latLngBounds, { padding: [50, 50], maxZoom: 8 });
    }
  }
}

function generateRadarsCsv(radars) {
  const lines = [
    "ident,name,country,latitude,longitude,mast_height_m,range_nm,azimuth_start_deg,azimuth_end_deg,elevation_min_deg,elevation_max_deg,type,mode_s",
    "# TEMPLATE GUIDE: Air Traffic Surveillance Radars (PSR, SSR, Mode S)",
    "# Generated by EuroGeoCov Dataset Builder for CLI Ingestion via scripts/ingest_custom_data.py",
    "#"
  ];
  radars.forEach(r => {
    const ident = (r.ident || "RAD").trim().toUpperCase();
    const name = (r.name || "Radar Station").replace(/,/g, " ").trim();
    const country = (r.country || "EU").trim().toUpperCase().slice(0, 2);
    const lat = Number(r.latitude || 0).toFixed(4);
    const lon = Number(r.longitude || 0).toFixed(4);
    const mastH = Number(r.mast_height_m || 25.0).toFixed(1);
    const rng = Number(r.range_nm || 200.0).toFixed(1);
    const azS = Number(r.azimuth_start_deg !== undefined ? r.azimuth_start_deg : 0.0).toFixed(1);
    const azE = Number(r.azimuth_end_deg !== undefined ? r.azimuth_end_deg : 360.0).toFixed(1);
    const elMin = Number(r.elevation_min_deg !== undefined ? r.elevation_min_deg : 0.5).toFixed(1);
    const elMax = Number(r.elevation_max_deg !== undefined ? r.elevation_max_deg : 34.0).toFixed(1);
    const typ = (r.type || "MODE-S").trim().toUpperCase();
    const modeS = (r.mode_s === true || r.mode_s === "true" || r.mode_s === 1 || r.mode_s === "1") ? "true" : "false";
    lines.push(`${ident},${name},${country},${lat},${lon},${mastH},${rng},${azS},${azE},${elMin},${elMax},${typ},${modeS}`);
  });
  return lines.join("\n") + "\n";
}

function generateNavaidsCsv(navaids) {
  const lines = [
    "ident,name,country,latitude,longitude,type,service_category,power,elevation_ft,frequency_khz,dme_channel,range_nm,elevation_min_deg,elevation_max_deg",
    "# TEMPLATE GUIDE: Radio Navigation Aids (VOR, DME, VORTAC, TACAN)",
    "# Generated by EuroGeoCov Dataset Builder for CLI Ingestion via scripts/ingest_custom_data.py",
    "#"
  ];
  navaids.forEach(n => {
    const ident = (n.ident || "NAV").trim().toUpperCase();
    const name = (n.name || "Navaid Station").replace(/,/g, " ").trim();
    const country = (n.country || "EU").trim().toUpperCase().slice(0, 2);
    const lat = Number(n.latitude || 0).toFixed(4);
    const lon = Number(n.longitude || 0).toFixed(4);
    const typ = (n.type || "VOR-DME").trim().toUpperCase();
    const serviceCat = (n.service_category || (typ.includes("TMA") ? "TMA" : "ENROUTE")).trim().toUpperCase();
    const power = (n.power || (serviceCat === "TMA" ? "LOW" : "HIGH")).trim().toUpperCase();
    const rawElev = n.elevation_ft !== undefined ? n.elevation_ft : n.reported_elev_ft;
    const elevFt = Math.round(Number(rawElev !== undefined ? rawElev : ((n.ground_elev_m || n.dem_elev_m || 0) * 3.28084)));
    const freqKhz = Math.round(Number(n.frequency_khz || 115000));
    const dmeCh = (n.dme_channel || "95X").trim().toUpperCase();
    const rng = Number(n.range_nm || (serviceCat === "TMA" ? 40.0 : 130.0)).toFixed(1);
    const isDme = typ.includes("DME");
    const elMin = Number(n.elevation_min_deg !== undefined ? n.elevation_min_deg : (isDme ? 30.0 : 0.5)).toFixed(1);
    const elMax = Number(n.elevation_max_deg !== undefined ? n.elevation_max_deg : (isDme ? 150.0 : 60.0)).toFixed(1);
    lines.push(`${ident},${name},${country},${lat},${lon},${typ},${serviceCat},${power},${elevFt},${freqKhz},${dmeCh},${rng},${elMin},${elMax}`);
  });
  return lines.join("\n") + "\n";
}

function downloadBlob(content, filename, mimeType = "text/csv;charset=utf-8;") {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function downloadStagedDataset(category) {
  const cat = (category || "RADAR").toUpperCase();
  const items = stagedDataset.filter(s => s.category === cat);
  if (items.length === 0) {
    alert(`No ${cat === "RADAR" ? "Radars" : "VOR/DME"} in your staged dataset. Add or select stations first.`);
    return;
  }

  const filename = cat === "RADAR" ? "radars_custom.csv" : "navaids_custom.csv";
  const csvContent = cat === "RADAR" ? generateRadarsCsv(items) : generateNavaidsCsv(items);

  downloadBlob(csvContent, filename);

  const toast = document.createElement("div");
  toast.style.cssText = "position:fixed; bottom:20px; right:20px; background:#3fb950; color:#fff; padding:10px 16px; border-radius:6px; font-size:12px; font-weight:600; z-index:9999; box-shadow:0 4px 12px rgba(0,0,0,0.4);";
  toast.textContent = `✓ Downloaded ${filename} (${items.length} records ready for CLI ingestion)`;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

function copyCliCommand() {
  const cliBox = document.getElementById("cliCommandBox");
  if (!cliBox) return;
  navigator.clipboard.writeText(cliBox.textContent).then(() => {
    const toast = document.createElement("div");
    toast.style.cssText = "position:fixed; bottom:20px; right:20px; background:#1f6feb; color:#fff; padding:10px 16px; border-radius:6px; font-size:12px; font-weight:600; z-index:9999;";
    toast.textContent = `✓ CLI command copied to clipboard!`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2500);
  });
}

// ==========================================================================
// 3D Airspace Coverage Volume & Multi-Site Sculpture (Three.js WebGL)
// ==========================================================================

let threeScene = null;
let threeCamera = null;
let threeRenderer = null;
let threeControls = null;
let threeAnimFrameId = null;
let threeVolumeGroup = null;
let threeGridGroup = null;
let threeConeGroup = null;
let threeActiveStationId = null;
let threeCurrentVolumeData = null;
let threeMultiData = null;
let three3DMode = "single"; // "single" or "multi"
let threeIsRotating = false;
let threeConeVisible = true;
let threeRingsVisible = true;
let threeTheme = "multi";
let threeExaggeration = 6;
let threeStationGroups = {};
let threeStationEnabled = {};

const THREE_STATION_PALETTE = [
  0x38bdf8, // Sky Cyan
  0x10b981, // Emerald Green
  0xf59e0b, // Amber Gold
  0xec4899, // Pink / Magenta
  0xa855f7, // Purple
  0x06b6d4, // Neon Cyan
  0xef4444, // Crimson Red
  0x84cc16, // Lime
  0x6366f1, // Indigo
  0x14b8a6, // Teal
  0xeab308, // Sun Gold
  0xf97316  // Sunset Orange
];

function hexToRgb(hex) {
  const r = (hex >> 16) & 255;
  const g = (hex >> 8) & 255;
  const b = hex & 255;
  return `${r}, ${g}, ${b}`;
}

function getThemeColor(theme) {
  if (theme === "radar") return 0x10b981;
  if (theme === "amber") return 0xf59e0b;
  if (theme === "wireframe") return 0x38bdf8;
  return 0x00d2ff;
}

function disposeThreeObject(obj) {
  if (!obj) return;
  if (obj.geometry) obj.geometry.dispose();
  if (obj.material) {
    if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
    else obj.material.dispose();
  }
  if (obj.children) {
    while (obj.children.length > 0) {
      const child = obj.children[0];
      disposeThreeObject(child);
      obj.remove(child);
    }
  }
}

function createThreeTextSprite(text, colorHex) {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 128;
  const ctx = canvas.getContext("2d");

  // Translucent dark rounded pill background
  ctx.fillStyle = "rgba(5, 8, 17, 0.88)";
  ctx.strokeStyle = colorHex || "#38bdf8";
  ctx.lineWidth = 4;
  ctx.beginPath();
  if (ctx.roundRect) {
    ctx.roundRect(16, 20, 224, 88, 16);
  } else {
    ctx.rect(16, 20, 224, 88);
  }
  ctx.fill();
  ctx.stroke();

  // White bold text
  ctx.font = "bold 44px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  ctx.fillStyle = "#ffffff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 128, 64);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
  const sprite = new THREE.Sprite(spriteMat);
  sprite.scale.set(36, 18, 1);
  return sprite;
}

function initThreeScene() {
  const container = document.getElementById("threeVolumeContainer");
  if (!container) return;

  if (threeRenderer) {
    onThreeResize();
    return;
  }

  const width = container.clientWidth || 900;
  const height = container.clientHeight || 550;

  // Scene
  threeScene = new THREE.Scene();
  threeScene.background = new THREE.Color(0x050811);
  threeScene.fog = new THREE.FogExp2(0x050811, 0.0004);

  // Camera
  threeCamera = new THREE.PerspectiveCamera(45, width / height, 1, 10000);
  threeCamera.position.set(240, 220, 320);

  // Renderer
  threeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  threeRenderer.setSize(width, height);
  threeRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  threeRenderer.shadowMap.enabled = false;
  container.appendChild(threeRenderer.domElement);

  // OrbitControls
  if (typeof THREE.OrbitControls !== "undefined") {
    threeControls = new THREE.OrbitControls(threeCamera, threeRenderer.domElement);
    threeControls.enableDamping = true;
    threeControls.dampingFactor = 0.05;
    threeControls.maxPolarAngle = Math.PI / 2 - 0.01; // Stay above ground plane
    threeControls.minDistance = 20;
    threeControls.maxDistance = 5000;
    threeControls.target.set(0, 40, 0);
  }

  // Lighting
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
  threeScene.add(ambientLight);

  const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.85);
  dirLight1.position.set(500, 700, 400);
  threeScene.add(dirLight1);

  const dirLight2 = new THREE.DirectionalLight(0x38bdf8, 0.45);
  dirLight2.position.set(-500, 400, -400);
  threeScene.add(dirLight2);

  // Master Groups
  threeGridGroup = new THREE.Group();
  threeScene.add(threeGridGroup);

  threeConeGroup = new THREE.Group();
  threeScene.add(threeConeGroup);

  threeVolumeGroup = new THREE.Group();
  threeScene.add(threeVolumeGroup);

  // Event Listeners
  window.addEventListener("resize", onThreeResize);
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeCoverage3DModal();
    }
  });

  animateThree();
}

function onThreeResize() {
  const container = document.getElementById("threeVolumeContainer");
  if (!container || !threeCamera || !threeRenderer) return;
  const width = container.clientWidth;
  const height = container.clientHeight;
  if (width === 0 || height === 0) return;
  threeCamera.aspect = width / height;
  threeCamera.updateProjectionMatrix();
  threeRenderer.setSize(width, height);
}

function animateThree() {
  threeAnimFrameId = requestAnimationFrame(animateThree);
  if (threeIsRotating && threeVolumeGroup) {
    threeVolumeGroup.rotation.y += 0.003;
    if (threeConeGroup) threeConeGroup.rotation.y += 0.003;
  }
  if (threeControls) {
    threeControls.update();
  }
  if (threeRenderer && threeScene && threeCamera) {
    threeRenderer.render(threeScene, threeCamera);
  }
}

// ---------------------------------------------------------------------------
// Facility Mesh Construction Core
// ---------------------------------------------------------------------------

function buildFacilityVolumeMeshIntoGroup(fac, targetGroup, colorHex, exagg, theme) {
  const slices = fac.slices;
  if (!slices || slices.length < 2) return;

  const numSlices = slices.length;
  const numRadials = slices[0].outer_radii_km.length;
  const azimuths = fac.azimuths_deg || Array.from({ length: numRadials }, (_, i) => i * (360 / numRadials));

  const isWireframeOnly = (theme === "wireframe");
  const solidColor = colorHex;
  const emissiveColor = colorHex;
  const wireColor = colorHex;
  const coneColor = 0xff0055;

  const outerVerts = [];
  const innerVerts = [];

  for (let s = 0; s < numSlices; s++) {
    const sl = slices[s];
    const y = Math.max(0.1, sl.z_km * exagg);
    const rIn = Math.max(0.1, sl.inner_radius_km);

    const outerRow = [];
    const innerRow = [];

    for (let i = 0; i < numRadials; i++) {
      const az = azimuths[i];
      const rad = (az * Math.PI) / 180.0;
      const sinAz = Math.sin(rad);
      const cosAz = Math.cos(rad);

      const rOut = Math.max(rIn + 0.5, sl.outer_radii_km[i]);

      outerRow.push(new THREE.Vector3(rOut * sinAz, y, -rOut * cosAz));
      innerRow.push(new THREE.Vector3(rIn * sinAz, y, -rIn * cosAz));
    }
    outerVerts.push(outerRow);
    innerVerts.push(innerRow);
  }

  // --- A. Outer Jagged Shell ---
  const outerGeom = new THREE.BufferGeometry();
  const outerPositions = [];

  for (let s = 0; s < numSlices - 1; s++) {
    for (let i = 0; i < numRadials; i++) {
      const nextI = (i + 1) % numRadials;

      const p00 = outerVerts[s][i];
      const p01 = outerVerts[s][nextI];
      const p11 = outerVerts[s + 1][nextI];
      const p10 = outerVerts[s + 1][i];

      outerPositions.push(p00.x, p00.y, p00.z);
      outerPositions.push(p01.x, p01.y, p01.z);
      outerPositions.push(p11.x, p11.y, p11.z);

      outerPositions.push(p00.x, p00.y, p00.z);
      outerPositions.push(p11.x, p11.y, p11.z);
      outerPositions.push(p10.x, p10.y, p10.z);
    }
  }

  outerGeom.setAttribute("position", new THREE.Float32BufferAttribute(outerPositions, 3));
  outerGeom.computeVertexNormals();

  if (!isWireframeOnly) {
    const outerMat = new THREE.MeshPhongMaterial({
      color: solidColor,
      emissive: emissiveColor,
      emissiveIntensity: 0.28,
      specular: 0xffffff,
      shininess: 45,
      transparent: true,
      opacity: 0.44,
      side: THREE.DoubleSide,
      depthWrite: false
    });
    targetGroup.add(new THREE.Mesh(outerGeom, outerMat));
  }

  const wireLines = new THREE.LineSegments(
    new THREE.WireframeGeometry(outerGeom),
    new THREE.LineBasicMaterial({ color: wireColor, transparent: true, opacity: isWireframeOnly ? 0.85 : 0.25 })
  );
  targetGroup.add(wireLines);

  // --- B. Top Ceiling Cap Annulus ---
  const topCapGeom = new THREE.BufferGeometry();
  const topPositions = [];
  const topS = numSlices - 1;

  for (let i = 0; i < numRadials; i++) {
    const nextI = (i + 1) % numRadials;
    const in0 = innerVerts[topS][i];
    const out0 = outerVerts[topS][i];
    const out1 = outerVerts[topS][nextI];
    const in1 = innerVerts[topS][nextI];

    topPositions.push(in0.x, in0.y, in0.z);
    topPositions.push(out0.x, out0.y, out0.z);
    topPositions.push(out1.x, out1.y, out1.z);

    topPositions.push(in0.x, in0.y, in0.z);
    topPositions.push(out1.x, out1.y, out1.z);
    topPositions.push(in1.x, in1.y, in1.z);
  }

  topCapGeom.setAttribute("position", new THREE.Float32BufferAttribute(topPositions, 3));
  topCapGeom.computeVertexNormals();

  if (!isWireframeOnly) {
    const topCapMat = new THREE.MeshPhongMaterial({
      color: solidColor,
      emissive: emissiveColor,
      emissiveIntensity: 0.35,
      transparent: true,
      opacity: 0.52,
      side: THREE.DoubleSide,
      depthWrite: false
    });
    targetGroup.add(new THREE.Mesh(topCapGeom, topCapMat));
  }
  targetGroup.add(new THREE.LineSegments(new THREE.WireframeGeometry(topCapGeom), wireLines.material));

  // --- C. Floor Cap Annulus ---
  const floorCapGeom = new THREE.BufferGeometry();
  const floorPositions = [];
  for (let i = 0; i < numRadials; i++) {
    const nextI = (i + 1) % numRadials;
    const in0 = innerVerts[0][i];
    const out0 = outerVerts[0][i];
    const out1 = outerVerts[0][nextI];
    const in1 = innerVerts[0][nextI];

    floorPositions.push(in0.x, in0.y, in0.z);
    floorPositions.push(out1.x, out1.y, out1.z);
    floorPositions.push(out0.x, out0.y, out0.z);

    floorPositions.push(in0.x, in0.y, in0.z);
    floorPositions.push(in1.x, in1.y, in1.z);
    floorPositions.push(out1.x, out1.y, out1.z);
  }
  floorCapGeom.setAttribute("position", new THREE.Float32BufferAttribute(floorPositions, 3));
  floorCapGeom.computeVertexNormals();

  if (!isWireframeOnly) {
    const floorCapMat = new THREE.MeshPhongMaterial({
      color: solidColor,
      transparent: true,
      opacity: 0.32,
      side: THREE.DoubleSide,
      depthWrite: false
    });
    targetGroup.add(new THREE.Mesh(floorCapGeom, floorCapMat));
  }

  // --- D. Inner Cone of Silence Funnel ---
  const coneGeom = new THREE.BufferGeometry();
  const conePositions = [];

  for (let s = 0; s < numSlices - 1; s++) {
    for (let i = 0; i < numRadials; i++) {
      const nextI = (i + 1) % numRadials;
      const c00 = innerVerts[s][i];
      const c01 = innerVerts[s][nextI];
      const c11 = innerVerts[s + 1][nextI];
      const c10 = innerVerts[s + 1][i];

      conePositions.push(c00.x, c00.y, c00.z);
      conePositions.push(c11.x, c11.y, c11.z);
      conePositions.push(c01.x, c01.y, c01.z);

      conePositions.push(c00.x, c00.y, c00.z);
      conePositions.push(c10.x, c10.y, c10.z);
      conePositions.push(c11.x, c11.y, c11.z);
    }
  }

  coneGeom.setAttribute("position", new THREE.Float32BufferAttribute(conePositions, 3));
  coneGeom.computeVertexNormals();

  const coneSubGroup = new THREE.Group();
  coneSubGroup.name = "coneSubGroup";
  const coneMat = new THREE.MeshPhongMaterial({
    color: coneColor,
    emissive: coneColor,
    emissiveIntensity: 0.3,
    transparent: true,
    opacity: 0.45,
    side: THREE.DoubleSide,
    depthWrite: false
  });
  coneSubGroup.add(new THREE.Mesh(coneGeom, coneMat));
  coneSubGroup.add(new THREE.LineSegments(
    new THREE.WireframeGeometry(coneGeom),
    new THREE.LineBasicMaterial({ color: coneColor, transparent: true, opacity: 0.5 })
  ));
  coneSubGroup.visible = threeConeVisible;
  targetGroup.add(coneSubGroup);
}

function buildStationAntennaMastInGroup(targetGroup, txAmsl, beaconColorHex) {
  const mastHeight = 8;
  const mastGeom = new THREE.CylinderGeometry(0.8, 1.4, mastHeight, 12);
  const mastMat = new THREE.MeshLambertMaterial({ color: 0x94a3b8 });
  const mastMesh = new THREE.Mesh(mastGeom, mastMat);
  mastMesh.position.set(0, mastHeight / 2, 0);
  targetGroup.add(mastMesh);

  // Glowing Colored Beacon Sphere
  const beaconGeom = new THREE.SphereGeometry(1.6, 16, 16);
  const beaconMat = new THREE.MeshBasicMaterial({ color: beaconColorHex || 0xff0044 });
  const beaconMesh = new THREE.Mesh(beaconGeom, beaconMat);
  beaconMesh.position.set(0, mastHeight + 0.8, 0);
  targetGroup.add(beaconMesh);
}

// ---------------------------------------------------------------------------
// Single Site Mesh Builder
// ---------------------------------------------------------------------------

function buildThreeVolumeMesh(data) {
  if (!data || !data.slices || data.slices.length < 2) return;
  threeCurrentVolumeData = data;

  while (threeVolumeGroup.children.length > 0) {
    const obj = threeVolumeGroup.children[0];
    disposeThreeObject(obj);
    threeVolumeGroup.remove(obj);
  }
  while (threeConeGroup.children.length > 0) {
    const obj = threeConeGroup.children[0];
    disposeThreeObject(obj);
    threeConeGroup.remove(obj);
  }
  while (threeGridGroup.children.length > 0) {
    const obj = threeGridGroup.children[0];
    disposeThreeObject(obj);
    threeGridGroup.remove(obj);
  }

  threeStationGroups = {};
  threeVolumeGroup.rotation.y = 0;
  threeConeGroup.rotation.y = 0;

  const exagg = parseFloat(document.getElementById("modal3DExaggeration")?.value || 6);
  threeExaggeration = exagg;
  const theme = document.getElementById("modal3DTheme")?.value || "cyan";
  threeTheme = theme;

  const colorHex = (theme === "multi") ? 0x00d2ff : getThemeColor(theme);

  let maxOuterReach = 100;
  data.slices.forEach(s => {
    s.outer_radii_km.forEach(r => { if (r > maxOuterReach) maxOuterReach = r; });
  });

  buildGroundEnvironment(maxOuterReach);
  buildFacilityVolumeMeshIntoGroup(data, threeVolumeGroup, colorHex, exagg, theme);
  buildStationAntennaMastInGroup(threeVolumeGroup, data.tx_amsl_m || 0, 0xff0044);

  // Set default single camera view
  threeCamera.position.set(240, 220, 320);
  if (threeControls) {
    threeControls.target.set(0, 40, 0);
    threeControls.update();
  }

  const badgesBar = document.getElementById("modal3DStationBadges");
  if (badgesBar) badgesBar.style.display = "none";

  updateModal3DStats(data, maxOuterReach);
}

// ---------------------------------------------------------------------------
// Multi-Site Sculpture Builder
// ---------------------------------------------------------------------------

function buildThreeMultiSiteSculpture(data) {
  if (!data || !data.facilities || data.facilities.length === 0) return;

  while (threeVolumeGroup.children.length > 0) {
    const obj = threeVolumeGroup.children[0];
    disposeThreeObject(obj);
    threeVolumeGroup.remove(obj);
  }
  while (threeConeGroup.children.length > 0) {
    const obj = threeConeGroup.children[0];
    disposeThreeObject(obj);
    threeConeGroup.remove(obj);
  }
  while (threeGridGroup.children.length > 0) {
    const obj = threeGridGroup.children[0];
    disposeThreeObject(obj);
    threeGridGroup.remove(obj);
  }

  threeStationGroups = {};
  threeVolumeGroup.rotation.y = 0;
  threeConeGroup.rotation.y = 0;

  const exagg = parseFloat(document.getElementById("modal3DExaggeration")?.value || 6);
  threeExaggeration = exagg;
  const theme = document.getElementById("modal3DTheme")?.value || "multi";
  threeTheme = theme;

  const bounds = data.sculpture_bounds_km;
  const maxSpan = Math.max(bounds.width_km, bounds.depth_km, 150);

  // Build cluster ground grid & rings
  buildMultiGroundEnvironment(bounds);

  const badgesBar = document.getElementById("modal3DStationBadges");
  if (badgesBar) {
    badgesBar.style.display = "flex";
    badgesBar.innerHTML = "";
  }

  // Position camera to frame entire sculpture
  const camDist = Math.max(380, maxSpan * 0.95);
  threeCamera.position.set(camDist * 0.65, camDist * 0.55, camDist * 0.85);
  if (threeControls) {
    threeControls.target.set(0, 30, 0);
    threeControls.maxDistance = camDist * 4;
    threeControls.update();
  }

  data.facilities.forEach((fac, idx) => {
    const colorHex = (theme === "multi") 
      ? THREE_STATION_PALETTE[idx % THREE_STATION_PALETTE.length]
      : getThemeColor(theme);

    const colorCss = "#" + colorHex.toString(16).padStart(6, "0");
    const facId = fac.facility_id;
    if (threeStationEnabled[facId] === undefined) {
      threeStationEnabled[facId] = true;
    }

    const stGroup = new THREE.Group();
    stGroup.name = facId;

    // True spatial offset from sculpture centroid
    const dx = fac.offset_from_centroid_km?.x || 0;
    const dz = fac.offset_from_centroid_km?.z || 0;
    stGroup.position.set(dx, 0, dz);

    buildFacilityVolumeMeshIntoGroup(fac, stGroup, colorHex, exagg, theme);
    buildStationAntennaMastInGroup(stGroup, fac.tx_amsl_m || 0, colorHex);

    // Floating 3D billboard text sprite
    const ceilingSlice = fac.slices[fac.slices.length - 1];
    const spriteY = (ceilingSlice ? ceilingSlice.z_km * exagg : 50) + 16;
    const sprite = createThreeTextSprite(fac.ident || facId.slice(0, 4), colorCss);
    sprite.position.set(0, spriteY, 0);
    stGroup.add(sprite);

    stGroup.visible = threeStationEnabled[facId];
    threeVolumeGroup.add(stGroup);
    threeStationGroups[facId] = stGroup;

    // Interactive station pill in toolbar
    if (badgesBar) {
      const pill = document.createElement("div");
      pill.className = `sculpture-station-pill ${threeStationEnabled[facId] ? '' : 'disabled'}`;
      pill.style.borderColor = colorCss;
      pill.style.background = threeStationEnabled[facId] ? `rgba(${hexToRgb(colorHex)}, 0.2)` : 'rgba(22, 27, 34, 0.6)';
      pill.style.color = colorCss;
      pill.innerHTML = `
        <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${colorCss};"></span>
        <span><b>[${fac.ident || facId}]</b> ${fac.name || ''}</span>
      `;
      pill.onclick = () => {
        threeStationEnabled[facId] = !threeStationEnabled[facId];
        stGroup.visible = threeStationEnabled[facId];
        pill.className = `sculpture-station-pill ${threeStationEnabled[facId] ? '' : 'disabled'}`;
        pill.style.background = threeStationEnabled[facId] ? `rgba(${hexToRgb(colorHex)}, 0.2)` : 'rgba(22, 27, 34, 0.6)';
      };
      badgesBar.appendChild(pill);
    }
  });

  updateModal3DMultiStats(data);
}

// ---------------------------------------------------------------------------
// Ground Environments
// ---------------------------------------------------------------------------

function buildGroundEnvironment(maxRadiusKm) {
  const ringDistances = [50, 100, 200, 300, 400, 500, 600].filter(d => d <= maxRadiusKm * 1.25);
  if (ringDistances.length === 0) ringDistances.push(50, 100);

  const ringMaterial = new THREE.LineBasicMaterial({
    color: 0x334155,
    transparent: true,
    opacity: 0.6
  });

  const cardinalMaterial = new THREE.LineBasicMaterial({
    color: 0x475569,
    transparent: true,
    opacity: 0.8
  });

  const maxR = ringDistances[ringDistances.length - 1];

  ringDistances.forEach(r => {
    const ringGeom = new THREE.BufferGeometry();
    const pts = [];
    const segs = 96;
    for (let i = 0; i <= segs; i++) {
      const theta = (i / segs) * Math.PI * 2;
      pts.push(new THREE.Vector3(r * Math.sin(theta), 0, -r * Math.cos(theta)));
    }
    ringGeom.setFromPoints(pts);
    threeGridGroup.add(new THREE.Line(ringGeom, ringMaterial));
  });

  const crossGeom = new THREE.BufferGeometry();
  crossGeom.setFromPoints([
    new THREE.Vector3(0, 0, -maxR), new THREE.Vector3(0, 0, maxR),
    new THREE.Vector3(-maxR, 0, 0), new THREE.Vector3(maxR, 0, 0)
  ]);
  threeGridGroup.add(new THREE.LineSegments(crossGeom, cardinalMaterial));

  const northArrowGeom = new THREE.BufferGeometry();
  northArrowGeom.setFromPoints([
    new THREE.Vector3(-8, 0, -maxR + 15),
    new THREE.Vector3(0, 0, -maxR),
    new THREE.Vector3(8, 0, -maxR + 15)
  ]);
  threeGridGroup.add(new THREE.Line(northArrowGeom, new THREE.LineBasicMaterial({ color: 0x38bdf8 })));

  threeGridGroup.visible = threeRingsVisible;
}

function buildMultiGroundEnvironment(bounds) {
  const maxR = Math.max(bounds.width_km, bounds.depth_km, 300) * 0.75;
  const ringDistances = [100, 200, 300, 500, 800, 1200].filter(d => d <= maxR * 1.3);
  if (ringDistances.length === 0) ringDistances.push(100, 200);

  const ringMaterial = new THREE.LineBasicMaterial({
    color: 0x334155,
    transparent: true,
    opacity: 0.5
  });

  const cardinalMaterial = new THREE.LineBasicMaterial({
    color: 0x475569,
    transparent: true,
    opacity: 0.75
  });

  ringDistances.forEach(r => {
    const ringGeom = new THREE.BufferGeometry();
    const pts = [];
    const segs = 96;
    for (let i = 0; i <= segs; i++) {
      const theta = (i / segs) * Math.PI * 2;
      pts.push(new THREE.Vector3(r * Math.sin(theta), 0, -r * Math.cos(theta)));
    }
    ringGeom.setFromPoints(pts);
    threeGridGroup.add(new THREE.Line(ringGeom, ringMaterial));
  });

  const topR = ringDistances[ringDistances.length - 1];
  const crossGeom = new THREE.BufferGeometry();
  crossGeom.setFromPoints([
    new THREE.Vector3(0, 0, -topR), new THREE.Vector3(0, 0, topR),
    new THREE.Vector3(-topR, 0, 0), new THREE.Vector3(topR, 0, 0)
  ]);
  threeGridGroup.add(new THREE.LineSegments(crossGeom, cardinalMaterial));

  const northArrowGeom = new THREE.BufferGeometry();
  northArrowGeom.setFromPoints([
    new THREE.Vector3(-12, 0, -topR + 25),
    new THREE.Vector3(0, 0, -topR),
    new THREE.Vector3(12, 0, -topR + 25)
  ]);
  threeGridGroup.add(new THREE.Line(northArrowGeom, new THREE.LineBasicMaterial({ color: 0x38bdf8 })));

  threeGridGroup.visible = threeRingsVisible;
}

// ---------------------------------------------------------------------------
// Open / Close & Mode Switching Controllers
// ---------------------------------------------------------------------------

async function openCoverage3DModal(stationId) {
  if (!stationId) {
    if (activeRayStationId) stationId = activeRayStationId;
    else if (lastCoverageData?.stations?.length > 0) stationId = lastCoverageData.stations[0].station_id;
  }
  if (!stationId) {
    alert("Please select or activate a radar/navaid station first.");
    return;
  }

  threeActiveStationId = stationId;
  three3DMode = "single";
  const modal = document.getElementById("modalCoverage3D");
  if (!modal) return;
  modal.style.display = "flex";

  updateModeButtonsUI("single");
  initThreeScene();
  setTimeout(() => onThreeResize(), 50);

  const ceilingFt = document.getElementById("modal3DCeilingSelect")?.value || 60000;
  await loadCoverage3DData(stationId, ceilingFt);
}

async function openCoverage3DMultiSiteModal() {
  const stations = lastCoverageData?.stations || [];
  if (stations.length === 0) {
    alert("Please select and load stations on the map first using '⚡ Load & Merge Precalculated Coverage'.");
    return;
  }

  const modal = document.getElementById("modalCoverage3D");
  if (!modal) return;
  modal.style.display = "flex";

  three3DMode = "multi";
  updateModeButtonsUI("multi");
  initThreeScene();
  setTimeout(() => onThreeResize(), 50);

  await loadCoverage3DMultiData();
}

function updateModeButtonsUI(mode) {
  const singleBtn = document.getElementById("modal3DModeSingleBtn");
  const multiBtn = document.getElementById("modal3DModeMultiBtn");
  if (mode === "single") {
    if (singleBtn) {
      singleBtn.style.background = "rgba(88, 166, 255, 0.25)";
      singleBtn.style.borderColor = "var(--accent-blue)";
      singleBtn.style.color = "#fff";
    }
    if (multiBtn) {
      multiBtn.style.background = "";
      multiBtn.style.borderColor = "";
      multiBtn.style.color = "";
    }
  } else {
    if (multiBtn) {
      multiBtn.style.background = "rgba(88, 166, 255, 0.25)";
      multiBtn.style.borderColor = "var(--accent-blue)";
      multiBtn.style.color = "#fff";
    }
    if (singleBtn) {
      singleBtn.style.background = "";
      singleBtn.style.borderColor = "";
      singleBtn.style.color = "";
    }
  }
}

async function switch3DMode(mode) {
  three3DMode = mode;
  updateModeButtonsUI(mode);

  if (mode === "single") {
    const badgesBar = document.getElementById("modal3DStationBadges");
    if (badgesBar) badgesBar.style.display = "none";

    const ceilingFt = document.getElementById("modal3DCeilingSelect")?.value || 60000;
    const stationId = threeActiveStationId || (lastCoverageData?.stations?.length > 0 ? lastCoverageData.stations[0].station_id : null);
    if (stationId) {
      await loadCoverage3DData(stationId, ceilingFt);
    }
  } else {
    await loadCoverage3DMultiData();
  }
}

function closeCoverage3DModal() {
  const modal = document.getElementById("modalCoverage3D");
  if (modal) modal.style.display = "none";
}

async function loadCoverage3DData(stationId, ceilingFt) {
  const spinner = document.getElementById("threeVolumeSpinner");
  const spinnerText = document.getElementById("threeVolumeSpinnerText");
  if (spinnerText) spinnerText.textContent = "Generating 3D Volumetric Mesh...";
  if (spinner) spinner.style.display = "flex";

  try {
    const res = await fetch(`/api/facilities/${encodeURIComponent(stationId)}/volume-3d?max_flight_level_ft=${ceilingFt}&num_slices=15`);
    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }
    const data = await res.json();
    buildThreeVolumeMesh(data);
  } catch (err) {
    console.error("Failed to load 3D coverage volume:", err);
    alert(`Could not generate 3D coverage volume: ${err.message}`);
  } finally {
    if (spinner) spinner.style.display = "none";
  }
}

async function loadCoverage3DMultiData() {
  const spinner = document.getElementById("threeVolumeSpinner");
  const spinnerText = document.getElementById("threeVolumeSpinnerText");
  if (spinnerText) spinnerText.textContent = "Sculpting Multi-Site 3D Airspace Mesh...";
  if (spinner) spinner.style.display = "flex";

  try {
    const stations = lastCoverageData?.stations || [];
    let ids = stations.map(s => s.station_id).join(",");
    if (!ids && threeActiveStationId) ids = threeActiveStationId;
    if (!ids) {
      alert("No active stations loaded on the map.");
      return;
    }

    const ceilingFt = document.getElementById("modal3DCeilingSelect")?.value || 60000;
    const res = await fetch(`/api/facilities/volume-3d-multi?ids=${encodeURIComponent(ids)}&max_flight_level_ft=${ceilingFt}&num_slices=12`);
    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }
    const data = await res.json();
    threeMultiData = data;
    buildThreeMultiSiteSculpture(data);
  } catch (err) {
    console.error("Failed to load multi-site 3D sculpture:", err);
    alert(`Could not generate multi-site 3D sculpture: ${err.message}`);
  } finally {
    if (spinner) spinner.style.display = "none";
  }
}

async function updateCoverage3DCeiling() {
  const ceilingFt = document.getElementById("modal3DCeilingSelect")?.value || 60000;
  if (three3DMode === "single") {
    if (threeActiveStationId) await loadCoverage3DData(threeActiveStationId, ceilingFt);
  } else {
    await loadCoverage3DMultiData();
  }
}

function updateCoverage3DMesh() {
  if (three3DMode === "single") {
    if (threeCurrentVolumeData) buildThreeVolumeMesh(threeCurrentVolumeData);
  } else {
    if (threeMultiData) buildThreeMultiSiteSculpture(threeMultiData);
  }
}

function updateCoverage3DTheme() {
  if (three3DMode === "single") {
    if (threeCurrentVolumeData) buildThreeVolumeMesh(threeCurrentVolumeData);
  } else {
    if (threeMultiData) buildThreeMultiSiteSculpture(threeMultiData);
  }
}

function toggleCoverage3DCone() {
  threeConeVisible = document.getElementById("modal3DConeToggle")?.checked ?? true;
  if (threeConeGroup) threeConeGroup.visible = threeConeVisible;

  // Also toggle inner cone sub-groups across all stations in multi-site mode
  threeVolumeGroup.traverse(child => {
    if (child.name === "coneSubGroup") child.visible = threeConeVisible;
  });
}

function toggleCoverage3DRings() {
  threeRingsVisible = document.getElementById("modal3DRingsToggle")?.checked ?? true;
  if (threeGridGroup) threeGridGroup.visible = threeRingsVisible;
}

function toggleCoverage3DAutoRotate() {
  threeIsRotating = !threeIsRotating;
  const btn = document.getElementById("modal3DRotateBtn");
  if (btn) {
    btn.style.color = threeIsRotating ? "var(--accent-cyan)" : "";
    btn.style.borderColor = threeIsRotating ? "var(--accent-cyan)" : "";
  }
}

function resetCoverage3DCamera() {
  if (three3DMode === "single") {
    if (threeCamera && threeControls) {
      threeCamera.position.set(240, 220, 320);
      threeControls.target.set(0, 40, 0);
      threeControls.update();
    }
  } else {
    if (threeMultiData && threeCamera && threeControls) {
      const bounds = threeMultiData.sculpture_bounds_km;
      const maxSpan = Math.max(bounds.width_km, bounds.depth_km, 150);
      const camDist = Math.max(380, maxSpan * 0.95);
      threeCamera.position.set(camDist * 0.65, camDist * 0.55, camDist * 0.85);
      threeControls.target.set(0, 30, 0);
      threeControls.update();
    }
  }
  if (threeVolumeGroup) threeVolumeGroup.rotation.y = 0;
  if (threeConeGroup) threeConeGroup.rotation.y = 0;
}

function updateModal3DStats(data, maxOuterReach) {
  const title = document.getElementById("modal3DTitle");
  if (title) title.innerHTML = `🧊 ${data.ident || data.facility_id} &middot; 3D Coverage Volume`;

  const sub = document.getElementById("modal3DSubtitle");
  if (sub) {
    sub.innerHTML = `${data.name || ''} (${data.type || data.category}) &middot; ${data.country_name || data.country || 'EU'} &middot; Horizon LoS &amp; Zenith Silence Cone`;
  }

  const vol = document.getElementById("modal3DStatVolume");
  if (vol) vol.textContent = `${(data.total_volume_km3 || 0).toLocaleString()} km³`;

  const brk = document.getElementById("modal3DStatBracket");
  const brkLabel = document.getElementById("modal3DStatBracketLabel");
  if (brkLabel) brkLabel.textContent = "Airspace Bracket";
  if (brk) brk.textContent = `FL${String(Math.round(data.floor_flight_level_ft / 100)).padStart(3, '0')} - FL${Math.round(data.ceiling_flight_level_ft / 100)}`;

  const reach = document.getElementById("modal3DStatReach");
  const reachLabel = document.getElementById("modal3DStatReachLabel");
  if (reachLabel) reachLabel.textContent = "Max Reach @ Ceiling";
  if (reach) reach.textContent = `${Math.round(maxOuterReach)} km`;

  const cone = document.getElementById("modal3DStatCone");
  const coneLabel = document.getElementById("modal3DStatConeLabel");
  if (coneLabel) coneLabel.textContent = "Silence Cone Radius";
  const ceilingSlice = data.slices[data.slices.length - 1];
  if (cone) cone.textContent = `${ceilingSlice ? ceilingSlice.inner_radius_km : '--'} km`;

  const tx = document.getElementById("modal3DStatTx");
  const txLabel = document.getElementById("modal3DStatTxLabel");
  if (txLabel) txLabel.textContent = "Station AMSL / Mast";
  if (tx) tx.textContent = `${Math.round(data.tx_amsl_m)}m AMSL (+${Math.round(data.mast_height_m || 25)}m mast)`;
}

function updateModal3DMultiStats(data) {
  const title = document.getElementById("modal3DTitle");
  if (title) title.innerHTML = `🌐 Multi-Site Airspace Sculpture (${data.stations_count} Facilities)`;

  const sub = document.getElementById("modal3DSubtitle");
  if (sub) {
    sub.innerHTML = `Centroid: ${data.centroid.latitude.toFixed(2)}°N, ${data.centroid.longitude.toFixed(2)}°E &middot; Spatial Span: ${Math.round(data.sculpture_bounds_km.width_km)} km &times; ${Math.round(data.sculpture_bounds_km.depth_km)} km &middot; Horizon Overlap`;
  }

  const vol = document.getElementById("modal3DStatVolume");
  if (vol) vol.textContent = `${(data.total_volume_km3 || 0).toLocaleString()} km³`;

  const brk = document.getElementById("modal3DStatBracket");
  const brkLabel = document.getElementById("modal3DStatBracketLabel");
  if (brkLabel) brkLabel.textContent = "Active Stations";
  if (brk) brk.textContent = `${data.stations_count} Sites`;

  const reach = document.getElementById("modal3DStatReach");
  const reachLabel = document.getElementById("modal3DStatReachLabel");
  if (reachLabel) reachLabel.textContent = "Cluster Width";
  if (reach) reach.textContent = `${Math.round(data.sculpture_bounds_km.width_km)} km`;

  const cone = document.getElementById("modal3DStatCone");
  const coneLabel = document.getElementById("modal3DStatConeLabel");
  if (coneLabel) coneLabel.textContent = "Cluster Depth";
  if (cone) cone.textContent = `${Math.round(data.sculpture_bounds_km.depth_km)} km`;

  const tx = document.getElementById("modal3DStatTx");
  const txLabel = document.getElementById("modal3DStatTxLabel");
  if (txLabel) txLabel.textContent = "Centroid WGS84";
  if (tx) tx.textContent = `${data.centroid.latitude.toFixed(2)}°N, ${data.centroid.longitude.toFixed(2)}°E`;
}

