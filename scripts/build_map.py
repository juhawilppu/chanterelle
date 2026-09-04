"""Score Karkkila forest stands for chanterelle (kantarelli) habitat
suitability and render the result as a standalone Leaflet HTML map.

Habitat heuristic (see README discussion in the chat this script came
from): chanterelles are mycorrhizal mainly with spruce, favour mesic to
herb-rich heath forest (OMT/MT), mid-aged to mature stands with an open
enough canopy for moss to carpet the floor, well-drained mineral soil,
and often occur near esker/moraine formations. Wet peatland, very young
or clear-cut stands, and non-forest land are excluded outright.

Run scripts/download_data.py first.
"""

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

MUNICIPALITY = "Karkkila"

ROOT = Path(__file__).resolve().parent.parent
GPKG_PATH = ROOT / "data" / "raw" / f"MV_{MUNICIPALITY}" / f"MV_{MUNICIPALITY}.gpkg"
GTK_FORMATIONS_PATH = ROOT / "data" / "cache" / f"gtk_formations_{MUNICIPALITY}.geojson"
OUTPUT_GEOJSON = ROOT / "output" / "scored_stands.geojson"
OUTPUT_HTML = ROOT / "output" / "karkkila_kantarelli_map.html"

ESKER_BUFFER_M = 150
CURRENT_TREESTAND_CLASS = "2"  # "Nykytilan puusto" = current, as opposed to inventory/forecast

# --- code -> points lookups, derived from the metsätietostandardi code tables ---

FERTILITY_POINTS = {  # kasvupaikka / fertilityclass
    # Weights calibrated against real Cantharellus cibarius sightings from
    # laji.fi (see scripts/calibrate.py): compared against Karkkila's own
    # stand population, MT-fertility sightings landed almost exactly at
    # prevalence (well calibrated already), VT was notably under-weighted
    # here relative to how often real sightings land there, and OMT was
    # somewhat over-weighted relative to its (high) prevalence.
    "1": 17,  # Lehto - lush but often too dense/herby
    "2": 19,  # Lehtomainen kangas (OMT) - good, but not as dominant as raw prevalence suggests
    "3": 25,  # Tuore kangas (MT) - prime, matches real sightings almost exactly
    "4": 18,  # Kuivahko kangas (VT) - real sightings favor this more than expected
    "5": 10,  # Kuiva kangas (CT)
    "6": 3,   # Karukkokangas
    "7": 0,   # Kalliomaa ja hietikko
    "8": 0,   # Lakimetsä ja tunturi
}

DEVELOPMENT_POINTS = {  # developmentclass
    # Calibrated against laji.fi sightings: the oldest, regeneration-ready
    # stands (04) were 4x over-represented at real sighting locations
    # relative to their prevalence -- the strongest single signal in the
    # calibration -- while 03 (previously tied for best) was slightly
    # under-represented. 04 is now the top category instead of 03.
    "02": 10,  # Nuori kasvatusmetsikkö - real sightings avoid this
    "03": 20,  # Varttunut kasvatusmetsikkö - good, but not the top anymore
    "04": 25,  # Uudistuskypsä metsikkö - real sightings favor this most
    "05": 15,  # Suojuspuumetsikkö
    "ER": 18,  # Eri-ikäisrakenteinen
    "S0": 5,   # Siemenpuumetsikkö - too open
    "Y1": 5,   # Ylispuustoinen taimikko
    "T2": 2,   # Taimikko yli 1.3 m - too young
}
EXCLUDED_DEVELOPMENT = {"A0", "T1"}  # Aukea, Taimikko alle 1.3 m

SOIL_POINTS = {  # soiltype, coarse/well-drained mineral soils score best
    "10": 15, "11": 15, "12": 15, "30": 14, "31": 14, "32": 14,
    "20": 9, "21": 9, "22": 9, "23": 8, "24": 7, "40": 8,
    "50": 8,
}

DRAINAGE_MULTIPLIER = {  # drainagestate
    "1": 1.0,  # Ojittamaton kangas - natural
    "3": 0.8,  # Ojitettu kangas - ditched, altered hydrology
    "2": 0.5,  # Soistunut kangas - paludified
}

EXCLUDED_SUBGROUP = {"2", "3", "4", "5"}  # Korpi, Räme, Neva, Letto - mire types

SPECIES_WEIGHT = {  # treespecies -> mycorrhizal-partner weight for kantarelli
    # Calibrated against real laji.fi sightings (scripts/calibrate.py):
    # Mänty-dominant stands were 2x over-represented at real sighting
    # locations relative to their prevalence -- pine is a much stronger
    # chanterelle host here than a low weight would suggest, raised sharply.
    # Lehtipuu (unspecified broadleaf) was previously raised on the
    # assumption that unresolved broadleaf is mostly birch, but real
    # sightings are 10x LESS common there than prevalence would predict --
    # that assumption doesn't hold up against the data, so it's lowered
    # back down, below its original default even.
    "2": 1.0,   # Kuusi / Norway spruce - main host, matches real sightings closely
    "1": 0.75,  # Mänty / Scots pine - real sightings show this is a strong host too
    "3": 0.6,   # Rauduskoivu / silver birch (too few sightings to recalibrate)
    "4": 0.6,   # Hieskoivu / downy birch (too few sightings to recalibrate)
    "30": 0.4,  # Havupuu / unspecified conifer - no sighting data to calibrate against
    "29": 0.2,  # Lehtipuu / unspecified broadleaf - real sightings clearly avoid this
}
DEFAULT_SPECIES_WEIGHT = 0.1

TREESPECIES_LABELS = {
    "1": "Mänty", "2": "Kuusi", "3": "Rauduskoivu", "4": "Hieskoivu",
    "5": "Haapa", "6": "Harmaaleppä", "7": "Tervaleppä",
    "29": "Lehtipuu", "30": "Havupuu",
}


def load_layers():
    stand = gpd.read_file(GPKG_PATH, layer="stand")[["standid", "area", "geometry"]]
    growthplace = gpd.read_file(GPKG_PATH, layer="growthplacedata")[
        ["standid", "maingroup", "subgroup", "fertilityclass", "soiltype", "drainagestate"]
    ]
    treestand = gpd.read_file(GPKG_PATH, layer="treestand")
    treestand = treestand[treestand["treestandclass"] == CURRENT_TREESTAND_CLASS][
        ["treestandid", "standid", "developmentclass"]
    ]
    treestandsummary = gpd.read_file(GPKG_PATH, layer="treestandsummary")[
        ["treestandid", "age"]
    ]
    treestratum = gpd.read_file(GPKG_PATH, layer="treestratum")[
        ["treestandid", "treespecies", "basalarea"]
    ]
    return stand, growthplace, treestand, treestandsummary, treestratum


def compute_species_mix(treestand: pd.DataFrame, treestratum: pd.DataFrame) -> pd.DataFrame:
    current_ids = set(treestand["treestandid"])
    tt = treestratum[treestratum["treestandid"].isin(current_ids)].copy()
    tt["basalarea"] = tt["basalarea"].fillna(0)
    tt["weight"] = tt["treespecies"].map(SPECIES_WEIGHT).fillna(DEFAULT_SPECIES_WEIGHT)

    totals = tt.groupby("treestandid")["basalarea"].sum().rename("total_ba")
    weighted = (tt["basalarea"] * tt["weight"]).groupby(tt["treestandid"]).sum().rename("weighted_ba")

    dominant_idx = tt.groupby("treestandid")["basalarea"].idxmax()
    dominant = tt.loc[dominant_idx, ["treestandid", "treespecies"]].set_index("treestandid")
    dominant["dominant_species"] = dominant["treespecies"].map(TREESPECIES_LABELS).fillna("Muu")

    mix = pd.concat([totals, weighted], axis=1).join(dominant["dominant_species"])
    mix["species_fraction"] = (mix["weighted_ba"] / mix["total_ba"]).clip(upper=1).fillna(0)
    return mix.reset_index()


def score_stands(stand, growthplace, treestand, treestandsummary, treestratum) -> gpd.GeoDataFrame:
    species_mix = compute_species_mix(treestand, treestratum)

    df = stand.merge(growthplace, on="standid", how="left")
    df = df.merge(treestand, on="standid", how="left")
    df = df.merge(treestandsummary, on="treestandid", how="left")
    df = df.merge(species_mix, on="treestandid", how="left")

    excluded = (
        (df["maingroup"] != "1")
        | df["subgroup"].isin(EXCLUDED_SUBGROUP)
        | df["developmentclass"].isin(EXCLUDED_DEVELOPMENT)
        | df["fertilityclass"].isin({"7", "8"})
    )

    fertility_score = df["fertilityclass"].map(FERTILITY_POINTS).fillna(6)
    development_score = df["developmentclass"].map(DEVELOPMENT_POINTS).fillna(8)
    soil_score = df["soiltype"].map(SOIL_POINTS).fillna(7)
    drainage_mult = df["drainagestate"].map(DRAINAGE_MULTIPLIER).fillna(0.2)
    species_score = 25 * df["species_fraction"].fillna(0.3)

    df["score"] = (
        fertility_score + development_score + species_score + soil_score * drainage_mult
    ).round(1)
    df.loc[excluded, "score"] = 0
    df["excluded"] = excluded

    # 0-1 ratios of each factor's contribution relative to its own max (25 for
    # all three), used to badge individual popup fields on the map
    df["fertility_ratio"] = (fertility_score / 25).round(2)
    df["development_ratio"] = (development_score / 25).round(2)
    df["species_ratio"] = (species_score / 25).round(2)

    return gpd.GeoDataFrame(df, geometry="geometry", crs=stand.crs)


def categorize(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rank non-excluded stands against each other rather than using fixed
    score thresholds: Karkkila's forest land is overwhelmingly mesic,
    coarse-mineral-soil spruce/mixed forest, so the raw weighted score
    clusters densely in the 70-90 range and a fixed cutoff would flag most
    of the municipality as "high". Relative ranking keeps the map useful
    for actually choosing where to go.
    """
    gdf["category"] = "excluded"
    non_excluded = ~gdf["excluded"]
    ranked = gdf.loc[non_excluded, "score"].rank(pct=True)
    gdf.loc[non_excluded, "category"] = pd.cut(
        ranked, bins=[0, 0.5, 0.85, 1.0], labels=["low", "medium", "high"], include_lowest=True
    )
    return gdf


def add_esker_bonus(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if not GTK_FORMATIONS_PATH.exists():
        gdf["near_esker"] = False
        return gdf
    formations = gpd.read_file(GTK_FORMATIONS_PATH).to_crs(gdf.crs)
    buffered = formations.buffer(ESKER_BUFFER_M).union_all()
    centroids = gdf.geometry.centroid
    gdf["near_esker"] = centroids.within(buffered)
    bonus = gdf["near_esker"] & (~gdf["excluded"])
    gdf.loc[bonus, "score"] = (gdf.loc[bonus, "score"] + 10).clip(upper=100)
    return gdf


LABELS = {
    "fertilityclass": {
        "1": "Lehto", "2": "Lehtomainen kangas (OMT)", "3": "Tuore kangas (MT)",
        "4": "Kuivahko kangas (VT)", "5": "Kuiva kangas (CT)", "6": "Karukkokangas",
    },
    "developmentclass": {
        "02": "Nuori kasvatusmetsikkö", "03": "Varttunut kasvatusmetsikkö",
        "04": "Uudistuskypsä metsikkö", "05": "Suojuspuumetsikkö",
        "ER": "Eri-ikäisrakenteinen", "S0": "Siemenpuumetsikkö",
        "Y1": "Ylispuustoinen taimikko", "T2": "Taimikko",
    },
}


def to_geojson_dict(gdf: gpd.GeoDataFrame) -> dict:
    # the map only ever shows "high"/"medium" (no user toggle for "low"), so
    # there's no reason to ship "low" stands to the client at all
    keep = gdf[gdf["category"].isin(["high", "medium"])].copy()

    # centroid computed in the planar CRS (before simplify/reproject) so it's a
    # true geometric centroid, used as the Google Maps navigation destination
    centroid_4326 = keep.geometry.centroid.to_crs(4326)
    keep["lat"] = centroid_4326.y.round(6)
    keep["lon"] = centroid_4326.x.round(6)

    keep["geometry"] = keep["geometry"].simplify(2.0)
    keep = keep.to_crs(4326)

    keep["fertility_label"] = keep["fertilityclass"].map(LABELS["fertilityclass"]).fillna("?")
    keep["development_label"] = keep["developmentclass"].map(LABELS["developmentclass"]).fillna("?")
    keep["area_ha"] = keep["area"].round(2)
    keep["age"] = keep["age"].round(0)

    out_cols = [
        "standid", "score", "category", "fertility_label", "development_label",
        "dominant_species", "age", "area_ha", "near_esker", "lat", "lon", "geometry",
        "fertility_ratio", "development_ratio", "species_ratio",
    ]
    keep = keep[out_cols]
    return json.loads(keep.to_json())


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Karkkila kantarelli-todennäköisyyskartta</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
  html, body { margin: 0; height: 100%; font-family: sans-serif; }
  #map { height: 100%; }

  .legend { position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000;
            background: white; box-shadow: 0 -1px 6px rgba(0,0,0,.3);
            padding: 10px 40px calc(10px + env(safe-area-inset-bottom, 0px)) 14px;
            font-size: 16px; line-height: 1.4; }
  .legend b { display: block; }
  .legend-row { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 16px; margin-top: 4px; }
  .legend span.swatch { display: inline-block; width: 14px; height: 14px; margin-right: 4px; vertical-align: middle; border-radius: 3px; }
  .legend small { display: block; margin-top: 4px; font-size: 13px; color: #444; }
  .legend-close { position: absolute; top: 6px; right: 8px; width: 28px; height: 28px; border: none; background: none;
                  font-size: 20px; line-height: 28px; color: #888; cursor: pointer; }

  .my-location-dot { width: 16px; height: 16px; border-radius: 50%; background: #1a73e8; border: 2px solid white; box-shadow: 0 0 0 2px rgba(26,115,232,.5); }

  .leaflet-popup-content-wrapper { padding: 0; border-radius: 12px; overflow: hidden; }
  .leaflet-popup-content { margin: 0; font-size: 16px; line-height: 1.5; min-width: 230px; }
  .leaflet-popup-close-button {
    color: white !important; background: rgba(0,0,0,.2); border-radius: 50%;
    top: 8px !important; right: 8px !important; font-size: 20px !important;
    width: 26px !important; height: 26px !important; line-height: 24px !important; text-align: center;
  }
  .leaflet-popup-close-button:hover { background: rgba(0,0,0,.35); color: white !important; }
  .popup-header { padding: 12px 40px 12px 16px; color: white !important; display: flex; justify-content: space-between; align-items: baseline; }
  .popup-header .popup-score { font-size: 20px; font-weight: bold; }
  .popup-body { padding: 10px 16px; }
  .popup-field { padding: 7px 0; border-bottom: 1px solid #eee; }
  .popup-field:last-child { border-bottom: none; }
  .popup-label { display: block; color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
  .popup-value { display: block; margin-top: 2px; }
  .score-badge { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-left: 7px; vertical-align: middle; }
  .score-badge.good { background: #1a73e8; }
  .score-badge.mid { background: #e0a72e; }
  .score-badge.poor { background: #d64545; }
  .gmaps-btn { display: block; text-align: center; margin-top: 10px; padding: 9px 12px; background: #1a73e8; color: white !important; border-radius: 6px; text-decoration: none; font-size: 15px; font-weight: bold; }
</style>
</head>
<body>
<div id="map"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const STANDS = __GEOJSON__;

const COLORS = { high: "#1a7a2e", medium: "#d9a441" };
const CATEGORY_LABELS = { high: "Korkea", medium: "Kohtalainen" };

const map = L.map('map', { preferCanvas: true, zoomControl: false });
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors',
  maxZoom: 19,
}).addTo(map);

function style(feature) {
  const cat = feature.properties.category;
  return {
    color: COLORS[cat] || "#999",
    weight: feature.properties.near_esker ? 2 : 1,
    fillColor: COLORS[cat] || "#999",
    fillOpacity: cat === "high" ? 0.55 : 0.35,
  };
}

// ratio is this field's contribution to the score, 0-1 relative to its own
// max -- null means "not a scored factor" (Ikä/Ala), so no badge is shown
function scoreBadge(ratio) {
  if (ratio == null) return "";
  const tier = ratio >= 0.65 ? "good" : ratio >= 0.3 ? "mid" : "poor";
  return `<span class="score-badge ${tier}" title="Vaikutus pisteisiin: ${tier}"></span>`;
}

function popupRow(label, value, ratio) {
  return `<div class="popup-field"><span class="popup-label">${label}</span>` +
    `<span class="popup-value">${value}${scoreBadge(ratio)}</span></div>`;
}

// Finland uses "," as the decimal separator
function fiNum(n) {
  return String(n).replace(".", ",");
}

function onEachFeature(feature, layer) {
  const p = feature.properties;
  const rows = [
    popupRow("Kasvupaikka", p.fertility_label, p.fertility_ratio),
    popupRow("Kehitysluokka", p.development_label, p.development_ratio),
    popupRow("Vallitseva puulaji", p.dominant_species, p.species_ratio),
    popupRow("Ikä", `${p.age ?? "?"} v`),
    popupRow("Ala", `${fiNum(p.area_ha)} ha`),
  ];
  if (p.near_esker) rows.push(popupRow("Sijainti", "Lähellä harju-/reunamuodostumaa", 1));

  layer.bindPopup(
    `<div class="popup-header" style="background:${COLORS[p.category] || "#666"}">` +
    `<span>${CATEGORY_LABELS[p.category] || p.category}</span>` +
    `<span class="popup-score">${fiNum(p.score)}/100</span>` +
    `</div>` +
    `<div class="popup-body">` +
    rows.join("") +
    `<a class="gmaps-btn" target="_blank" rel="noopener" ` +
    `href="https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lon}&travelmode=driving">` +
    `Navigoi tänne (Google Maps)</a>` +
    `</div>`,
    { minWidth: 230 }
  );
}

// no layer toggle: STANDS already only contains "high"/"medium" stands
const layer = L.geoJSON(STANDS, { style, onEachFeature }).addTo(map);
map.fitBounds(layer.getBounds());

const legend = document.createElement("div");
legend.className = "legend";
legend.innerHTML =
  '<button class="legend-close" aria-label="Piilota selite">×</button>' +
  "<b>Kantarelli-todennäköisyys</b>" +
  '<div class="legend-row">' +
  `<span><span class="swatch" style="background:${COLORS.high}"></span>Korkea</span>` +
  `<span><span class="swatch" style="background:${COLORS.medium}"></span>Kohtalainen</span>` +
  "<span>Paksu reuna = lähellä harjumuodostumaa</span>" +
  "</div>" +
  "<small>Metsäkuvioiden ekologisiin tunnuksiin (kasvupaikka, puusto, maaperä) perustuva arvio - ei mittaustietoa itiöemistä.</small>";
document.body.appendChild(legend);

// closing hides it for the rest of this page view; no reopen button, since a
// floating "reopen" button ended up sitting awkwardly over the map itself
legend.querySelector(".legend-close").addEventListener("click", () => {
  legend.hidden = true;
});

// Live location: read the browser's geolocation and refresh a "you are here"
// dot every 30s. file:// and localhost both count as secure contexts, so
// this works when the map is opened straight from disk.
const LOCATION_REFRESH_MS = 30000;
let locationMarker = null;
let accuracyCircle = null;
let firstFix = true;

function updateLocation() {
  if (!("geolocation" in navigator)) {
    console.warn("Geolocation not supported by this browser.");
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const latlng = [pos.coords.latitude, pos.coords.longitude];
      if (!locationMarker) {
        locationMarker = L.marker(latlng, {
          icon: L.divIcon({ className: "", html: '<div class="my-location-dot"></div>', iconSize: [16, 16] }),
          zIndexOffset: 1000,
        }).addTo(map).bindPopup("Nykyinen sijainti");
        accuracyCircle = L.circle(latlng, { radius: pos.coords.accuracy, color: "#1a73e8", weight: 1, fillOpacity: 0.1 }).addTo(map);
      } else {
        locationMarker.setLatLng(latlng);
        accuracyCircle.setLatLng(latlng).setRadius(pos.coords.accuracy);
      }
      if (firstFix) {
        map.setView(latlng, 15);
        firstFix = false;
      }
    },
    (err) => console.warn("Sijainnin haku epaonnistui:", err.message),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
  );
}

updateLocation();
setInterval(updateLocation, LOCATION_REFRESH_MS);
</script>
</body>
</html>
"""


def render_html(geojson_dict: dict) -> str:
    return HTML_TEMPLATE.replace("__GEOJSON__", json.dumps(geojson_dict, ensure_ascii=False))


def main() -> None:
    stand, growthplace, treestand, treestandsummary, treestratum = load_layers()
    scored = score_stands(stand, growthplace, treestand, treestandsummary, treestratum)
    scored = add_esker_bonus(scored)
    scored = categorize(scored)

    print(scored["category"].value_counts(dropna=False))

    OUTPUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    geojson_dict = to_geojson_dict(scored)
    OUTPUT_GEOJSON.write_text(json.dumps(geojson_dict, ensure_ascii=False), encoding="utf-8")
    OUTPUT_HTML.write_text(render_html(geojson_dict), encoding="utf-8")
    print(f"Wrote {OUTPUT_GEOJSON}")
    print(f"Wrote {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
