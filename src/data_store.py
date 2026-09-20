"""
data_store.py

Lightweight CSV-backed pandas store for structured organic consumer feedback,
including closed-loop response tracking, brand manager sign-off, and customer disputes.
Supports multi-tenant client views via a client_id column.
"""

import os
import uuid
from datetime import datetime, timezone
import pandas as pd

try:
    from crypto_utils import encrypt_name, decrypt_name
except ImportError as e:
    print(f"[data_store] WARNING: crypto_utils unavailable, names will NOT be stored: {e}")
    def encrypt_name(name: str) -> str: return ""
    def decrypt_name(token: str) -> str: return ""

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "complaints.csv")

COLUMNS = [
    "id", "client_id", "category", "urgency", "county", "english_summary", "raw_text", "timestamp",
    "phone_encrypted", "phone_hash", "status", "resolution_note", "resolution_photo",
    "resolved_by_encrypted", "resolved_date", "dispute_count", "dispute_reasons",
]

_STR_COLS = [
    "id", "client_id", "category", "urgency", "county", "english_summary", "raw_text",
    "phone_encrypted", "phone_hash", "status", "resolution_note", "resolution_photo",
    "resolved_by_encrypted", "resolved_date", "dispute_reasons",
]


def _save_df_atomic(df: pd.DataFrame) -> None:
    """Safely saves a DataFrame to disk using atomic file operations."""
    _ensure_store()
    temp_path = f"{DATA_PATH}.tmp"
    df.to_csv(temp_path, index=False)
    os.replace(temp_path, DATA_PATH)


def _ensure_store() -> None:
    """Ensures the storage directory and file exist with standard headers."""
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    if not os.path.exists(DATA_PATH) or os.path.getsize(DATA_PATH) == 0:
        pd.DataFrame(columns=COLUMNS).to_csv(DATA_PATH, index=False)


def _coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Forces columns to consistent string/numeric types to prevent NaN/float casting issues."""
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)

    df = df.copy()

    # Ensure all expected columns exist before typing
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in _STR_COLS else 0

    for col in _STR_COLS:
        df[col] = df[col].fillna("").astype(str)

    # Fill default IDs and fallback tags
    df["id"] = df["id"].apply(lambda v: str(v).strip() if str(v).strip() else str(uuid.uuid4())[:8])
    df["status"] = df["status"].replace("", "Open")
    df["client_id"] = df["client_id"].replace("", "default")

    df["dispute_count"] = pd.to_numeric(df["dispute_count"], errors="coerce").fillna(0).astype(int)

    return df[COLUMNS]


def load_complaints(client_id: str = None, status: str = None) -> pd.DataFrame:
    """Loads all consumer feedback records, with optional filtering by client_id and status."""
    _ensure_store()

    try:
        df = pd.read_csv(DATA_PATH)
    except Exception:
        df = pd.DataFrame(columns=COLUMNS)

    if df.empty:
        empty_df = pd.DataFrame(columns=COLUMNS)
        empty_df["days_unresolved"] = 0
        return empty_df

    df = _coerce_dtypes(df)

    # Safely parse timestamps for age calculations
    timestamp_dt = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    now = datetime.now(timezone.utc)
    timestamp_dt = timestamp_dt.fillna(now)
    df["days_unresolved"] = (now - timestamp_dt).dt.days.clip(lower=0)

    # Filter by client_id if specified
    if client_id is not None:
        df = df[df["client_id"] == client_id].copy()

    # Filter by status if specified
    if status is not None:
        df = df[df["status"] == status].copy()

    # Priority sorting: Status -> Urgency -> Unresolved duration
    urgency_map = {"High": 0, "Medium": 1, "Low": 2}
    df["_urgency_rank"] = df["urgency"].map(urgency_map).fillna(3)

    sorted_df = df.sort_values(
        by=["status", "_urgency_rank", "days_unresolved"],
        ascending=[True, True, False]
    ).drop(columns=["_urgency_rank"])

    return sorted_df


def add_complaint(record: dict) -> str:
    """Appends a new structured feedback record to the store."""
    _ensure_store()
    rec = dict(record)

    complaint_id = rec.setdefault("id", str(uuid.uuid4())[:8])
    rec.setdefault("client_id", "default")
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

    row = {k: rec.get(k, "") for k in COLUMNS}
    new_row_df = _coerce_dtypes(pd.DataFrame([row]))

    # If non-empty, append directly to file without rewriting entire CSV
    if os.path.exists(DATA_PATH) and os.path.getsize(DATA_PATH) > 0:
        new_row_df.to_csv(DATA_PATH, mode="a", header=False, index=False)
    else:
        _save_df_atomic(new_row_df)

    return complaint_id


def seed_from_csv(seed_path: str, client_id: str = "default") -> int:
    """Loads an external or synthetic dataset into the store, tagged to a specific client_id."""
    _ensure_store()
    if not os.path.exists(seed_path):
        raise FileNotFoundError(f"Seed file not found: {seed_path}")

    seed_df = pd.read_csv(seed_path)
    if seed_df.empty:
        return 0

    if "id" not in seed_df.columns:
        seed_df["id"] = [str(uuid.uuid4())[:8] for _ in range(len(seed_df))]

    seed_df["client_id"] = client_id

    defaults = {
        "phone_encrypted": "", "phone_hash": "", "status": "Open",
        "resolution_note": "", "resolution_photo": "", "resolved_by_encrypted": "",
        "resolved_date": "", "dispute_count": 0, "dispute_reasons": "",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    for col, default in defaults.items():
        if col not in seed_df.columns:
            seed_df[col] = default

    seed_df = _coerce_dtypes(seed_df)
    existing = pd.read_csv(DATA_PATH) if os.path.getsize(DATA_PATH) > 0 else pd.DataFrame(columns=COLUMNS)

    combined = pd.concat([existing, seed_df[COLUMNS]], ignore_index=True)
    _save_df_atomic(combined)

    return len(seed_df)


def mark_resolved(complaint_id: str, note: str, resolved_by: str, photo_path: str = "", resolved_date: str = None) -> dict:
    """
    Marks a feedback record as resolved with resolution details and encrypted sign-off.
    Automatically encrypts raw admin name if unencrypted string is provided.
    """
    _ensure_store()
    df = pd.read_csv(DATA_PATH)
    df = _coerce_dtypes(df)

    idx = df.index[df["id"] == complaint_id]
    if len(idx) == 0:
        raise ValueError(f"No record found with id {complaint_id}")

    resolved_date = resolved_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Encrypt name if it's not already an encrypted Fernet token
    encrypted_admin = resolved_by if resolved_by.startswith("gAAAAA") else encrypt_name(resolved_by)

    df.loc[idx, "status"] = "Resolved"
    df.loc[idx, "resolution_note"] = note
    df.loc[idx, "resolution_photo"] = photo_path
    df.loc[idx, "resolved_by_encrypted"] = encrypted_admin
    df.loc[idx, "resolved_date"] = resolved_date
    df.loc[idx, "dispute_count"] = 0
    df.loc[idx, "dispute_reasons"] = ""

    _save_df_atomic(df)
    return df.loc[idx].iloc[0].to_dict()


def dispute_resolution(complaint_id: str, reason: str, reopen_threshold: int = 2) -> dict:
    """Disputes a resolved record. Reopens status to 'Disputed' once threshold is reached."""
    _ensure_store()
    df = pd.read_csv(DATA_PATH)
    df = _coerce_dtypes(df)

    idx = df.index[df["id"] == complaint_id]
    if len(idx) == 0:
        raise ValueError(f"No record found with id {complaint_id}")

    existing_reasons = df.loc[idx, "dispute_reasons"].iloc[0]
    combined_reasons = f"{existing_reasons} | {reason}" if existing_reasons else reason

    current_count = int(df.loc[idx, "dispute_count"].iloc[0]) + 1

    df.loc[idx, "dispute_reasons"] = combined_reasons
    df.loc[idx, "dispute_count"] = current_count

    if current_count >= reopen_threshold:
        df.loc[idx, "status"] = "Disputed"

    _save_df_atomic(df)
    return df.loc[idx].iloc[0].to_dict()