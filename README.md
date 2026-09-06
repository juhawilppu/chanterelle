# Karkkila mushroom map

A map of Karkkila, Finland that highlights the forest areas most likely
to grow chanterelles (*Cantharellus cibarius*, kantarelli) and funnel
chanterelles (*Craterellus tubaeformis*, suppilovahvero) — built from
real forest inventory data, not guesswork, and usable straight from your
phone in the woods. One map per mushroom, switched with the buttons at
the top.

Karkkila is my home town. I've spent years walking those forests looking
for kantarelli and have never once come home with enough to actually
cook, so this is my fix for that. It's also why the map only covers this
one municipality instead of all of Finland. It works: the kantarelli map
found mushrooms on its first outing, which is what earned suppilovahvero
a map of its own.

**Live map: [kantarelli.juhawilppu.com](https://kantarelli.juhawilppu.com)**

![Screenshot of the Karkkila mushroom map: a Kantarelli / Suppilovahvero switcher above forest stands shaded by probability, with an open popup breaking one stand's score down factor by factor — a green, yellow or red dot per factor showing which ones earned the score and which held it back](docs/screenshot.jpg)

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

## The two species

Each mushroom gets its own habitat model in `scripts/species.py`, and the
map switcher swaps which one is being drawn.

Kantarelli wants dry, half-open, well-drained mineral soil near an esker.
Suppilovahvero is usually described as its opposite — dank, shady spruce
mire — and calibrating that description against real sightings mostly
refuted it. The sightings say old regeneration-ready spruce stands (4.6x
over-represented), a canopy no denser than kantarelli's, coarse and even
stony soil rather than fine damp soil, and a *drier* fertility range than
expected. What did hold up: a much stronger spruce association (70% vs 62%
spruce-dominant), and real tolerance for paludified ground, so spruce mires
(korpi) stay on the suppilovahvero map where the kantarelli model throws
them out.

The honest summary is that **these two mushrooms are hard to tell apart from
forest data**. Their sighting distributions match within a couple of
percentage points on fertility class, development class, soil and stem
density, and a model tuned for one scores the other's sightings about as
well as its own. Where they genuinely differ is spruce dominance, tolerance
of wet ground, slope — and, most usefully, *season*: suppilovahvero is 85%
September–November and effectively absent before August, while kantarelli
peaks in July and August. Each profile's tables carry the calibration
evidence in comments, including the places where the data contradicted the
field-guide description.

## Does it work?

`scripts/validate.py` scores real sighting locations with the map's own code
and asks whether the score ranks them above random forest:

| | AUC | top 15% of the map catches |
|---|---|---|
| Kantarelli | 0.753 | 48% of sightings — 3.2x chance |
| Suppilovahvero | 0.767 | 47% of sightings — 3.2x chance |

Both numbers are in-sample — the weights were tuned against these same
sightings — so treat them as an upper bound and as a way to compare model
versions, not as absolute accuracy.

Two lessons are baked into that script. Sighting coordinates are capped at
100 m accuracy, because stands are 1–3 ha and a kilometre-wide record
describes the forest someone walked through rather than the one the mushroom
grew in. And lift is measured against the share of stands a cutoff *actually*
selects: the scoring tables are discrete, so thousands of stands share a
score, and a nominal "top 10%" can select 19% of the map. Comparing a
tie-heavy model against a tie-free one on the nominal figure reverses the
conclusion — it made a genuine improvement look like a regression.

It's a habitat-suitability heuristic. The factor weights are calibrated
against real sightings from laji.fi (see `scripts/calibrate.py`),
but it's still a model, not a guarantee — treat it as "worth checking."
The sightings are also opportunistic: they partly describe where foragers
walk, so the map inherits some of that bias.
And a reminder: mushroom picking is covered by *jokamiehenoikeus*
(everyman's right) everywhere shown, regardless of who owns the land.

## Landform

The forest inventory describes the stand but not where it sits, and two
stands with identical rows can be a dry crest and the damp hollow below it.
Adding landform from the elevation model was the largest single improvement
either model has had: it roughly *doubles* how densely real sightings
concentrate in the best-scoring tenth of the map.

The finding itself is blunt, and it is the same for both species: ground
sitting 3 m or more below its surroundings holds a quarter of Karkkila's
forest but only an eighth of the sightings (0.5x). Depressions here are wet,
and neither mushroom fruits in wet. This is the opposite of what
suppilovahvero's "damp hollows and ditch banks" reputation predicts. Level
to gently raised ground is the sweet spot; crests fall back slightly, being
thin and dry.

## Data sources

- [Suomen metsäkeskus](https://www.metsakeskus.fi/fi/avoin-metsa-ja-luontotieto) —
  open forest resource data (metsävarakuviot): species, age, development
  class, site fertility, soil type, drainage state.
- [GTK](https://www.gtk.fi/) (Geological Survey of Finland) — glaciofluvial
  and moraine formation polygons (eskers), via ArcGIS REST.
- [Maanmittauslaitos](https://www.maanmittauslaitos.fi/) 10 m elevation
  model (lidar-derived ground model), for landform: whether a stand sits in
  a hollow, on a hillside or on a crest, and how steeply the ground falls.
  Read by HTTP range request from the openly mirrored nationwide VRT at
  funet, so only the window over Karkkila is ever fetched.
- [laji.fi](https://laji.fi/) (Finnish Biodiversity Information Facility) —
  real sighting coordinates per species, used both to calibrate the scoring
  weights and, for sightings inside Karkkila, as the flags on the map.
  Requires a free API token; see `scripts/calibrate.py`.

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
python scripts/build_map.py       # scores stands for every species, writes output/
```

Open `output/karkkila_sienikartta.html` directly in a browser. Both species
live in that one file: stand geometry is written once and shared, and the
attribute labels are expanded in the browser from inventory codes, so the
two-species map is smaller than the single-species one it replaced.

To recalibrate a species' weights against real sightings, put a free
[laji.fi](https://laji.fi/) API token in `.env` as `LAJI_FI_TOKEN=...`, then
run `python scripts/calibrate.py --species suppilovahvero`. It prints a
presence-vs-background comparison per factor; use that to inform the weights
in that species' profile in `scripts/species.py` by hand.

To check whether a change to the weights actually helped, run
`python scripts/validate.py`.

To add a mushroom, write another `SpeciesProfile` in `scripts/species.py`
and add it to `PROFILES` — the scoring engine, the map, the switcher and
the sighting downloads all pick it up from there.

To target a different municipality, change `MUNICIPALITY` at the top of
both scripts and rerun.
