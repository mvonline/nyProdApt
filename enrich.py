"""Best-effort enrichment: fetch each project page for og:title/description/image
and any JSON-LD price/address data, then geocode with Nominatim (OpenStreetMap).

Run standalone: `python3 enrich.py [--limit N] [--geocode-only] [--force]`

Notes / limitations:
- Several developer sites (HSB, JM, Balder, ...) are JavaScript-rendered SPAs;
  a plain HTTP GET will often only return a shell with little/no og:image. This
  script does a best-effort static-HTML pass and leaves fields empty rather than
  guessing when nothing is found. Re-running later (sites do change) may pick up
  more.
- Geocoding uses the free Nominatim API (1 req/sec, please don't hammer it).
"""
import argparse
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

from db import get_conn, all_projects, update_project_fields

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; apartment-research-bot/1.0; personal use)"
}

_geolocator = Nominatim(user_agent="stockholm-apartment-tracker")
_geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=1.1, max_retries=2)
_reverse = RateLimiter(_geolocator.reverse, min_delay_seconds=1.1, max_retries=2)


def short_address(display_name: str) -> str:
    """Nominatim's `display_name` is very verbose (street, area, kommun, county,
    postcode, country...); keep roughly the first 4 comma-separated parts, which
    is usually street + area/kommun + postcode, and drop trailing ', Sverige'."""
    parts = [p.strip() for p in display_name.split(",")]
    parts = [p for p in parts if p.lower() != "sverige"]
    return ", ".join(parts[:4])


def fetch_meta(url: str, timeout=12):
    """Return dict with og_title/og_description/og_image/price_hint, or {} on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        return {"_error": str(e)}

    soup = BeautifulSoup(r.text, "lxml")
    out = {}

    def og(prop):
        tag = soup.find("meta", property=f"og:{prop}") or soup.find(
            "meta", attrs={"name": f"og:{prop}"}
        )
        return tag["content"].strip() if tag and tag.get("content") else None

    out["og_title"] = og("title")
    out["og_description"] = og("description")
    out["og_image"] = og("image")

    if not out["og_description"]:
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            out["og_description"] = desc["content"].strip()

    # crude price sniff from visible text, in case og tags are missing
    text = soup.get_text(" ", strip=True)
    price_matches = re.findall(r"(\d[\d\s]{5,12}\d)\s?kr", text)
    if price_matches:
        out["price_hint"] = price_matches[:5]

    return out


def enrich_all(limit=None, force=False, sleep=1.0):
    with get_conn() as conn:
        projects = all_projects(conn)
        if limit:
            projects = projects[:limit]
        for i, p in enumerate(projects, 1):
            if p["og_image"] and not force:
                continue
            print(f"[{i}/{len(projects)}] fetching {p['url']}")
            meta = fetch_meta(p["url"])
            if meta.get("_error"):
                print(f"  -> failed: {meta['_error']}")
                time.sleep(sleep)
                continue
            fields = {
                "og_title": meta.get("og_title"),
                "og_description": meta.get("og_description"),
                "og_image": meta.get("og_image"),
                "last_enriched_at": datetime.now(timezone.utc).isoformat(),
            }
            fields = {k: v for k, v in fields.items() if v}
            fields["last_enriched_at"] = datetime.now(timezone.utc).isoformat()
            update_project_fields(conn, p["id"], fields)
            time.sleep(sleep)


def geocode_all(limit=None, force=False):
    with get_conn() as conn:
        projects = all_projects(conn)
        if limit:
            projects = projects[:limit]
        for i, p in enumerate(projects, 1):
            if p["lat"] and not force:
                continue
            query_parts = [p["name"], p["municipality"], "Sverige"]
            query = ", ".join([q for q in query_parts if q])
            if not query.strip():
                continue
            print(f"[{i}/{len(projects)}] geocoding: {query}")
            try:
                loc = _geocode(query)
            except Exception as e:
                print(f"  -> geocode error: {e}")
                continue
            if not loc and p["municipality"]:
                # fallback: just the municipality, better than nothing for the map
                try:
                    loc = _geocode(f"{p['municipality']}, Sverige")
                except Exception:
                    loc = None
            if loc:
                update_project_fields(
                    conn,
                    p["id"],
                    {
                        "lat": loc.latitude,
                        "lon": loc.longitude,
                        "geocode_query": query,
                        "address": short_address(loc.address),
                    },
                )
            else:
                print("  -> no match")


def backfill_addresses(limit=None, force=False):
    """Reverse-geocode existing lat/lon into a human-readable `address`, for
    rows that were geocoded before the `address` column/reverse-geocode step
    existed."""
    with get_conn() as conn:
        projects = all_projects(conn)
        projects = [p for p in projects if p["lat"] is not None]
        if not force:
            projects = [p for p in projects if not p["address"]]
        if limit:
            projects = projects[:limit]
        for i, p in enumerate(projects, 1):
            print(f"[{i}/{len(projects)}] reverse-geocoding id={p['id']} ({p['lat']}, {p['lon']})")
            try:
                loc = _reverse((p["lat"], p["lon"]), language="sv")
            except Exception as e:
                print(f"  -> reverse geocode error: {e}")
                continue
            if loc:
                update_project_fields(conn, p["id"], {"address": short_address(loc.address)})
            else:
                print("  -> no match")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--geocode-only", action="store_true")
    ap.add_argument("--meta-only", action="store_true")
    ap.add_argument("--addresses-only", action="store_true", help="only reverse-geocode addresses for rows with lat/lon")
    args = ap.parse_args()

    if args.addresses_only:
        backfill_addresses(limit=args.limit, force=args.force)
    else:
        if not args.geocode_only:
            enrich_all(limit=args.limit, force=args.force)
        if not args.meta_only:
            geocode_all(limit=args.limit, force=args.force)
        backfill_addresses(limit=args.limit, force=args.force)
