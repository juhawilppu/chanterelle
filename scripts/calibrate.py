"""Calibrate the chanterelle habitat scoring model against real sighting data.

Not used to place pins on the map -- used as a check on the model itself.
Pulls real Cantharellus cibarius (kantarelli) observation coordinates from
laji.fi (FinBIF) across a region ecologically comparable to Karkkila
(southern Finland; Karkkila alone has too few sightings to be useful), looks
up the actual forest stand each sighting landed in via Metsakeskus's
point-queryable WFS, and compares that distribution (fertility class,
development class, species mix, soil, drainage) against Karkkila's own stand
population as the "available habitat" background. Categories that are
over-represented at real sighting locations relative to background support
the model's weighting for that factor; under-represented ones call it into
question.

Requires a free laji.fi API token in .env as LAJI_FI_TOKEN (see README).
"""

import json
import os
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import Point, shape

import build_map as bm

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "cache" / "kantarelli_sightings_with_stands.json"

# Uusimaa + neighbouring Kanta-Hame/Paijat-Hame/western Varsinais-Suomi: the
# same southern-Finland managed-forest zone Karkkila sits in, so comparing
# sighting locations against Karkkila's own stand population is apples-to-apples
BBOX_WGS84 = "60.0:61.3:22.5:26.0:WGS84"
COORDINATE_ACCURACY_MAX_M = 1000

LAJI_API = "https://api.laji.fi/v0/warehouse/query/unit/list"
MK_WFS = "https://avoin.metsakeskus.fi/rajapinnat/v1/stand/ows"

WGS84_TO_TM35FIN = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)


def load_token() -> str:
    env_path = ROOT / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("LAJI_FI_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("LAJI_FI_TOKEN not found in .env")


def fetch_sightings(token: str) -> list[dict]:
    sightings = []
    page = 1
    while True:
        resp = requests.get(LAJI_API, params={
            "target": "Cantharellus cibarius",
            "coordinates": BBOX_WGS84,
            "coordinateAccuracyMax": COORDINATE_ACCURACY_MAX_M,
            "pageSize": 1000,
            "page": page,
            "access_token": token,
        }, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        for r in data["results"]:
            pt = r.get("gathering", {}).get("conversions", {}).get("wgs84CenterPoint")
            if pt:
                sightings.append({"lat": pt["lat"], "lon": pt["lon"], "date": r["gathering"].get("displayDateTime")})
        print(f"  page {page}/{data['lastPage']}: {len(data['results'])} records")
        if page >= data["lastPage"]:
            break
        page += 1
    return sightings


def lookup_stand(x: float, y: float, buffer_m: float = 25) -> dict | None:
    bbox = f"{x-buffer_m},{y-buffer_m},{x+buffer_m},{y+buffer_m},EPSG:3067"
    resp = requests.get(MK_WFS, params={
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "v1:stand", "outputFormat": "application/json",
        "srsName": "EPSG:3067", "bbox": bbox,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    point = Point(x, y)
    for feature in data.get("features", []):
        geom = shape(feature["geometry"])
        if geom.contains(point):
            return feature["properties"]
    return None


def build_sightings_with_stands(token: str) -> pd.DataFrame:
    if CACHE_PATH.exists():
        print(f"Using cached {CACHE_PATH}")
        return pd.DataFrame(json.loads(CACHE_PATH.read_text()))

    print("Fetching sightings from laji.fi ...")
    sightings = fetch_sightings(token)
    print(f"{len(sightings)} sightings with coordinates")

    rows = []
    for i, s in enumerate(sightings):
        x, y = WGS84_TO_TM35FIN.transform(s["lon"], s["lat"])
        try:
            stand = lookup_stand(x, y)
        except requests.RequestException as e:
            print(f"  [{i}] WFS lookup failed: {e}")
            stand = None
        if stand:
            rows.append({**s, **stand})
        if (i + 1) % 50 == 0:
            print(f"  looked up {i + 1}/{len(sightings)} ({len(rows)} matched a stand)")
        time.sleep(0.05)  # be polite to the WFS

    df = pd.DataFrame(rows)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(df.to_json(orient="records"))
    print(f"Matched {len(df)}/{len(sightings)} sightings to a forest stand. Cached to {CACHE_PATH}")
    return df


def karkkila_background() -> pd.DataFrame:
    stand, growthplace, treestand, treestandsummary, treestratum = bm.load_layers()
    scored = bm.score_stands(stand, growthplace, treestand, treestandsummary, treestratum)
    return scored[~scored["excluded"]].copy()


def compare(field: str, presence: pd.Series, background: pd.Series, labels: dict | None = None) -> None:
    p = presence.value_counts(normalize=True)
    b = background.value_counts(normalize=True)
    both = pd.concat([p, b], axis=1, keys=["presence_%", "background_%"]).fillna(0) * 100
    both["enrichment"] = (both["presence_%"] / both["background_%"].replace(0, float("nan"))).round(2)
    both = both.sort_values("presence_%", ascending=False).round(1)
    if labels:
        both.index = [labels.get(i, i) for i in both.index]
    print(f"\n=== {field} ===")
    print(both)


def to_code_str(series: pd.Series) -> pd.Series:
    """WFS numeric codes -> the same string-coded space growthplacedata uses."""
    return series.dropna().astype(float).astype(int).astype(str)


def main() -> None:
    token = load_token()
    df = build_sightings_with_stands(token)
    bg = karkkila_background()

    print(f"\n{len(df)} sightings matched to a stand; {len(bg)} Karkkila stands as background")

    compare("Kasvupaikka (fertilityclass)", to_code_str(df["FERTILITYCLASS"]), bg["fertilityclass"], bm.LABELS["fertilityclass"])
    compare("Kehitysluokka (developmentclass)", df["DEVELOPMENTCLASS"], bg["developmentclass"], bm.LABELS["developmentclass"])
    compare("Vallitseva puulaji (main species)", to_code_str(df["MAINTREESPECIES"]).map(bm.TREESPECIES_LABELS).fillna("Muu"),
            bg["dominant_species"])
    compare("Maaryhma (subgroup, 1=kangas)", to_code_str(df["SUBGROUP"]), bg["subgroup"])
    compare("Kuivatustilanne (drainagestate)", to_code_str(df["DRAINAGESTATE"]), bg["drainagestate"])

    print("\n=== mean PROPORTIONSPRUCE / PROPORTIONPINE / PROPORTIONOTHER at sighting locations ===")
    print(df[["PROPORTIONSPRUCE", "PROPORTIONPINE", "PROPORTIONOTHER"]].mean().round(3))


if __name__ == "__main__":
    main()
