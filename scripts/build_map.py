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
import numpy as np
import pandas as pd

MUNICIPALITY = "Karkkila"

ROOT = Path(__file__).resolve().parent.parent
GPKG_PATH = ROOT / "data" / "raw" / f"MV_{MUNICIPALITY}" / f"MV_{MUNICIPALITY}.gpkg"
GTK_FORMATIONS_PATH = ROOT / "data" / "cache" / f"gtk_formations_{MUNICIPALITY}.geojson"
LAJI_SIGHTINGS_PATH = ROOT / "data" / "cache" / f"laji_sightings_{MUNICIPALITY}.json"
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
    "70": 7,  # Multamaa - organic-rich, holds moisture, middling for kantarelli
}

DRAINAGE_MULTIPLIER = {  # drainagestate
    "1": 1.0,  # Ojittamaton kangas - natural
    "3": 0.8,  # Ojitettu kangas - ditched, altered hydrology
    "2": 0.5,  # Soistunut kangas - paludified
}

EXCLUDED_SUBGROUP = {"2", "3", "4", "5"}  # Korpi, Räme, Neva, Letto - mire types

# Canopy openness ("valoisuus") response to stem density, as a piecewise-linear
# curve calibrated against stem counts at real laji.fi sighting locations:
# too sparse = no living mycorrhizal host, too dense = no light on the floor.
LIGHT_STEMCOUNT_KNOTS = [0, 100, 400, 800, 2000]
LIGHT_OPENNESS_KNOTS = [0.25, 0.25, 1.0, 1.0, 0.0]
# Single source of truth for "this factor is green". Used both by the
# "Excellent" rule (every factor green) and injected into the map's JS for the
# popup badges, so the category and the dots can never disagree -- they did
# once, and a stand showing a yellow dot still counted as all-green.
GREEN_THRESHOLDS = {
    "fertility": 0.65,
    "development": 0.65,
    "species": 0.65,
    "mixture": 0.55,   # Gini-Simpson tops out near 0.67 in practice
    "light": 0.75,     # roughly 325-1100 stems/ha, the empirically enriched band
    "soil": 0.65,
}
MID_THRESHOLD = 0.3
LIGHT_GOOD_THRESHOLD = GREEN_THRESHOLDS["light"]
LIGHT_MID_THRESHOLD = MID_THRESHOLD

# Share of the raw point total a stand keeps when one factor is at rock
# bottom. 1.0 would be a pure sum (full compensation between factors);
# lower values make the worst factor bite harder.
LIMITING_FLOOR = 0.7

# Point budget per factor. Kept explicit so the "x/100" shown on the map stays
# honest when factors are added or reweighted.
ESKER_BONUS_POINTS = 10
MAX_RAW_SCORE = (
    25   # fertility (kasvupaikka)
    + 25  # development class (kehitysluokka)
    + 10  # species host quality
    + 15  # sekametsä mixture
    + 15  # soil x drainage
    + 10  # valoisuus (canopy openness)
    + ESKER_BONUS_POINTS
)

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
    # stemcount (stems/ha) is used as the canopy-openness ("valoisuus") proxy:
    # a stand can have high basal area from a few big old trees (open, light)
    # or the same basal area from many small crowded ones (dark) -- stem
    # density tells those apart, basal area alone does not
    treestandsummary = gpd.read_file(GPKG_PATH, layer="treestandsummary")[
        ["treestandid", "stemcount"]
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

    # Gini-Simpson diversity index (1 - sum of squared species shares) over
    # actual basal-area composition: 0 = pure monoculture, closer to 1 = a
    # genuine "sekametsä" of several well-balanced species. Independent of
    # SPECIES_WEIGHT/host quality -- this measures mixedness itself.
    species_ba = tt.groupby(["treestandid", "treespecies"])["basalarea"].sum()
    shares = species_ba / species_ba.groupby(level="treestandid").transform("sum")
    diversity = (1 - (shares ** 2).groupby(level="treestandid").sum()).rename("diversity_index")

    mix = pd.concat([totals, weighted, diversity], axis=1).join(dominant["dominant_species"])
    mix["species_fraction"] = (mix["weighted_ba"] / mix["total_ba"]).clip(upper=1).fillna(0)
    mix["diversity_index"] = mix["diversity_index"].fillna(0)
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
    soil_score = df["soiltype"].map(SOIL_POINTS).fillna(7) * df["drainagestate"].map(DRAINAGE_MULTIPLIER).fillna(0.2)
    # species contribution is split into host quality (spruce/pine/birch as a
    # mycorrhizal partner, weighted per SPECIES_WEIGHT) and a separate
    # "sekametsä" mixture bonus (Gini-Simpson diversity of the actual species
    # composition) -- a stand can score well on one without the other. The
    # mixture half now outweighs raw host quality, per specific request to
    # emphasize genuinely mixed forest over a monoculture of the "best" species.
    species_quality_score = 10 * df["species_fraction"].fillna(0.3)
    mixture_score = 15 * df["diversity_index"].fillna(0)
    # "valoisuus" (light reaching the forest floor): repeatedly cited as
    # important in foraging sources ("avoid dense dark forest"), but not
    # captured by development class alone -- a stand can have high basal
    # area from a few big old trees (open) or many small crowded ones
    # (dark) at the same age. Stem density is the proxy, and it peaks in a
    # BAND rather than rising as trees disappear: calibrated against real
    # laji.fi sightings, 74% fall in 300-800 stems/ha (vs 44% of background),
    # dropping off sharply above 800 and effectively absent below 300. A
    # nearly treeless seed-tree stand has plenty of light but no living
    # mycorrhizal host, so it must not score as "maximally light".
    openness = pd.Series(
        np.interp(df["stemcount"], LIGHT_STEMCOUNT_KNOTS, LIGHT_OPENNESS_KNOTS),
        index=df.index,
    ).where(df["stemcount"].notna())
    light_score = 10 * openness.fillna(0.4)

    df["fertility_ratio"] = (fertility_score / 25).round(2)
    df["development_ratio"] = (development_score / 25).round(2)
    df["species_ratio"] = (species_quality_score / 10).round(2)
    df["mixture_ratio"] = df["diversity_index"].round(2)
    df["soil_ratio"] = (soil_score / 15).round(2)
    df["light_ratio"] = (light_score / 10).round(2)

    # Limiting-factor penalty (Liebig's law of the minimum): habitat is
    # limited by its worst attribute, not its average. A plain sum lets a
    # stand offset a fatal weakness -- no light, say -- with two maxed-out
    # factors, which both overrates it ecologically and made some
    # "Erinomainen" stands (green everywhere, maxed nowhere) score below
    # "Korkea" stands carrying a red factor. Each factor is measured against
    # its own green threshold, so "green everywhere" means no penalty at all.
    weakest = pd.concat(
        [(df[f"{factor}_ratio"] / threshold).clip(upper=1)
         for factor, threshold in GREEN_THRESHOLDS.items()],
        axis=1,
    ).min(axis=1).fillna(0)

    raw = (
        fertility_score + development_score + species_quality_score
        + mixture_score + soil_score + light_score
    )
    df["score"] = (raw * (LIMITING_FLOOR + (1 - LIMITING_FLOOR) * weakest)).round(1)
    df.loc[excluded, "score"] = 0
    df["excluded"] = excluded

    return gpd.GeoDataFrame(df, geometry="geometry", crs=stand.crs)


def categorize(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """"Excellent" is a hard rule, not a percentile: every single badged
    factor has to be green (its own "good" threshold, matching what the
    popup actually shows), so an "Excellent" stand is explainable purely by
    "look, everything is green" -- no exceptions or partial credit.

    Everything else ranks against everything else rather than using fixed
    score thresholds: Karkkila's forest land is overwhelmingly mesic,
    coarse-mineral-soil spruce/mixed forest, so the raw weighted score
    clusters densely and a fixed cutoff would flag most of the municipality
    as "high". Relative ranking keeps the map useful for choosing where to go.
    """
    gdf["category"] = "excluded"
    non_excluded = ~gdf["excluded"]

    all_green = gdf["near_esker"].copy()
    for factor, threshold in GREEN_THRESHOLDS.items():
        all_green &= gdf[f"{factor}_ratio"] >= threshold
    excellent = non_excluded & all_green
    gdf.loc[excellent, "category"] = "excellent"

    rest = non_excluded & ~excellent
    ranked = gdf.loc[rest, "score"].rank(pct=True)
    gdf.loc[rest, "category"] = pd.cut(
        ranked, bins=[0, 0.5, 0.85, 1.0], labels=["low", "medium", "high"], include_lowest=True
    )
    return gdf


def add_esker_bonus(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Proximity to glaciofluvial deposits -- eskers, sandurs, deltas,
    ice-contact deposits. The point is the *substrate*, not elevation: these
    are sorted sand and gravel laid down by glacial meltwater rivers, so they
    drain exceptionally well, which is the soil condition Finnish sources tie
    to chanterelle-friendly forest.

    The GTK layer also carries moraine (unsorted till) and littoral deposits.
    Buffering all of them put 62% of Karkkila "near an esker", which made the
    factor almost meaningless -- and moraine is the opposite of the sorted,
    free-draining substrate we are actually looking for. Restricting to
    genuine glaciofluvial deposits brings it to a selective 25%.
    """
    if not GTK_FORMATIONS_PATH.exists():
        gdf["near_esker"] = False
        return gdf
    formations = gpd.read_file(GTK_FORMATIONS_PATH).to_crs(gdf.crs)
    deposit_class = formations["DEPOSIT_TYPE_CLASS"].astype(str)
    glaciofluvial = deposit_class.str.startswith("1") & ~deposit_class.str.startswith("1.5")
    formations = formations[glaciofluvial]
    buffered = formations.buffer(ESKER_BUFFER_M).union_all()
    centroids = gdf.geometry.centroid
    gdf["near_esker"] = centroids.within(buffered)
    bonus = gdf["near_esker"] & (~gdf["excluded"])
    gdf.loc[bonus, "score"] = gdf.loc[bonus, "score"] + ESKER_BONUS_POINTS
    return gdf


def normalize_scores(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rescale the raw point total onto a true 0-100 scale.

    The esker bonus used to be added and then clipped at 100, which silently
    penalised exactly the best stands: once the other factors already summed
    near the 100-point maximum, part of the +10 was thrown away, so an
    excellent stand near an esker got less credit for it than a mediocre one.
    Dividing by the real theoretical maximum keeps every factor's calibrated
    weight intact and keeps the displayed "x/100" honest.
    """
    gdf["score"] = (gdf["score"] / MAX_RAW_SCORE * 100).round(1)
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
    "soiltype": {
        "10": "Karkea kangasmaa", "11": "Karkea moreeni", "12": "Karkea lajittunut maalaji",
        "30": "Kivinen karkea kangasmaa", "31": "Kivinen karkea moreeni", "32": "Kivinen karkea lajittunut maalaji",
        "20": "Hienojakoinen kangasmaa", "21": "Hienoainesmoreeni", "22": "Hienojakoinen lajittunut maalaji",
        "23": "Silttipitoinen maalaji", "24": "Savimaa", "40": "Kivinen hienojakoinen kangasmaa",
        "50": "Kallio/kivikko",
    },
    "drainagestate": {
        "1": "ojittamaton", "2": "soistunut", "3": "ojitettu",
    },
}


def mixture_label(diversity_index: float) -> str:
    if diversity_index >= 0.55:
        return "Vahva sekametsä"
    if diversity_index >= 0.3:
        return "Jonkin verran sekapuustoa"
    return "Lähes yksipuulajinen"


def light_label(light_ratio: float, stemcount: float) -> str:
    """Openness peaks in a band, so a low ratio means one of two opposite
    things: too few trees or too many. The label has to say which, or a
    nearly treeless stand would read as "dense, little light".
    """
    if light_ratio >= LIGHT_GOOD_THRESHOLD:
        return "Avoin, valoisa"
    if pd.notna(stemcount) and stemcount < LIGHT_STEMCOUNT_KNOTS[2]:
        return "Hyvin harva puusto"  # too open: little living host left
    if light_ratio >= LIGHT_MID_THRESHOLD:
        return "Melko tiheä"
    return "Tiheä, vähän valoa"


def to_geojson_dict(gdf: gpd.GeoDataFrame) -> dict:
    # the map only ever shows "high"/"medium" (no user toggle for "low"), so
    # there's no reason to ship "low" stands to the client at all
    keep = gdf[gdf["category"].isin(["excellent", "high", "medium"])].copy()

    # centroid computed in the planar CRS (before simplify/reproject) so it's a
    # true geometric centroid, used as the Google Maps navigation destination
    centroid_4326 = keep.geometry.centroid.to_crs(4326)
    keep["lat"] = centroid_4326.y.round(6)
    keep["lon"] = centroid_4326.x.round(6)

    keep["geometry"] = keep["geometry"].simplify(2.0)
    keep = keep.to_crs(4326)

    keep["fertility_label"] = keep["fertilityclass"].map(LABELS["fertilityclass"]).fillna("?")
    keep["development_label"] = keep["developmentclass"].map(LABELS["developmentclass"]).fillna("?")
    keep["soil_label"] = (
        keep["soiltype"].map(LABELS["soiltype"]).fillna("?") + " ("
        + keep["drainagestate"].map(LABELS["drainagestate"]).fillna("?") + ")"
    )
    # label from the same rounded value the badge uses, or values just under a
    # threshold round up to green while the text still says otherwise
    keep["mixture_label"] = keep["mixture_ratio"].map(mixture_label)
    keep["light_label"] = [
        light_label(r, s) for r, s in zip(keep["light_ratio"], keep["stemcount"])
    ]

    # age and area don't feed the score at all (development class already
    # captures stand-age effects; area is purely descriptive) -- not shipped.
    # diversity_index itself isn't shipped either -- mixture_ratio is the
    # same number, already rounded, and nothing client-side needs both.
    out_cols = [
        "standid", "score", "category", "fertility_label", "development_label",
        "dominant_species", "near_esker", "lat", "lon", "geometry",
        "fertility_ratio", "development_ratio", "species_ratio", "mixture_ratio",
        "soil_ratio", "soil_label", "mixture_label",
        "light_ratio", "light_label",
    ]
    keep = keep[out_cols]
    return json.loads(keep.to_json())


def load_sightings_geojson() -> dict:
    if not LAJI_SIGHTINGS_PATH.exists():
        return {"type": "FeatureCollection", "features": []}
    sightings = json.loads(LAJI_SIGHTINGS_PATH.read_text())
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {"date": s["date"], "standid": s["standid"]},
        }
        for s in sightings
    ]
    return {"type": "FeatureCollection", "features": features}


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
  /* text colour is set per category inline: white washes out badly on the
     lighter lime/amber headers, so those get dark text instead */
  .popup-header { padding: 12px 40px 12px 16px; display: flex; justify-content: space-between; align-items: baseline; }
  .popup-header .popup-score { font-size: 20px; font-weight: bold; }
  .popup-body { padding: 10px 16px; }
  .popup-field { padding: 7px 0; border-bottom: 1px solid #eee; }
  .popup-field:last-child { border-bottom: none; }
  .popup-label { display: block; color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
  .popup-value { display: block; margin-top: 2px; }
  .score-badge { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-left: 7px; vertical-align: middle; }
  .score-badge.good { background: #1a7a2e; }
  .score-badge.mid { background: #e0a72e; }
  .score-badge.poor { background: #d64545; }
  .gmaps-btn { display: block; text-align: center; margin-top: 10px; padding: 9px 12px; background: #1a73e8; color: white !important; border-radius: 6px; text-decoration: none; font-size: 15px; font-weight: bold; }
  .sighting-flag { font-size: 20px; line-height: 1; text-shadow: 0 1px 2px rgba(0,0,0,.5); }
</style>
</head>
<body>
<div id="map"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const STANDS = __GEOJSON__;
const SIGHTINGS = __SIGHTINGS__;
const GREEN = __GREEN_THRESHOLDS__;  // injected from Python: single source of truth
const MID = __MID_THRESHOLD__;

// three distinct hues, not shades of the same color -- "Excellent" already
// implies strong sekametsä (it's one of the all-green requirements), so it
// gets its own color rather than a lighter/brighter variant of "Korkea"
const COLORS = { excellent: "#84cc16", high: "#166534", medium: "#d9a441" };
const CATEGORY_LABELS = { excellent: "Erinomainen", high: "Korkea", medium: "Kohtalainen" };
// dark text on the light lime/amber headers, white only on the dark green
const HEADER_TEXT = { excellent: "#1a2e05", high: "#ffffff", medium: "#3d2c06" };
const FILL_OPACITY = { excellent: 0.65, high: 0.5, medium: 0.35 };

const map = L.map('map', { preferCanvas: true, zoomControl: false });
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors',
  maxZoom: 19,
}).addTo(map);

function style(feature) {
  const p = feature.properties;
  return {
    color: COLORS[p.category] || "#999",
    weight: p.near_esker ? 2 : 1,
    fillColor: COLORS[p.category] || "#999",
    fillOpacity: FILL_OPACITY[p.category] ?? 0.35,
  };
}

// ratio is this field's contribution to the score, 0-1 relative to its own
// max -- null means "not a scored factor", so no badge is shown. Thresholds
// come from GREEN/MID, injected from the same Python constants the
// "Erinomainen" rule uses, so a category and its dots can never disagree.
function scoreBadge(ratio, good) {
  if (ratio == null) return "";
  const tier = ratio >= good ? "good" : ratio >= MID ? "mid" : "poor";
  return `<span class="score-badge ${tier}" title="Vaikutus pisteisiin: ${tier}"></span>`;
}

function popupRow(label, value, ratio, good) {
  return `<div class="popup-field"><span class="popup-label">${label}</span>` +
    `<span class="popup-value">${value}${scoreBadge(ratio, good)}</span></div>`;
}

function onEachFeature(feature, layer) {
  const p = feature.properties;
  const rows = [
    popupRow("Kasvupaikka", p.fertility_label, p.fertility_ratio, GREEN.fertility),
    popupRow("Kehitysluokka", p.development_label, p.development_ratio, GREEN.development),
    popupRow("Vallitseva puulaji", p.dominant_species, p.species_ratio, GREEN.species),
    popupRow("Sekametsäisyys", p.mixture_label, p.mixture_ratio, GREEN.mixture),
    popupRow("Valoisuus", p.light_label, p.light_ratio, GREEN.light),
    popupRow("Maaperä", p.soil_label, p.soil_ratio, GREEN.soil),
    // binary factor: green when near an esker, red when not
    popupRow(
      "Sijainti",
      p.near_esker ? "Lähellä harju-/reunamuodostumaa" : "Ei lähellä harjumuodostumaa",
      p.near_esker ? 1 : 0,
      1
    ),
  ];

  layer.bindPopup(
    `<div class="popup-header" style="background:${COLORS[p.category] || "#666"};` +
    `color:${HEADER_TEXT[p.category] || "#fff"}">` +
    `<span>${CATEGORY_LABELS[p.category] || p.category}</span>` +
    `<span class="popup-score">${Math.round(p.score)}/100</span>` +
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

// Real laji.fi kantarelli sighting flags, where a report happens to fall
// inside a stand shown on the map
L.geoJSON(SIGHTINGS, {
  pointToLayer: (feature, latlng) => L.marker(latlng, {
    icon: L.divIcon({ className: "", html: '<div class="sighting-flag">🚩</div>', iconSize: [20, 20], iconAnchor: [4, 18] }),
  }),
  onEachFeature: (feature, layer) => {
    const d = feature.properties.date || "tuntematon ajankohta";
    layer.bindPopup(`<b>Kantarellihavainto</b><br>Ilmoitettu laji.fi-palveluun<br>${d}`);
  },
}).addTo(map);

const legend = document.createElement("div");
legend.className = "legend";
legend.innerHTML =
  '<button class="legend-close" aria-label="Piilota selite">×</button>' +
  "<b>Kantarelli-todennäköisyys</b>" +
  '<div class="legend-row">' +
  `<span><span class="swatch" style="background:${COLORS.excellent}"></span>Erinomainen</span>` +
  `<span><span class="swatch" style="background:${COLORS.high}"></span>Korkea</span>` +
  `<span><span class="swatch" style="background:${COLORS.medium}"></span>Kohtalainen</span>` +
  "<span>Paksu reuna = lähellä harjumuodostumaa</span>" +
  "<span>🚩 = Ilmoitettu löytö (laji.fi)</span>" +
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


def render_html(geojson_dict: dict, sightings_dict: dict) -> str:
    html = HTML_TEMPLATE.replace("__GEOJSON__", json.dumps(geojson_dict, ensure_ascii=False))
    html = html.replace("__SIGHTINGS__", json.dumps(sightings_dict, ensure_ascii=False))
    html = html.replace("__GREEN_THRESHOLDS__", json.dumps(GREEN_THRESHOLDS))
    return html.replace("__MID_THRESHOLD__", json.dumps(MID_THRESHOLD))


def main() -> None:
    stand, growthplace, treestand, treestandsummary, treestratum = load_layers()
    scored = score_stands(stand, growthplace, treestand, treestandsummary, treestratum)
    scored = add_esker_bonus(scored)
    scored = normalize_scores(scored)
    scored = categorize(scored)

    print(scored["category"].value_counts(dropna=False))

    OUTPUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    geojson_dict = to_geojson_dict(scored)
    sightings_dict = load_sightings_geojson()
    OUTPUT_GEOJSON.write_text(json.dumps(geojson_dict, ensure_ascii=False), encoding="utf-8")
    OUTPUT_HTML.write_text(render_html(geojson_dict, sightings_dict), encoding="utf-8")
    print(f"Wrote {OUTPUT_GEOJSON}")
    print(f"Wrote {OUTPUT_HTML}")
    print(f"{len(sightings_dict['features'])} laji.fi sightings embedded as flags")


if __name__ == "__main__":
    main()
