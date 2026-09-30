import db
import brief

# ---------- Thresholds (illustrative demo values, to be calibrated on real data) ----------
URGENCY_MIN_SEVERITY = 0.85
URGENCY_MIN_CONFIDENCE = 0.80
URGENCY_MIN_REPORTERS = 2        # independent reporters, unless photo evidence is attached
PATTERN_MIN_REPORTS = 15         # independent reports in the rolling window
WINDOW_HOURS = 24

# Never alert on complaints that failed to cluster: unrelated reports would be lumped together.
SKIP_CLUSTERS = {"unclassified"}


def _fire(brand_id, cluster_id, alert_type, count, has_photo):
    brief_text, _source = brief.generate_brief(alert_type, brand_id, cluster_id, count, has_photo)
    alert_id = db.insert_alert(brand_id, cluster_id, alert_type, count, has_photo, brief_text)
    return {
        "alert_id": alert_id,
        "alert_type": alert_type,
        "cluster_id": cluster_id,
        "trigger_count": count,
    }


def check_alerts(brand_id, cluster_id):
    """Runs both engines for one brand/cluster. Returns a list of alerts fired by
    THIS call (empty if nothing new). Safe to call repeatedly: an alert of a given
    type is never fired twice for the same active cluster."""
    fired = []
    if cluster_id in SKIP_CLUSTERS:
        return fired

    # Engine 1: Urgency (fire alarm). Severity AND confidence bars must both be met,
    # then either 2+ independent reporters or at least one with photo evidence.
    stats = db.get_urgent_stats(
        brand_id, cluster_id, URGENCY_MIN_SEVERITY, URGENCY_MIN_CONFIDENCE, WINDOW_HOURS
    )
    qualifies = stats["reporters"] >= URGENCY_MIN_REPORTERS or (
        stats["reporters"] >= 1 and stats["has_photo"]
    )
    if qualifies and not db.alert_exists(brand_id, cluster_id, "URGENCY_SPIKE"):
        fired.append(_fire(brand_id, cluster_id, "URGENCY_SPIKE",
                           stats["reporters"], stats["has_photo"]))

    # Engine 2: Pattern (smoke detector). Volume of independent reports, any severity.
    count = db.count_cluster_reports(brand_id, cluster_id, WINDOW_HOURS)
    if count >= PATTERN_MIN_REPORTS and not db.alert_exists(brand_id, cluster_id, "PATTERN_TREND"):
        fired.append(_fire(brand_id, cluster_id, "PATTERN_TREND",
                           count, db.cluster_has_photo(brand_id, cluster_id)))

    return fired