# Karkkila kantarelli map

A map of Karkkila, Finland that highlights the forest areas most likely
to grow chanterelles (*Cantharellus cibarius*, kantarelli) — built from
real forest inventory data, not guesswork, and usable straight from your
phone in the woods.

Karkkila is my home town. I've spent years walking those forests looking
for kantarelli and have never once come home with enough to actually
cook, so this is my fix for that. It's also why the map only covers this
one municipality instead of all of Finland.

**Live map: [kantarelli.juhawilppu.com](https://kantarelli.juhawilppu.com)**

![Screenshot of the Karkkila kantarelli map: forest stands shaded by chanterelle probability, with an open popup breaking one stand's score down factor by factor — a green, yellow or red dot per factor showing which ones earned the score and which held it back](docs/screenshot.jpg)

## What it does

Chanterelles are picky about where they grow: mostly under spruce, in
moss-floored forest that's mid-aged to mature and not too dark or too
wet, on well-drained soil, often near eskers. Those aren't vibes —
they're attributes that Finland's forest inventories actually record per
stand.

This project pulls that data for every one of Karkkila's ~13,000 forest
stands, scores each one against those habitat correlates, ranks them
against each other (since most of Karkkila is decent spruce forest, a
fixed score cutoff would flag nearly everything as "good" — relative
ranking is what actually points you somewhere useful), and renders the
result as an interactive map. Click any stand for its score and the
forestry data behind it. Open it on your phone and it'll track your live
location on the map too, refreshed every 30 seconds.

It's a habitat-suitability heuristic. The factor weights are calibrated
against real chanterelle sightings from laji.fi (see `scripts/calibrate.py`),
but it's still a model, not a guarantee — treat it as "worth checking."
And a reminder: mushroom picking is covered by *jokamiehenoikeus*
(everyman's right) everywhere shown, regardless of who owns the land.

## Data sources

- [Suomen metsäkeskus](https://www.metsakeskus.fi/fi/avoin-metsa-ja-luontotieto) —
  open forest resource data (metsävarakuviot): species, age, development
  class, site fertility, soil type, drainage state.
- [GTK](https://www.gtk.fi/) (Geological Survey of Finland) — glaciofluvial
  and moraine formation polygons (eskers), via ArcGIS REST.
- [laji.fi](https://laji.fi/) (Finnish Biodiversity Information Facility) —
  real Cantharellus cibarius sighting coordinates, used to calibrate the
  scoring weights (not shown on the map itself). Requires a free API token;
  see `scripts/calibrate.py`.

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

To recalibrate the scoring weights against real sightings, put a free
[laji.fi](https://laji.fi/) API token in `.env` as `LAJI_FI_TOKEN=...`, then
run `python scripts/calibrate.py`. It prints a presence-vs-background
comparison per factor; use that to inform the weight constants at the top of
`build_map.py` by hand.

To target a different municipality, change `MUNICIPALITY` at the top of
both scripts and rerun.
