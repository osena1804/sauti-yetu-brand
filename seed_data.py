import sqlite3


def create_schema(cursor):
    """Creates tables if they don't already exist, so this script is safe to run standalone."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS brands (
            brand_id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_name VARCHAR(100) NOT NULL UNIQUE,
            category VARCHAR(50) NOT NULL,
            alert_phone_encrypted TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id INT REFERENCES brands(brand_id),
            county VARCHAR(50) NOT NULL,
            issue_cluster VARCHAR(100) NOT NULL,
            raw_text_scrubbed TEXT NOT NULL,
            image_url VARCHAR(255),
            phone_hash VARCHAR(64) NOT NULL,
            severity_score NUMERIC(3,2) NOT NULL,
            confidence_score NUMERIC(3,2) NOT NULL,
            urgency_level VARCHAR(20) DEFAULT 'HIGH',
            is_quarantined BOOLEAN DEFAULT FALSE,
            status VARCHAR(30) DEFAULT 'UNADDRESSED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS critical_alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id INT REFERENCES brands(brand_id),
            cluster_id VARCHAR(100) NOT NULL,
            alert_type VARCHAR(20) NOT NULL,
            trigger_count INT NOT NULL,
            has_photo_evidence BOOLEAN DEFAULT FALSE,
            action_brief_text TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resolutions (
            resolution_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INT REFERENCES complaints(incident_id),
            admin_name_encrypted TEXT NOT NULL,
            admin_public_id VARCHAR(50) NOT NULL,
            proof_image_url VARCHAR(255) NOT NULL,
            official_statement TEXT NOT NULL,
            verification_expires_at TIMESTAMP NOT NULL,
            dispute_count INT DEFAULT 0
        )
    """)


def get_brand_id(cursor, brand_name):
    """Looks up brand_id by name instead of relying on hardcoded insertion order.
    Safe to call after INSERT OR IGNORE, even on reruns against a non-empty db."""
    cursor.execute("SELECT brand_id FROM brands WHERE brand_name = ?", (brand_name,))
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Brand '{brand_name}' not found — check spelling against the brands list.")
    return row[0]


def seed_database(db_path="sauti_yetu.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    create_schema(cursor)

    # 1. Reset demo data so reruns are safe and idempotent (brands are preserved via INSERT OR IGNORE)
    cursor.execute("DELETE FROM resolutions")
    cursor.execute("DELETE FROM critical_alerts")
    cursor.execute("DELETE FROM complaints")

    # 2. Primary Brands (Local Enterprise Leaders + Top Kantar Global Accounts)
    brands = [
        ("Safaricom", "Telecom & Financial Services", "0722000000_enc"),
        ("Equity Bank", "Financial Services", "0711000000_enc"),
        ("Naivas", "Retail & Supermarkets", "0733000000_enc"),
        ("Bidco Africa", "FMCG & Edible Oils", "0744000000_enc"),
        ("Brookside Dairy", "FMCG & Dairy", "0755000000_enc"),
        ("Diageo / EABL", "Alcohol & Beverages", "0766000000_enc"),
        ("Unilever", "FMCG & Personal Care", "0777000000_enc"),
        ("Coca-Cola", "Beverages", "0788000000_enc"),
        ("Carrefour", "Retail", "0799000000_enc"),
        ("Samsung", "Consumer Electronics", "0700000000_enc"),
        ("KCB Group", "Financial Services", "0701000000_enc"),
        ("L'Oreal", "Beauty & Personal Care", "0702000000_enc"),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO brands (brand_name, category, alert_phone_encrypted) VALUES (?, ?, ?)",
        brands,
    )
    conn.commit()

    safaricom_id = get_brand_id(cursor, "Safaricom")
    unilever_id = get_brand_id(cursor, "Unilever")
    equity_id = get_brand_id(cursor, "Equity Bank")
    brookside_id = get_brand_id(cursor, "Brookside Dairy")
    kcb_id = get_brand_id(cursor, "KCB Group")
    naivas_id = get_brand_id(cursor, "Naivas")

    # 3. Pattern Trigger cluster — Safaricom "app_freeze_step2"
    # 15 distinct reports across 6 valid Kenyan counties (Nairobi, Kiambu, Mombasa, Nakuru, Kisumu, Uasin Gishu)
    freeze_variants = [
        ("Nairobi", "M-Pesa app imestuck na haicommence payment kwa step 2 screen inahung"),
        ("Nairobi", "The app freezes every time I try to pay, stuck on step 2"),
        ("Kiambu", "Screen inahang kabisa nikijaribu ku-confirm payment"),
        ("Mombasa", "App yangu inastuck step ya pili, sijui shida ni nini"),
        ("Nakuru", "Payment screen hangs and I have to force close the app"),
        ("Kisumu", "Naeza confirm step one but step two haiendi mbele"),
        ("Uasin Gishu", "App inafreeze kila nikijaribu kulipa kupitia step 2"),
        ("Nairobi", "Cannot press pay button, screen just hangs there"),
        ("Kiambu", "Imekuwa ikistuck kwa siku mbili, step 2 haiwork"),
        ("Nairobi", "The confirm payment button does nothing, app frozen"),
        ("Mombasa", "Screen hang mara moja nikifika step two ya malipo"),
        ("Nakuru", "App crashes softly, stuck on second screen every time"),
        ("Kisumu", "Sijawahi maliza malipo, inastuck step 2 kila mara"),
        ("Nairobi", "Freezing issue on payment step two, tried reinstalling too"),
        ("Kiambu", "Inahang step mbili tu, ingine zote zinaendaga poa"),
    ]
    for i, (county, text) in enumerate(freeze_variants, start=1):
        cursor.execute(
            """
            INSERT INTO complaints
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url, phone_hash,
             severity_score, confidence_score, urgency_level, status)
            VALUES (?, ?, 'app_freeze_step2', ?, NULL, ?, 0.45, 0.90, 'MEDIUM', 'UNADDRESSED')
            """,
            (safaricom_id, county, text, f"mock_hash_freeze_{i:03d}"),
        )

    # Pre-populate Amber Alert
    cursor.execute(
        """
        INSERT INTO critical_alerts
        (brand_id, cluster_id, alert_type, trigger_count, has_photo_evidence, action_brief_text)
        VALUES (?, 'app_freeze_step2', 'PATTERN_TREND', ?, 0, ?)
        """,
        (
            safaricom_id,
            len(freeze_variants),
            "15 independent reports across 6 counties describe the M-Pesa app freezing "
            "at the payment confirmation step. No single report is high-severity, but "
            "volume and geographic spread indicate a widespread app bug worth QA triage.",
        ),
    )

    # 4. Urgency Trigger — Unilever "oil_seal_leakage" (Red Alert: high severity + photo + 2 reports)
    oil_reports = [
        (
            "Kiambu",
            "Bought cooking oil batch UN-882 and the seal was broken causing contamination",
            "static/uploads/evidence_oil_contamination.jpg",
        ),
        (
            "Nairobi",
            "Same batch UN-882, oil smells off and seal was already broken at purchase",
            None,
        ),
    ]
    for i, (county, text, image) in enumerate(oil_reports, start=1):
        cursor.execute(
            """
            INSERT INTO complaints
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url, phone_hash,
             severity_score, confidence_score, urgency_level, status)
            VALUES (?, ?, 'oil_seal_leakage', ?, ?, ?, 0.90, 0.95, 'CRITICAL', 'UNADDRESSED')
            """,
            (unilever_id, county, text, image, f"mock_hash_oil_{i:03d}"),
        )

    cursor.execute(
        """
        INSERT INTO critical_alerts
        (brand_id, cluster_id, alert_type, trigger_count, has_photo_evidence, action_brief_text)
        VALUES (?, 'oil_seal_leakage', 'URGENCY_SPIKE', ?, 1, ?)
        """,
        (
            unilever_id,
            len(oil_reports),
            "Two independent reports of broken seals on cooking oil batch UN-882 in "
            "Kiambu and Nairobi, one with photo evidence of contamination. Recommend "
            "immediate batch trace and PR/legal notification.",
        ),
    )

    # 5. Background data — Equity Bank cluster
    cursor.execute(
        """
        INSERT INTO complaints
        (brand_id, county, issue_cluster, raw_text_scrubbed, image_url, phone_hash,
         severity_score, confidence_score, urgency_level, status)
        VALUES (?, 'Mombasa', 'atm_card_retention', ?, NULL, 'mock_hash_atm_001', 0.60, 0.88, 'HIGH', 'UNADDRESSED')
        """,
        (equity_id, "ATM machine retention without reversal notification at Changamwe branch"),
    )

    # 6. Urgency Trigger — Brookside Dairy "spoiled_milk" (Red Alert: contamination + photo + 2 reports)
    milk_reports = [
        (
            "Nairobi",
            "Nimenunua maziwa ya Brookside batch BD-441 na ni sour, mtoto wangu ana tumbo inauma sana",
            "static/uploads/evidence_spoiled_milk.jpg",
        ),
        (
            "Kiambu",
            "Same batch BD-441, milk was curdled and smelled bad straight out of the packet",
            None,
        ),
    ]
    for i, (county, text, image) in enumerate(milk_reports, start=1):
        cursor.execute(
            """
            INSERT INTO complaints
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url, phone_hash,
             severity_score, confidence_score, urgency_level, status)
            VALUES (?, ?, 'spoiled_milk', ?, ?, ?, 0.90, 0.92, 'CRITICAL', 'UNADDRESSED')
            """,
            (brookside_id, county, text, image, f"mock_hash_milk_{i:03d}"),
        )

    cursor.execute(
        """
        INSERT INTO critical_alerts
        (brand_id, cluster_id, alert_type, trigger_count, has_photo_evidence, action_brief_text)
        VALUES (?, 'spoiled_milk', 'URGENCY_SPIKE', ?, 1, ?)
        """,
        (
            brookside_id,
            len(milk_reports),
            "Two independent reports of spoiled milk from batch BD-441 in Nairobi and "
            "Kiambu, one describing a child's stomach illness and photo evidence attached. "
            "Recommend immediate batch trace and food-safety notification.",
        ),
    )

    # 7. Pattern Trigger cluster — KCB Group "failed_transaction"
    # 15 distinct reports across 6 valid Kenyan counties
    kcb_variants = [
        ("Nairobi", "KCB mobile banking transaction declined but money imekatwa from my account"),
        ("Mombasa", "Transfer failed twice today, no reversal notification received"),
        ("Kisumu", "Nilijaribu kutuma pesa lakini transaction ikadeclinewa, pesa haijarudi"),
        ("Nakuru", "App shows failed transaction but the money was deducted anyway"),
        ("Uasin Gishu", "Double debit on the same transfer, KCB app charged me twice"),
        ("Nairobi", "My account was debited but the recipient never received the funds"),
        ("Kiambu", "Transaction ilishindwa mara tatu leo, pesa bado haijaingia kwa account"),
        ("Mombasa", "Failed transfer, no reversal after two days of waiting"),
        ("Kisumu", "KCB app inaonyesha transaction failed lakini akaunti imekatwa"),
        ("Nakuru", "Money not received on the other end despite a successful debit message"),
        ("Nairobi", "Declined transaction but the balance still reflects the deduction"),
        ("Uasin Gishu", "Transfer haijafika, nimejaribu mara mbili leo asubuhi"),
        ("Kiambu", "Charged twice for one transaction, need a reversal urgently"),
        ("Mombasa", "Mobile banking transaction failed and support hasn't responded"),
        ("Nairobi", "Another failed transfer today, this is the third time this week"),
    ]
    for i, (county, text) in enumerate(kcb_variants, start=1):
        cursor.execute(
            """
            INSERT INTO complaints
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url, phone_hash,
             severity_score, confidence_score, urgency_level, status)
            VALUES (?, ?, 'failed_transaction', ?, NULL, ?, 0.55, 0.88, 'MEDIUM', 'UNADDRESSED')
            """,
            (kcb_id, county, text, f"mock_hash_kcb_{i:03d}"),
        )

    cursor.execute(
        """
        INSERT INTO critical_alerts
        (brand_id, cluster_id, alert_type, trigger_count, has_photo_evidence, action_brief_text)
        VALUES (?, 'failed_transaction', 'PATTERN_TREND', ?, 0, ?)
        """,
        (
            kcb_id,
            len(kcb_variants),
            "15 independent reports across 6 counties describe failed or declined KCB "
            "transactions where the account was still debited. No single report is "
            "high-severity, but the volume and repeated double-debit pattern warrant "
            "urgent reconciliation review.",
        ),
    )

    # 8. Naivas — background data only, deliberately left under the 15-report pattern
    # threshold. Submit one more live during the demo to cross it in real time.
    naivas_reports = [
        ("Nairobi", "Naivas Ngong Road hakuna stock ya sugar since last week"),
        ("Nakuru", "The receipt showed a different price than the shelf tag for cooking oil"),
        ("Mombasa", "Out of stock on bread again at the Nyali branch"),
        ("Kiambu", "Huduma mbaya kwa till, staff walikuwa rude sana leo"),
    ]
    for i, (county, text) in enumerate(naivas_reports, start=1):
        cursor.execute(
            """
            INSERT INTO complaints
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url, phone_hash,
             severity_score, confidence_score, urgency_level, status)
            VALUES (?, ?, 'stockout_and_pricing', ?, NULL, ?, 0.35, 0.85, 'LOW', 'UNADDRESSED')
            """,
            (naivas_id, county, text, f"mock_hash_naivas_{i:03d}"),
        )

    conn.commit()

    # Sanity checks
    cursor.execute("SELECT COUNT(*) FROM complaints")
    complaint_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM critical_alerts")
    alert_count = cursor.fetchone()[0]

    conn.close()
    print("Sauti-Yetu database successfully seeded!")
    print(f"Sanity Check: {complaint_count} complaints (Expected: 39) | {alert_count} alerts (Expected: 4)")


if __name__ == "__main__":
    seed_database()