"""
data_store.py

SQLite-backed store for structured organic consumer feedback,
including closed-loop response tracking, brand manager sign-off, and customer disputes.
Supports multi-tenant client views via a client_id column.
"""

import os
import uuid
import sqlite3
import pandas as pd
from datetime import datetime, timezone

try:
    from crypto_utils import encrypt_name, decrypt_name
except ImportError as e:
    print(f"[data_store] WARNING: crypto_utils unavailable, names will NOT be stored: {e}")
    def encrypt_name(name: str): return ""
    def decrypt_name(token: str): return ""

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "complaints.db")

COLUMNS = [
    "id", "client_id", "category", "urgency", "county", "english_summary", "raw_text", "submitted_photo", "timestamp",
    "phone_encrypted", "phone_hash", "status", "resolution_note", "resolution_photo",
    "resolved_by_encrypted", "resolved_date", "dispute_count", "dispute_reasons",
]

def _ensure_store():
    """Ensures SQLite DB and table exist, auto-recovering from corruption."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    try:
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
    except sqlite3.DatabaseError as e:
        # If the disk image is malformed, delete the corrupt file and recreate it cleanly
        if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
            if 'conn' in locals():
                conn.close()
            if os.path.exists(DB_PATH):
                os.remove(DB_PATH)
            _ensure_store()  # Retry initialization with a fresh database file
        else:
            raise e

def add_complaint(record: dict) -> str:
    """Insert a new complaint into SQLite."""
    _ensure_store()
    rec = dict(record)
    complaint_id = rec.setdefault("id", str(uuid.uuid4())[:8])
    rec.setdefault("client_id", "default")
    rec.setdefault("submitted_photo", "")
    rec.setdefault("phone_encrypted", "")
    rec.setdefault("phone_hash", "")
    rec.setdefault("status", "Open")
    rec.setdefault("resolution_note", "")
    rec.setdefault("resolution_photo", "")
    rec.setdefault("resolved_by_encrypted", "")
    rec.setdefault("resolved_date", "")
    rec.setdefault("dispute_count", 0)
    rec.setdefault("dispute_reasons", "")
    rec.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"""
        INSERT INTO complaints ({",".join(COLUMNS)})
        VALUES ({",".join(["?"]*len(COLUMNS))})
    """, [rec.get(col, "") for col in COLUMNS])
    conn.commit()
    conn.close()
    return complaint_id

def load_complaints(client_id: str = None, status: str = None) -> pd.DataFrame:
    """Load complaints into a DataFrame, with filters and auto-hide resolved unless disputed."""
    _ensure_store()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM complaints", conn)
    conn.close()

    if df.empty:
        df["days_unresolved"] = 0
        return df

    # Filter by client_id
    if client_id:
        df = df[df["client_id"] == client_id]

    # Filter by status
    if status:
        df = df[df["status"] == status]

    # Auto-hide resolved complaints unless disputed
    df = df[(df["status"] != "Resolved") | (df["dispute_count"].astype(int) > 0)]

    # Add days_unresolved
    timestamp_dt = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    now = datetime.now(timezone.utc)
    df["days_unresolved"] = (now - timestamp_dt.fillna(now)).dt.days.clip(lower=0)

    # Priority sorting
    urgency_map = {"High": 0, "Medium": 1, "Low": 2}
    df["_urgency_rank"] = df["urgency"].map(urgency_map).fillna(3)
    df = df.sort_values(by=["status", "_urgency_rank", "days_unresolved"],
                        ascending=[True, True, False]).drop(columns=["_urgency_rank"])
    return df

def mark_resolved(complaint_id: str, note: str, resolved_by: str,
                  photo_path: str = "", resolved_date: str = None) -> dict:
    """Mark complaint as resolved and update details."""
    _ensure_store()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    resolved_date = resolved_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    encrypted_admin = resolved_by if resolved_by.startswith("gAAAAA") else encrypt_name(resolved_by)

    cur.execute("""
        UPDATE complaints
        SET status = ?, resolution_note = ?, resolution_photo = ?, resolved_by_encrypted = ?, resolved_date = ?, dispute_count = 0, dispute_reasons = ''
        WHERE id = ?
    """, ("Resolved", note, photo_path, encrypted_admin, resolved_date, complaint_id))
    conn.commit()

    df = pd.read_sql_query("SELECT * FROM complaints WHERE id = ?", conn, params=(complaint_id,))
    conn.close()
    return df.iloc[0].to_dict()

def dispute_resolution(complaint_id: str, reason: str, reopen_threshold: int = 1) -> dict:
    """Dispute a resolved complaint. Updates dispute history and sets status to Disputed."""
    _ensure_store()
    conn = sqlite3.connect(DB_PATH)
    
    try:
        df = pd.read_sql_query("SELECT * FROM complaints WHERE id = ?", conn, params=(complaint_id,))
        if df.empty:
            raise ValueError(f"No record found with id {complaint_id}")

        # Safely handle potential NaN or None values from Pandas/SQLite
        raw_reasons = df.loc[0, "dispute_reasons"]
        existing_reasons = "" if pd.isna(raw_reasons) or not raw_reasons else str(raw_reasons)

        raw_count = df.loc[0, "dispute_count"]
        current_count = 1 if (pd.isna(raw_count) or not raw_count) else int(raw_count) + 1

        timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
        formatted_entry = f"[{timestamp}] {reason.strip()}"
        combined_reasons = f"{existing_reasons}\n{formatted_entry}" if existing_reasons else formatted_entry

        # Instantly set to 'Disputed' once threshold is reached (default 1)
        new_status = "Disputed" if current_count >= reopen_threshold else str(df.loc[0, "status"])

        cur = conn.cursor()
        cur.execute("""
            UPDATE complaints
            SET dispute_reasons = ?,
                dispute_count = ?,
                status = ?
            WHERE id = ?
        """, (combined_reasons, current_count, new_status, complaint_id))
        
        conn.commit()

        # Retrieve updated record
        updated_df = pd.read_sql_query("SELECT * FROM complaints WHERE id = ?", conn, params=(complaint_id,))
        return updated_df.iloc[0].to_dict()

    finally:
        conn.close()