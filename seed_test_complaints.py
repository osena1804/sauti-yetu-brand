import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "complaints.db")
def seed():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    test_records = [
        {
            "id": "test1",
            "client_id": "default",
            "category": "Product Quality",
            "urgency": "High",
            "county": "Nairobi",
            "english_summary": "Milk packet was leaking at the supermarket.",
            "raw_text": "Bidhaa ya maziwa ilikuwa imeharibika dukani Nairobi.",
            "submitted_photo": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_encrypted": "",
            "phone_hash": "",
            "status": "Open",
            "resolution_note": "",
            "resolution_photo": "",
            "resolved_by_encrypted": "",
            "resolved_date": "",
            "dispute_count": 0,
            "dispute_reasons": ""
        },
        {
            "id": "test2",
            "client_id": "fmcg_beverage",
            "category": "Stockout/Availability",
            "urgency": "Medium",
            "county": "Kisumu",
            "english_summary": "No soda available in Kisumu branch.",
            "raw_text": "Hakuna soda kwa duka la Kisumu.",
            "submitted_photo": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_encrypted": "",
            "phone_hash": "",
            "status": "Open",
            "resolution_note": "",
            "resolution_photo": "",
            "resolved_by_encrypted": "",
            "resolved_date": "",
            "dispute_count": 0,
            "dispute_reasons": ""
        },
        {
            "id": "test3",
            "client_id": "retail_chain",
            "category": "Expired Stock",
            "urgency": "High",
            "county": "Mombasa",
            "english_summary": "Found expired bread on shelf in Mombasa.",
            "raw_text": "Mkate ulikuwa umeisha muda dukani Mombasa.",
            "submitted_photo": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_encrypted": "",
            "phone_hash": "",
            "status": "Open",
            "resolution_note": "",
            "resolution_photo": "",
            "resolved_by_encrypted": "",
            "resolved_date": "",
            "dispute_count": 0,
            "dispute_reasons": ""
        }
    ]

    for rec in test_records:
        cur.execute(f"""
            INSERT OR REPLACE INTO complaints ({",".join(rec.keys())})
            VALUES ({",".join(["?"]*len(rec))})
        """, list(rec.values()))

    conn.commit()
    conn.close()
    print(f"Seeded {len(test_records)} test complaints into {DB_PATH}")

if __name__ == "__main__":
    seed()
