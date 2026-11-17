import os
import uuid
import consent
import streamlit as st

import db
import admins
import ingestion
import transcription
import resolution_notifier
import fraud_audit
import clustering
import retention
import settings

admins.seed_admin_accounts()
# TEMPORARY: shows which accounts exist (usernames and roles only). Remove once fixed.
with db.get_connection() as _c:
    print("[debug] admin accounts:", [(r["username"], r["role"]) for r in _c.execute("SELECT username, role FROM admins")])

st.set_page_config(page_title="Sauti-Yetu", page_icon="📡", layout="wide")

# ---------- Small helpers ----------

ALERT_COLORS = {"URGENCY_SPIKE": "🔴", "PATTERN_TREND": "🟠"}
ALERT_LABELS = {"URGENCY_SPIKE": "CRITICAL", "PATTERN_TREND": "PATTERN DETECTED"}


def urgency_badge(level):
    return {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(level, "⚪")


@st.cache_data(ttl=5)
def load_brands():
    return db.list_brands()

CF_OUTLET_TYPES = [
    "Supermarket / minimarket",
    "Duka / kiosk",
    "Open-air market or street vendor",
    "Wholesaler / distributor",
    "Chemist / pharmacy",
    "Beauty shop / salon",
    "Online or social media seller",
    "Other",
]
CF_STATUSES = ["New", "Needs more evidence", "Suspected counterfeit", "Likely genuine"]
# Roles allowed to see counterfeit photos and reports (restricted queue).
CF_REVIEW_ROLES = {"brand_protection", "auditor"}


def save_cf_photo(file, label):
    """Saves an uploaded photo under a random file name (never a phone number)."""
    folder = os.path.join("uploads", "counterfeit")
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(getattr(file, "name", "") or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        ext = ".jpg"
    path = os.path.join(folder, f"{uuid.uuid4().hex}_{label}{ext}")
    with open(path, "wb") as f:
        f.write(file.getbuffer())
    return path

def render_consent(txt, key_prefix, ask_health):
    """Shows the privacy notice and the consent tick boxes. Returns
    (agreed, health_ok, sms_ok). health_ok is True when ask_health is False."""
    if consent.WORDING_IS_DRAFT:
        st.caption(txt["draft_note"])
    with st.expander(txt["notice_title"]):
        st.markdown(txt["notice_body"])
    agreed = st.checkbox(txt["consent_main"], key=f"{key_prefix}_consent_main")
    health_ok = True
    if ask_health:
        health_ok = st.checkbox(txt["consent_health"], key=f"{key_prefix}_consent_health")
    sms_ok = st.checkbox(txt["consent_sms"], key=f"{key_prefix}_consent_sms")
    return agreed, health_ok, sms_ok

def clear_consent(key_prefix):
    """Un-ticks the boxes after a report, so the next report needs fresh consent."""
    for suffix in ("consent_main", "consent_health", "consent_sms"):
        st.session_state.pop(f"{key_prefix}_{suffix}", None)

def render_photo_authenticity_check(row, key_suffix):
    """Admin-only, on-demand AI photo check for submissions that weren't
    auto-checked (i.e. lower-severity photos, per the hybrid policy)."""
    if not row.get("image_url") or not os.path.exists(row["image_url"]):
        return
    if row.get("authenticity_checked"):
        verdict = "🚩 Flagged synthetic" if row.get("is_flagged_synthetic") else "✅ Looks genuine"
        st.caption(f"Photo authenticity: {verdict} (score {row['authenticity_score']:.2f})")
        return
    admin = st.session_state.auth_admin
    if not admin:
        st.caption("📷 Not yet authenticity-checked (admin login required to check).")
        return
    if st.button("🔍 Check photo authenticity", key=f"authcheck_{key_suffix}"):
        with st.spinner("Checking photo..."):
            with open(row["image_url"], "rb") as f:
                image_bytes = f.read()
            result = fraud_audit.analyze_image_authenticity(image_bytes)
        db.set_photo_authenticity(row["incident_id"], result["authenticity_score"], result["is_flagged_synthetic"])
        db.log_audit_action(admin, "PHOTO_AUTH_CHECK", detail=f"complaint #{row['incident_id']}")
        st.rerun()

def render_public_verification(alert_id):
    """Public panel: shows the brand's resolution claim and lets consumers confirm or dispute it."""
    db.finalize_if_expired(alert_id)
    full = db.get_alert(alert_id)
    if full["resolution_status"] == "DISPUTED":
        st.error("🔺 The brand's fix was disputed by affected consumers. This issue is open again.")
        return
    if full["resolution_status"] != "PENDING_VERIFICATION":
        return

    st.warning("🕓 **Brand says this is resolved. Community verification open (72 hours).**")
    st.write(f"**Official statement:** {full['official_statement']}")
    st.caption(f"Proof submitted by {full['admin_public_id']}")

    threshold = max(1, round(0.20 * full["trigger_count"]))
    st.progress(
        min(1.0, full["dispute_count"] / threshold),
        text=f"{full['dispute_count']} of {threshold} disputes needed to reopen this alert",
    )
    st.caption(f"👍 {full.get('confirm_count') or 0} confirmed fixed · 👎 {full['dispute_count']} still affected")
    voted_key = f"voted_{alert_id}"
    if st.session_state.get(voted_key):
        st.success("✅ Thanks, your response was recorded.")
        return

    choice = st.selectbox(
        "Has this been fixed for you?",
        ["Select an option...", "👎 Still experiencing the issue", "👍 All good now"],
        key=f"verify_choice_{alert_id}",
    )
    if st.button("Submit response", key=f"verify_submit_{alert_id}"):
        if choice.startswith("👎"):
            db.add_dispute(alert_id)
            st.session_state[voted_key] = True
            st.rerun()
        elif choice.startswith("👍"):
            db.add_confirmation(alert_id)
            st.session_state[voted_key] = True
            st.rerun()
        else:
            st.error("Please pick an option first.")        

def render_alert_card(alert):
    icon = ALERT_COLORS.get(alert["alert_type"], "⚪")
    label = ALERT_LABELS.get(alert["alert_type"], alert["alert_type"])
    is_admin = bool(st.session_state.get("auth_admin"))

    with st.container(border=True):
        col_title, col_badge = st.columns([4, 1])
        with col_title:
            st.markdown(f"### {icon} {label} - {alert['brand_name']}")
        with col_badge:
            st.caption(f"**Cluster:** `{alert['cluster_id']}`")

        st.write(alert["action_brief_text"])
        render_public_verification(alert["alert_id"])
        st.caption(f"📈 **Trigger Volume:** {alert['trigger_count']} independent report(s)")

        if is_admin:
            with st.expander("View underlying reports"):
                render_cluster_reports(alert["brand_id"], alert["cluster_id"])
        else:
            reports = db.get_complaints_for_cluster(alert["brand_id"], alert["cluster_id"])
            n_counties = len({r["county"] for r in reports})
            word = "county" if n_counties == 1 else "counties"
            st.caption(f"📍 Reported across {n_counties} {word}")
            if alert.get("has_photo_evidence"):
                st.caption("🖼️ Photo evidence on file (visible to authorised reviewers only)")
            st.caption("🔒 Individual reports are visible to authorised reviewers only.")


def render_cluster_reports(brand_id, cluster_id):
    # Individual reports and photos: logged-in admins only.
    if not st.session_state.get("auth_admin"):
        st.info("🔒 Log in as an admin to view individual reports and photos.")
        return

    reports = db.get_complaints_for_cluster(brand_id, cluster_id)
    if not reports:
        st.info("No reports found for this cluster.")
        return
    for r in reports:
        cols = st.columns([3, 1]) if r.get("image_url") else [st.container()]
        with cols[0]:
            st.write(f"**{r['county']}** - {r['raw_text_scrubbed']}")
            st.caption(
                f"Severity {r['severity_score']:.2f} · Confidence {r['confidence_score']:.2f} "
                f"· {r['urgency_level']} · {r['created_at']}"
            )
        if r.get("image_url"):
            with cols[1]:
                if os.path.exists(r["image_url"]):
                    st.image(r["image_url"], caption="🖼️ Photo evidence", width=140)
                else:
                    st.caption("🖼️ Photo evidence (file not found in this environment)")
            render_photo_authenticity_check(r, key_suffix=r["incident_id"])
        st.divider()


def render_admin_audit_expander(alert):
    """Decrypt-on-demand identity view + audit trail. Only an 'auditor' role can
    decrypt; any logged-in admin can see the trail. NOTE: this app has no
    fine-grained session security beyond st.session_state - fine for a demo,
    not a substitute for real access control in production."""
    with st.expander("🔒 Decrypt admin identity (dispute audit only)"):
        st.caption("Real identity is AES-256-GCM encrypted at rest and only decrypted here, on demand.")
        admin = st.session_state.auth_admin
        if not admin:
            st.info("Log in as an auditor (sidebar) to decrypt.")
        elif admin["role"] != "auditor":
            st.warning(f"🔒 {admin['real_name']} is a {admin['role']}, not an auditor. Access denied.")
        elif st.button("Decrypt now", key=f"decrypt_{alert['alert_id']}"):
            real_identity = db.get_decrypted_admin_identity(alert["alert_id"])
            db.log_audit_action(admin, "DECRYPT_IDENTITY", alert_id=alert["alert_id"])
            st.code(real_identity or "No identity on file.")

        trail = db.get_audit_log_for_alert(alert["alert_id"])
        if trail:
            st.caption("Audit trail for this alert:")
            st.dataframe(trail, hide_index=True, width="stretch")


# ---------- Sidebar ----------

st.sidebar.title("📡 Sauti-Yetu")
st.sidebar.caption("Enterprise Brand Risk Telemetry - Demo")
if settings.DEMO_MODE:
    st.sidebar.warning("Demo data: all incidents below are simulated for this walkthrough.")

brands = load_brands()
brand_names = ["All brands"] + [b["brand_name"] for b in brands]
selected_brand = st.sidebar.selectbox("Brand workspace", brand_names)
selected_brand_id = None
if selected_brand != "All brands":
    selected_brand_id = next(b["brand_id"] for b in brands if b["brand_name"] == selected_brand)

if st.sidebar.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.caption(f"AI scoring: {'OFFLINE mode' if os.environ.get('SAUTI_OFFLINE') == '1' else 'live (with fallback)'}")

# ---------- Admin login (gates internal tabs below) ----------

if "auth_admin" not in st.session_state:
    st.session_state.auth_admin = None

with st.sidebar:
    st.divider()
    if st.session_state.auth_admin:
        admin_session = st.session_state.auth_admin
        st.success(f"🔓 {admin_session['real_name']} ({admin_session['role']})")
        if st.button("Log out"):
            st.session_state.auth_admin = None
            st.rerun()
    else:
        with st.expander("🔐 Admin login"):
            login_user = st.text_input("Username", key="login_user")
            login_pass = st.text_input("Password", type="password", key="login_pass")
            if st.button("Log in", key="login_btn"):
                admin_session = db.verify_admin_login(login_user, login_pass)
                if admin_session:
                    st.session_state.auth_admin = admin_session
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

# ---------- Main: tabs ----------
# Public: Alert Board + Submit a Report. Internal (All Data, Resolution Tracker):
# only rendered once an admin is logged in.

PRIVACY_ROLES = {"auditor"}        # who can run retention and handle rights requests
BRAND_ADMIN_ROLES = {"auditor"}    # who can add and edit brands

_admin_now = st.session_state.auth_admin
_role = _admin_now["role"] if _admin_now else None
_can_review_cf = _role in CF_REVIEW_ROLES
_can_privacy = _role in PRIVACY_ROLES
_can_brands = _role in BRAND_ADMIN_ROLES

lang = st.radio("Language / Lugha", consent.LANGUAGES, horizontal=True, key="lang")
consent_text = consent.get_text(lang)

_tab_labels = ["🚨 Alert Board", "📝 Submit a Report", "🔎 Report Counterfeit"]
if _admin_now:
    _tab_labels += ["📊 All Data", "✅ Resolution Tracker", "☣️ Fraud Audit"]
if _can_review_cf:
    _tab_labels += ["🕵️ Counterfeit Review"]
if _can_privacy:
    _tab_labels += ["🧹 Data & Privacy"]
if _can_brands:
    _tab_labels += ["🏷️ Brands"]
_tabs = st.tabs(_tab_labels)

# The order below must match the order of the labels above.
_it = iter(_tabs)
tab_board, tab_submit, tab_counterfeit = next(_it), next(_it), next(_it)
tab_data = next(_it) if _admin_now else None
tab_resolve = next(_it) if _admin_now else None
tab_fraud = next(_it) if _admin_now else None
tab_cf_review = next(_it) if _can_review_cf else None
tab_privacy = next(_it) if _can_privacy else None
tab_brands = next(_it) if _can_brands else None

if not _admin_now:
    st.caption("🔒 Log in as an admin (sidebar) to see internal data and resolution tools.")

with tab_board:
    st.header("Critical Alerts")
    alerts_list = db.get_active_alerts(selected_brand_id)
    if not alerts_list:
        st.success("No active alerts for this selection.")
    else:
        red = [a for a in alerts_list if a["alert_type"] == "URGENCY_SPIKE"]
        amber = [a for a in alerts_list if a["alert_type"] == "PATTERN_TREND"]
        c1, c2 = st.columns(2)
        c1.metric("🔴 Urgency alerts", len(red))
        c2.metric("🟠 Pattern alerts", len(amber))
        st.divider()
        for a in red + amber:
            render_alert_card(a)

with tab_submit:
    st.header("📢 Welcome to Sauti-Yetu")
    if settings.DEMO_MODE:
        st.warning(settings.DEMO_BANNER)
    if not brands:
        st.info("This service is not open yet. Please check back soon.")
    st.write( "Tap below to submit a report - it only takes a moment.")
    #st.caption("Simulates multi-channel telemetry (SMS, Voice Memo & Photo Evidence) hitting the live ingestion pipeline.")

    if st.session_state.get("last_submission"):
        last = st.session_state["last_submission"]
        st.success("✅ Thank you! Your report has been submitted and is being reviewed.")
        st.caption(f"Reference number: #{last['incident_id']}")
        st.caption(consent_text["withdraw_hint"])
        with st.expander("🔧 Technical details"):
            m1, m2, m3 = st.columns(3)
            m1.metric("Cluster", last["issue_cluster"])
            m2.metric("Severity", f"{last['severity_score']:.2f}")
            m3.metric("Confidence", f"{last['confidence_score']:.2f}")
            if last["alerts_fired"]:
                for fired in last["alerts_fired"]:
                    st.warning(f"🚨 New {fired['alert_type']} alert fired on `{fired['cluster_id']}`!")
            else:
                st.info("No new alert threshold crossed by this report.")
        if st.button("📝 Submit another report"):
            del st.session_state["last_submission"]
            st.rerun()
        st.divider()

    input_channel = st.radio(
        "Reporting Channel",
        ["💬 Text / SMS", "🎙️ Voice Note", "📷 Upload Photo", "📸 Take Photo"],
        horizontal=True,
        key="submit_channel",
    )

    st.subheader(consent_text["heading"])
    consent_ok, health_ok, sms_ok = render_consent(consent_text, "rep", ask_health=True)
    can_submit = consent_ok and health_ok
    if not can_submit:
        st.caption(consent_text["need_consent"])

    with st.form("submit_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            brand_choice = st.selectbox("Brand", [b["brand_name"] for b in brands])
            phone = st.text_input(
                "Phone number (optional)",
                value="",
                placeholder="e.g. 0712345678",
                help="Only needed if you want an SMS update on this report. Leave it blank to stay anonymous.",
            )
        with col2:
            county = st.selectbox(
                "County",
                ingestion.KENYAN_COUNTIES,
                index=ingestion.KENYAN_COUNTIES.index("Nairobi")
            )

        uploaded_photo = None
        camera_photo = None
        voice_recording = None

        if input_channel == "📷 Upload Photo":
            uploaded_photo = st.file_uploader(
                "Upload photo evidence (batch code, damaged packaging, or receipt)",
                type=["jpg", "jpeg", "png"]
            )
            if uploaded_photo:
                st.image(uploaded_photo, caption="Uploaded Evidence Preview", width=250)

        elif input_channel == "📸 Take Photo":
            camera_photo = st.camera_input("Take a photo of the product defect")

        elif input_channel == "🎙️ Voice Note":
            voice_recording = st.audio_input("Record voice complaint (Swahili, Sheng, or English)")
            st.caption("⚡ Voice notes are automatically transcribed on submit.")

        text_label = "Complaint text / Notes" if input_channel != "🎙️ Voice Note" else "Additional notes (optional)"
        st.caption("Please don't include names or other personal details in your description.")
        text = st.text_area(
            text_label,
            height=100,
            placeholder="e.g. M-Pesa app imestuck kwa step ya malipo..."
        )

        submitted = st.form_submit_button("Submit report", type="primary", disabled=not can_submit)

    if submitted:
        photo_file = uploaded_photo if input_channel == "📷 Upload Photo" else camera_photo
        has_photo = photo_file is not None
        final_text = text.strip()

        if input_channel == "🎙️ Voice Note" and voice_recording is not None:
            with st.spinner("Transcribing voice note..."):
                transcript, transcribe_error = transcription.transcribe_audio(
                    voice_recording.getvalue(),
                    mime_type=getattr(voice_recording, "type", "audio/wav"),
                )
            if transcript:
                final_text = f"{transcript} {final_text}".strip() if final_text else transcript
            elif not final_text:
                st.error(f"Couldn't transcribe your voice note ({transcribe_error}). Please type a summary instead.")
                st.stop()

        if not final_text and not has_photo:
            st.error("Please provide a description, or attach a photo, for this report.")
        else:
            image_url = None
            image_bytes = None
            image_mime_type = None
            if has_photo:
                os.makedirs("uploads", exist_ok=True)
                ext = os.path.splitext(getattr(photo_file, "name", "") or "")[1].lower()
                if ext not in (".jpg", ".jpeg", ".png"):
                    ext = ".jpg"
                image_url = os.path.join("uploads", f"{uuid.uuid4().hex}{ext}")
                image_bytes = photo_file.getbuffer().tobytes()
                image_mime_type = getattr(photo_file, "type", "image/jpeg")
                with open(image_url, "wb") as f:
                    f.write(image_bytes)

            fallback_text = final_text or "[Photo evidence submitted, no description provided]"

            try:
                with st.spinner("Submitting your report..."):
                    result = ingestion.submit_complaint(
                        brand_name=brand_choice,
                        phone=phone,
                        county=county,
                        text=fallback_text,
                        image_url=image_url,
                        image_bytes=image_bytes,
                        image_mime_type=image_mime_type,
                        consent_version=consent.CONSENT_VERSION,
                        consent_sms=sms_ok,
                        consent_language=lang,
                    )
                if result["alerts_fired"]:
                    st.cache_data.clear()
                st.session_state["last_submission"] = result
                st.session_state.pop("submit_channel", None)
                clear_consent("rep") 
                st.rerun()
            except ValueError as e:
                st.error(str(e))

with tab_counterfeit:
    st.header("🔎 Report a Suspected Counterfeit")
    if settings.DEMO_MODE:
        st.warning(settings.DEMO_BANNER)
    st.write("Bought a product that doesn't look, smell or feel right? Tell us.")

    if st.session_state.get("cf_done"):
        st.success("✅ Thank you for your submission. Our team will review it.")
        st.caption(f"Reference number: CF-{st.session_state['cf_done']}")
        st.caption(consent_text["withdraw_hint"])
        if st.button("Report another product", key="cf_again"):
            st.session_state.pop("cf_done", None)
            st.rerun()
    else:
        is_cf = st.selectbox(
            "Do you think this product is counterfeit?",
            ["Select an option...", "Yes", "No"],
            key="cf_is_counterfeit",
        )

        if is_cf == "No":
            st.success("✅ Thank you for your submission.")

        elif is_cf == "Yes":
            st.subheader(consent_text["heading"])
            cf_consent_ok, _unused, cf_sms_ok = render_consent(consent_text, "cf", ask_health=False)
            if not cf_consent_ok:
                st.caption(consent_text["need_consent"])

            with st.form("cf_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    cf_brand = st.selectbox("Brand", [b["brand_name"] for b in brands])
                    cf_county = st.selectbox(
                        "County", ingestion.KENYAN_COUNTIES,
                        index=ingestion.KENYAN_COUNTIES.index("Nairobi"),
                    )
                with col2:
                    cf_outlet_type = st.selectbox("Where did you buy it?", CF_OUTLET_TYPES)
                    cf_outlet_name = st.text_input(
                        "Outlet name or area (optional)",
                        placeholder="e.g. shop name, market, or estate",
                    )

                st.caption("📷 Photograph the product and the shopfront or stall. "
                           "Please do not photograph people, and do not confront the seller.")
                p1, p2, p3 = st.columns(3)
                with p1:
                    cf_front = st.file_uploader("Front of product", type=["jpg", "jpeg", "png"], key="cf_front")
                with p2:
                    cf_back = st.file_uploader("Back of product", type=["jpg", "jpeg", "png"], key="cf_back")
                with p3:
                    cf_outlet = st.file_uploader("The outlet", type=["jpg", "jpeg", "png"], key="cf_outlet")

                cf_reason = st.text_area(
                    "Why do you think it's counterfeit?",
                    height=100,
                    placeholder="e.g. packaging colour looks different, no batch code, much cheaper than usual, smells odd...",
                )
                st.caption("Please don't include names or other personal details.")
                cf_phone = st.text_input(
                    "Phone number (optional)",
                    help="Only needed if you want us to be able to follow up. Leave blank to stay anonymous.",
                )
                cf_submit = st.form_submit_button("Submit report", type="primary", disabled=not cf_consent_ok)

            if cf_submit:
                if not (cf_front and cf_back and cf_outlet):
                    st.error("Please upload all three photos: front, back and the outlet.")
                elif not cf_reason.strip():
                    st.error("Please tell us why you think it's counterfeit.")
                elif cf_phone.strip() and ingestion.normalize_phone(cf_phone) is None:
                    st.error("That phone number doesn't look right. Leave it blank or check it.")
                else:
                    saved = []
                    try:
                        saved = [
                            save_cf_photo(cf_front, "front"),
                            save_cf_photo(cf_back, "back"),
                            save_cf_photo(cf_outlet, "outlet"),
                        ]
                        new_report_id = ingestion.submit_counterfeit_report(
                            brand_name=cf_brand,
                            county=cf_county,
                            outlet_type=cf_outlet_type,
                            outlet_name=cf_outlet_name,
                            reason_text=cf_reason,
                            front_photo=saved[0],
                            back_photo=saved[1],
                            outlet_photo=saved[2],
                            phone=cf_phone,
                            consent_version=consent.CONSENT_VERSION,
                            consent_sms=cf_sms_ok,
                            consent_language=lang,
                        )
                    except ValueError as e:
                        for pth in saved:  # don't leave photos behind if the report was rejected
                            try:
                                os.remove(pth)
                            except OSError:
                                pass
                        st.error(str(e))
                    else:
                        st.session_state["cf_done"] = new_report_id
                        clear_consent("cf")
                        st.rerun()


if tab_data is not None:
    with tab_data:
        st.header("All complaints in the database")
        filter_brand_id = selected_brand_id
        
        with db.get_connection() as conn:
            # Filter out quarantined/flagged reports so they only appear in Fraud Audit
            query = """
                SELECT c.*, b.brand_name 
                FROM complaints c 
                JOIN brands b ON b.brand_id = c.brand_id 
                WHERE (c.low_confidence_flag IS NULL OR c.low_confidence_flag = 0)
            """
            params = []
            
            if filter_brand_id:
                query += " AND c.brand_id = ?"
                params.append(filter_brand_id)
                
            query += " ORDER BY c.created_at DESC"
            all_rows = [dict(r) for r in conn.execute(query, tuple(params)).fetchall()]

        st.caption(f"{len(all_rows)} complaint(s) shown")
        if all_rows:
            st.dataframe(
                [
                    {
                        "ID": r["incident_id"],
                        "Brand": r["brand_name"],
                        "County": r["county"],
                        "Cluster": r["issue_cluster"],
                        "Severity": f"{r['severity_score']:.2f}",
                        "Confidence": f"{r['confidence_score']:.2f}",
                        "Urgency": f"{urgency_badge(r['urgency_level'])} {r['urgency_level']}",
                        "Text": r["raw_text_scrubbed"],
                        "When": r["created_at"],
                    }
                    for r in all_rows
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No complaints yet for this selection.")

if tab_resolve is not None:
    with tab_resolve:
        st.header("✅ Resolution & Dispute Tracker")
        st.caption("Pick an active alert to review, resolve, or dispute.")

        # Same alerts the Alert Board shows (respects the sidebar brand filter)
        active_alerts = db.get_active_alerts(selected_brand_id)

        if not active_alerts:
            st.success("No active alerts to resolve for this selection.")
        else:
            # Critical (red) first, then pattern (amber)
            type_order = {"URGENCY_SPIKE": 0, "PATTERN_TREND": 1}
            active_alerts = sorted(active_alerts, key=lambda a: type_order.get(a["alert_type"], 2))
            alert_lookup = {a["alert_id"]: a for a in active_alerts}

            def format_alert(aid):
                a = alert_lookup[aid]
                icon = ALERT_COLORS.get(a["alert_type"], "⚪")
                label = ALERT_LABELS.get(a["alert_type"], a["alert_type"])
                return f"{icon} {label} · {a['brand_name']} · {a['cluster_id']} ({a['trigger_count']} reports)"

            alert_id = st.selectbox(
                "Select an alert to resolve",
                options=list(alert_lookup.keys()),
                format_func=format_alert,
                key="resolve_alert_select",
            )

            db.finalize_if_expired(alert_id)
            resolution_notifier.notify_resolution_if_needed(alert_id)
            alert = db.get_alert(alert_id)
            status = alert["resolution_status"]

            st.subheader(f"{alert['brand_name']} - `{alert['cluster_id']}`")
            st.write(alert["action_brief_text"])

            c1, c2, c3 = st.columns(3)
            c1.metric("⏱️ Days Unaddressed", f"{alert['days_unaddressed']:.2f}")
            c2.metric("Status", status.replace("_", " "))
            c3.metric("Disputes", f"{alert['dispute_count']} / {alert['trigger_count']} reporters")
            st.divider()

            if status == "UNADDRESSED":
                st.info("This incident has not yet been marked resolved by the brand.")
                resolve_admin = st.session_state.auth_admin
                if not resolve_admin:
                    st.warning("🔒 Log in as an admin (sidebar) to submit a resolution.")
                else:
                    st.caption(f"Submitting as **{resolve_admin['real_name']}** — this becomes the encrypted admin signature.")
                    with st.form(f"resolve_form_{alert_id}"):
                        proof = st.text_area("Proof of resolution", key=f"proof_{alert_id}",
                                             placeholder="e.g. Batch BD-441 recalled, replacement stock issued")
                        statement = st.text_area("Official statement", key=f"statement_{alert_id}",
                                                 placeholder="e.g. We have identified and recalled the affected batch.")
                        submit_res = st.form_submit_button("📤 Submit resolution proof", type="primary")
                    if submit_res:
                        if not proof.strip() or not statement.strip():
                            st.error("Proof and statement are both required.")
                        else:
                            db.submit_resolution(alert_id, resolve_admin["real_name"], proof, statement)
                            db.log_audit_action(resolve_admin, "SUBMIT_RESOLUTION", alert_id=alert_id)
                            st.rerun()

            elif status == "PENDING_VERIFICATION":
                st.warning("🕓 Pending Verification - the 72-hour community dispute window is open.")
                st.write(f"**Official statement:** {alert['official_statement']}")
                st.write(f"**Proof submitted:** {alert['proof_text']}")
                st.caption(f"Submitted by {alert['admin_public_id']} · true identity stays "
                           f"encrypted unless decrypted below for audit purposes.")
                render_admin_audit_expander(alert)

                threshold = max(1, round(0.20 * alert["trigger_count"]))
                st.progress(
                    min(1.0, alert["dispute_count"] / threshold),
                    text=f"{alert['dispute_count']} of {threshold} disputes needed to escalate "
                         f"(20% of {alert['trigger_count']} reporters)",
                )

                b1, b2 = st.columns(2)
                if b1.button("👎 Simulate: user reports 'Still experiencing issue'", key=f"dispute_{alert_id}"):
                    db.add_dispute(alert_id)
                    st.rerun()
                if b2.button("⏩ Simulate: 72 hours pass", key=f"window_{alert_id}"):
                    db.simulate_verification_window_passed(alert_id)
                    st.rerun()

            elif status == "RESOLVED":
                st.success("✅ Verified Resolved - the dispute window closed with disputes below threshold.")
                st.write(f"**Official statement:** {alert['official_statement']}")
                st.caption("This alert is now inactive and no longer appears on the main Alert Board.")

            elif status == "DISPUTED":
                st.error("🔺 Escalation Reversal - disputes crossed 20% of reporters. Reverted to unresolved.")
                st.caption(f"The Days Unaddressed counter keeps counting from {alert['days_unaddressed']:.2f} "
                           f"days - it does not reset on escalation.")
                render_admin_audit_expander(alert)
                if st.button("🔁 Allow brand to attempt resolution again", key=f"reopen_{alert_id}"):
                    db.reopen_alert(alert_id)
                    st.rerun()

if tab_fraud is not None:
    with tab_fraud:
        st.header("☣️ Quarantined & Fraud Audit")
        st.caption(
            "Items here are isolated from brand alert counts and public trends. "
            "Authenticity and confidence flags are advisory signals for human review, "
            "not automatic verdicts."
        )
        quarantined = db.get_quarantined_complaints(selected_brand_id)
        if not quarantined:
            st.success("No items currently in quarantine.")
        else:
            fraud_admin = st.session_state.auth_admin
            for row in quarantined:
                is_synthetic = bool(row.get("is_flagged_synthetic"))
                is_defamation = bool(row.get("low_confidence_flag"))
                risk_label = "☣️ HIGH RISK" if (is_synthetic and is_defamation) else "⚠️ FLAGGED FOR REVIEW"

                with st.expander(f"{risk_label}: {row['brand_name']} - {row['issue_cluster']} "
                                  f"({row['county']}) #{row['incident_id']}"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Authenticity Score", f"{row['authenticity_score']:.2f}")
                    c2.metric("AI/Synthetic Photo", "Yes" if is_synthetic else "No")
                    c3.metric("Low-Confidence Text", "Yes" if is_defamation else "No")

                    st.divider()

                    if row.get("image_url") and os.path.exists(row["image_url"]):
                        st.image(row["image_url"], caption="Quarantined photo submission", width=350)
                        with open(row["image_url"], "rb") as f:
                            st.download_button(
                                "⬇️ Download photo", data=f.read(),
                                file_name=os.path.basename(row["image_url"]),
                                mime="image/jpeg",
                                key=f"fraud_download_{row['incident_id']}",
                            )
                    elif row.get("image_url"):
                        st.caption("📷 Photo attached (file missing on this server)")

                    render_photo_authenticity_check(row, key_suffix=f"fraud_{row['incident_id']}")

                    st.write(f"**Text:** {row['raw_text_scrubbed']}")
                    st.caption(
                        f"Severity {row['severity_score']:.2f} · Confidence {row['confidence_score']:.2f} "
                        f"· Submitted {row['created_at']}"
                    )

                    st.markdown("**Manager override**")
                    if not fraud_admin:
                        st.warning("🔒 Log in as an admin (sidebar) to override.")
                    else:
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("✅ Override & move to Open", key=f"fraud_approve_{row['incident_id']}"):
                                db.update_complaint_status(row["incident_id"], "Open", is_quarantined=False)
                                db.log_audit_action(fraud_admin, "QUARANTINE_OVERRIDE_APPROVE",
                                                     detail=f"complaint #{row['incident_id']}")
                                st.success(f"Complaint #{row['incident_id']} moved to Open.")
                                st.rerun()
                        with col_b:
                            if st.button("❌ Confirm fraud", key=f"fraud_reject_{row['incident_id']}"):
                                db.update_complaint_status(row["incident_id"], "Fraud", is_quarantined=True)
                                db.log_audit_action(fraud_admin, "QUARANTINE_CONFIRM_FRAUD",
                                                     detail=f"complaint #{row['incident_id']}")
                                st.error(f"Complaint #{row['incident_id']} confirmed as fraud.")
                                st.rerun()     

if tab_cf_review is not None:
    with tab_cf_review:
        st.header("🕵️ Counterfeit Review")
        st.caption(
            "Restricted to brand protection reviewers. These reports are leads for investigation, "
            "not verdicts. Do not share photos outside the review team, and keep notes factual."
        )
        cf_reviewer = st.session_state.auth_admin

        st.subheader("Hotspots")
        st.caption("Counts only. Reports judged 'Likely genuine' are left out.")
        hotspots = db.get_counterfeit_hotspots(selected_brand_id)
        if hotspots:
            st.dataframe(hotspots, hide_index=True, width="stretch")
        else:
            st.info("No counterfeit reports yet for this selection.")

        st.subheader("Reports")
        status_filter = st.selectbox("Show", ["All"] + CF_STATUSES, key="cf_status_filter")
        cf_reports = db.get_counterfeit_reports(
            selected_brand_id, None if status_filter == "All" else status_filter
        )
        st.caption(f"{len(cf_reports)} report(s) shown")

        for r in cf_reports:
            hold_tag = " · 🔒 legal hold" if r.get("legal_hold") else ""
            title = (f"#{r['report_id']} · {r['brand_name']} · {r['county']} · "
                     f"{r['outlet_type']} · {r['review_status']}{hold_tag}")
            with st.expander(title):
                photo_cols = st.columns(3)
                for col, key, caption in zip(
                    photo_cols, ["front_photo", "back_photo", "outlet_photo"], ["Front", "Back", "Outlet"]
                ):
                    with col:
                        path = r.get(key)
                        if path and os.path.exists(path):
                            st.image(path, caption=caption, width=200)
                        else:
                            st.caption(f"{caption}: file not found in this environment")

                st.write(f"**Outlet:** {r['outlet_name'] or 'not given'}")
                st.write(f"**Why the reporter thinks it is counterfeit:** {r['reason_text']}")
                st.caption(
                    f"Submitted {r['created_at']} · "
                    f"{'reporter gave a phone number' if r['phone_hash'] else 'anonymous reporter'}"
                )
                if r.get("reviewed_by"):
                    st.caption(f"Last reviewed by {r['reviewed_by']} on {r['reviewed_at']}")

                rid = r["report_id"]
                with st.form(f"cf_review_{rid}"):
                    current = r["review_status"] if r["review_status"] in CF_STATUSES else CF_STATUSES[0]
                    new_status = st.selectbox(
                        "Review outcome", CF_STATUSES, index=CF_STATUSES.index(current), key=f"cf_status_{rid}"
                    )
                    note = st.text_area(
                        "Reviewer note (internal, factual)", value=r.get("reviewer_note") or "", key=f"cf_note_{rid}"
                    )
                    hold = st.checkbox(
                        "Legal hold: do not delete (an investigation is open)",
                        value=bool(r.get("legal_hold")), key=f"cf_hold_{rid}",
                    )
                    saved_review = st.form_submit_button("Save review", type="primary")
                if saved_review:
                    db.update_counterfeit_review(rid, new_status, note.strip(), cf_reviewer["real_name"], hold)
                    db.log_audit_action(
                        cf_reviewer, "COUNTERFEIT_REVIEW",
                        detail=f"counterfeit report #{rid}: {new_status}{' (legal hold)' if hold else ''}",
                    )
                    st.rerun()
if tab_privacy is not None:
    with tab_privacy:
        st.header("🧹 Data & Privacy")
        st.caption("Restricted to auditors. Every action here is recorded in the audit log.")
        privacy_admin = st.session_state.auth_admin

        st.subheader("1. Retention")
        st.write(
            f"Consumer reports are deleted {retention.AFTER_RESOLUTION_DAYS} days after their alert is resolved "
            f"({retention.UNTIED_DAYS} days if they never joined an alert). Counterfeit reports are deleted after "
            f"{retention.COUNTERFEIT_DAYS} days unless a reviewer placed a legal hold. Only anonymous counts are kept."
        )
        due = retention.run_retention(apply=False)
        st.dataframe(
            [{"Item": retention.LABELS[k].strip(), "Due now": due[k]} for k in retention.LABELS],
            hide_index=True, width="stretch",
        )
        if st.button("Run retention now", key="ret_run"):
            done = retention.run_retention(apply=True, admin=privacy_admin)
            st.cache_data.clear()
            st.success(
                f"Done. Deleted {done['complaints']} consumer report(s) and {done['counterfeit']} counterfeit "
                f"report(s), and {done['orphan_files']} unreferenced photo file(s)."
            )

        st.divider()
        st.subheader("2. Rights request: delete one report")
        st.caption("Ask the person for their reference number, for example 12 or CF-3.")
        ref_text = st.text_input("Reference number", key="dsr_ref")
        parsed = retention.parse_reference(ref_text) if ref_text.strip() else None
        if ref_text.strip() and not parsed:
            st.error("That doesn't look like a reference number.")
        elif parsed:
            info = retention.describe_report(*parsed)
            if not info:
                st.warning("No report with that reference.")
            else:
                st.write(
                    f"**Brand:** {info['brand']} · **Submitted:** {info['submitted']} · "
                    f"**Photos:** {info['photos']} · "
                    f"**Phone number on file:** {'yes' if info['phone_on_file'] else 'no (anonymous)'}"
                )
                if info["legal_hold"]:
                    st.error("This report is on legal hold and cannot be deleted here. Ask the lawyer.")
                else:
                    requester_phone = ""
                    if info["phone_on_file"]:
                        requester_phone = st.text_input(
                            "Phone number the person used (identity check)", key="dsr_phone")
                    confirm = st.checkbox(
                        "I have checked this request and want to delete this report permanently.",
                        key="dsr_confirm")
                    if st.button("Delete this report", key="dsr_delete", disabled=not confirm):
                        phone_hash = None
                        valid = True
                        if info["phone_on_file"]:
                            try:
                                phone_hash = ingestion.hash_phone(requester_phone)
                            except ValueError:
                                valid = False
                                st.error("That phone number is not valid.")
                        if valid:
                            ok, msg = retention.delete_report(
                                parsed[0], parsed[1], phone_hash=phone_hash, admin=privacy_admin)
                            if ok:
                                st.success(msg)
                            else:
                                st.error(msg)

        st.divider()
        st.subheader("3. End of pilot: delete everything")
        st.caption(
            "Deletes all consumer reports and photos. Only anonymous counts, and counterfeit reports on "
            "legal hold, are kept. This cannot be undone."
        )
        typed = st.text_input("Type DELETE ALL to enable the button", key="purge_typed")
        if st.button("Delete everything", key="purge_btn", type="primary", disabled=typed.strip() != "DELETE ALL"):
            res = retention.purge_everything(admin=privacy_admin)
            st.cache_data.clear()
            st.success(
                f"Deleted {res['complaints']} consumer report(s) and {res['counterfeit']} counterfeit report(s). "
                f"{res['counterfeit_on_hold']} counterfeit report(s) on legal hold were kept."
            )
            
if tab_brands is not None:
    with tab_brands:
        st.header("🏷️ Brands")
        st.caption(
            f"The brands consumers can choose from for {settings.CLIENT_NAME}. "
            "Consumers see only active brands, and nothing from any other client."
        )
        brand_admin = st.session_state.auth_admin
        if st.session_state.get("brand_flash"):
            st.success(st.session_state.pop("brand_flash"))

        all_brands = db.list_brands(include_inactive=True)
        if all_brands:
            st.dataframe(
                [{"Brand": b["brand_name"], "Category": b["category"], "Rule pack": b["rule_pack"],
                  "Active": "yes" if b["is_active"] else "no"} for b in all_brands],
                hide_index=True, width="stretch",
            )
        else:
            st.info("No brands yet. Add the first one below.")

        pack_keys = list(clustering.RULE_PACKS)

        def _pack_label(key):
            return f"{key}: {clustering.RULE_PACK_INFO[key]}"

        st.subheader("Add a brand")
        with st.form("brand_add", clear_on_submit=True):
            new_name = st.text_input("Brand name, exactly as consumers know it")
            new_category = st.text_input("Category", value="Beauty & Personal Care")
            new_pack = st.selectbox("Rule pack", pack_keys, format_func=_pack_label)
            add_clicked = st.form_submit_button("Add brand", type="primary")
        if add_clicked:
            try:
                db.add_brand(new_name, new_category, new_pack)
                shown = " ".join(new_name.split())
                db.log_audit_action(brand_admin, "BRAND_ADD", detail=shown)
                st.cache_data.clear()
                st.session_state["brand_flash"] = f"Added. Consumers will now see: {shown}"
                st.rerun()
            except ValueError as e:
                st.error(str(e))

        st.subheader("Edit a brand")
        st.caption("Switch a brand off instead of deleting it, because existing reports point to it. "
                   "A new name shows to consumers straight away, so check the spelling.")
        for b in all_brands:
            bid = b["brand_id"]
            with st.expander(f"{b['brand_name']}{'' if b['is_active'] else ' (inactive)'}"):
                with st.form(f"brand_edit_{bid}"):
                    e_name = st.text_input("Name", value=b["brand_name"], key=f"bn_{bid}")
                    e_cat = st.text_input("Category", value=b["category"], key=f"bc_{bid}")
                    e_pack = st.selectbox(
                        "Rule pack", pack_keys,
                        index=pack_keys.index(b["rule_pack"]) if b["rule_pack"] in pack_keys else 0,
                        format_func=_pack_label, key=f"bp_{bid}")
                    e_active = st.checkbox("Active (visible to consumers)", value=bool(b["is_active"]), key=f"ba_{bid}")
                    saved_brand = st.form_submit_button("Save changes")
                if saved_brand:
                    try:
                        db.update_brand(bid, e_name, e_cat, e_pack, e_active)
                        db.log_audit_action(brand_admin, "BRAND_UPDATE", detail=f"brand #{bid}: {' '.join(e_name.split())}")
                        st.cache_data.clear()
                        st.session_state["brand_flash"] = "Saved."
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))