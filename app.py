import os

import streamlit as st

import db
import admins
import ingestion
import transcription
import resolution_notifier
import fraud_audit

admins.seed_admin_accounts()

st.set_page_config(page_title="Sauti-Yetu", page_icon="📡", layout="wide")

# ---------- Small helpers ----------

ALERT_COLORS = {"URGENCY_SPIKE": "🔴", "PATTERN_TREND": "🟠"}
ALERT_LABELS = {"URGENCY_SPIKE": "CRITICAL", "PATTERN_TREND": "PATTERN DETECTED"}


def urgency_badge(level):
    return {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(level, "⚪")


@st.cache_data(ttl=5)
def load_brands():
    return db.list_brands()

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

def render_alert_card(alert):
    icon = ALERT_COLORS.get(alert["alert_type"], "⚪")
    label = ALERT_LABELS.get(alert["alert_type"], alert["alert_type"])
    with st.container(border=True):
        col_title, col_badge = st.columns([4, 1])
        with col_title:
            st.markdown(f"### {icon} {label} - {alert['brand_name']}")
        with col_badge:
            st.caption(f"**Cluster:** `{alert['cluster_id']}`")

        st.write(alert["action_brief_text"])
        st.caption(f"📈 **Trigger Volume:** {alert['trigger_count']} independent report(s)")

        with st.expander("View underlying reports"):
            render_cluster_reports(alert["brand_id"], alert["cluster_id"])


def render_cluster_reports(brand_id, cluster_id):
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

if st.session_state.auth_admin:
    tab_board, tab_submit, tab_data, tab_resolve, tab_fraud = st.tabs(
        ["🚨 Alert Board", "📝 Submit a Report", "📊 All Data", "✅ Resolution Tracker", "☣️ Fraud Audit"]
    )
else:
    tab_board, tab_submit = st.tabs(["🚨 Alert Board", "📝 Submit a Report"])
    tab_data = None
    tab_resolve = None
    tab_fraud = None
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
    st.write("Had an issue with a product or service? Tap below to submit a report - it only takes a moment.")
    st.caption("Simulates multi-channel telemetry (SMS, Voice Memo & Photo Evidence) hitting the live ingestion pipeline.")

    if st.session_state.get("last_submission"):
        last = st.session_state["last_submission"]
        st.success("✅ Thank you! Your report has been submitted and is being reviewed.")
        st.caption(f"Reference number: #{last['incident_id']}")
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

    with st.form("submit_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            brand_choice = st.selectbox("Brand", [b["brand_name"] for b in brands])
            phone = st.text_input("Phone number", value="0712345678")
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
        text = st.text_area(
            text_label,
            height=100,
            placeholder="e.g. M-Pesa app imestuck kwa step ya malipo..."
        )

        submitted = st.form_submit_button("Submit report", type="primary")

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
                filename = getattr(photo_file, "name", "camera_capture.jpg")
                image_url = os.path.join("uploads", f"{phone}_{filename}")
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
                    )
                if result["alerts_fired"]:
                    st.cache_data.clear()
                st.session_state["last_submission"] = result
                st.session_state.pop("submit_channel", None)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

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
        st.caption(
            "Scoped to one alert for this walkthrough: Unilever - cooking oil seal contamination. "
            "The full platform would offer this for every active alert."
        )

        DEMO_BRAND, DEMO_CLUSTER = "Unilever", "oil_seal_leakage"
        alert_id = db.find_alert(DEMO_BRAND, DEMO_CLUSTER)

        if not alert_id:
            st.error(f"Demo alert not found for {DEMO_BRAND} / {DEMO_CLUSTER}. Run python seed_data.py to reset.")
        else:
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
                    with st.form("resolve_form"):
                        proof = st.text_area("Proof of resolution",
                                              placeholder="e.g. Batch BD-441 recalled, replacement stock issued")
                        statement = st.text_area("Official statement",
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
                if b1.button("👎 Simulate: user reports 'Still experiencing issue'"):
                    db.add_dispute(alert_id)
                    st.rerun()
                if b2.button("⏩ Simulate: 72 hours pass"):
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
                if st.button("🔁 Allow brand to attempt resolution again"):
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