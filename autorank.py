"""Heuristic, offline auto-ranking for a newly-added project.

This is NOT an LLM call (the Streamlit app has no model access at runtime) —
it's a lookup-table heuristic distilled from the manual web-research pass done
earlier over the existing 58 projects (see comments in apartments.db / the
conversation that built this tool). It gives a reasonable starting point, not
a verified judgement — the UI always labels these as "auto (unverified)" and
the user is expected to review/adjust in the project detail page.
"""
import re

# kommun -> (location, safety, investment) baseline, 1-5.
# Compiled from the earlier research pass: affluent/well-connected inner and
# near-in municipalities score higher; further-out or car-dependent ones lower.
KOMMUN_PROFILE = {
    "stockholm": (4, 4, 4),
    "nacka": (4, 4, 5),
    "solna": (4, 4, 4),
    "sundbyberg": (4, 4, 4),
    "danderyd": (5, 5, 4),
    "lidingö": (4, 5, 4),
    "lidingo": (4, 5, 4),
    "täby": (4, 5, 4),
    "taby": (4, 5, 4),
    "sollentuna": (3, 4, 3),
    "vaxholm": (3, 5, 3),
    "ekerö": (3, 5, 3),
    "ekero": (3, 5, 3),
    "huddinge": (3, 4, 3),
    "järfälla": (3, 4, 3),
    "jarfalla": (3, 4, 3),
    "botkyrka": (2, 3, 3),
    "vallentuna": (2, 5, 2),
    "salem": (2, 4, 2),
    "upplands väsby": (3, 4, 3),
    "upplands vasby": (3, 4, 3),
    "sigtuna": (3, 4, 3),
    "haninge": (3, 4, 3),
    "tyresö": (3, 4, 3),
    "tyreso": (3, 4, 3),
    "värmdö": (3, 4, 3),
    "varmdo": (3, 4, 3),
}
DEFAULT_KOMMUN_PROFILE = (3, 3, 3)

# substring (lowercased) found in name/area/url/description -> override for
# (location, safety, investment). Checked in order; last match wins, so put
# more specific overrides after broader ones.
AREA_HINTS = [
    ("hagastaden", (5, 5, 5)),
    ("kungsholmen", (5, 5, 4)),
    ("stadshagen", (5, 5, 4)),
    ("södermalm", (5, 5, 4)),
    ("sodermalm", (5, 5, 4)),
    ("norra djurgårdsstaden", (4, 5, 5)),
    ("norra djurgardsstaden", (4, 5, 5)),
    ("hjorthagen", (4, 5, 5)),
    ("slakthusområdet", (4, 4, 5)),
    ("slakthusomradet", (4, 4, 5)),
    ("telefonplan", (4, 3, 5)),
    ("liljeholmen", (4, 4, 4)),
    ("hornstull", (4, 4, 4)),
    ("årstafältet", (4, 4, 4)),
    ("arstafaltet", (4, 4, 4)),
    ("bromma", (4, 4, 4)),
    ("vällingby", (3, 4, 3)),
    ("vallingby", (3, 4, 3)),
    ("nacka strand", (4, 5, 5)),
    ("centrala nacka", (4, 4, 5)),
    ("sickla", (4, 4, 5)),
    ("arenastaden", (4, 4, 4)),
    ("järvastaden", (4, 5, 4)),
    ("jarvastaden", (4, 5, 4)),
    # areas on/near the Swedish police "utsatta områden" list — flagged lower
    # on safety pending manual verification, not a certainty for the exact site.
    ("rinkeby", (2, 2, 2)),
    ("tensta", (2, 2, 2)),
    ("husby", (2, 2, 2)),
    ("hjulsta", (2, 2, 2)),
    ("fittja", (2, 2, 2)),
    ("alby", (2, 2, 2)),
    ("hallunda", (2, 2, 2)),
    ("norsborg", (2, 2, 2)),
    ("vårberg", (2, 2, 2)),
    ("varberg", (2, 2, 2)),
    ("skärholmen", (3, 3, 3)),
    ("skarholmen", (3, 3, 3)),
]

# developer name (as guessed from the URL) -> build-quality/reputation score.
DEVELOPER_REPUTATION = {
    "skanska": 5,
    "jm": 4,
    "besqab": 4,
    "hsb": 4,
    "riksbyggen": 4,
    "bonava": 4,
    "wallenstam": 4,
    "balder": 4,
    "åke sundvall": 4,
    "ake sundvall": 4,
    "veidekke": 4,
    "nordr": 4,
    "obos": 3,
    "k2a": 3,
    "klövern": 3,
    "klovern": 3,
}
DEFAULT_DEVELOPER_REPUTATION = 3


def _lookup_kommun(municipality: str):
    key = (municipality or "").strip().lower()
    return KOMMUN_PROFILE.get(key, DEFAULT_KOMMUN_PROFILE)


def auto_rank(name: str, municipality: str, developer: str, extra_text: str = ""):
    """Return {score_location, score_safety, score_price, score_investment,
    score_quality, comment} — a best-effort, offline heuristic starting point."""
    location, safety, investment = _lookup_kommun(municipality)
    haystack = " ".join(filter(None, [name, municipality, extra_text])).lower()

    matched_hint = None
    for keyword, override in AREA_HINTS:
        if keyword in haystack:
            location, safety, investment = override
            matched_hint = keyword

    quality = DEVELOPER_REPUTATION.get((developer or "").strip().lower(), DEFAULT_DEVELOPER_REPUTATION)
    price = 3  # no comparable-price data available at add-time; left neutral

    basis = f"area keyword '{matched_hint}'" if matched_hint else f"municipality baseline for '{municipality or 'unknown'}'"
    comment = (
        f"Auto-ranked (offline heuristic, NOT verified research) from {basis} and "
        f"developer reputation for '{developer or 'unknown'}'. Location={location}, "
        f"safety={safety}, investment={investment}, quality={quality}, price=3 (unknown — "
        f"no price data was available to compare). Please review and adjust these scores "
        f"once you've looked at the actual listing."
    )
    return {
        "score_location": location,
        "score_safety": safety,
        "score_price": price,
        "score_investment": investment,
        "score_quality": quality,
        "comment": comment,
    }
