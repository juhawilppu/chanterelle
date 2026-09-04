# Karkkila kantarelli map

Scores forest stands in Karkkila, Finland for chanterelle (*Cantharellus
cibarius*, kantarelli) habitat suitability, and renders the result as a
standalone Leaflet map (`output/karkkila_kantarelli_map.html`).

Chanterelles are mycorrhizal mainly with spruce, favour mesic to
herb-rich heath forest (OMT/MT site type), mid-aged to mature stands with
an open enough canopy for moss to carpet the floor, well-drained mineral
soil, and often occur near esker/moraine formations. The scoring in
`scripts/build_map.py` combines these factors from real forest inventory
data and ranks stands relative to each other within the municipality
(Karkkila's forest land is overwhelmingly mesic spruce forest, so a fixed
score threshold would flag most of it as "high" — ranking keeps the map
actually useful for picking where to go).

This is a habitat-suitability heuristic derived from forest inventory
attributes, not a model verified against real chanterelle sightings —
treat the output as "worth checking," not a guarantee. Mushroom picking
is covered by *jokamiehenoikeus* (everyman's right) everywhere shown,
regardless of land ownership.

## Data sources

- [Suomen metsakeskus](https://www.metsakeskus.fi/fi/avoin-metsa-ja-luontotieto) —
  open forest resource data (metsavarakuviot): species, age, development
  class, site fertility, soil type, drainage state.
- [GTK](https://www.gtk.fi/) (Geological Survey of Finland) — glaciofluvial
  and moraine formation polygons (eskers), via ArcGIS REST.

## Setup

Requires Python 3.11+ (the system Python on macOS is usually too old for
current geopandas).

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```
python scripts/download_data.py   # downloads + caches source data under data/
python scripts/build_map.py       # scores stands, writes output/
```

Open `output/karkkila_kantarelli_map.html` directly in a browser.

To target a different municipality, change `MUNICIPALITY` at the top of
both scripts and rerun.

## Commit messages

This repo uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>
```

Common types here:

- `feat` — a new capability (e.g. a new scoring factor, a new output format)
- `fix` — correcting a bug in the scoring or map generation
- `data` — changes related to source data (refreshing a download, adding a dataset)
- `docs` — README/comments only
- `refactor` — code restructuring with no behavior change
- `chore` — tooling, dependencies, `.gitignore`, etc.

Scope is optional and usually the script or area affected, e.g.
`fix(scoring): correct esker buffer distance` or `data: refresh Karkkila stand download`.
Keep the summary imperative and under ~72 characters; add a body paragraph
below a blank line when the "why" needs more explanation.
