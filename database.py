"""SQLite storage for CivicSense (complaints and officer corrections)."""
import json
import os
import secrets
import sqlite3

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "civicsense.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    lat REAL, lon REAL, ward INTEGER,
    category TEXT, category_conf REAL, ml_priority TEXT, needs_review INTEGER DEFAULT 0,
    duplicate_of INTEGER,
    department TEXT, priority TEXT, priority_level INTEGER, score REAL,
    flags TEXT DEFAULT '[]', trace TEXT DEFAULT '[]',
    status TEXT DEFAULT 'open', resolved_at TEXT,
    photo_path TEXT,
    tracking_code TEXT,
    after_photo_path TEXT,
    resolution_note TEXT,
    reopened_count INTEGER DEFAULT 0,
    assigned_crew TEXT,
    screen_note TEXT
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT, category TEXT, priority TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL,
    failed_attempts INTEGER DEFAULT 0, locked_until TEXT, active INTEGER DEFAULT 1, crew_id TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL, at TEXT NOT NULL, cycle INTEGER NOT NULL,
    fixed INTEGER NOT NULL, rating INTEGER NOT NULL, comment TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL, username TEXT, action TEXT NOT NULL, complaint_id INTEGER, detail TEXT
);
"""
JSON_FIELDS = ("flags", "trace")


def connect(path):
    # Streamlit serves each browser session from a different thread, so allow cross-thread use.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """Databases created by an earlier version lack newer columns: add them."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(complaints)")}
    for name, definition in (("photo_path", "TEXT"), ("tracking_code", "TEXT"), ("after_photo_path", "TEXT"),
                             ("resolution_note", "TEXT"), ("reopened_count", "INTEGER DEFAULT 0"),
                             ("assigned_crew", "TEXT"), ("screen_note", "TEXT")):
        if name not in columns:
            conn.execute(f"ALTER TABLE complaints ADD COLUMN {name} {definition}")
    if "crew_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(users)")}:
        conn.execute("ALTER TABLE users ADD COLUMN crew_id TEXT")
    conn.commit()
    for row in conn.execute("SELECT id FROM complaints WHERE tracking_code IS NULL").fetchall():
        conn.execute("UPDATE complaints SET tracking_code=? WHERE id=?", (new_tracking_code(conn), row["id"]))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_code ON complaints(tracking_code)")
    conn.commit()


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # no 0/O or 1/I, so codes are easy to read out


def new_tracking_code(conn):
    """A random public code such as CS-7K4M9QXA. Not guessable, and unrelated to the complaint number."""
    while True:
        code = "CS-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not conn.execute("SELECT 1 FROM complaints WHERE tracking_code=?", (code,)).fetchone():
            return code


def _decode(row):
    d = dict(row)
    for k in JSON_FIELDS:
        d[k] = json.loads(d[k]) if d.get(k) else []
    return d


def _encode(fields):
    return {k: (json.dumps(v) if k in JSON_FIELDS else v) for k, v in fields.items()}


def insert(conn, **fields):
    fields.setdefault("tracking_code", new_tracking_code(conn))
    fields = _encode(fields)
    cur = conn.execute(f"INSERT INTO complaints ({','.join(fields)}) VALUES ({','.join('?' * len(fields))})",
                       tuple(fields.values()))
    conn.commit()
    return cur.lastrowid


def update(conn, cid, **fields):
    fields = _encode(fields)
    conn.execute(f"UPDATE complaints SET {', '.join(k + '=?' for k in fields)} WHERE id=?",
                 (*fields.values(), cid))
    conn.commit()


def get(conn, cid):
    row = conn.execute("SELECT * FROM complaints WHERE id=?", (cid,)).fetchone()
    return _decode(row) if row else None


def query(conn, where="1=1", params=()):
    return [_decode(r) for r in conn.execute(f"SELECT * FROM complaints WHERE {where} ORDER BY id", params)]


def add_correction(conn, text, category, priority, created_at):
    conn.execute("INSERT INTO corrections (text, category, priority, created_at) VALUES (?,?,?,?)",
                 (text, category, priority, created_at))
    conn.commit()


def corrections(conn):
    return [dict(r) for r in conn.execute("SELECT text, category, priority, created_at FROM corrections ORDER BY id")]


def reset(conn):
    """Delete complaints and corrections. Accounts and the audit log are kept."""
    conn.executescript("DELETE FROM complaints; DELETE FROM corrections; DELETE FROM events; DELETE FROM feedback; "
                       "DELETE FROM sqlite_sequence WHERE name IN ('complaints', 'corrections', 'events', 'feedback');")
    conn.commit()


# ---------------------------------------------------------------- accounts and audit log
def add_user(conn, username, password_hash, role, created_at, crew_id=None):
    conn.execute("INSERT INTO users (username, password_hash, role, created_at, crew_id) VALUES (?,?,?,?,?)",
                 (username, password_hash, role, created_at, crew_id))
    conn.commit()


def get_user(conn, username):
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def update_user(conn, username, **fields):
    conn.execute(f"UPDATE users SET {', '.join(k + '=?' for k in fields)} WHERE username=?",
                 (*fields.values(), username))
    conn.commit()


def list_users(conn):
    return [dict(r) for r in conn.execute(
        "SELECT username, role, crew_id, created_at, active FROM users ORDER BY username")]


def user_count(conn):
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def log_audit(conn, at, username, action, complaint_id=None, detail=""):
    conn.execute("INSERT INTO audit_log (at, username, action, complaint_id, detail) VALUES (?,?,?,?,?)",
                 (at, username, action, complaint_id, detail))
    conn.commit()


def audit_entries(conn, limit=300):
    return [dict(r) for r in conn.execute(
        "SELECT at, username, action, complaint_id, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]


# ---------------------------------------------------------------- status updates and citizen feedback
def add_event(conn, complaint_id, at, kind, message):
    conn.execute("INSERT INTO events (complaint_id, at, kind, message) VALUES (?,?,?,?)", (complaint_id, at, kind, message))
    conn.commit()


def events_for(conn, complaint_id):
    return [dict(r) for r in conn.execute(
        "SELECT id, at, kind, message FROM events WHERE complaint_id=? ORDER BY at, id", (complaint_id,))]


def add_feedback(conn, complaint_id, at, cycle, fixed, rating, comment):
    conn.execute("INSERT INTO feedback (complaint_id, at, cycle, fixed, rating, comment) VALUES (?,?,?,?,?,?)",
                 (complaint_id, at, cycle, int(fixed), int(rating), comment))
    conn.commit()


def feedback_given(conn, complaint_id, cycle):
    return conn.execute("SELECT 1 FROM feedback WHERE complaint_id=? AND cycle=?", (complaint_id, cycle)).fetchone() is not None


def feedback_rows(conn):
    return [dict(r) for r in conn.execute(
        "SELECT f.complaint_id, f.at, f.cycle, f.fixed, f.rating, f.comment, c.department "
        "FROM feedback f JOIN complaints c ON c.id = f.complaint_id ORDER BY f.id")]
