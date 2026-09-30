import sqlite3

import crypto_utils
import seed_data 

DB_PATH = "sauti_yetu.db"


def init_and_autoseed_db(db_path="sauti_yetu.db"):
    """Ensures tables exist and auto-seeds initial data on empty cloud deployments."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Create tables if they don't exist yet
    seed_data.create_schema(cursor)
    conn.commit()
    
    # 2. Check if database is empty
    cursor.execute("SELECT COUNT(*) FROM complaints")
    count = cursor.fetchone()[0]
    conn.close()
    
    # 3. If empty, run seed_database
    if count == 0:
        print("Empty database detected. Auto-seeding initial enterprise telemetry...")
        seed_data.seed_database(db_path)

# Call this on app startup
init_and_autoseed_db()


def get_connection(db_path=DB_PATH):
    """Returns a connection where rows behave like dicts (row["brand_name"])."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_resolution_columns():
    """Adds resolution/dispute columns to critical_alerts if they don't exist yet.
    Safe to run every time this module is imported: it's a no-op once the columns
    are present, and it does nothing if seed_data.py hasn't created the table yet."""
    with get_connection() as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='critical_alerts'"
        ).fetchone()
        if not table:
            return
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(critical_alerts)")}
        migrations = {
            "resolution_status": "ALTER TABLE critical_alerts ADD COLUMN resolution_status VARCHAR(30) DEFAULT 'UNADDRESSED'",
            "admin_public_id": "ALTER TABLE critical_alerts ADD COLUMN admin_public_id VARCHAR(50)",
            "admin_identity_encrypted": "ALTER TABLE critical_alerts ADD COLUMN admin_identity_encrypted TEXT",
            "proof_text": "ALTER TABLE critical_alerts ADD COLUMN proof_text TEXT",
            "official_statement": "ALTER TABLE critical_alerts ADD COLUMN official_statement TEXT",
            "verification_expires_at": "ALTER TABLE critical_alerts ADD COLUMN verification_expires_at TIMESTAMP",
            "dispute_count": "ALTER TABLE critical_alerts ADD COLUMN dispute_count INTEGER DEFAULT 0",
            "resolution_sms_sent": "ALTER TABLE critical_alerts ADD COLUMN resolution_sms_sent INTEGER DEFAULT 0",
        }

        for column, ddl in migrations.items():
            if column not in existing:
                conn.execute(ddl)
        conn.commit()


def _ensure_auth_tables():
    """Creates admins and audit_log if they don't exist. CREATE TABLE IF NOT
    EXISTS is a no-op once they're there, so this is safe on every import."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                real_name TEXT NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'brand_manager',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                username VARCHAR(50),
                action VARCHAR(50) NOT NULL,
                alert_id INTEGER,
                detail TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def _migrate_complaint_columns():
    """Adds phone_encrypted and fraud/authenticity columns to complaints if missing.
    Storing the phone in reversible (AES-256-GCM) form is a deliberate, narrow
    exception to the one-way-hash-only design: it exists ONLY so resolution SMS
    can be sent to the people who actually reported an issue, and it is decrypted
    ONLY inside get_first_n_reporters_for_cluster, never surfaced in any UI or
    query elsewhere. phone_hash remains the one-way field used for all dedupe/counting."""
    with get_connection() as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='complaints'"
        ).fetchone()
        if not table:
            return
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(complaints)")}
        migrations = {
            "phone_encrypted": "ALTER TABLE complaints ADD COLUMN phone_encrypted TEXT",
            "authenticity_score": "ALTER TABLE complaints ADD COLUMN authenticity_score REAL DEFAULT 1.0",
            "is_flagged_synthetic": "ALTER TABLE complaints ADD COLUMN is_flagged_synthetic INTEGER DEFAULT 0",
            "low_confidence_flag": "ALTER TABLE complaints ADD COLUMN low_confidence_flag INTEGER DEFAULT 0",
            "authenticity_checked": "ALTER TABLE complaints ADD COLUMN authenticity_checked INTEGER DEFAULT 0",
        }
        for column, ddl in migrations.items():
            if column not in existing:
                conn.execute(ddl)
        conn.commit()


def _migrate_admin_columns():
    """Adds phone to admins if missing, for the critical-alert SMS pipeline."""
    with get_connection() as conn:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(admins)")}
        if "phone" not in existing:
            conn.execute("ALTER TABLE admins ADD COLUMN phone VARCHAR(20)")
        conn.commit()


_migrate_resolution_columns()
_migrate_complaint_columns()
_ensure_auth_tables()
_migrate_admin_columns()


# ---------- Brands ----------

def get_brand_id(brand_name):
    """Returns brand_id for a brand name, or None if it doesn't exist."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT brand_id FROM brands WHERE brand_name = ?", (brand_name,)
        ).fetchone()
    return row["brand_id"] if row else None


def get_brand_name(brand_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT brand_name FROM brands WHERE brand_id = ?", (brand_id,)
        ).fetchone()
    return row["brand_name"] if row else None


def list_brands():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT brand_id, brand_name, category FROM brands ORDER BY brand_name"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- Complaints ----------

def insert_complaint(brand_id, county, issue_cluster, raw_text_scrubbed,
                     phone_hash, severity_score, confidence_score,
                     urgency_level="MEDIUM", image_url=None, phone_encrypted=None,
                     authenticity_score=1.0, is_flagged_synthetic=False,
                     low_confidence_flag=False, is_quarantined=False, status="Open",
                     authenticity_checked=False):
    """Inserts one complaint and returns its new incident_id."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO complaints
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url,
             phone_hash, severity_score, confidence_score, urgency_level, phone_encrypted,
             authenticity_score, is_flagged_synthetic, low_confidence_flag, is_quarantined, status,
             authenticity_checked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url,
             phone_hash, severity_score, confidence_score, urgency_level, phone_encrypted,
             authenticity_score, 1 if is_flagged_synthetic else 0,
             1 if low_confidence_flag else 0, 1 if is_quarantined else 0, status,
             1 if authenticity_checked else 0),
        )
        return cur.lastrowid


def count_cluster_reports(brand_id, issue_cluster, hours=24):
    """Counts independent reports (distinct phone_hash) in a cluster within the
    rolling window. Quarantined (suspected fraud) rows are excluded."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT phone_hash) AS n
            FROM complaints
            WHERE brand_id = ?
              AND issue_cluster = ?
              AND is_quarantined = 0
              AND created_at >= datetime('now', ?)
            """,
            (brand_id, issue_cluster, f"-{int(hours)} hours"),
        ).fetchone()
    return row["n"]


def cluster_has_photo(brand_id, issue_cluster):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM complaints
            WHERE brand_id = ? AND issue_cluster = ?
              AND image_url IS NOT NULL AND is_quarantined = 0
            """,
            (brand_id, issue_cluster),
        ).fetchone()
    return row["n"] > 0


def get_complaints_for_cluster(brand_id, issue_cluster):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT incident_id, county, raw_text_scrubbed, image_url,
                   severity_score, confidence_score, urgency_level, status, created_at,
                   authenticity_score, is_flagged_synthetic, authenticity_checked
            FROM complaints
            WHERE brand_id = ? AND issue_cluster = ? AND is_quarantined = 0
            ORDER BY created_at DESC
            """,
            (brand_id, issue_cluster),
        ).fetchall()
    return [dict(r) for r in rows]


def get_urgent_stats(brand_id, issue_cluster, min_severity, min_confidence, hours=24):
    """Independent reporters in a cluster who meet BOTH the severity and confidence
    bars inside the window, and whether any of those reports has a photo."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT phone_hash) AS reporters,
                   MAX(CASE WHEN image_url IS NOT NULL THEN 1 ELSE 0 END) AS has_photo
            FROM complaints
            WHERE brand_id = ? AND issue_cluster = ? AND is_quarantined = 0
              AND severity_score >= ? AND confidence_score >= ?
              AND created_at >= datetime('now', ?)
            """,
            (brand_id, issue_cluster, min_severity, min_confidence, f"-{int(hours)} hours"),
        ).fetchone()
    return {"reporters": row["reporters"], "has_photo": bool(row["has_photo"])}


# ---------- Alerts ----------

def get_active_alerts(brand_id=None):
    """Active alerts, newest first. Pass brand_id to filter to one brand."""
    query = """
        SELECT a.alert_id, a.brand_id, b.brand_name, a.cluster_id, a.alert_type,
               a.trigger_count, a.has_photo_evidence, a.action_brief_text,
               a.triggered_at
        FROM critical_alerts a
        JOIN brands b ON b.brand_id = a.brand_id
        WHERE a.is_active = 1
    """
    params = ()
    if brand_id is not None:
        query += " AND a.brand_id = ?"
        params = (brand_id,)
    query += " ORDER BY a.triggered_at DESC, a.alert_id DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def alert_exists(brand_id, cluster_id, alert_type):
    """True if an active alert of this type already exists for the cluster,
    so the alert engine never fires the same alert twice."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM critical_alerts
            WHERE brand_id = ? AND cluster_id = ? AND alert_type = ? AND is_active = 1
            """,
            (brand_id, cluster_id, alert_type),
        ).fetchone()
    return row is not None


def insert_alert(brand_id, cluster_id, alert_type, trigger_count,
                 has_photo_evidence, action_brief_text):
    """Inserts an alert and returns its alert_id."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO critical_alerts
            (brand_id, cluster_id, alert_type, trigger_count,
             has_photo_evidence, action_brief_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (brand_id, cluster_id, alert_type, trigger_count,
             1 if has_photo_evidence else 0, action_brief_text),
        )
        return cur.lastrowid


# ---------- Resolution & dispute tracking ----------
# Scoped to the alert (brand + cluster), not to individual complaints, to keep the
# demo simple. The real admin identity behind a resolution is never stored in
# plaintext: it's AES-256-GCM encrypted (admin_identity_encrypted), and only a
# deterministic, one-way masked badge (admin_public_id) is shown publicly. The
# encrypted value is decrypted only on-demand, from the dispute audit flow.

def get_alert(alert_id):
    """Returns the alert with its brand name and a live days_unaddressed figure
    computed directly from triggered_at, so it is never a value that needs resetting."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT a.*, b.brand_name,
                   CAST(julianday('now') - julianday(a.triggered_at) AS REAL) AS days_unaddressed
            FROM critical_alerts a
            JOIN brands b ON b.brand_id = a.brand_id
            WHERE a.alert_id = ?
            """,
            (alert_id,),
        ).fetchone()
    return dict(row) if row else None


def find_alert(brand_name, cluster_id):
    """Looks up the active alert_id for a brand + cluster, so the demo doesn't need
    to hardcode an alert_id that could shift after a reseed."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT a.alert_id
            FROM critical_alerts a
            JOIN brands b ON b.brand_id = a.brand_id
            WHERE b.brand_name = ? AND a.cluster_id = ? AND a.is_active = 1
            ORDER BY a.alert_id DESC LIMIT 1
            """,
            (brand_name, cluster_id),
        ).fetchone()
    return row["alert_id"] if row else None


def submit_resolution(alert_id, admin_real_identity, proof_text, official_statement, hours=72):
    """Brand submits proof + statement. admin_real_identity (name/employee ID) is
    NEVER stored in plaintext: it's AES-256-GCM encrypted at rest, and only a
    deterministic, one-way masked badge derived from it is shown publicly. The
    encrypted value is decrypted only on-demand, from the dispute audit flow."""
    admin_public_id = crypto_utils.generate_public_badge(admin_real_identity)
    admin_identity_encrypted = crypto_utils.encrypt_field(admin_real_identity)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE critical_alerts
            SET resolution_status = 'PENDING_VERIFICATION',
                admin_public_id = ?, admin_identity_encrypted = ?,
                proof_text = ?, official_statement = ?,
                verification_expires_at = datetime('now', ?)
            WHERE alert_id = ?
            """,
            (admin_public_id, admin_identity_encrypted, proof_text, official_statement,
             f"+{int(hours)} hours", alert_id),
        )
        conn.commit()


def get_decrypted_admin_identity(alert_id):
    """Decrypts and returns the real admin identity for one alert. Intended to be
    called only from an explicit, on-demand audit action in the UI - NOT for
    routine rendering of the alert. There is currently no login/session system
    gating who can trigger this beyond app.py's role check; that's a real gap
    versus the KMS/Vault-backed access control the architecture describes,
    tracked separately, not solved by the encryption itself."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT admin_identity_encrypted FROM critical_alerts WHERE alert_id = ?",
            (alert_id,),
        ).fetchone()
    if not row or not row["admin_identity_encrypted"]:
        return None
    return crypto_utils.decrypt_field(row["admin_identity_encrypted"])


def simulate_verification_window_passed(alert_id):
    """Demo-only: fast-forwards the 72h window into the past so the next render's
    finalize_if_expired() call resolves it immediately, with no real waiting."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE critical_alerts SET verification_expires_at = datetime('now', '-1 minutes') "
            "WHERE alert_id = ?",
            (alert_id,),
        )
        conn.commit()


def add_dispute(alert_id):
    """Simulates one affected user tapping 'Still experiencing issue'."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE critical_alerts SET dispute_count = dispute_count + 1 WHERE alert_id = ?",
            (alert_id,),
        )
        conn.commit()


def finalize_if_expired(alert_id, dispute_threshold_ratio=0.20):
    """If the verification window has passed, resolves it: RESOLVED if disputes stayed
    under the threshold, or DISPUTED (escalation reversal) if they crossed it. A no-op,
    returning the current status unchanged, if the window hasn't passed yet or the
    alert isn't in PENDING_VERIFICATION. Call this once at the top of any render that
    shows the alert, so time-based transitions happen without a separate poller."""
    alert = get_alert(alert_id)
    if not alert or alert["resolution_status"] != "PENDING_VERIFICATION":
        return alert["resolution_status"] if alert else None

    with get_connection() as conn:
        expired = conn.execute(
            "SELECT datetime('now') >= verification_expires_at AS expired "
            "FROM critical_alerts WHERE alert_id = ?",
            (alert_id,),
        ).fetchone()["expired"]
    if not expired:
        return "PENDING_VERIFICATION"

    ratio = alert["dispute_count"] / max(1, alert["trigger_count"])
    new_status = "DISPUTED" if ratio > dispute_threshold_ratio else "RESOLVED"
    with get_connection() as conn:
        if new_status == "RESOLVED":
            conn.execute(
                "UPDATE critical_alerts SET resolution_status = 'RESOLVED', is_active = 0 "
                "WHERE alert_id = ?",
                (alert_id,),
            )
        else:
            conn.execute(
                "UPDATE critical_alerts SET resolution_status = 'DISPUTED' WHERE alert_id = ?",
                (alert_id,),
            )
        conn.commit()
    return new_status


def reopen_alert(alert_id):
    """After a DISPUTED escalation, lets the brand attempt resolution again.
    dispute_count and days_unaddressed are deliberately NOT reset, matching the
    blueprint: 'the latency counter resumes without resetting'."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE critical_alerts
            SET resolution_status = 'UNADDRESSED', verification_expires_at = NULL,
                admin_public_id = NULL, admin_identity_encrypted = NULL,
                proof_text = NULL, official_statement = NULL
            WHERE alert_id = ?
            """,
            (alert_id,),
        )
        conn.commit()


# ---------- Admin accounts & access control ----------

def create_admin(username, password, real_name, role="brand_manager", phone=None):
    """role is 'brand_manager' (submits resolutions) or 'auditor' (decrypts
    identities during a dispute). phone is used to SMS auditors on a critical
    alert. Raises sqlite3.IntegrityError on a taken username."""
    password_hash = crypto_utils.hash_password(password)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO admins (username, password_hash, real_name, role, phone) VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, real_name, role, phone),
        )
        conn.commit()


def verify_admin_login(username, password):
    """Returns {admin_id, username, real_name, role} on success, else None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT admin_id, username, password_hash, real_name, role FROM admins WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or not crypto_utils.verify_password(password, row["password_hash"]):
        return None
    return {"admin_id": row["admin_id"], "username": row["username"],
            "real_name": row["real_name"], "role": row["role"]}


def log_audit_action(admin, action, alert_id=None, detail=None):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO audit_log (admin_id, username, action, alert_id, detail) VALUES (?, ?, ?, ?, ?)",
            (admin["admin_id"] if admin else None,
             admin["username"] if admin else "anonymous",
             action, alert_id, detail),
        )
        conn.commit()


def get_audit_log_for_alert(alert_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT username, action, detail, created_at FROM audit_log "
            "WHERE alert_id = ? ORDER BY created_at DESC",
            (alert_id,),
        ).fetchall()
    return [dict(r) for r in rows]

def get_first_n_reporters_for_cluster(brand_id, issue_cluster, n=10):
    """Decrypts and returns up to n phone numbers, one per distinct reporter,
    ordered by who reported FIRST in this cluster - not most recent. Decryption
    happens here and only here; the result is meant to be used immediately to
    send SMS and then discarded, never stored or displayed."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.phone_encrypted
            FROM complaints c
            JOIN (
                SELECT phone_hash, MIN(created_at) AS first_seen
                FROM complaints
                WHERE brand_id = ? AND issue_cluster = ? AND is_quarantined = 0
                  AND phone_encrypted IS NOT NULL
                GROUP BY phone_hash
            ) first ON first.phone_hash = c.phone_hash AND first.first_seen = c.created_at
            WHERE c.brand_id = ? AND c.issue_cluster = ?
            ORDER BY first.first_seen ASC
            LIMIT ?
            """,
            (brand_id, issue_cluster, brand_id, issue_cluster, n),
        ).fetchall()
    phones = []
    for row in rows:
        try:
            phones.append(crypto_utils.decrypt_field(row["phone_encrypted"]))
        except Exception:
            continue  # skip any row that fails to decrypt rather than crash the batch
    return phones


def mark_resolution_sms_sent(alert_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE critical_alerts SET resolution_sms_sent = 1 WHERE alert_id = ?",
            (alert_id,),
        )
        conn.commit()


def get_auditor_phones():
    """Phone numbers of all admins with role='auditor' who have one on file."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT phone FROM admins WHERE role = 'auditor' AND phone IS NOT NULL AND phone != ''"
        ).fetchall()
    return [row["phone"] for row in rows]


def update_admin_phone(username, phone):
    """For adding a phone to an admin created before this column existed -
    e.g. your existing kotieno account."""
    with get_connection() as conn:
        conn.execute("UPDATE admins SET phone = ? WHERE username = ?", (phone, username))
        conn.commit()

def set_photo_authenticity(incident_id, authenticity_score, is_flagged_synthetic):
    """Records the result of an on-demand photo authenticity check. If flagged
    synthetic, quarantines the complaint so it stops counting toward public
    alert thresholds until an admin reviews it in the Fraud Audit tab."""
    with get_connection() as conn:
        if is_flagged_synthetic:
            conn.execute(
                """
                UPDATE complaints
                SET authenticity_score = ?, is_flagged_synthetic = 1,
                    authenticity_checked = 1, is_quarantined = 1, status = 'Quarantined'
                WHERE incident_id = ?
                """,
                (authenticity_score, incident_id),
            )
        else:
                        conn.execute(
                """
                UPDATE complaints
                SET authenticity_score = ?, is_flagged_synthetic = 0, authenticity_checked = 1
                WHERE incident_id = ?
                """,
                (authenticity_score, incident_id),
            )
        conn.commit()


def get_quarantined_complaints(brand_id=None):
    """Quarantined complaints (is_quarantined = 1), newest first, joined with brand
    name for display in the fraud audit tab."""
    query = """
        SELECT c.*, b.brand_name
        FROM complaints c
        JOIN brands b ON b.brand_id = c.brand_id
        WHERE c.is_quarantined = 1
    """
    params = ()
    if brand_id is not None:
        query += " AND c.brand_id = ?"
        params = (brand_id,)
    query += " ORDER BY c.created_at DESC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def update_complaint_status(incident_id, new_status, is_quarantined=None):
    """Updates a complaint's status. Pass is_quarantined explicitly to also change
    quarantine state - e.g. clearing it when an admin overrides a false positive
    back to Open, so it starts counting toward alert thresholds again."""
    with get_connection() as conn:
        if is_quarantined is None:
            conn.execute("UPDATE complaints SET status = ? WHERE incident_id = ?", (new_status, incident_id))
        else:
            conn.execute(
                "UPDATE complaints SET status = ?, is_quarantined = ? WHERE incident_id = ?",
                (new_status, 1 if is_quarantined else 0, incident_id),
            )
        conn.commit()

# ---------- Read-only self-test ----------

if __name__ == "__main__":
    print("Brands:", len(list_brands()))

    safaricom = get_brand_id("Safaricom")
    unilever = get_brand_id("Unilever")
    print("Safaricom id:", safaricom, "| Unilever id:", unilever)

    print("Freeze cluster count (24h):", count_cluster_reports(safaricom, "app_freeze_step2"), "(expected 15)")
    print("Oil cluster count (24h):", count_cluster_reports(unilever, "oil_seal_leakage"), "(expected 2)")
    print("Oil cluster has photo:", cluster_has_photo(unilever, "oil_seal_leakage"), "(expected True)")

    alerts = get_active_alerts()
    print("Active alerts:", len(alerts), "(expected 4 after a fresh seed)")
    for a in alerts:
        print(f"  - {a['brand_name']}: {a['alert_type']} on {a['cluster_id']} ({a['trigger_count']})")

    print("Alert exists (Safaricom PATTERN_TREND):",
          alert_exists(safaricom, "app_freeze_step2", "PATTERN_TREND"), "(expected True)")

    oil_alert_id = find_alert("Unilever", "oil_seal_leakage")
    print("\nOil alert_id:", oil_alert_id)
    print("Oil alert details:", get_alert(oil_alert_id))