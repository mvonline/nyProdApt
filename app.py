"""Streamlit UI for tracking pre-sale (nyproduktion) apartment projects in
Stockholm ahead of a planned 2028/2029 purchase.

Run with: streamlit run app.py
"""
import json

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from add_project import AddProjectError, add_project_by_url
from db import (
    add_comment,
    all_projects,
    get_comments,
    get_conn,
    init_db,
    loads,
    update_project_fields,
)

st.set_page_config(page_title="Stockholm Nyproduktion Tracker", layout="wide")
init_db()

SCORE_FIELDS = {
    "score_location": "Location",
    "score_safety": "Safety/Security",
    "score_price": "Price",
    "score_investment": "Investment potential",
    "score_quality": "Build quality / developer",
}

STATUS_OPTIONS = ["watching", "contacted", "visited", "offer_made", "discarded"]


# ---------- data loading ----------

@st.cache_data(ttl=15)
def load_df():
    with get_conn() as conn:
        rows = all_projects(conn)
    df = pd.DataFrame([dict(r) for r in rows])
    return df


def refresh():
    load_df.clear()


def val(row, key, default=""):
    """Safe scalar accessor for a pandas Series row: NaN/None -> default.

    Needed because missing values in a pandas row are NaN (a float), and
    `bool(float('nan'))` is True, so plain `row.get(key) or default` /
    `row[key] or default` silently pass NaN through instead of falling back.
    """
    v = row.get(key)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    return v


def compute_rank(df, weights):
    total_w = sum(weights.values()) or 1
    score = sum(df[col] * w for col, w in weights.items()) / total_w
    return score


def render_project_detail(row):
    """Full detail view for one project row: image/floorplan, info, score editor,
    address, and comment thread. Used both by the in-tab selector and by the
    standalone `?project=<id>` details page linked from the ranked-list table."""
    pid = int(row["id"])

    col_img, col_info = st.columns([1, 2])
    with col_img:
        if val(row, "og_image"):
            st.image(val(row, "og_image"), use_container_width=True, caption="Source page preview image")
        else:
            st.info("No image scraped yet for this project.")
        if val(row, "floorplan_url"):
            st.image(val(row, "floorplan_url"), use_container_width=True, caption="Floor plan")

    with col_info:
        st.subheader(row["name"])
        st.markdown(f"**Address:** {val(row, 'address', 'Not set — add it below')}  \n"
                    f"**Developer:** {val(row, 'developer', '—')}  \n"
                    f"**Kommun/area:** {val(row, 'municipality', '—')}  \n"
                    f"**Completion:** {val(row, 'completion_year', '—')}  \n"
                    f"**Price:** {val(row, 'price_text', 'Not published')}  \n"
                    f"**Link:** [{row['url']}]({row['url']})")
        if val(row, "og_description"):
            st.caption(val(row, "og_description"))

        strengths = loads(val(row, "strengths", None), [])
        weaknesses = loads(val(row, "weaknesses", None), [])
        if strengths or weaknesses:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Strengths**")
                for s in strengths:
                    st.markdown(f"- ✅ {s}")
            with c2:
                st.markdown("**Weaknesses**")
                for w in weaknesses:
                    st.markdown(f"- ⚠️ {w}")

    st.markdown("---")
    st.subheader("Your scores")
    with st.form(f"scores_{pid}"):
        cols = st.columns(len(SCORE_FIELDS))
        new_scores = {}
        for (col_key, label), c in zip(SCORE_FIELDS.items(), cols):
            new_scores[col_key] = c.slider(label, 1, 5, int(val(row, col_key, 3) or 3), key=f"{col_key}_{pid}")
        c1, c2 = st.columns(2)
        new_status = c1.selectbox("Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(val(row, "status", "watching") or "watching"), key=f"status_{pid}")
        new_fav = c2.checkbox("⭐ Favorite", value=bool(val(row, "favorite", 0)), key=f"fav_{pid}")
        new_address = st.text_input("Address (street, postcode — mostly not scrapable, fill in manually)", value=val(row, "address"), key=f"addr_{pid}")
        new_floorplan = st.text_input("Floor plan image URL (paste manually)", value=val(row, "floorplan_url"), key=f"fp_{pid}")
        submitted = st.form_submit_button("💾 Save")
        if submitted:
            with get_conn() as conn:
                update_project_fields(conn, pid, {
                    **new_scores,
                    "status": new_status,
                    "favorite": 1 if new_fav else 0,
                    "address": new_address or None,
                    "floorplan_url": new_floorplan or None,
                })
            refresh()
            st.success("Saved.")
            st.rerun()

    st.markdown("---")
    st.subheader("💬 Comments / notes")
    with st.form(f"comment_{pid}", clear_on_submit=True):
        body = st.text_area("Add a note (e.g. visit impressions, agent calls, BRF economics)")
        if st.form_submit_button("Add comment") and body.strip():
            with get_conn() as conn:
                add_comment(conn, pid, body.strip())
            refresh()
            st.rerun()

    with get_conn() as conn:
        comments = get_comments(conn, pid)
    if not comments:
        st.caption("No comments yet.")
    for c in comments:
        st.markdown(f"**{c['created_at']}** — {c['body']}")


# ---------- sidebar filters ----------

st.sidebar.title("🏙️ Filters & Ranking")

df = load_df()

if df.empty:
    st.warning("No data yet. Run `python3 seed.py` first.")
    st.stop()

# ---------- standalone project details page (?project=<id>) ----------
_project_param = st.query_params.get("project")
if _project_param is not None:
    _matches = df[df["id"] == int(_project_param)] if _project_param.isdigit() else df.iloc[0:0]
    if st.button("← Back to list"):
        st.query_params.clear()
        st.rerun()
    if _matches.empty:
        st.error(f"No project with id {_project_param!r}.")
    else:
        render_project_detail(_matches.iloc[0])
    st.stop()

municipalities = sorted([m for m in df["municipality"].dropna().unique() if m])
sel_munis = st.sidebar.multiselect("Municipality (kommun)", municipalities)

years_all = sorted({y.strip() for cell in df["completion_year"].dropna() for y in str(cell).split(",") if y.strip()})
sel_years = st.sidebar.multiselect(
    "Completion year (blank = all years)", years_all, default=[],
    help="Defaults to showing every year. The plan targets 2028/2029, but narrow this explicitly if you want the list/map limited to that.",
)

price_min_bound = int(df["price_min"].dropna().min()) if df["price_min"].notna().any() else 0
price_max_bound = int(df["price_max"].dropna().max()) if df["price_max"].notna().any() else 15_000_000
price_range = st.sidebar.slider(
    "Price range (SEK)", 0, max(price_max_bound, 1_000_000), (0, max(price_max_bound, 1_000_000)), step=100_000,
    format="%d",
)

developers = sorted([d for d in df["developer"].dropna().unique() if d])
sel_devs = st.sidebar.multiselect("Developer", developers)

sel_status = st.sidebar.multiselect("Status", STATUS_OPTIONS)
only_fav = st.sidebar.checkbox("⭐ Favorites only")
hide_no_price = st.sidebar.checkbox("Hide listings with no published price", value=False)
show_discarded = st.sidebar.checkbox(
    "Include discarded (junk/duplicate/out-of-scope scrapes)", value=True,
    help="On by default so you can see everything that was ever collected (all ~124 rows). "
         "Turn off to only see the 58 real, in-scope Stockholm-region projects.",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Ranking weights")
st.sidebar.caption("Adjust to reflect what matters most to you; final rank is the weighted average of your 1–5 scores per project.")
weights = {}
for col, label in SCORE_FIELDS.items():
    weights[col] = st.sidebar.slider(label, 0, 5, 1)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh from DB"):
    refresh()
    st.rerun()

st.sidebar.caption(
    "Data sources: manually curated shortlist + scraped project links from HSB, "
    "Besqab, JM, Wallenstam, Riksbyggen, Åke Sundvall, Balder, Skanska, Bonava, OBOS, "
    "Veidekke, K2A, Svea Fastigheter. Prices/images are best-effort and may be stale — "
    "always verify on the developer's site before acting."
)

# ---------- apply filters ----------

f = df.copy()
if not show_discarded:
    f = f[f["status"] != "discarded"]
if sel_munis:
    f = f[f["municipality"].isin(sel_munis)]
if sel_years:
    f = f[f["completion_year"].fillna("").apply(lambda c: any(y in [p.strip() for p in c.split(",")] for y in sel_years))]
if sel_devs:
    f = f[f["developer"].isin(sel_devs)]
if sel_status:
    f = f[f["status"].isin(sel_status)]
if only_fav:
    f = f[f["favorite"] == 1]
if hide_no_price:
    f = f[f["price_min"].notna()]

lo, hi = price_range
f = f[
    (f["price_min"].isna() | (f["price_min"] <= hi))
    & (f["price_max"].isna() | (f["price_max"] >= lo) | f["price_max"].isna())
]

f["rank_score"] = compute_rank(f, weights)
f = f.sort_values("rank_score", ascending=False)

st.title("🏗️ Stockholm Nyproduktion Tracker — 2028/2029 purchase")
st.caption(f"{len(f)} of {len(df)} projects match your filters.")

tab_list, tab_map, tab_detail, tab_add = st.tabs(
    ["📋 Ranked list", "🗺️ Map", "🔎 Project detail & comments", "➕ Add project"]
)

# ---------- ranked list ----------
with tab_list:
    display_cols = [
        "id", "name", "address", "lat", "lon", "developer", "municipality",
        "completion_year", "price_text", "status", "favorite", "rank_score",
    ]
    show = f[display_cols].rename(columns={
        "name": "Name", "address": "Address", "developer": "Developer",
        "municipality": "Kommun", "completion_year": "Year", "price_text": "Price",
        "status": "Status", "rank_score": "Rank score",
    })
    # Fold the favorite star into the name instead of a separate column — one
    # less column competing for width. Vectorized (not .apply(axis=1)), which
    # also sidesteps a pandas quirk where .apply(axis=1) on an empty frame
    # returns an empty DataFrame instead of an empty Series.
    show["Name"] = show["favorite"].fillna(0).astype(bool).map({True: "⭐ ", False: ""}) + show["Name"]
    show = show.drop(columns=["favorite"])
    # Address cell becomes a Google Maps search link; fall back to lat/lon when
    # no street address was captured, so the column is always clickable if we
    # have any location at all.
    has_latlon = show["lat"].notna() & show["lon"].notna()
    maps_query = show["Address"].where(show["Address"].notna() & (show["Address"] != ""))
    maps_query = maps_query.fillna(show["lat"].astype(str) + "," + show["lon"].astype(str))
    show["Address"] = ("https://www.google.com/maps/search/?api=1&query=" + maps_query).where(
        show["Address"].notna() | has_latlon
    )
    show = show.drop(columns=["lat", "lon"])
    # Keep the Price cell short — some scraped price bands are long
    # comma-separated lists of every unit price found on the page; the full
    # text is still available on the project's detail page.
    show["Price"] = show["Price"].fillna("").astype(str).str.slice(0, 45)
    show["Price"] = show["Price"].where(show["Price"].str.len() < 45, show["Price"] + "…")
    show["Rank score"] = show["Rank score"].round(2)
    show["Details"] = "?project=" + show["id"].astype(str)
    st.dataframe(
        show.drop(columns=["id"]),
        use_container_width=True,
        height=560,
        hide_index=True,
        column_config={
            "Name": st.column_config.TextColumn("Name", width="medium"),
            "Address": st.column_config.LinkColumn(
                "Address", display_text=r"query=(.*)$", width="small",
                help="Opens this location in Google Maps",
            ),
            "Developer": st.column_config.TextColumn("Developer", width="small"),
            "Kommun": st.column_config.TextColumn("Kommun", width="small"),
            "Year": st.column_config.TextColumn("Year", width="small"),
            "Price": st.column_config.TextColumn("Price", width="small"),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Rank score": st.column_config.NumberColumn("Rank score", width="small", format="%.2f"),
            "Details": st.column_config.LinkColumn(
                "Details", display_text="Open →", width="small",
                help="Open this project's detail page",
            ),
        },
    )
    st.caption(
        "Set weights to 0 for aspects you don't care about. Click **Address** for Google Maps, "
        "or a row's **Open →** for the full detail page (image, floor plan, scores, comments); "
        "full/untruncated price text is on the detail page."
    )

# ---------- map ----------
with tab_map:
    geo = f[f["lat"].notna() & f["lon"].notna()]
    st.caption(f"{len(geo)} of {len(f)} filtered projects have coordinates. Run `python3 enrich.py` to geocode more.")
    center = [59.3293, 18.0686]  # Stockholm
    m = folium.Map(location=center, zoom_start=10, tiles="OpenStreetMap")
    # A fixed zoom cuts off outlying pins (Vaxholm, Danderyd, Sollentuna,
    # anything outside the county, ...) — they're on the map but outside the
    # initial viewport, which reads as "missing". But the map's center must
    # stay Stockholm, not drift toward wherever the filtered pins happen to
    # cluster — so build a bounding box that is symmetric *around the fixed
    # Stockholm center* (sized to the farthest pin in each direction) rather
    # than a plain min/max box of the pins themselves. fit_bounds() centers on
    # a box's midpoint, and the midpoint of a center-symmetric box is exactly
    # that center.
    if not geo.empty:
        lat_delta = max((geo["lat"] - center[0]).abs().max(), 0.05)
        lon_delta = max((geo["lon"] - center[1]).abs().max(), 0.05)
        bounds = [
            [center[0] - lat_delta, center[1] - lon_delta],
            [center[0] + lat_delta, center[1] + lon_delta],
        ]
        m.fit_bounds(bounds, padding=(20, 20))
    # Several projects share identical fallback (municipality-level) coordinates
    # when a precise address couldn't be geocoded. Plain markers would then stack
    # exactly on top of each other, silently hiding all but the last one drawn.
    # MarkerCluster groups/badges overlapping pins and spiderfies them apart on
    # click so every project stays reachable.
    cluster = MarkerCluster(disableClusteringAtZoom=17).add_to(m)
    for _, row in geo.iterrows():
        addr = val(row, "address")
        # This popup's HTML is rendered inside Leaflet's own iframe (embedded by
        # streamlit-folium), so a plain relative `href='?project=...'` resolves
        # against that iframe's blank document, not the actual Streamlit app
        # page, and goes nowhere. Navigate the top-level window's query string
        # via JS instead so it actually reaches the app.
        detail_link = (
            f"<a href='javascript:void(0)' "
            f"onclick='window.top.location.search=\"?project={int(row['id'])}\"'>"
            f"Open detail page</a>"
        )
        popup = folium.Popup(
            f"<b>{row['name']}</b><br>{addr + '<br>' if addr else ''}{row['developer']}<br>{row['municipality']}<br>"
            f"Year: {row['completion_year']}<br>Price: {row['price_text']}<br>"
            f"Rank: {round(row['rank_score'], 2)}<br>"
            f"{detail_link} · "
            f"<a href='{row['url']}' target='_blank'>Original listing</a>",
            max_width=300,
        )
        color = "orange" if row["favorite"] else ("gray" if row["status"] == "discarded" else "blue")
        folium.Marker(
            [row["lat"], row["lon"]], popup=popup, tooltip=row["name"],
            icon=folium.Icon(color=color, icon="home"),
        ).add_to(cluster)
    st.caption("Overlapping pins (identical fallback coordinates) are grouped into a numbered cluster — click a cluster to spread them apart.")
    st_folium(m, use_container_width=True, height=600, key="map")

# ---------- detail & comments ----------
with tab_detail:
    if f.empty:
        st.info("No projects match the current filters.")
    else:
        options = f["name"] + " — " + f["municipality"].fillna("")
        default_idx = 0
        if st.session_state.get("jump_to_pid") in f["id"].tolist():
            default_idx = f["id"].tolist().index(st.session_state["jump_to_pid"])
        choice = st.selectbox("Select a project", options, index=default_idx)
        row = f.iloc[options.tolist().index(choice)]
        render_project_detail(row)

# ---------- add project by URL ----------
with tab_add:
    st.subheader("Add a new project from its URL")
    st.caption(
        "Paste a developer's project page URL. This fetches the page's title/description/image, "
        "guesses developer & kommun from the URL, geocodes it for the map, and gives it an "
        "**offline heuristic auto-rank** (a lookup table built from the earlier research pass — "
        "not a live web search, not verified). Review and adjust the scores on its detail page "
        "afterwards."
    )
    with st.form("add_project_form", clear_on_submit=True):
        new_url = st.text_input("Project URL", placeholder="https://www.example.se/bostad/projekt/...")
        add_submitted = st.form_submit_button("🔎 Fetch & rank")

    if add_submitted and new_url.strip():
        with st.spinner("Fetching page, geocoding, and auto-ranking…"):
            try:
                result = add_project_by_url(new_url)
            except AddProjectError as e:
                st.error(str(e))
            else:
                refresh()
                st.success(f"Added **{result['name']}** (id {result['id']}).")
                if not result["geocoded"]:
                    st.warning("Could not geocode this project — it won't appear on the map until you add an address on its detail page.")
                if result["og_image"]:
                    st.image(result["og_image"], width=300)
                st.session_state["jump_to_pid"] = result["id"]
                st.info("Open the **Project detail & comments** tab to review/adjust the auto-generated scores.")
