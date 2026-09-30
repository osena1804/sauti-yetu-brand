import db
import sms_gateway

RESOLUTION_SMS_CAP = 10


def notify_resolution_if_needed(alert_id):
    """Sends a resolution SMS to at most the first RESOLUTION_SMS_CAP reporters
    in the cluster, exactly once per alert (guarded by resolution_sms_sent).
    Capped deliberately: texting every reporter on a large cluster could mean
    hundreds of SMS for one resolution - costly under real traffic, and not
    necessary to demonstrate the closed loop."""
    alert = db.get_alert(alert_id)
    if not alert or alert["resolution_status"] != "RESOLVED":
        return
    if alert.get("resolution_sms_sent"):
        return

    phones = db.get_first_n_reporters_for_cluster(
        alert["brand_id"], alert["cluster_id"], n=RESOLUTION_SMS_CAP
    )
    if not phones:
        print(f"[resolution_notifier] WARNING: no phone numbers found for alert {alert_id}; "
              f"marking as sent anyway with 0 SMS delivered.")
    message = (
        f"Update from Sauti-Yetu: the issue you reported about {alert['brand_name']} "
        f"has been resolved. Thank you for speaking up."
    )
    for phone in phones:
        sms_gateway.send_sms(phone, message)

    db.log_audit_action(None, "RESOLUTION_SMS_SENT", alert_id=alert_id,
                        detail=f"{len(phones)} reporter(s) notified")