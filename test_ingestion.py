"""
Tests the ingestion.py logic added for encryption, quarantine, and the hybrid
photo-check gate. Every case passes explicit severity_score/confidence_score,
and fraud_audit.analyze_image_authenticity is monkeypatched with a stub, so
this file makes ZERO real AI calls and costs nothing to run.

Uses Naivas with complaint text that matches no cluster rule, so every
complaint here lands in 'unclassified' and never fires an alert - this file
is isolated from alerts.py entirely, on purpose.
"""

import crypto_utils
import db
import fraud_audit
import ingestion

NAIVAS = "Naivas"
NEUTRAL_TEXT = "Just leaving a general comment, nothing specific to report today"


def _fetch_complaint(incident_id):
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT phone_encrypted, status, is_quarantined, low_confidence_flag,
                   is_flagged_synthetic, authenticity_checked, authenticity_score
            FROM complaints WHERE incident_id = ?
            """,
            (incident_id,),
        ).fetchone()
    return dict(row)


def _stub_fraud_check(calls, return_value):
    """Returns a drop-in replacement for fraud_audit.analyze_image_authenticity
    that records every call (so we can assert it was/wasn't invoked) and returns
    a fixed result instead of calling any real API."""
    def _stub(image_bytes, mime_type="image/jpeg"):
        calls.append((len(image_bytes), mime_type))
        return return_value
    return _stub


def main():
    phone_counter = [0]

    def next_phone():
        phone_counter[0] += 1
        return f"0711{phone_counter[0]:06d}"

    # ---------- 1. Phone encryption round-trip ----------
    phone = next_phone()
    result = ingestion.submit_complaint(
        brand_name=NAIVAS, phone=phone, county="Nairobi", text=NEUTRAL_TEXT,
        severity_score=0.30, confidence_score=0.80,
    )
    row = _fetch_complaint(result["incident_id"])
    assert row["phone_encrypted"] is not None, "phone_encrypted was not stored"
    decrypted = crypto_utils.decrypt_field(row["phone_encrypted"])
    expected = ingestion.normalize_phone(phone)
    assert decrypted == expected, f"decrypted {decrypted!r} != expected {expected!r}"
    print(f"OK  1. phone_encrypted round-trips correctly ({expected})")

    # ---------- 2. Normal complaint: not quarantined ----------
    result = ingestion.submit_complaint(
        brand_name=NAIVAS, phone=next_phone(), county="Nairobi", text=NEUTRAL_TEXT,
        severity_score=0.30, confidence_score=0.80,
    )
    row = _fetch_complaint(result["incident_id"])
    assert row["is_quarantined"] == 0, row
    assert row["low_confidence_flag"] == 0, row
    assert row["status"] == "Open", row
    print("OK  2. normal complaint (confidence 0.80) stays Open, not quarantined")

    # ---------- 3. Low confidence -> low_confidence_flag + quarantine ----------
    result = ingestion.submit_complaint(
        brand_name=NAIVAS, phone=next_phone(), county="Nairobi", text=NEUTRAL_TEXT,
        severity_score=0.30, confidence_score=0.20,  # exactly at the <= 0.20 boundary
    )
    row = _fetch_complaint(result["incident_id"])
    assert row["low_confidence_flag"] == 1, row
    assert row["is_quarantined"] == 1, row
    assert row["status"] == "Quarantined", row
    print("OK  3. confidence 0.20 (boundary) -> low_confidence_flag + quarantined")

    result = ingestion.submit_complaint(
        brand_name=NAIVAS, phone=next_phone(), county="Nairobi", text=NEUTRAL_TEXT,
        severity_score=0.30, confidence_score=0.21,  # just above the boundary
    )
    row = _fetch_complaint(result["incident_id"])
    assert row["low_confidence_flag"] == 0, row
    assert row["is_quarantined"] == 0, row
    print("OK  4. confidence 0.21 (just above boundary) -> NOT flagged")

    # ---------- 5. Hybrid photo-check gate ----------
    original_check = fraud_audit.analyze_image_authenticity
    fake_image = b"fake-image-bytes-not-a-real-photo"

    try:
        # 5a. High severity + photo -> the AI check SHOULD run
        calls = []
        fraud_audit.analyze_image_authenticity = _stub_fraud_check(
            calls, {"authenticity_score": 0.9, "is_flagged_synthetic": False, "rationale": "stub"}
        )
        result = ingestion.submit_complaint(
            brand_name=NAIVAS, phone=next_phone(), county="Nairobi", text=NEUTRAL_TEXT,
            severity_score=0.90, confidence_score=0.90,
            image_bytes=fake_image, image_mime_type="image/jpeg",
        )
        row = _fetch_complaint(result["incident_id"])
        assert len(calls) == 1, f"expected 1 fraud check call, got {len(calls)}"
        assert row["authenticity_checked"] == 1, row
        assert row["is_quarantined"] == 0, row
        print("OK  5a. severity 0.90 + photo -> hybrid check RUNS (1 call), not quarantined")

        # 5b. Low severity + photo -> the AI check should NOT run (admin reviews later)
        calls.clear()
        result = ingestion.submit_complaint(
            brand_name=NAIVAS, phone=next_phone(), county="Nairobi", text=NEUTRAL_TEXT,
            severity_score=0.40, confidence_score=0.90,
            image_bytes=fake_image, image_mime_type="image/jpeg",
        )
        row = _fetch_complaint(result["incident_id"])
        assert len(calls) == 0, f"expected 0 fraud check calls, got {len(calls)}"
        assert row["authenticity_checked"] == 0, row
        print("OK  5b. severity 0.40 + photo -> hybrid check SKIPPED (deferred to admin)")

        # 5c. High severity, no photo -> nothing to check, the AI check should NOT run
        calls.clear()
        result = ingestion.submit_complaint(
            brand_name=NAIVAS, phone=next_phone(), county="Nairobi", text=NEUTRAL_TEXT,
            severity_score=0.90, confidence_score=0.90,
        )
        row = _fetch_complaint(result["incident_id"])
        assert len(calls) == 0, f"expected 0 fraud check calls, got {len(calls)}"
        assert row["authenticity_checked"] == 0, row
        print("OK  5c. severity 0.90, no photo -> hybrid check SKIPPED (nothing to check)")

        # 5d. High severity + photo the AI flags as synthetic -> quarantined
        calls.clear()
        fraud_audit.analyze_image_authenticity = _stub_fraud_check(
            calls, {"authenticity_score": 0.1, "is_flagged_synthetic": True, "rationale": "stub: looks fake"}
        )
        result = ingestion.submit_complaint(
            brand_name=NAIVAS, phone=next_phone(), county="Nairobi", text=NEUTRAL_TEXT,
            severity_score=0.90, confidence_score=0.90,
            image_bytes=fake_image, image_mime_type="image/jpeg",
        )
        row = _fetch_complaint(result["incident_id"])
        assert row["is_flagged_synthetic"] == 1, row
        assert row["is_quarantined"] == 1, row
        assert row["status"] == "Quarantined", row
        print("OK  5d. photo flagged synthetic -> is_flagged_synthetic + quarantined")

    finally:
        fraud_audit.analyze_image_authenticity = original_check  # always restore, even on failure

    print("\nAll ingestion tests passed. Now run: python seed_data.py to reset the demo data.")


if __name__ == "__main__":
    main()