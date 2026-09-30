import alerts
import db
import ingestion


def phone(n):
    return f"0700{n:06d}"          # 0700000001, 0700000002, ... all valid and distinct


def submit(n, county, text, severity, confidence):
    """Submits one complaint and returns (result, alerts fired by it). Works whether or
    not submit_complaint already runs the alert check itself."""
    r = ingestion.submit_complaint(
        brand_name="Equity Bank", phone=phone(n), county=county, text=text,
        severity_score=severity, confidence_score=confidence,
    )
    fired = r.get("alerts_fired")
    if fired is None:
        fired = alerts.check_alerts(r["brand_id"], r["issue_cluster"])
    return r, fired


def main():
    equity = db.get_brand_id("Equity Bank")
    safaricom = db.get_brand_id("Safaricom")
    unilever = db.get_brand_id("Unilever")

    assert len(db.get_active_alerts()) == 4, "Run python seed_data.py first (expected exactly 2 alerts)."

    # 1. Idempotency: seeded clusters already have their alerts, so nothing new fires
    assert alerts.check_alerts(safaricom, "app_freeze_step2") == []
    assert alerts.check_alerts(unilever, "oil_seal_leakage") == []
    assert alerts.check_alerts(equity, "unclassified") == []
    print("OK  1. seeded alerts are not duplicated; 'unclassified' never alerts")

    text = "ATM machine retention again, it kept my card at the branch"

    # 2. Urgency: one high-severity reporter with no photo is NOT enough
    r, fired = submit(1, "Nairobi", text, 0.90, 0.95)
    assert r["issue_cluster"] == "atm_card_retention", r["issue_cluster"]
    assert fired == [], f"1 reporter, no photo should not alert: {fired}"
    print("OK  2. single high-severity report, no photo -> no alert")

    # 3. Urgency: a second independent reporter fires the Red alert
    r, fired = submit(2, "Mombasa", text, 0.90, 0.95)
    assert len(fired) == 1 and fired[0]["alert_type"] == "URGENCY_SPIKE", fired
    assert fired[0]["trigger_count"] == 2, fired
    print("OK  3. second independent reporter -> URGENCY_SPIKE fired")

    # 4. Pattern: low-severity reports; must fire exactly on the 15th distinct reporter
    #    (1 seeded + 2 above = 3 so far, so reporters 3..14 bring the total to 15)
    counties = ["Nairobi", "Mombasa", "Kilifi", "Nakuru"]
    for n in range(3, 15):
        r, fired = submit(n, counties[n % 4], text, 0.45, 0.90)
        total = db.count_cluster_reports(equity, "atm_card_retention")
        if total < 15:
            assert fired == [], f"Fired early at {total} reports: {fired}"
        else:
            assert total == 15
            assert len(fired) == 1 and fired[0]["alert_type"] == "PATTERN_TREND", fired
            assert fired[0]["trigger_count"] == 15, fired
    print("OK  4. PATTERN_TREND fired exactly at the 15th independent report")

    # 5. Idempotency after firing: the 16th report must not fire a duplicate
    r, fired = submit(15, "Kilifi", text, 0.45, 0.90)
    assert fired == [], f"Duplicate alert fired: {fired}"
    print("OK  5. 16th report -> no duplicate alert")

    active = db.get_active_alerts()
    assert len(active) == 6, len(active)
    print("\nActive alerts now:")
    for a in active:
        print(f"  - {a['brand_name']}: {a['alert_type']} on {a['cluster_id']} ({a['trigger_count']})")
        print(f"      {a['action_brief_text']}")

    print("\nAll alert tests passed. Now run: python seed_data.py to reset the demo data.")


if __name__ == "__main__":
    main()