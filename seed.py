"""Parse aptlist.txt + stockholm_newbuild_projects_2026.json into the SQLite DB."""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from db import get_conn, init_db, upsert_project, dumps

BASE = Path(__file__).parent
RAW_LIST = BASE / "aptlist.txt"
CURATED_JSON = BASE / "stockholm_newbuild_projects_2026.json"

RANK_SCORE_MAP = {  # letter rank -> 1-5 default investment/location score
    "A": 5, "A-": 4, "B+": 4, "B": 3, "B-": 3, "C+": 2, "C": 2,
}


def slug_to_name(url: str) -> str:
    """Derive a human-ish project name from a URL slug."""
    path = urlparse(url).path.strip("/")
    parts = [p for p in path.split("/") if p]
    # prefer the last non-generic segment
    ignore = {"projekt", "sok-bostad", "bostader", "bostad", "stockholm"}
    candidates = [p for p in parts if p.lower() not in ignore]
    slug = candidates[-1] if candidates else (parts[-1] if parts else url)
    # HSB-style urls end in a bare unit/building number (e.g. "012", "03") -
    # that's not a project name, so fall back to the segment before it.
    if slug.isdigit() and len(candidates) >= 2:
        slug = candidates[-2]
    name = slug.replace("-", " ").replace("_", " ").strip()
    return name.title() if name else url


def guess_developer(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    mapping = {
        "hsb.se": "HSB",
        "besqab.se": "Besqab",
        "wallenstam.se": "Wallenstam",
        "riksbyggen.se": "Riksbyggen",
        "akesundvall.se": "Åke Sundvall",
        "balder.se": "Balder",
        "bostad.stockholm.se": "Stockholmshem/Svenska Bostäder (kommunal)",
        "veidekke.se": "Veidekke",
        "hemnet.se": "Hemnet (listing)",
        "bonava.se": "Bonava",
        "via.tt.se": "Pressmeddelande (TT)",
        "nyaprojekt.se": "Nyaprojekt (aggregator)",
        "sveafastigheter.se": "Svea Fastigheter",
        "obos.se": "OBOS",
        "k2a.se": "K2A",
        "investerare.k2a.se": "K2A (investor page)",
        "bostad.skanska.se": "Skanska",
        "jm.se": "JM",
    }
    return mapping.get(host, host)


def guess_municipality(url: str) -> str:
    path = urlparse(url).path.lower()
    # known Stockholm-county municipalities that show up in slugs. "stockholm"
    # is deliberately last: URLs like JM's ".../stockholm-lan/nacka-kommun/..."
    # contain the *county* name ("Stockholms län") ahead of the actual kommun
    # segment, so a naive first-match-in-path-order scan would always return
    # "Stockholm" and never reach "nacka". Instead, prefer a segment explicitly
    # suffixed "-kommun" (the clearest per-URL signal of the real kommun), and
    # only fall back to plain substring order (with stockholm checked last) if
    # no "-kommun" segment is present.
    munis = [
        "nacka", "solna", "sundbyberg", "huddinge", "botkyrka",
        "vallentuna", "salem", "vaxholm", "upplands-vasby", "upplands vasby",
        "jarfalla", "sollentuna", "tyreso", "haninge", "varmdo", "lidingo",
        "danderyd", "taby", "sigtuna", "ekero", "nykvarn", "nynashamn",
        "sodertalje", "upplands bro", "stockholm",
    ]
    segments = [s for s in path.split("/") if s]
    for seg in segments:
        if seg.endswith("-kommun"):
            base = seg[: -len("-kommun")]
            for m in munis:
                if m == base:
                    return m.replace("-", " ").title()
    for m in munis:
        if m in path:
            return m.replace("-", " ").title()
    return ""


def parse_price_band(text: str):
    """'7,900,000 kr' or '2,595,000, 3,145,000 kr' or '(none in band)' -> (min, max)."""
    if not text or "none" in text.lower():
        return None, None
    nums = re.findall(r"[\d,]{4,}", text)
    vals = [float(n.replace(",", "")) for n in nums]
    if not vals:
        return None, None
    return min(vals), max(vals)


def parse_raw_list():
    """Yield dicts parsed from the scraped chat-export style txt file."""
    text = RAW_LIST.read_text(encoding="utf-8")
    # entries look like:
    # 105. 〜 <possibly-truncated-url>
    # years: 2027 | prices in band: (none in band) kr
    # https://full/url/
    # Looser pattern: doesn't require the numbered "N. 〜" header line, since the
    # first entry in each pasted chat block is often a wrapped/truncated line
    # instead. We only need the years/prices line immediately followed by the
    # canonical full URL line.
    pattern = re.compile(
        r"years:\s*(?P<years>[^|]+?)\s*\|\s*prices in band:\s*(?P<prices>.+?)\s*kr\s*\n"
        r"(?P<url>https?://\S+)",
        re.MULTILINE,
    )
    seen = set()
    for m in pattern.finditer(text):
        url = m.group("url").strip()
        if url in seen:
            continue
        seen.add(url)
        years = m.group("years").strip()
        price_min, price_max = parse_price_band(m.group("prices"))
        yield {
            "url": url,
            "name": slug_to_name(url),
            "developer": guess_developer(url),
            "municipality": guess_municipality(url),
            "area": "",
            "completion_year": years if years != "?" else "",
            "price_text": m.group("prices").strip() + " kr",
            "price_min": price_min,
            "price_max": price_max,
            "source": "raw_list",
        }


def parse_curated_json():
    data = json.loads(CURATED_JSON.read_text(encoding="utf-8"))
    for p in data["projects"]:
        price_min, price_max = None, None
        m = re.findall(r"[\d.]+\s*[MK]?", p.get("price_range_sek", "") or "")
        # keep as text; curated prices are often ranges in M SEK, parse loosely
        nums = re.findall(r"(\d+(?:\.\d+)?)\s*[MK]", p.get("price_range_sek", "") or "")
        if nums:
            vals = [float(n) * 1_000_000 for n in nums]
            price_min, price_max = min(vals), max(vals)
        rank_letter = (p.get("rank") or "").split("/")[0].strip()
        yield {
            "url": p["link"],
            "name": p["name"],
            "developer": p.get("developer", ""),
            "municipality": p.get("municipality", ""),
            "area": "",
            "completion_year": str(p.get("completion_year", "")),
            "price_text": p.get("price_range_sek", ""),
            "price_min": price_min,
            "price_max": price_max,
            "strengths": dumps(p.get("strengths")),
            "weaknesses": dumps(p.get("weaknesses")),
            "seed_rank": p.get("rank"),
            "score_investment": RANK_SCORE_MAP.get(rank_letter, 3),
            "score_location": RANK_SCORE_MAP.get(rank_letter, 3),
            "source": "curated_json",
        }


def run():
    init_db()
    inserted, skipped = 0, 0
    with get_conn() as conn:
        # curated json first so it "wins" the canonical name/developer for a URL
        for rec in list(parse_curated_json()) + list(parse_raw_list()):
            rec.setdefault("geocode_query", None)
            pid = upsert_project(conn, rec)
            if pid:
                inserted += 1
    print(f"Seed complete. Projects in DB: {inserted}")


if __name__ == "__main__":
    run()
