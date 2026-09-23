import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "complaints.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS complaints (
        id TEXT PRIMARY KEY,
        client_id TEXT,
        category TEXT,
        urgency TEXT,
        county TEXT,
        english_summary TEXT,
        raw_text TEXT,
        submitted_photo TEXT,
        timestamp TEXT,
        phone_encrypted TEXT,
        phone_hash TEXT,
        status TEXT,
        resolution_note TEXT,
        resolution_photo TEXT,
        resolved_by_encrypted TEXT,
        resolved_date TEXT,
        dispute_count INTEGER,
        dispute_reasons TEXT
    )
    """)
    conn.commit()
    conn.close()
    print("Database initialized at", DB_PATH)

if __name__ == "__main__":
    init_db()
