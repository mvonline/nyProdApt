"""SQLite schema and helper functions for the apartment tracker."""
import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "apartments.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    developer TEXT,
    municipality TEXT,
    area TEXT,
    address TEXT,               -- street address, mostly manually filled in (rarely scrapable)
    url TEXT UNIQUE,
    completion_year TEXT,
    price_text TEXT,
    price_min REAL,
    price_max REAL,
    price_per_sqm REAL,
    rooms TEXT,
    living_area_sqm REAL,
    lat REAL,
    lon REAL,
    geocode_query TEXT,
    og_title TEXT,
    og_description TEXT,
    og_image TEXT,
    floorplan_url TEXT,
    source TEXT,               -- 'curated_json' | 'raw_list'
    strengths TEXT,            -- json list
    weaknesses TEXT,           -- json list
    seed_rank TEXT,            -- original letter/score rank from curated json
    -- user-editable scores, 1-5
    score_location INTEGER DEFAULT 3,
    score_safety INTEGER DEFAULT 3,
    score_price INTEGER DEFAULT 3,
    score_investment INTEGER DEFAULT 3,
    score_quality INTEGER DEFAULT 3,
    favorite INTEGER DEFAULT 0,
    status TEXT DEFAULT 'watching',   -- watching | contacted | visited | discarded | offer_made
    last_enriched_at TEXT
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    author TEXT DEFAULT 'me',
    body TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


MIGRATIONS = [
    # (column, ddl) — applied best-effort against pre-existing DBs created before
    # a column was added to SCHEMA above.
    ("address", "ALTER TABLE projects ADD COLUMN address TEXT"),
]


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
        for col, ddl in MIGRATIONS:
            if col not in existing:
                conn.execute(ddl)


def upsert_project(conn, data: dict):
    """Insert a project if url not present, else return existing id."""
    cur = conn.execute("SELECT id FROM projects WHERE url = ?", (data["url"],))
    row = cur.fetchone()
    if row:
        return row["id"]
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO projects ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    return cur.lastrowid


def update_project_fields(conn, project_id: int, fields: dict):
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
    conn.execute(
        f"UPDATE projects SET {set_clause} WHERE id = ?",
        list(fields.values()) + [project_id],
    )


def add_comment(conn, project_id: int, body: str, author: str = "me"):
    conn.execute(
        "INSERT INTO comments (project_id, author, body) VALUES (?, ?, ?)",
        (project_id, author, body),
    )


def get_comments(conn, project_id: int):
    return conn.execute(
        "SELECT * FROM comments WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()


def all_projects(conn):
    return conn.execute("SELECT * FROM projects ORDER BY name").fetchall()


def dumps(v):
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def loads(v, default=None):
    if not v:
        return default
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return default


if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at {DB_PATH}")
