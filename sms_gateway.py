import os

import africastalking

AT_USERNAME = os.environ.get("AT_USERNAME", "sandbox")
AT_API_KEY = os.environ.get("AT_API_KEY", "")

_initialized = False


def _ensure_initialized():
    global _initialized
    if not _initialized:
        africastalking.initialize(AT_USERNAME, AT_API_KEY)
        _initialized = True


def send_sms(to_phone_e164, message):
    """Sends an SMS via Africa's Talking. Returns (success, detail). Never raises -
    a failed outbound SMS should not crash whichever flow triggered it (webhook
    ingestion, resolution alerts)."""
    if not AT_API_KEY:
        return False, "AT_API_KEY not set - sandbox SMS will fail silently upstream."
    try:
        _ensure_initialized()
        sms = africastalking.SMS
        response = sms.send(message, [to_phone_e164])
        return True, response
    except Exception as e:
        return False, str(e)