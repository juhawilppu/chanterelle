"""Download the source datasets for the chanterelle habitat map.

Sources:
- Suomen metsäkeskus (Finnish Forest Centre) open forest resource data
  (metsävarakuviot), municipality-level GeoPackage.
- GTK (Geological Survey of Finland) glaciofluvial / moraine formation
  polygons (eskers etc.), fetched by bounding box from their ArcGIS REST
  service, clipped to the extent of the forest stand data above.
- laji.fi (FinBIF) real Cantharellus cibarius sighting coordinates within
  the municipality, for the "reported here" flags on the map. Optional:
  skipped if no LAJI_FI_TOKEN is set in .env.

All are cached under data/ so re-running this script is a no-op unless
the cache is deleted.
"""

import json
import zipfile
from pathlib import Path

import geopandas as gpd
import requests
from pyproj import Transformer
from shapely.geometry import Point

MUNICIPALITY = "Karkkila"

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CACHE_DIR = ROOT / "data" / "cache"

MV_ZIP_URL = f"https://avoin.metsakeskus.fi/aineistot/MV/Kunta/MV_{MUNICIPALITY}.zip"
MV_ZIP_PATH = RAW_DIR / f"MV_{MUNICIPALITY}.zip"
MV_GPKG_DIR = RAW_DIR / f"MV_{MUNICIPALITY}"
MV_GPKG_PATH = MV_GPKG_DIR / f"MV_{MUNICIPALITY}.gpkg"

GTK_FORMATIONS_LAYER_URL = (
    "https://gtkdata.gtk.fi/arcgis/rest/services/Rajapinnat/GTK_Maapera_WFS/"
    "MapServer/60/query"
)
GTK_FORMATIONS_PATH = CACHE_DIR / f"gtk_formations_{MUNICIPALITY}.geojson"

LAJI_API = "https://api.laji.fi/v0/warehouse/query/unit/list"
LAJI_SIGHTINGS_PATH = CACHE_DIR / f"laji_sightings_{MUNICIPALITY}.json"


def download_forest_stand_data() -> Path:
    if not MV_GPKG_PATH.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {MV_ZIP_URL} ...")
        resp = requests.get(MV_ZIP_URL, timeout=120)
        resp.raise_for_status()
        MV_ZIP_PATH.write_bytes(resp.content)
        with zipfile.ZipFile(MV_ZIP_PATH) as zf:
            zf.extractall(MV_GPKG_DIR)
        print(f"Extracted to {MV_GPKG_PATH}")
    else:
        print(f"Using cached {MV_GPKG_PATH}")
    return MV_GPKG_PATH


def download_gtk_formations(bounds_epsg3067: tuple[float, float, float, float]) -> Path:
    if GTK_FORMATIONS_PATH.exists():
        print(f"Using cached {GTK_FORMATIONS_PATH}")
        return GTK_FORMATIONS_PATH

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    xmin, ymin, xmax, ymax = bounds_epsg3067
    params = {
        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 3067,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "DEPOSIT_TYPE_CLASS,DEPOSIT_TYPE,DEPOSIT_TYPE_NAME",
        "outSR": 3067,
        "f": "geojson",
    }
    print("Querying GTK glaciofluvial/moraine formations ...")
    resp = requests.get(GTK_FORMATIONS_LAYER_URL, params=params, timeout=120)
    resp.raise_for_status()
    GTK_FORMATIONS_PATH.write_bytes(resp.content)
    n = len(resp.json().get("features", []))
    print(f"Saved {n} formation polygons to {GTK_FORMATIONS_PATH}")
    return GTK_FORMATIONS_PATH


def load_laji_token() -> str | None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("LAJI_FI_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def download_laji_sightings(stand_gdf: gpd.GeoDataFrame) -> Path | None:
    """Real kantarelli sighting coordinates within this municipality, for the
    "reported here" flags on the map. Optional -- skipped without a token."""
    if LAJI_SIGHTINGS_PATH.exists():
        print(f"Using cached {LAJI_SIGHTINGS_PATH}")
        return LAJI_SIGHTINGS_PATH

    token = load_laji_token()
    if not token:
        print("No LAJI_FI_TOKEN in .env -- skipping laji.fi sighting flags (optional).")
        return None

    minx, miny, maxx, maxy = stand_gdf.to_crs(4326).total_bounds
    coordinates = f"{miny}:{maxy}:{minx}:{maxx}:WGS84"

    print(f"Querying laji.fi for kantarelli sightings within {MUNICIPALITY} ...")
    resp = requests.get(LAJI_API, params={
        "target": "Cantharellus cibarius",
        "coordinates": coordinates,
        "pageSize": 1000,
        "access_token": token,
    }, timeout=60)
    resp.raise_for_status()
    results = resp.json()["results"]

    to_stand_crs = Transformer.from_crs("EPSG:4326", stand_gdf.crs, always_xy=True)
    stand_union = stand_gdf.union_all()
    sightings = []
    for r in results:
        pt = r.get("gathering", {}).get("conversions", {}).get("wgs84CenterPoint")
        if not pt:
            continue
        x, y = to_stand_crs.transform(pt["lon"], pt["lat"])
        point = Point(x, y)
        if not point.within(stand_union):
            continue  # bbox query can return points just outside the municipality
        containing = stand_gdf[stand_gdf.contains(point)]
        standid = int(containing.iloc[0]["standid"]) if len(containing) else None
        sightings.append({
            "lat": pt["lat"], "lon": pt["lon"],
            "date": r["gathering"].get("displayDateTime"),
            "standid": standid,
        })

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LAJI_SIGHTINGS_PATH.write_text(json.dumps(sightings, ensure_ascii=False))
    print(f"Found {len(sightings)} kantarelli sightings within {MUNICIPALITY}. Cached to {LAJI_SIGHTINGS_PATH}")
    return LAJI_SIGHTINGS_PATH


def main() -> None:
    gpkg_path = download_forest_stand_data()
    stand = gpd.read_file(gpkg_path, layer="stand")
    download_gtk_formations(tuple(stand.total_bounds))
    download_laji_sightings(stand)


if __name__ == "__main__":
    main()
