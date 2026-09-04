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

# --- code -> points lookups, derived from the metsatietostandardi code tables ---

FERTILITY_POINTS = {  # kasvupaikka / fertilityclass
    "1": 15,  # Lehto - lush but often too dense/herby
    "2": 25,  # Lehtomainen kangas (OMT) - prime
    "3": 25,  # Tuore kangas (MT) - prime
    "4": 12,  # Kuivahko kangas (VT)
    "5": 5,   # Kuiva kangas (CT)
    "6": 0,   # Karukkokangas
    "7": 0,   # Kalliomaa ja hietikko
    "8": 0,   # Lakimetsa ja tunturi
}

DEVELOPMENT_POINTS = {  # developmentclass
    "02": 15,  # Nuori kasvatusmetsikko
    "03": 25,  # Varttunut kasvatusmetsikko - prime
    "04": 22,  # Uudistuskypsa metsikko - prime
    "05": 15,  # Suojuspuumetsikko
    "ER": 18,  # Eri-ikaisrakenteinen
    "S0": 5,   # Siemenpuumetsikko - too open
    "Y1": 5,   # Ylispuustoinen taimikko
    "T2": 3,   # Taimikko yli 1.3 m - too young
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

EXCLUDED_SUBGROUP = {"2", "3", "4", "5"}  # Korpi, Rame, Neva, Letto - mire types

SPECIES_WEIGHT = {  # treespecies -> mycorrhizal-partner weight for kantarelli
    "2": 1.0,   # Kuusi / Norway spruce - main host
    "3": 0.6,   # Rauduskoivu / silver birch
    "4": 0.6,   # Hieskoivu / downy birch
    "1": 0.25,  # Manty / Scots pine
}
DEFAULT_SPECIES_WEIGHT = 0.1

TREESPECIES_LABELS = {
    "1": "manty", "2": "kuusi", "3": "rauduskoivu", "4": "hieskoivu",
    "5": "haapa", "6": "harmaaleppa", "7": "tervaleppa",
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
    dominant["dominant_species"] = dominant["treespecies"].map(TREESPECIES_LABELS).fillna("muu")

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
        "02": "Nuori kasvatusmetsikko", "03": "Varttunut kasvatusmetsikko",
        "04": "Uudistuskypsa metsikko", "05": "Suojuspuumetsikko",
        "ER": "Eri-ikaisrakenteinen", "S0": "Siemenpuumetsikko",
        "Y1": "Ylispuustoinen taimikko", "T2": "Taimikko",
    },
}


def to_geojson_dict(gdf: gpd.GeoDataFrame) -> dict:
    keep = gdf[~gdf["excluded"]].copy()
    keep["geometry"] = keep["geometry"].simplify(2.0)
    keep = keep.to_crs(4326)

    keep["fertility_label"] = keep["fertilityclass"].map(LABELS["fertilityclass"]).fillna("?")
    keep["development_label"] = keep["developmentclass"].map(LABELS["developmentclass"]).fillna("?")
    keep["area_ha"] = keep["area"].round(2)
    keep["age"] = keep["age"].round(0)

    out_cols = [
        "standid", "score", "category", "fertility_label", "development_label",
        "dominant_species", "age", "area_ha", "near_esker", "geometry",
    ]
    keep = keep[out_cols]
    return json.loads(keep.to_json())


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Karkkila kantarelli-todennakoisyyskartta</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
  html, body { margin: 0; height: 100%; font-family: sans-serif; }
  #map { height: 100%; }
  .legend { background: white; padding: 8px 12px; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,.4); font-size: 13px; line-height: 1.5; }
  .legend span { display: inline-block; width: 14px; height: 14px; margin-right: 6px; vertical-align: middle; border-radius: 3px; }
  .my-location-dot { width: 16px; height: 16px; border-radius: 50%; background: #1a73e8; border: 2px solid white; box-shadow: 0 0 0 2px rgba(26,115,232,.5); }
</style>
</head>
<body>
<div id="map"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const STANDS = __GEOJSON__;

const COLORS = { high: "#1a7a2e", medium: "#d9a441", low: "#9a9a9a" };

const map = L.map('map', { preferCanvas: true });
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
    fillOpacity: cat === "high" ? 0.55 : cat === "medium" ? 0.35 : 0.15,
  };
}

function onEachFeature(feature, layer) {
  const p = feature.properties;
  layer.bindPopup(
    `<b>Pisteet: ${p.score} / 100 (${p.category})</b><br>` +
    `Kasvupaikka: ${p.fertility_label}<br>` +
    `Kehitysluokka: ${p.development_label}<br>` +
    `Vallitseva puulaji: ${p.dominant_species}<br>` +
    `Ika: ${p.age ?? "?"} v, Ala: ${p.area_ha} ha` +
    (p.near_esker ? "<br>Lahella harju-/reunamuodostumaa" : "")
  );
}

const layer = L.geoJSON(STANDS, { style, onEachFeature }).addTo(map);
map.fitBounds(layer.getBounds());

const overlays = {
  "Korkea todennakoisyys": L.geoJSON(STANDS, {
    filter: f => f.properties.category === "high", style, onEachFeature,
  }),
  "Kohtalainen todennakoisyys": L.geoJSON(STANDS, {
    filter: f => f.properties.category === "medium", style, onEachFeature,
  }),
  "Matala todennakoisyys": L.geoJSON(STANDS, {
    filter: f => f.properties.category === "low", style, onEachFeature,
  }),
};
// swap the combined layer for the three toggleable ones; "low" starts hidden to keep the map readable
map.removeLayer(layer);
overlays["Korkea todennakoisyys"].addTo(map);
overlays["Kohtalainen todennakoisyys"].addTo(map);
L.control.layers(null, overlays, { collapsed: false }).addTo(map);

const legend = L.control({ position: "bottomright" });
legend.onAdd = function () {
  const div = L.DomUtil.create("div", "legend");
  div.innerHTML =
    "<b>Kantarelli-todennakoisyys</b><br>" +
    `<span style="background:${COLORS.high}"></span> Korkea<br>` +
    `<span style="background:${COLORS.medium}"></span> Kohtalainen<br>` +
    `<span style="background:${COLORS.low}"></span> Matala<br>` +
    "Paksumpi reunaviiva = lahella harjumuodostumaa<br>" +
    "<small>Metsakuvioiden ekologisiin tunnuksiin (kasvupaikka, puusto, maapera) perustuva arvio - ei mittaustietoa itiemista.</small>";
  return div;
};
legend.addTo(map);

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
    return HTML_TEMPLATE.replace("__GEOJSON__", json.dumps(geojson_dict))


def main() -> None:
    stand, growthplace, treestand, treestandsummary, treestratum = load_layers()
    scored = score_stands(stand, growthplace, treestand, treestandsummary, treestratum)
    scored = add_esker_bonus(scored)
    scored = categorize(scored)

    print(scored["category"].value_counts(dropna=False))

    OUTPUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    geojson_dict = to_geojson_dict(scored)
    OUTPUT_GEOJSON.write_text(json.dumps(geojson_dict))
    OUTPUT_HTML.write_text(render_html(geojson_dict))
    print(f"Wrote {OUTPUT_GEOJSON}")
    print(f"Wrote {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
