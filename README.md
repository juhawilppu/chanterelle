# Karkkila kantarelli map

A map of Karkkila, Finland that highlights the forest areas most likely
to grow chanterelles (*Cantharellus cibarius*, kantarelli) — built from
real forest inventory data, not guesswork, and usable straight from your
phone in the woods.

**Live map: [kantarelli.juhawilppu.com](https://kantarelli.juhawilppu.com)**

![Screenshot of the Karkkila kantarelli map, showing green and orange forest stands colored by chanterelle probability, with a popup showing a stand's score and attributes](docs/screenshot.jpg)

## What it does

Chanterelles are picky about where they grow: they partner mycorrhizally
mostly with spruce, favour mesic to herb-rich heath forest, mid-aged to
mature stands with enough light for moss to carpet the floor, well-drained
soil, and often turn up near eskers. Those aren't vibes — they're
attributes that Finland's forest inventories actually record per stand.

This project pulls that data for every one of Karkkila's ~13,000 forest
stands, scores each one against those habitat correlates, ranks them
against each other (since most of Karkkila is decent spruce forest, a
fixed score cutoff would flag nearly everything as "good" — relative
ranking is what actually points you somewhere useful), and renders the
result as an interactive map. Click any stand for its score and the
forestry data behind it. Open it on your phone and it'll track your live
location on the map too, refreshed every 30 seconds.

It's a habitat-suitability heuristic, not a model verified against actual
chanterelle sightings — treat it as "worth checking," not a guarantee.
And a reminder: mushroom picking is covered by *jokamiehenoikeus*
(everyman's right) everywhere shown, regardless of who owns the land.

## Built with AI

This entire project — the idea, the data pipeline, the scoring model, the
map, and the deployment — was built in conversation with [Claude
Code](https://claude.com/claude-code), and I want to be upfront and a
little proud about that rather than bury it. Concretely, that meant:

- Researching and wiring up two real open-data sources (Suomen
  metsäkeskus's forest stand data, GTK's geological formation data),
  including working around a dataset that turned out to have no coverage
  for Karkkila and swapping in a better one
- Designing the habitat scoring model from actual chanterelle ecology,
  then noticing the first version wasn't discriminating (70% of stands
  scored "high") and fixing it with relative ranking instead of fixed
  thresholds
- Debugging a real templating bug that broke the generated map, verified
  by actually loading the page in a browser and checking the console —
  not just assuming the code was right
- Standing up the whole toolchain from a fairly bare Mac (ancient system
  Python, a stale Homebrew, an outdated Xcode) to a working geospatial
  Python environment, Node, and the Cloudflare `wrangler` CLI
- Deploying it to Cloudflare Pages on a custom subdomain, including
  diagnosing a production-vs-preview branch mismatch that was causing a
  404

I reviewed and steered all of it, but the code, the debugging, and most
of this README were written by Claude. If that's interesting to you as a
demonstration of what's possible, that's a nice bonus on top of a map
that (hopefully) finds you some mushrooms.

## Data sources

- [Suomen metsäkeskus](https://www.metsakeskus.fi/fi/avoin-metsa-ja-luontotieto) —
  open forest resource data (metsävarakuviot): species, age, development
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
