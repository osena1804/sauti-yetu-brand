import hashlib
import hmac
import os
import re
import secrets
import sys

import db
import clustering
import alerts
import scoring
import crypto_utils
import sms_gateway
import fraud_audit

# ---------- Salt ----------
# Set a real secret before any live use (PowerShell):
#   $env:SAUTI_SALT = "some-long-random-string"
# Changing the salt later changes every hash, which breaks dedupe continuity.
_DEV_SALT = "dev-only-salt-change-me"
SALT = os.environ.get("SAUTI_SALT", _DEV_SALT)
if SALT == _DEV_SALT:
    print("[ingestion] WARNING: using dev salt. Set SAUTI_SALT for anything beyond local testing.")

# ---------- Counties ----------
KENYAN_COUNTIES = [
    "Mombasa", "Kwale", "Kilifi", "Tana River", "Lamu", "Taita-Taveta", "Garissa",
    "Wajir", "Mandera", "Marsabit", "Isiolo", "Meru", "Tharaka-Nithi", "Embu", "Kitui",
    "Machakos", "Makueni", "Nyandarua", "Nyeri", "Kirinyaga", "Murang'a", "Kiambu",
    "Turkana", "West Pokot", "Samburu", "Trans Nzoia", "Uasin Gishu", "Elgeyo-Marakwet",
    "Nandi", "Baringo", "Laikipia", "Nakuru", "Narok", "Kajiado", "Kericho", "Bomet",
    "Kakamega", "Vihiga", "Bungoma", "Busia", "Siaya", "Kisumu", "Homa Bay", "Migori",
    "Kisii", "Nyamira", "Nairobi",
]
_COUNTY_LOOKUP = {c.lower(): c for c in KENYAN_COUNTIES}


def normalize_county(county):
    """Returns the canonical county name, or None if it isn't one of the 47."""
    return _COUNTY_LOOKUP.get(str(county).strip().lower())


# ---------- Phone handling ----------

def normalize_phone(phone):
    """Converts common Kenyan formats (0712..., 254712..., +254712..., with spaces
    or dashes) to canonical +2547XXXXXXXX / +2541XXXXXXXX. Returns None if invalid."""
    digits = re.sub(r"[^\d+]", "", str(phone))
    digits = digits.lstrip("+")
    if digits.startswith("254") and len(digits) == 12:
        national = digits[3:]
    elif digits.startswith("0") and len(digits) == 10:
        national = digits[1:]
    elif len(digits) == 9:
        national = digits
    else:
        return None
    if national[0] not in "17":
        return None
    return "+254" + national


def hash_phone(phone):
    """One-way keyed hash (HMAC-SHA256) of the normalized number. The same person
    always produces the same hash, so dedupe works without storing the number."""
    normalized = normalize_phone(phone)
    if normalized is None:
        raise ValueError("Invalid Kenyan phone number.")
    return hmac.new(SALT.encode(), normalized.encode(), hashlib.sha256).hexdigest()


# ---------- PII scrubbing ----------
_PHONE_IN_TEXT = re.compile(r"(?:\+?254|\b0)[\s-]?[17]\d{2}[\s-]?\d{3}[\s-]?\d{3}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ID_NUMBER = re.compile(r"\b\d{7,8}\b")
_MPESA_CODE = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{10}\b")


def scrub_pii(text):
    """Masks phone numbers, emails, ID-number-like digits and M-Pesa transaction
    codes. Batch codes like 'UN-882' are left alone. Names cannot be reliably
    removed with patterns, so this is a first line of defence, not a guarantee."""
    text = _EMAIL.sub("[EMAIL]", text)
    text = _PHONE_IN_TEXT.sub("[PHONE]", text)
    text = _MPESA_CODE.sub("[TXN_CODE]", text)
    text = _ID_NUMBER.sub("[ID]", text)
    return text.strip()


# ---------- Main entry point ----------

def submit_complaint(brand_name, phone, county, text, image_url=None,
                     issue_cluster=None, severity_score=None,
                     confidence_score=None, urgency_level=None,
                     image_bytes=None, image_mime_type=None, 
                     consent_version=None, consent_sms=False, 
                     consent_language=None):
    """Validates input, hashes the phone, scrubs the text, classifies into a cluster,
    and stores the complaint. Returns a dict with the new incident_id and details."""
    if not consent_version:
        raise ValueError("Consent is required before a report can be submitted.")
    brand_id = db.get_brand_id(brand_name)
    if brand_id is None:
        raise ValueError(f"Unknown brand: {brand_name!r}")
    if not db.brand_is_active(brand_id):
        raise ValueError(f"Brand not available: {brand_name!r}")

    clean_county = normalize_county(county)
    if clean_county is None:
        raise ValueError(f"Not a valid Kenyan county: {county!r}")

    if not text or not text.strip():
        raise ValueError("Complaint text is empty.")

        phone = (phone or "").strip()
    if phone:
        phone_hash = hash_phone(phone)  # raises ValueError if the number is invalid
        phone_encrypted = crypto_utils.encrypt_field(normalize_phone(phone)) if consent_sms else None
    else:
        # Anonymous report: no phone stored, so no SMS can be sent for it.
        phone_hash = "anon_" + secrets.token_hex(16)
        phone_encrypted = None
    scrubbed = scrub_pii(text)

    if issue_cluster is None:
        issue_cluster = clustering.classify(brand_name, scrubbed)

    if severity_score is None or confidence_score is None:
        score = scoring.score_complaint(brand_name, scrubbed)
        severity_score = score["severity_score"]
        confidence_score = score["confidence_score"]
    if urgency_level is None:
        urgency_level = scoring.urgency_from_severity(severity_score)

        # Fraud/authenticity signals. low_confidence_flag reuses the same confidence
    # threshold scoring.py already applies to prompt-injection and implausible
    # text (<= 0.20) - advisory for human review, not an accusation.
    low_confidence_flag = confidence_score <= 0.20

    authenticity_score = 1.0
    is_flagged_synthetic = False
    authenticity_checked = False
    # Hybrid check: only spend the extra Gemini vision call when the text is
    # already severe enough to matter - that's the exact case where alerts.py's
    # "1 reporter + photo = URGENCY_SPIKE" shortcut could be exploited with a
    # fake image. Lower-severity photos are checked on-demand by an admin instead.
    if image_bytes and severity_score >= alerts.URGENCY_MIN_SEVERITY:
        try:
            image_check = fraud_audit.analyze_image_authenticity(
                image_bytes, mime_type=image_mime_type or "image/jpeg"
            )
            authenticity_score = image_check["authenticity_score"]
            is_flagged_synthetic = image_check["is_flagged_synthetic"]
            authenticity_checked = True
        except Exception as e:  # leave it unchecked; an admin can run the check on demand
             print(f"[ingestion] photo check unavailable: {e}")

    is_quarantined = low_confidence_flag or is_flagged_synthetic
    complaint_status = "Quarantined" if is_quarantined else "Open"

    incident_id = db.insert_complaint(
        brand_id=brand_id,
        county=clean_county,
        issue_cluster=issue_cluster,
        raw_text_scrubbed=scrubbed,
        phone_hash=phone_hash,
        severity_score=severity_score,
        confidence_score=confidence_score,
        urgency_level=urgency_level,
        image_url=image_url,
        phone_encrypted=phone_encrypted,
        authenticity_score=authenticity_score,
        is_flagged_synthetic=is_flagged_synthetic,
        low_confidence_flag=low_confidence_flag,
        is_quarantined=is_quarantined,
        status=complaint_status,
        authenticity_checked=authenticity_checked,
        consent_version=consent_version,
        consent_sms=consent_sms,
        consent_language=consent_language,
    )
    # Check and trigger alerts for this brand + cluster
    fired_alerts = alerts.check_alerts(brand_id, issue_cluster)
    for fired in fired_alerts:
        if fired.get("alert_type") == "URGENCY_SPIKE":
            _notify_auditors_critical(brand_name, issue_cluster, fired)
    return {
        "incident_id": incident_id,
        "brand_id": brand_id,
        "county": clean_county,
        "issue_cluster": issue_cluster,
        "text_stored": scrubbed,
        "phone_hash": phone_hash,
        "alerts_fired": fired_alerts,
        "severity_score": severity_score,
        "confidence_score": confidence_score,
    }


def submit_counterfeit_report(brand_name, county, outlet_type, outlet_name, reason_text,
                              front_photo, back_photo, outlet_photo, phone=None,
                              consent_version=None, consent_sms=False, consent_language=None):
    """Validates and stores one suspected-counterfeit report. Uses the same checks as
    submit_complaint: consent recorded, valid brand and county, personal details
    scrubbed from free text, and the phone (optional) stored only as a keyed hash plus
    an encrypted copy. Returns the new report_id."""
    if not consent_version:
        raise ValueError("Consent is required before a report can be submitted.")

    brand_id = db.get_brand_id(brand_name)
    if brand_id is None:
        raise ValueError(f"Unknown brand: {brand_name!r}")
    if not db.brand_is_active(brand_id):
        raise ValueError(f"Brand not available: {brand_name!r}")

    clean_county = normalize_county(county)
    if clean_county is None:
        raise ValueError(f"Not a valid Kenyan county: {county!r}")

    reason = scrub_pii((reason_text or "").strip())
    if not reason:
        raise ValueError("Please tell us why you think it is counterfeit.")

    if not (front_photo and back_photo and outlet_photo):
        raise ValueError("Please add all three photos: front, back and the outlet.")

    clean_outlet_name = scrub_pii(outlet_name.strip()) if outlet_name and outlet_name.strip() else None

    phone = (phone or "").strip()
    if phone:
        phone_hash = hash_phone(phone)  # raises ValueError if the number is invalid
        phone_encrypted = crypto_utils.encrypt_field(normalize_phone(phone)) if consent_sms else None
    else:
        phone_hash = None
        phone_encrypted = None

    return db.insert_counterfeit_report(
        brand_id=brand_id,
        county=clean_county,
        outlet_type=outlet_type,
        outlet_name=clean_outlet_name,
        reason_text=reason,
        front_photo=front_photo,
        back_photo=back_photo,
        outlet_photo=outlet_photo,
        phone_hash=phone_hash,
        phone_encrypted=phone_encrypted,
        consent_version=consent_version,
        consent_sms=consent_sms,
        consent_language=consent_language,
    )


# ---------- Self-test ----------

def _notify_auditors_critical(brand_name, cluster_id, fired_alert):
    """Texts every admin with role='auditor' the moment a URGENCY_SPIKE fires,
    so an auditor doesn't have to keep the dashboard open to catch it.
    Assumption to verify: fired_alert may or may not include 'trigger_count' -
    this reads it defensively with .get() so a missing key never breaks ingestion."""
    phones = db.get_auditor_phones()
    if not phones:
        return
    count = fired_alert.get("trigger_count", "multiple")
    message = (
        f"🚨 CRITICAL Sauti-Yetu alert: {brand_name} / {cluster_id} - "
        f"{count} reports. Check the Alert Board now."
    )
    for phone in phones:
        try:
             sms_gateway.send_sms(phone, message)
        except Exception as e:  # an SMS failure must never lose a report or an alert
             print(f"[ingestion] SMS to auditor failed: {e}")

def _self_test():
    # Phone normalization: all of these are the same number
    variants = ["0712345678", "+254712345678", "254 712 345 678", "0712-345-678", "712345678"]
    normalized = {normalize_phone(v) for v in variants}
    assert normalized == {"+254712345678"}, normalized
    assert normalize_phone("12345") is None
    assert normalize_phone("0812345678") is None

    # Hashing: same person -> same hash, different person -> different hash
    assert hash_phone("0712345678") == hash_phone("+254 712 345 678")
    assert hash_phone("0712345678") != hash_phone("0722345678")
    assert "712345678" not in hash_phone("0712345678")

    # Scrubbing
    s = scrub_pii("Call me on 0712 345 678 or a@b.com, ID 12345678, ref QGH7XYZ123, batch UN-882")
    assert "[PHONE]" in s and "[EMAIL]" in s and "[ID]" in s and "[TXN_CODE]" in s, s
    assert "UN-882" in s, s
    assert "0712" not in s and "12345678" not in s
    assert "CONNECTION" in scrub_pii("CONNECTION IMEKATIKA AGAIN"), "caps words must survive"

    # Counties
    assert normalize_county("  nairobi ") == "Nairobi"
    assert normalize_county("Eldoret") is None
    assert len(KENYAN_COUNTIES) == 47

    print("Pure-function tests: all passed.")
    print("Scrub example ->", s)


if __name__ == "__main__":
    _self_test()

    if "--live" in sys.argv:
        result = submit_complaint(
            brand_name="Safaricom",
            phone="0700 123 456",
            county="nairobi",
            text="Test complaint, my number is 0700123456 and M-Pesa app iko stuck",
            consent_version="self-test",
        )
        print("Live insert ->", result)
        print("Now run: python seed_data.py to reset the demo data.")