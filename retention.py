"""Data retention and data-subject rights for Sauti-Yetu.

What it does (matches the retention schedule in the DPIA):
  1. Deletes consumer reports (and their photos) a set time after their alert is
     resolved, or after a longer time if they never belonged to an alert.
  2. Deletes encrypted phone numbers once the resolution SMS has been sent.
  3. Deletes counterfeit reports and photos after a set time, unless a reviewer
     placed a legal hold on them.
  4. Deletes photo files nothing points to any more, and the AI score cache.
  5. Before deleting, keeps ANONYMOUS counts only (week, brand, cluster, how many).
     No county, text, phone or photo is kept.
  6. Lets an admin delete one person's report by reference number (rights request).
  7. Lets an admin delete everything at the end of a pilot.

Run it from the command line (a dry run by default, which deletes nothing):
    python retention.py            # shows what WOULD be deleted
    python retention.py --apply    # deletes it

Later, a scheduler (Cloud Scheduler on Google Cloud) runs the same command daily.
"""
import hmac
import json
import os
import re
import sys
import time

import db

AFTER_RESOLUTION_DAYS = int(os.environ.get("SAUTI_RETAIN_AFTER_RESOLUTION_DAYS", "30"))
UNTIED_DAYS = int(os.environ.get("SAUTI_RETAIN_UNTIED_DAYS", "90"))
COUNTERFEIT_DAYS = int(os.environ.get("SAUTI_RETAIN_COUNTERFEIT_DAYS", "60"))
UPLOAD_ROOT = os.environ.get("SAUTI_UPLOAD_DIR", "uploads")
CACHE_PATH = "score_cache.json"
ORPHAN_GRACE_HOURS = 24


# ---------- setup ----------

def ensure_tables():
    """Tables that hold ANONYMOUS counts only, kept after reports are deleted."""
    with db.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_aggregates (
                agg_id INTEGER PRIMARY KEY AUTOINCREMENT,
                week TEXT NOT NULL,
                brand_id INTEGER NOT NULL,
                issue_cluster TEXT NOT NULL,
                reports INTEGER NOT NULL,
                avg_severity REAL,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS counterfeit_aggregates (
                agg_id INTEGER PRIMARY KEY AUTOINCREMENT,
                month TEXT NOT NULL,
                brand_id INTEGER NOT NULL,
                county TEXT NOT NULL,
                outlet_type TEXT NOT NULL,
                reports INTEGER NOT NULL,
                suspected INTEGER NOT NULL,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


ensure_tables()


# ---------- file helpers ----------

def _abs(path):
    return os.path.abspath(path)


def _within_upload_root(path):
    """Only files inside the uploads folder are ever deleted."""
    root = _abs(UPLOAD_ROOT) + os.sep
    return bool(path) and _abs(path).startswith(root)


def _file_exists(path):
    return _within_upload_root(path) and os.path.isfile(path)


def _delete_file(path):
    if _file_exists(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return False


def _referenced_paths(conn):
    paths = set()
    for (p,) in conn.execute("SELECT image_url FROM complaints WHERE image_url IS NOT NULL"):
        paths.add(_abs(p))
    for row in conn.execute("SELECT front_photo, back_photo, outlet_photo FROM counterfeit_reports"):
        for p in row:
            if p:
                paths.add(_abs(p))
    return paths


def _orphan_files(conn):
    """Files in the uploads folder that no report points to, older than the grace period
    (so a photo being saved right now is never touched)."""
    if not os.path.isdir(UPLOAD_ROOT):
        return []
    referenced = _referenced_paths(conn)
    cutoff = time.time() - ORPHAN_GRACE_HOURS * 3600
    found = []
    for folder, _dirs, files in os.walk(UPLOAD_ROOT):
        for name in files:
            full = os.path.join(folder, name)
            if _abs(full) not in referenced and os.path.getmtime(full) < cutoff:
                found.append(full)
    return found


# ---------- staging: which rows are due ----------

def _days(n):
    return f"-{int(n)} days"


def _stage_due(conn, everything=False):
    """Fills two temporary tables with the ids that are due for deletion."""
    conn.execute("DROP TABLE IF EXISTS temp.due_complaints")
    conn.execute("DROP TABLE IF EXISTS temp.due_counterfeit")
    conn.execute("CREATE TEMP TABLE due_complaints (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE due_counterfeit (id INTEGER PRIMARY KEY)")

    if everything:
        conn.execute("INSERT INTO due_complaints (id) SELECT incident_id FROM complaints")
        conn.execute("INSERT INTO due_counterfeit (id) SELECT report_id FROM counterfeit_reports WHERE legal_hold = 0")
        return

    # A. Reports in an alert that was resolved long enough ago (reports made up to the resolution)
    conn.execute(
        """
        INSERT OR IGNORE INTO due_complaints (id)
        SELECT c.incident_id
        FROM complaints c
        JOIN critical_alerts a ON a.brand_id = c.brand_id AND a.cluster_id = c.issue_cluster
        WHERE a.resolution_status = 'RESOLVED'
          AND a.verification_expires_at IS NOT NULL
          AND a.verification_expires_at <= datetime('now', ?)
          AND c.created_at <= a.verification_expires_at
        """,
        (_days(AFTER_RESOLUTION_DAYS),),
    )
    # B. Old reports that are not part of any unresolved alert
    conn.execute(
        """
        INSERT OR IGNORE INTO due_complaints (id)
        SELECT c.incident_id
        FROM complaints c
        WHERE c.created_at <= datetime('now', ?)
          AND NOT EXISTS (
              SELECT 1 FROM critical_alerts a
              WHERE a.brand_id = c.brand_id AND a.cluster_id = c.issue_cluster
                AND COALESCE(a.resolution_status, 'UNADDRESSED') != 'RESOLVED'
          )
        """,
        (_days(UNTIED_DAYS),),
    )
    # C. Counterfeit reports past their retention, unless on legal hold
    conn.execute(
        """
        INSERT OR IGNORE INTO due_counterfeit (id)
        SELECT report_id FROM counterfeit_reports
        WHERE legal_hold = 0 AND created_at <= datetime('now', ?)
        """,
        (_days(COUNTERFEIT_DAYS),),
    )


_PHONE_DONE_SQL = """
    FROM complaints c
    WHERE c.phone_encrypted IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM critical_alerts a
          WHERE a.brand_id = c.brand_id AND a.cluster_id = c.issue_cluster
            AND a.resolution_sms_sent = 1
      )
"""


def _archive_aggregates(conn):
    """Keeps anonymous counts for the due rows: week, brand, cluster, how many."""
    conn.execute(
        """
        INSERT INTO report_aggregates (week, brand_id, issue_cluster, reports, avg_severity)
        SELECT strftime('%Y-W%W', created_at), brand_id, issue_cluster, COUNT(*), ROUND(AVG(severity_score), 2)
        FROM complaints
        WHERE incident_id IN (SELECT id FROM due_complaints)
        GROUP BY 1, 2, 3
        """
    )
    conn.execute(
        """
        INSERT INTO counterfeit_aggregates (month, brand_id, county, outlet_type, reports, suspected)
        SELECT strftime('%Y-%m', created_at), brand_id, county, outlet_type, COUNT(*),
               SUM(CASE WHEN review_status = 'Suspected counterfeit' THEN 1 ELSE 0 END)
        FROM counterfeit_reports
        WHERE report_id IN (SELECT id FROM due_counterfeit)
        GROUP BY 1, 2, 3, 4
        """
    )


# ---------- the retention run ----------

def run_retention(apply=False, admin=None, everything=False):
    """Works out what is due. With apply=False (default) nothing is changed and the
    counts are returned. With apply=True it archives anonymous counts, deletes, and
    writes one line to the audit log. everything=True is the end-of-pilot purge:
    all reports go, except counterfeit reports on legal hold."""
    conn = db.get_connection()
    try:
        _stage_due(conn, everything=everything)
        complaint_paths = [r[0] for r in conn.execute(
            "SELECT image_url FROM complaints WHERE incident_id IN (SELECT id FROM due_complaints) "
            "AND image_url IS NOT NULL")]
        cf_paths = []
        for row in conn.execute(
                "SELECT front_photo, back_photo, outlet_photo FROM counterfeit_reports "
                "WHERE report_id IN (SELECT id FROM due_counterfeit)"):
            cf_paths.extend(p for p in row if p)

        summary = {
            "complaints": conn.execute("SELECT COUNT(*) FROM due_complaints").fetchone()[0],
            "complaint_photos": sum(1 for p in complaint_paths if _file_exists(p)),
            "phones_cleared": conn.execute("SELECT COUNT(*) " + _PHONE_DONE_SQL).fetchone()[0],
            "counterfeit": conn.execute("SELECT COUNT(*) FROM due_counterfeit").fetchone()[0],
            "counterfeit_photos": sum(1 for p in cf_paths if _file_exists(p)),
            "counterfeit_on_hold": conn.execute(
                "SELECT COUNT(*) FROM counterfeit_reports WHERE legal_hold = 1").fetchone()[0],
            "score_cache_file": 1 if os.path.isfile(CACHE_PATH) else 0,
        }

        if apply:
            _archive_aggregates(conn)
            conn.execute("DELETE FROM complaints WHERE incident_id IN (SELECT id FROM due_complaints)")
            conn.execute("DELETE FROM counterfeit_reports WHERE report_id IN (SELECT id FROM due_counterfeit)")
            conn.execute(
                "UPDATE complaints SET phone_encrypted = NULL WHERE incident_id IN "
                "(SELECT c.incident_id " + _PHONE_DONE_SQL + ")")
            conn.commit()
            for path in complaint_paths + cf_paths:
                _delete_file(path)
            if os.path.isfile(CACHE_PATH):
                try:
                    os.remove(CACHE_PATH)
                except OSError:
                    pass

        orphans = _orphan_files(conn)
        summary["orphan_files"] = len(orphans)
        if apply:
            for path in orphans:
                _delete_file(path)
    finally:
        conn.close()

    if apply:
        action = "PURGE_ALL" if everything else "RETENTION_RUN"
        db.log_audit_action(admin, action, detail=json.dumps(summary))
    return summary


def purge_everything(admin=None):
    """End of pilot: deletes ALL reports and photos (keeping only anonymous counts, and
    any counterfeit report on legal hold). Callers must ask for explicit confirmation."""
    return run_retention(apply=True, admin=admin, everything=True)


# ---------- rights requests: delete one report ----------

def parse_reference(reference):
    """'12' or '#12' -> ('complaint', 12).  'CF-3' -> ('counterfeit', 3).  Otherwise None."""
    text = (reference or "").strip().upper().replace(" ", "")
    match = re.fullmatch(r"CF-?(\d+)", text)
    if match:
        return "counterfeit", int(match.group(1))
    match = re.fullmatch(r"#?(\d+)", text)
    if match:
        return "complaint", int(match.group(1))
    return None


def _real_phone_hash(value):
    """True if a stored hash belongs to a real phone number (not an anonymous report)."""
    return bool(value) and not str(value).startswith("anon_")


def describe_report(kind, report_id):
    """A short, non-sensitive summary for the admin to confirm they have the right
    report. Never returns the report text, photos or phone number."""
    with db.get_connection() as conn:
        if kind == "complaint":
            row = conn.execute(
                "SELECT c.incident_id AS id, b.brand_name, c.created_at, c.image_url AS photo, c.phone_hash "
                "FROM complaints c JOIN brands b ON b.brand_id = c.brand_id WHERE c.incident_id = ?",
                (report_id,)).fetchone()
            if not row:
                return None
            return {"kind": kind, "id": row["id"], "brand": row["brand_name"], "submitted": row["created_at"],
                    "photos": 1 if row["photo"] else 0, "phone_on_file": _real_phone_hash(row["phone_hash"]),
                    "legal_hold": False}
        row = conn.execute(
            "SELECT r.report_id AS id, b.brand_name, r.created_at, r.phone_hash, r.legal_hold "
            "FROM counterfeit_reports r JOIN brands b ON b.brand_id = r.brand_id WHERE r.report_id = ?",
            (report_id,)).fetchone()
        if not row:
            return None
        return {"kind": kind, "id": row["id"], "brand": row["brand_name"], "submitted": row["created_at"],
                "photos": 3, "phone_on_file": _real_phone_hash(row["phone_hash"]),
                "legal_hold": bool(row["legal_hold"])}


def delete_report(kind, report_id, phone_hash=None, admin=None):
    """Deletes one report and its photos. If the report has a phone number on file, the
    requester must supply that number (as the keyed hash) so we know it is theirs.
    Anonymous reports are deleted on the reference number alone. A counterfeit report on
    legal hold is never deleted here. Returns (ok, message)."""
    with db.get_connection() as conn:
        if kind == "complaint":
            row = conn.execute(
                "SELECT phone_hash, image_url FROM complaints WHERE incident_id = ?", (report_id,)).fetchone()
            hold, paths = False, [row["image_url"]] if row and row["image_url"] else []
        else:
            row = conn.execute(
                "SELECT phone_hash, legal_hold, front_photo, back_photo, outlet_photo "
                "FROM counterfeit_reports WHERE report_id = ?", (report_id,)).fetchone()
            hold = bool(row and row["legal_hold"])
            paths = [row[k] for k in ("front_photo", "back_photo", "outlet_photo")] if row else []

        if not row:
            return False, "No report with that reference."
        if hold:
            return False, "This report is on legal hold and cannot be deleted here. Ask the lawyer."
        stored = row["phone_hash"]
        if _real_phone_hash(stored):
            if not phone_hash or not hmac.compare_digest(str(stored), str(phone_hash)):
                return False, "Identity check failed: the phone number does not match this report."

        if kind == "complaint":
            conn.execute("DELETE FROM complaints WHERE incident_id = ?", (report_id,))
        else:
            conn.execute("DELETE FROM counterfeit_reports WHERE report_id = ?", (report_id,))
        conn.commit()

    deleted = sum(1 for p in paths if _delete_file(p))
    label = f"CF-{report_id}" if kind == "counterfeit" else f"#{report_id}"
    db.log_audit_action(admin, "DELETE_REPORT", detail=f"rights request: {label}")
    return True, f"Deleted report {label} and {deleted} photo(s)."


# ---------- command line ----------

LABELS = {
    "complaints": "Consumer reports to delete",
    "complaint_photos": "  of which photos",
    "phones_cleared": "Encrypted phone numbers to clear (SMS already sent)",
    "counterfeit": "Counterfeit reports to delete",
    "counterfeit_photos": "  of which photos",
    "counterfeit_on_hold": "Counterfeit reports kept on legal hold",
    "orphan_files": "Unreferenced photo files to delete",
    "score_cache_file": "AI score cache file to delete",
}

if __name__ == "__main__":
    apply_changes = "--apply" in sys.argv
    result = run_retention(apply=apply_changes)
    print("RETENTION RUN" + (" (APPLIED)" if apply_changes else " (dry run, nothing deleted)"))
    print(f"Rules: {AFTER_RESOLUTION_DAYS} days after resolution | {UNTIED_DAYS} days if never in an alert | "
          f"counterfeit {COUNTERFEIT_DAYS} days")
    for key, label in LABELS.items():
        print(f"  {label}: {result[key]}")
    if not apply_changes:
        print("Run again with --apply to delete.")