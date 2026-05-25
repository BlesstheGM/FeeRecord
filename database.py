import sqlite3
import config

def get_db():
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

_TIER_SEEDS = [
    # (branch, name, age_min, age_max, monthly_fee)
    ("Naturena", "Infant",     4,  11,  1900.00),
    ("Naturena", "Toddler",   12,  72,  1750.00),
    ("Naturena", "2 Siblings", None, None, 3400.00),
    ("Naturena", "3 Siblings", None, None, 5100.00),
    ("Ridgeway",  "Infant",     4,  11,  2000.00),
    ("Ridgeway",  "Toddler",   12,  72,  1850.00),
    ("Ridgeway",  "2 Siblings", None, None, 3600.00),
    ("Ridgeway",  "3 Siblings", None, None, 5400.00),
]


def _migrate(conn):
    """Add columns to existing tables if they were created before branch support."""
    ft_cols = {row[1] for row in conn.execute("PRAGMA table_info(fee_tiers)").fetchall()}
    if "branch" not in ft_cols:
        conn.execute("ALTER TABLE fee_tiers ADD COLUMN branch TEXT")
    st_cols = {row[1] for row in conn.execute("PRAGMA table_info(students)").fetchall()}
    if "branch" not in st_cols:
        conn.execute("ALTER TABLE students ADD COLUMN branch TEXT")
    conn.commit()


def _seed_tiers(conn):
    for branch, name, age_min, age_max, fee in _TIER_SEEDS:
        exists = conn.execute(
            "SELECT id FROM fee_tiers WHERE name=? AND branch=?", (name, branch)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO fee_tiers (name, age_min, age_max, monthly_fee, branch) VALUES (?,?,?,?,?)",
                (name, age_min, age_max, fee, branch),
            )
    conn.commit()


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS allowed_ips (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address  TEXT NOT NULL UNIQUE,
            label       TEXT,
            added_at    TEXT DEFAULT (date('now'))
        );

        CREATE TABLE IF NOT EXISTS fee_tiers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            age_min     INTEGER,
            age_max     INTEGER,
            monthly_fee REAL NOT NULL,
            branch      TEXT
        );

        CREATE TABLE IF NOT EXISTS students (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name   TEXT NOT NULL,
            last_name    TEXT NOT NULL,
            date_of_birth TEXT,
            tier_id      INTEGER REFERENCES fee_tiers(id),
            branch       TEXT,
            parent_name  TEXT,
            parent_phone TEXT,
            start_date   TEXT,
            is_active    INTEGER DEFAULT 1,
            notes        TEXT
        );

        CREATE TABLE IF NOT EXISTS keyword_rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword     TEXT NOT NULL,
            student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            notes       TEXT
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            description     TEXT NOT NULL,
            amount          REAL NOT NULL,
            reference       TEXT,
            student_id      INTEGER REFERENCES students(id),
            matched_how     TEXT,
            upload_batch    TEXT,
            imported_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS extra_charges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            date        TEXT NOT NULL,
            description TEXT NOT NULL,
            amount      REAL NOT NULL,
            category    TEXT
        );

        CREATE TABLE IF NOT EXISTS invoices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            month       TEXT NOT NULL,
            fee_amount  REAL NOT NULL,
            notes       TEXT,
            generated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(student_id, month)
        );
    """)

    # Seed default IPs so the system is accessible on first run
    c.execute("""
        INSERT OR IGNORE INTO allowed_ips (ip_address, label)
        VALUES ('127.0.0.1', 'Localhost')
    """)

    import os
    owner_ip = os.environ.get("OWNER_IP", "").strip()
    if owner_ip:
        c.execute("""
            INSERT OR IGNORE INTO allowed_ips (ip_address, label)
            VALUES (?, 'Owner')
        """, (owner_ip,))

    conn.commit()

    _migrate(conn)
    _seed_tiers(conn)

    conn.close()
