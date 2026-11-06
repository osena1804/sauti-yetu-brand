"""
Rehearses the L'Oreal live demo moment WITHOUT using any AI or sending any SMS:
scores are passed in explicitly, SAUTI_OFFLINE=1 turns the AI off, and the
auditor SMS function is replaced with a stub that only records what it would send.

Run python seed_data.py before this, and again after it (this test adds rows).
"""
import os

os.environ["SAUTI_OFFLINE"] = "1"

import db
import ingestion

LOREAL = "L'Oreal"


def main():
    brand_id = db.get_brand_id(LOREAL)
    assert brand_id, "L'Oreal brand not found - run python seed_data.py"

    start_types = sorted(a["alert_type"] for a in db.get_active_alerts(brand_id))
    assert start_types == ["PATTERN_TREND"], (
        f"Expected only the seeded amber alert at the start, found {start_types}. "
        "Run python seed_data.py first."
    )
    print("OK  0. starting state: one amber (pattern) alert, no red alert yet")

    sent_sms = []
    original_send = ingestion.sms_gateway.send_sms
    ingestion.sms_gateway.send_sms = lambda to, message: (sent_sms.append((to, message)) or (True, "stub"))

    def submit(n, county, text, severity, confidence):
        return ingestion.submit_complaint(
            brand_name=LOREAL, phone=f"0711900{n:03d}", county=county, text=text,
            severity_score=severity, confidence_score=confidence,
        )

    try:
        # 1. A joke: scary words but low confidence -> must NOT count toward a red alert
        r = submit(1, "Nairobi", "This cream literally burned my face lol I'm fine, just kidding", 0.90, 0.50)
        assert r["issue_cluster"] == "skin_reaction", r["issue_cluster"]
        assert r["alerts_fired"] == [], r["alerts_fired"]
        print("OK  1. joke (severity 0.90, confidence 0.50) -> no alert")

        # 2. A mild reaction: real, but below the red-alert severity bar
        r = submit(2, "Kisumu", "L'Oreal lotion made my skin itchy and red for a day", 0.65, 0.85)
        assert r["issue_cluster"] == "skin_reaction", r["issue_cluster"]
        assert r["alerts_fired"] == [], r["alerts_fired"]
        print("OK  2. mild itch (severity 0.65) -> no alert")

        # 3. THE LIVE MOMENT: a second independent severe report fires the red alert
        r = submit(3, "Mombasa", "My face swelled up and blistered after using this new L'Oreal serum", 0.90, 0.92)
        assert r["issue_cluster"] == "skin_reaction", r["issue_cluster"]
        fired = r["alerts_fired"]
        assert len(fired) == 1 and fired[0]["alert_type"] == "URGENCY_SPIKE", fired
        assert fired[0]["trigger_count"] == 2, fired
        print("OK  3. second severe report -> URGENCY_SPIKE fired (2 independent reporters)")

        # 4. The alert has a readable brief
        red = [a for a in db.get_active_alerts(brand_id) if a["alert_type"] == "URGENCY_SPIKE"]
        assert len(red) == 1, red
        brief = red[0]["action_brief_text"]
        assert "skin reaction" in brief and "L'Oreal" in brief, brief
        print("OK  4. red alert brief mentions the brand and the issue")

        # 5. A third severe report must not create a duplicate alert
        r = submit(4, "Nairobi", "Blisters and swelling on my scalp after the L'Oreal relaxer", 0.90, 0.90)
        assert r["alerts_fired"] == [], r["alerts_fired"]
        print("OK  5. third severe report -> no duplicate alert")

        # 6. The amber alert is untouched
        types = sorted(a["alert_type"] for a in db.get_active_alerts(brand_id))
        assert types == ["PATTERN_TREND", "URGENCY_SPIKE"], types
        print("OK  6. L'Oreal now shows one amber and one red alert")

        # 7. Auditor SMS (stubbed): exactly one text per auditor with a phone on file
        auditor_phones = db.get_auditor_phones()
        assert len(sent_sms) == len(auditor_phones), (sent_sms, auditor_phones)
        print(f"OK  7. auditor SMS attempted for {len(auditor_phones)} auditor(s) (stubbed, nothing really sent)")
    finally:
        ingestion.sms_gateway.send_sms = original_send

    print("\nL'Oreal demo moment works. Now run: python seed_data.py to reset.")


if __name__ == "__main__":
    main()