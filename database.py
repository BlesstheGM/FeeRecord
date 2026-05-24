import sqlite3
import config

def get_db():
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

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
            monthly_fee REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS students (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name   TEXT NOT NULL,
            last_name    TEXT NOT NULL,
            date_of_birth TEXT,
            tier_id      INTEGER REFERENCES fee_tiers(id),
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

    # Seed one default IP so the system is accessible on first run
    c.execute("""
        INSERT OR IGNORE INTO allowed_ips (ip_address, label)
        VALUES ('127.0.0.1', 'Localhost')
    """)

    conn.commit()
    conn.close()
