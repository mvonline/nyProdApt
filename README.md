# Stockholm Nyproduktion Tracker

Personal tool to research and rank new-build (nyproduktion / pre-sale) apartment
projects in Stockholm ahead of a 2028/2029 purchase.

## What it does
- Parses your two input files (`aptlist.txt` scraped links + the curated
  `stockholm_newbuild_projects_2026.json` shortlist) into a local SQLite DB
  (`apartments.db`).
- Best-effort enriches each project by fetching its page for `og:title` /
  `og:description` / `og:image`, and geocodes it (OpenStreetMap Nominatim) for
  the map.
- Streamlit UI to filter (kommun, year, price, developer, status), rank by
  your own weighted 1–5 scores (location, safety, price, investment, quality),
  view on a Leaflet/Folium map, see the scraped image/floor plan, and leave
  timestamped comments — all stored in SQLite.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 seed.py       # (re)build the DB from the two source files
python3 enrich.py     # best-effort scrape images/descriptions + geocode (slow, ~1-2 req/sec)
streamlit run app.py
```
Once created, just `source .venv/bin/activate` before running any of the
scripts/app in a new shell (`deactivate` to leave it).

## Notes & limitations
- Many developer sites (HSB, JM, Balder, Wallenstam...) are JS-rendered SPAs.
  A plain HTTP fetch often can't see prices/floor plans that only render
  client-side — `enrich.py` fills in what it can (mostly `og:image` /
  description) and leaves the rest blank rather than guessing. Floor plan
  images are a manual paste field in the project detail tab.
- Prices are frequently "not yet published" this far ahead of 2028/29
  delivery — treat everything here as a **research shortlist**, verify
  current price/BRF-economics/plan on the developer's own page before acting.
- Re-run `python3 enrich.py --force` periodically as projects get more public
  info (new price bands, updated images).
- `enrich.py --geocode-only` / `--meta-only` to run just one half.

## Files
- `db.py` — SQLite schema & helpers
- `seed.py` — one-time/re-runnable import from the two source files
- `enrich.py` — scraper + geocoder
- `app.py` — Streamlit UI
- `apartments.db` — generated, your working data + comments/scores (not a source file — back it up)
