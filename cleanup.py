"""One-off cleanup pass over the seeded/scraped data:
1. Discard rows that aren't actual sellable projects (press releases,
   aggregator/overview pages, site-rules pages, other counties).
2. Collapse duplicate rows (same project scraped once per building/unit page,
   e.g. HSB "Diktafonen 012/032/..." or "Nasby Dunge 03/04/...") into one
   canonical row per project, merging their price bands, and discard the rest
   with a comment pointing at the canonical id.

Idempotent-ish: safe to re-run, but re-running after canonical ids have been
scored will just leave duplicates re-discarded (harmless).
"""
from collections import defaultdict

from db import get_conn, add_comment, update_project_fields

# ids that are not real individual sellable projects
JUNK_IDS = {
    99,   # bare balder GUID, duplicate of Safiren (124)
    48,   # Riksbyggen press room index page
    56,   # Göteborg, out of scope (Stockholm only)
    54,   # Wallenstam Åbybergsgatan -> Göteborg area, not Stockholm county project page (overview)
    47,   # Riksbyggen Bonum Brf Svalan -> Vänersborg, out of scope
    50,   # K2A investor PR ("climate positive by 2027"), not a project
    19,   # Besqab "hitta bostad" search page, not a project
    116,  # Skanska raw unit-id URL, duplicate of Ekerö Strand (15)
    49,   # Riksbyggen Brf Sjöklinten -> Borås, out of scope
    123,  # Riksbyggen Brf Klarapoeten -> Karlstad, out of scope
    42,   # Besqab Skeppskajen -> Uppsala, out of scope
    100,  # Wallenstam press releases index
    80,   # broken/truncated URL (https://www.veidekke.)
    78,   # nyaprojekt.se news aggregator article
    74,   # TT press release (Stockholms Allmännytta 4100 rental units, not a purchasable project)
    77,   # TT press release (104 Stockholmshus rentals, not a purchasable project)
    114,  # Hemnet county-wide search overview, not a project
    76,   # Hemnet county-wide search overview, not a project
    24,   # Stockholm municipal housing company tenant-approval rules page
    113,  # OBOS "Lån" (loan/finance info page), not a project
    112,  # HSB "/sto" broken slug fragment
    75,   # Svea Fastigheter generic "nyproduktion" landing page
    41,   # Veidekke press release, not a specific project page
}

# canonical_id -> [duplicate ids] ; canonical chosen as the project's own
# overview URL (no trailing unit/building number) where one exists, else the
# first-seen id.
DUPLICATE_GROUPS = {
    106: [81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 108, 109, 110, 111],  # Diktafonen
    91: [63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 92, 93, 94, 95, 96, 97, 98],  # Nasby Dunge
    33: [20, 21, 39, 40],  # Vaxeln
}


def run():
    with get_conn() as conn:
        for jid in JUNK_IDS:
            update_project_fields(conn, jid, {"status": "discarded"})
        for canonical, dupes in DUPLICATE_GROUPS.items():
            rows = conn.execute(
                f"SELECT id, price_text, price_min, price_max FROM projects WHERE id IN ({','.join('?' * len(dupes))})",
                dupes,
            ).fetchall()
            price_texts = [r["price_text"] for r in rows if r["price_text"] and "none" not in r["price_text"].lower()]
            mins = [r["price_min"] for r in rows if r["price_min"] is not None]
            maxs = [r["price_max"] for r in rows if r["price_max"] is not None]
            canon_row = conn.execute("SELECT price_min, price_max FROM projects WHERE id=?", (canonical,)).fetchone()
            if canon_row["price_min"] is not None:
                mins.append(canon_row["price_min"])
            if canon_row["price_max"] is not None:
                maxs.append(canon_row["price_max"])
            fields = {}
            if mins or maxs:
                fields["price_min"] = min(mins) if mins else None
                fields["price_max"] = max(maxs) if maxs else None
                fields["price_text"] = f"units observed from {int(min(mins)):,} to {int(max(maxs)):,} kr".replace(",", " ") if mins and maxs else "; ".join(sorted(set(price_texts)))
            update_project_fields(conn, canonical, fields)
            for d in dupes:
                update_project_fields(conn, d, {"status": "discarded"})
                add_comment(conn, d, f"Duplicate building/unit page of project id {canonical} — merged there.", author="cleanup")

    print("Cleanup done.")


if __name__ == "__main__":
    run()
