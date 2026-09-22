"""
Sauti-Yetu -- Enterprise Consumer Intelligence
Public Portal (consumer feedback dashboard) + Admin Portal (brand action briefs)
"""

import os
import sys
import tempfile
import uuid
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image

# Safely handle imports whether modules are in root or in src/
try:
    import crypto_utils as crypto
    import data_store as ds
    import gemma_client as gc
    import sms_client as sms
    from admin_dispute_view import render_admin_dispute_view
except ModuleNotFoundError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
    import crypto_utils as crypto
    import data_store as ds
    import gemma_client as gc
    import sms_client as sms
    from admin_dispute_view import render_admin_dispute_view

# Page Configuration
st.set_page_config(page_title="Sauti-Yetu", page_icon="📣", layout="wide")

# Sidebar - Environment & Mode Checks
if getattr(gc, "FORCE_MOCK", False) or not getattr(gc, "GOOGLE_API_KEY", None):
    st.sidebar.warning("⚠️ Running in MOCK mode — no live Gemma connection")
else:
    st.sidebar.success("✅ Live Gemma connected")

# App Header
st.title("📣 Sauti-Yetu")
st.caption("Enterprise Consumer Intelligence — streaming, organic consumer feedback, powered by Gemma.")

# Access Control (Supports OS environment variables AND Streamlit Cloud Secrets)
admin_param = st.query_params.get("admin", "false").lower() == "true"
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

admin_key_env = os.environ.get("ADMIN_KEY")
if not admin_key_env:
    try:
        admin_key_env = st.secrets.get("ADMIN_KEY", "admin")
    except Exception:
        admin_key_env = "admin"

if admin_param and not st.session_state.is_admin:
    st.sidebar.markdown("---")
    pwd = st.sidebar.text_input("Enter Admin Key", type="password", key="admin_pwd_input")
    if pwd == admin_key_env:
        st.session_state.is_admin = True
        st.sidebar.success("🔒 Administrator Authenticated")
        st.rerun()
    elif pwd:
        st.sidebar.error("Incorrect Admin Key")

if st.session_state.is_admin:
    st.sidebar.markdown("---")
    st.sidebar.info("🔒 Logged in as Administrator")
    if st.sidebar.button("Logout Admin"):
        st.session_state.is_admin = False
        st.query_params.clear()
        st.rerun()

# Dynamic Tab Configuration
if st.session_state.is_admin:
    tab_public, tab_admin, tab_submit = st.tabs(["🌍 Public Portal", "🏛️ Admin Portal", "📝 Submit a Report"])
else:
    tab_public, tab_submit = st.tabs(["🌍 Public Portal", "📝 Submit a Report"])
    tab_admin = None

# ---------------------------------------------------------------------------
# SUBMIT TAB -- Multi-modal Input (Text, Mic, Photo)
# ---------------------------------------------------------------------------
with tab_submit:
    st.subheader("Submit consumer feedback")
    st.write("Type, speak, or attach a photo — Swahili, Sheng, or English, Gemma handles the rest.")

    client_choice = st.selectbox(
        "Client",
        list(gc.CLIENT_CONFIGS.keys()),
        format_func=lambda k: gc.CLIENT_CONFIGS[k]["display_name"],
        key="submit_client",
    )
    raw_text = st.text_input("Type a message", placeholder="e.g. Bidhaa hii ilikuwa mbaya, dukani Kisumu...", key="input_raw_text")
    phone = st.text_input("Phone number (optional — get an SMS when this is resolved)", placeholder="07XXXXXXXX", key="input_phone")
    county_choice = st.selectbox("Select your county", sorted(gc.KENYA_COUNTIES), key="input_county")

    col_mic, col_photo = st.columns(2)
    with col_mic:
        st.markdown("🎙️ **Or record a voice note**")
        recorded_audio = st.audio_input("Tap to record", key="input_audio")
    with col_photo:
        st.markdown("📎 **Or attach a photo**")
        photo_source = st.radio("Photo source", ["Camera", "Upload"], horizontal=True, label_visibility="collapsed", key="input_photo_src")
        if photo_source == "Camera":
            attached_photo = st.camera_input("Take a photo", label_visibility="collapsed", key="input_camera")
        else:
            attached_photo = st.file_uploader("Upload a photo", type=["jpg", "jpeg", "png"], label_visibility="collapsed", key="input_upload")

    if st.button("Send report", type="primary", key="send_report_btn"):
        record = None
        debug_error = None

        if recorded_audio is not None:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(recorded_audio.getbuffer())
                tmp_path = tmp.name

            try:
                with st.spinner("Gemma is processing your voice note..."):
                    record = gc.classify_complaint_audio(tmp_path, client_id=client_choice)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        elif attached_photo is not None:
            os.makedirs("data/submitted_photos", exist_ok=True)
            permanent_path = os.path.join("data/submitted_photos", f"{uuid.uuid4().hex[:8]}.jpg")

            # Process and downscale image to prevent stream bottlenecks
            img = Image.open(attached_photo)
            img = img.convert("RGB")
            img.thumbnail((1024, 1024))
            img.save(permanent_path, "JPEG", quality=80)
            
            # Reset file pointer for buffer safety
            if hasattr(attached_photo, "seek"):
                attached_photo.seek(0)

            with st.spinner("Gemma is looking at your photo..."):
                try:
                    record = gc.classify_complaint_image(permanent_path, client_id=client_choice)
                except Exception as e:
                    st.warning(f"Classification hit an error, saving with basic info instead: {e}")
                    record = gc._mock_classify("Photo report submitted.", client_choice)
                    record.update({
                        "timestamp": datetime.now().isoformat(),
                        "raw_text": f"[photo report: {os.path.basename(permanent_path)}]",
                        "client_id": client_choice,
                        "status": "Open",
                    })

                record["submitted_photo"] = permanent_path
                st.image(permanent_path, caption="Photo submitted", width=300)
                debug_error = record.pop("_debug_error", None)

        elif raw_text.strip():
            with st.spinner("Gemma is structuring your report..."):
                record = gc.classify_complaint(raw_text, client_id=client_choice)

        else:
            st.warning("Type a message, record a voice note, or attach a photo before sending.")

        if record:
            record["phone_encrypted"] = crypto.encrypt_phone(phone) if phone else None
            record["phone_hash"] = crypto.hash_phone(phone) if phone else None
            record["county"] = county_choice
            ds.add_complaint(record)

            st.success(f"Logged as **{record.get('category', 'General')}** ({record.get('urgency', 'Low')} urgency) — {county_choice}")

            if debug_error:
                with st.expander("⚠️ Debug: Why this report used fallback mode"):
                    st.code(debug_error)

# ---------------------------------------------------------------------------
# PUBLIC PORTAL -- Feedback Dashboard & Responsiveness Clock
# ---------------------------------------------------------------------------
with tab_public:
    st.subheader("Consumer feedback dashboard")

    portal_client = st.selectbox(
        "Viewing client",
        list(gc.CLIENT_CONFIGS.keys()),
        format_func=lambda k: gc.CLIENT_CONFIGS[k]["display_name"],
        key="public_client",
    )
    df = ds.load_complaints(client_id=portal_client)

    if df.empty:
        st.info("No feedback yet for this client. Submit one under the 'Submit a Report' tab.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total reports", len(df))
        high_urgency_count = int((df["urgency"] == "High").sum()) if "urgency" in df.columns else 0
        max_days = int(df['days_unresolved'].max()) if "days_unresolved" in df.columns and not df['days_unresolved'].isnull().all() else 0
        col2.metric("High urgency (open)", high_urgency_count)
        col3.metric("Longest unresolved", f"{max_days} days")

        counties = ["All"] + sorted(df["county"].dropna().unique().tolist()) if "county" in df.columns else ["All"]
        categories = ["All"] + sorted(df["category"].dropna().unique().tolist()) if "category" in df.columns else ["All"]
        
        c1, c2 = st.columns(2)
        county_filter = c1.selectbox("Filter by county", counties, key="public_county_filter")
        category_filter = c2.selectbox("Filter by category", categories, key="public_cat_filter")

        view = df.copy()
        if county_filter != "All" and "county" in view.columns:
            view = view[view["county"] == county_filter]
        if category_filter != "All" and "category" in view.columns:
            view = view[view["category"] == category_filter]

        dash_col, clock_col = st.columns([1, 1])

        with dash_col:
            st.markdown("#### 📊 Feedback Hotspots by County")
            top_n = st.slider("Show top N counties by volume", 5, 20, 10, key="top_n_slider")
            if "county" in view.columns and not view.empty:
                county_totals = view["county"].value_counts().head(top_n).index
                county_view = view[view["county"].isin(county_totals)]

                if not county_view.empty and "category" in county_view.columns:
                    county_breakdown = pd.crosstab(county_view["county"], county_view["category"])
                    st.bar_chart(county_breakdown, stack=False)
                else:
                    st.info("No breakdown data available for selected filters.")
            else:
                st.info("No data available for selected filters.")

        with clock_col:
            st.markdown("#### ⏱️ Responsiveness Clock")
            st.caption("Sorted by urgency, then by how long the issue has gone unaddressed.")

            status_badge = {"Open": "", "Resolved": "✅ **Resolved**", "Disputed": "⚠️ **Disputed by consumer**"}

            for _, row in view.iterrows():
                row_id = str(row.get("id", uuid.uuid4().hex))
                urgency_color = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(row.get("urgency"), "⚪")
                badge = status_badge.get(row.get("status"), "")
                days_unresolved = int(row.get('days_unresolved', 0)) if pd.notnull(row.get('days_unresolved')) else 0

                st.markdown(
                    f"{urgency_color} **{row.get('category', 'General')}** — {row.get('county', 'Unknown')} {badge}  \n"
                    f"· *{days_unresolved} days unaddressed*  \n"
                    f"> {row.get('english_summary', 'No summary available.')}"
                )
                if row.get("submitted_photo") and os.path.exists(str(row["submitted_photo"])):
                    st.image(row["submitted_photo"], width=250)

                if row.get("status") == "Resolved":
                    with st.expander("🚩 This isn't actually fixed", expanded=False):
                        dispute_reason = st.text_area(
                            "Why do you think this isn't resolved?",
                            key=f"reason_{row_id}",
                            placeholder="e.g. I bought the same batch again yesterday, still an issue.",
                        )
                        if st.button("Submit dispute", key=f"dispute_btn_{row_id}"):
                            if dispute_reason.strip():
                                ds.dispute_resolution(row.get("id"), dispute_reason.strip())
                                st.rerun()
                            else:
                                st.warning("Please explain why you're disputing this.")

                if row.get("status") in ("Resolved", "Disputed") and row.get("resolution_note"):
                    st.caption(f"Resolution claim: {row['resolution_note']} — reviewed and signed off internally on {row.get('resolved_date', 'N/A')}")

# ---------------------------------------------------------------------------
# ADMIN PORTAL -- Cluster Gap Detector & Brief Generator
# ---------------------------------------------------------------------------
if tab_admin is not None:
    with tab_admin:
        st.subheader("Administrator tools")

        admin_client = st.selectbox(
            "Client",
            list(gc.CLIENT_CONFIGS.keys()),
            format_func=lambda k: gc.CLIENT_CONFIGS[k]["display_name"],
            key="admin_client",
        )
        df = ds.load_complaints(client_id=admin_client)

        if df.empty:
            st.info("No feedback yet for this client.")
        else:
            st.markdown("#### Gap detector — clusters by county & category")
            if "county" in df.columns and "category" in df.columns:
                cluster = (
                    df.groupby(["county", "category"])
                    .agg(count=("category", "size"), max_days_unresolved=("days_unresolved", "max"))
                    .reset_index()
                    .sort_values(by=["count", "max_days_unresolved"], ascending=False)
                )
                st.dataframe(cluster, use_container_width=True, hide_index=True)

            st.markdown("#### One-click Action Brief Generator")
            counties = sorted(df["county"].dropna().unique().tolist()) if "county" in df.columns else []
            if counties:
                chosen_county = st.selectbox("Select county cluster to draft a brief for", counties, key="brief_county_select")

                subset = df[df["county"] == chosen_county]
                st.write(f"{len(subset)} report(s) will be used as evidence for this brief.")

                if st.button("📄 Generate Action Brief", type="primary", key="gen_brief_btn"):
                    with st.spinner("Gemma is drafting the action brief..."):
                        brief = gc.generate_action_brief(subset)
                    st.text_area("Action brief", brief, height=400, key="brief_output_area")
                    st.download_button("Download brief (.txt)", brief, file_name=f"ActionBrief_{chosen_county}.txt", key="download_brief_btn")

        # Wire in Dispute Audit Dashboard scoped to the selected admin client
        st.divider()
        render_admin_dispute_view(client_id=admin_client)