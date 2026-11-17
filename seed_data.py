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
    """Looks up brand_id by name instead of relying on hardcoded insertion order."""
    cursor.execute("SELECT brand_id FROM brands WHERE brand_name = ?", (brand_name,))
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Brand '{brand_name}' not found - check spelling against the brands list.")
    return row[0]


# ---------------------------------------------------------------------------
# PILOT BRANDS - the only brands in the platform.
# IMPORTANT: these names must match the PILOT_BRANDS list in clustering.py
# exactly (same spelling, same punctuation), or reports for that brand will
# not be clustered. Confirm the final list and spellings with L'Oreal.
# ---------------------------------------------------------------------------
PILOT_BRANDS = [
    "Nice & Lovely",
    "Versman",
    "Mizani",
    "Garnier",
    "Dark & Lovely",
    "CeraVe",
]
BRAND_CATEGORY = "Beauty & Personal Care"  # adjust per brand once L'Oreal confirms


def seed_database(db_path="sauti_yetu.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    create_schema(cursor)

    # 1. Reset demo data so reruns are safe. Brands are reset too, so brands from
    #    older demo versions (Safaricom, Unilever, ...) cannot linger.
    cursor.execute("DELETE FROM resolutions")
    cursor.execute("DELETE FROM critical_alerts")
    cursor.execute("DELETE FROM complaints")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='counterfeit_reports'")
    if cursor.fetchone():
        cursor.execute("DELETE FROM counterfeit_reports")
    cursor.execute("DELETE FROM brands")

    # 2. Pilot brands
    cursor.executemany(
        "INSERT INTO brands (brand_name, category, alert_phone_encrypted) VALUES (?, ?, ?)",
        [(name, BRAND_CATEGORY, "not_set") for name in PILOT_BRANDS],
    )
    conn.commit()

    garnier_id = get_brand_id(cursor, "Garnier")
    dark_lovely_id = get_brand_id(cursor, "Dark & Lovely")

    # 3. Demo scenario (all simulated), on Garnier so the whole walkthrough happens in one workspace.
    # (a) AMBER pattern alert: white cast on deep skin tones, 15 reports, 6 counties.
    white_cast = [
        ("Nairobi", "Garnier sunscreen leaves a white cast on my face, I look ashy by noon"),
        ("Mombasa", "Sunscreen ya Garnier inaacha rangi nyeupe usoni, ngozi nyeusi inaonekana kijivu"),
        ("Kisumu", "The Garnier moisturiser with SPF looks chalky on deep skin tones"),
        ("Nakuru", "Foundation inaacha white film kwenye ngozi yangu nyeusi, haiblendi vizuri"),
        ("Nairobi", "Why does this sunscreen leave a whitish layer on dark skin? I look grey"),
        ("Kiambu", "Sunblock hii ni nyeupe sana kwenye ngozi nyeusi, naonekana kama nimepaka unga"),
        ("Uasin Gishu", "This face cream gives me an ashy white cast, it was not made for dark skin"),
        ("Mombasa", "Sunscreen hii ni chalky kwa ngozi nyeusi, naonekana nimepakwa chaki"),
        ("Nairobi", "The white residue from this SPF cream does not rub in on my skin"),
        ("Kisumu", "Sunscreen yenu inaacha rangi ya kijivu usoni, sijui kama imetengenezwa kwa ngozi nyeusi"),
        ("Nakuru", "Foundation shade looks ashy and chalky on my dark skin after an hour"),
        ("Nairobi", "I stopped using the sunscreen, the white cast is embarrassing on deep skin"),
        ("Kiambu", "Lotion hii ya SPF inaacha weupe usoni, haiendi hata nikisugua"),
        ("Mombasa", "Sunscreen white cast on dark skin, please make a version for us"),
        ("Uasin Gishu", "The foundation looks grey and chalky on my face, not made for deep skin"),
    ]
    for i, (county, text) in enumerate(white_cast, start=1):
        cursor.execute(
            """
            INSERT INTO complaints
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url, phone_hash,
             severity_score, confidence_score, urgency_level, status)
            VALUES (?, ?, 'white_cast_deep_skin', ?, NULL, ?, 0.40, 0.88, 'MEDIUM', 'UNADDRESSED')
            """,
            (garnier_id, county, text, f"mock_hash_garnier_cast_{i:03d}"),
        )

    counties_covered = len({county for county, _ in white_cast})
    cursor.execute(
        """
        INSERT INTO critical_alerts
        (brand_id, cluster_id, alert_type, trigger_count, has_photo_evidence, action_brief_text)
        VALUES (?, 'white_cast_deep_skin', 'PATTERN_TREND', ?, 0, ?)
        """,
        (
            garnier_id,
            len(white_cast),
            f"{len(white_cast)} independent reports across {counties_covered} counties describe a white "
            "or ashy cast left by sunscreen and face products on deep skin tones. No single report is "
            "a safety issue, but the volume and geographic spread suggest a shade-range or formulation "
            "issue worth R&I review. The reports do not establish a cause.",
        ),
    )

    # (b) RED alert waiting to fire: one severe report is already in, so ONE more severe
    # live submission makes 2 independent reporters and fires the alert on stage.
    skin_reaction = [
        ("Nairobi", "My skin swelled up and blistered after using a new face serum, I had to go to the pharmacy", 0.90, 0.92, "CRITICAL"),
        ("Kisumu", "New lotion made my skin itchy and red for two days, I stopped using it", 0.65, 0.85, "HIGH"),
        ("Mombasa", "Nimepata vipele usoni baada ya kutumia cream mpya", 0.65, 0.80, "HIGH"),
    ]
    for i, (county, text, sev, conf, level) in enumerate(skin_reaction, start=1):
        cursor.execute(
            """
            INSERT INTO complaints
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url, phone_hash,
             severity_score, confidence_score, urgency_level, status)
            VALUES (?, ?, 'skin_reaction', ?, NULL, ?, ?, ?, ?, 'UNADDRESSED')
            """,
            (garnier_id, county, text, f"mock_hash_garnier_skin_{i:03d}", sev, conf, level),
        )

    # (c) Background data: a few hair-damage reports, deliberately under the 15-report pattern
    # threshold. Shows the third cluster without raising an alert.
    hair_damage = [
        ("Nairobi", "Nywele zangu zinakatika baada ya kutumia relaxer mpya ya Dark & Lovely"),
        ("Kisumu", "My hair is breaking off at the edges since I used the Dark & Lovely relaxer"),
        ("Mombasa", "Hair loss after the Dark & Lovely treatment, it is falling out in clumps"),
        ("Nakuru", "Hair became dry and brittle after the relaxer, lots of breakage"),
    ]
    for i, (county, text) in enumerate(hair_damage, start=1):
        cursor.execute(
            """
            INSERT INTO complaints
            (brand_id, county, issue_cluster, raw_text_scrubbed, image_url, phone_hash,
             severity_score, confidence_score, urgency_level, status)
            VALUES (?, ?, 'hair_damage', ?, NULL, ?, 0.55, 0.85, 'MEDIUM', 'UNADDRESSED')
            """,
            (dark_lovely_id, county, text, f"mock_hash_dl_hair_{i:03d}"),
        )

    conn.commit()

    # Sanity checks
    cursor.execute("SELECT COUNT(*) FROM brands")
    brand_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM complaints")
    complaint_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM critical_alerts")
    alert_count = cursor.fetchone()[0]

    conn.close()
    print("Sauti-Yetu database successfully seeded!")
    print(f"Sanity Check: {brand_count} brands (Expected: 6) | {complaint_count} complaints (Expected: 22) "
          f"| {alert_count} alerts (Expected: 1)")


if __name__ == "__main__":
    seed_database()