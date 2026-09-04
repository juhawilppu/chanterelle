"""Download the source datasets for the chanterelle habitat map.

Sources:
- Suomen metsäkeskus (Finnish Forest Centre) open forest resource data
  (metsävarakuviot), municipality-level GeoPackage.
- GTK (Geological Survey of Finland) glaciofluvial / moraine formation
  polygons (eskers etc.), fetched by bounding box from their ArcGIS REST
  service, clipped to the extent of the forest stand data above.

Both are cached under data/ so re-running this script is a no-op unless
the cache is deleted.
"""

import zipfile
from pathlib import Path

import geopandas as gpd
import requests

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


def main() -> None:
    gpkg_path = download_forest_stand_data()
    stand = gpd.read_file(gpkg_path, layer="stand")
    download_gtk_formations(tuple(stand.total_bounds))


if __name__ == "__main__":
    main()
