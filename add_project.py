"""Add a single project by URL: fetch its page metadata, geocode it, and
apply an offline heuristic auto-rank — used by the Streamlit "Add project"
form so a user can paste a new developer-listing URL and get a usable,
reviewable starting point without re-running the whole scrape/seed pipeline.
"""
from autorank import auto_rank
from db import get_conn, upsert_project, add_comment
from enrich import fetch_meta, short_address, _geocode
from seed import slug_to_name, guess_developer, guess_municipality


class AddProjectError(Exception):
    pass


def add_project_by_url(url: str) -> dict:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise AddProjectError("Please paste a full URL (starting with http:// or https://).")

    with get_conn() as conn:
        existing = conn.execute("SELECT id, name FROM projects WHERE url = ?", (url,)).fetchone()
        if existing:
            raise AddProjectError(f"This URL is already in the list as '{existing['name']}' (id {existing['id']}).")

    name = slug_to_name(url)
    developer = guess_developer(url)
    municipality = guess_municipality(url)

    meta = fetch_meta(url)
    if meta.get("_error"):
        # Still add the project — many sites are JS-rendered SPAs a plain GET
        # can't read anyway — just without the scraped title/image.
        meta = {}
    og_title = meta.get("og_title")
    og_description = meta.get("og_description")
    og_image = meta.get("og_image")
    # og:title is usually cleaner/more accurate than our slug-derived guess.
    display_name = (og_title or name).strip() or url

    lat = lon = address = None
    query = ", ".join(p for p in [display_name, municipality, "Sverige"] if p)
    try:
        loc = _geocode(query)
    except Exception:
        loc = None
    if loc:
        lat, lon = loc.latitude, loc.longitude
        address = short_address(loc.address)

    scores = auto_rank(display_name, municipality, developer, extra_text=og_description or "")

    record = {
        "name": display_name,
        "developer": developer,
        "municipality": municipality,
        "area": "",
        "url": url,
        "completion_year": "",
        "price_text": "Not captured — check listing",
        "og_title": og_title,
        "og_description": og_description,
        "og_image": og_image,
        "lat": lat,
        "lon": lon,
        "geocode_query": query,
        "address": address,
        "source": "user_added",
        "status": "watching",
        **{k: v for k, v in scores.items() if k != "comment"},
    }

    with get_conn() as conn:
        pid = upsert_project(conn, record)
        add_comment(conn, pid, scores["comment"], author="auto-rank")

    return {"id": pid, "name": display_name, "geocoded": lat is not None, "og_image": og_image}
