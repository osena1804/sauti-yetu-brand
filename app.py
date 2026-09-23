"""
Sauti-Yetu -- Enterprise Consumer Intelligence
Public Portal (consumer feedback dashboard) + Admin Portal (brand action briefs)
"""

import os
import sys
import tempfile
import uuid
import streamlit as st
from PIL import Image

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
    import pandas as pd
    from admin_dispute_view import render_admin_dispute_view

st.set_page_config(page_title="Sauti-Yetu", page_icon="📣", layout="wide")

# Sidebar connection status
if getattr(gc, "FORCE_MOCK", False) or not getattr(gc, "GOOGLE_API_KEY", None):
    st.sidebar.warning("⚠️ Running in MOCK mode — no live Gemma connection")
else:
    st.sidebar.success("✅ Live Gemma connected")

st.title("📣 Sauti-Yetu")
st.caption("Enterprise Consumer Intelligence — streaming, organic consumer feedback, powered by Gemma.")

# Admin access control
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

# Tab configuration with active_tab logic
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "submit"

if st.session_state.is_admin:
    tab_submit, tab_public, tab_admin = st.tabs(
        ["📝 Submit a Report", "🌍 Public Portal", "🏛️ Admin Portal"]
    )
else:
    tab_submit, tab_public = st.tabs(["📝 Submit a Report", "🌍 Public Portal"])
    tab_admin = None

# ---------------------------------------------------------------------------
# SUBMIT TAB
# ---------------------------------------------------------------------------
if st.session_state.get("active_tab") == "submit":
    with tab_submit:
        st.subheader("📢 Welcome to Sauti-Yetu")
        st.write("Please submit your complaint below. Type, speak, or attach a photo — Swahili, Sheng, or English, Gemma handles the rest.")

        if "submitted" not in st.session_state:
            st.session_state.submitted = False
            st.session_state.last_id = None
            st.session_state.last_client = None
            st.session_state.jump_admin = False

        if not st.session_state.submitted:
            client_choice = st.selectbox(
                "Client",
                list(gc.CLIENT_CONFIGS.keys()),
                format_func=lambda k: gc.CLIENT_CONFIGS[k]["display_name"],
                key="submit_client",
            )
            raw_text = st.text_input("Type a message", placeholder="e.g. Bidhaa hii ilikuwa mbaya, dukani Kisumu...", key="input_raw_text")
            phone = st.text_input("Phone number (optional)", placeholder="07XXXXXXXX", key="input_phone")
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

            if st.button("Submit Complaint", type="primary", key="send_report_btn"):
                record = None

                if raw_text.strip():
                    with st.spinner("Gemma is structuring your report..."):
                        record = gc.classify_complaint(raw_text, client_id=client_choice)
                elif recorded_audio is not None:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                        tmp.write(recorded_audio.getbuffer())
                        tmp_path = tmp.name
                    with st.spinner("Gemma is processing your voice note..."):
                        record = gc.classify_complaint_audio(tmp_path, client_id=client_choice)
                    os.remove(tmp_path)
                elif attached_photo is not None:
                    os.makedirs("data/submitted_photos", exist_ok=True)
                    permanent_path = os.path.join("data/submitted_photos", f"{uuid.uuid4().hex[:8]}.jpg")
                    photo_bytes = attached_photo.getvalue()
                    import io
                    img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
                    img.thumbnail((1024, 1024))   # ✅ resizing step
                    img.save(permanent_path, "JPEG", quality=80)

                    with st.spinner("Gemma is looking at your photo..."):
                        record = gc.classify_complaint_image(permanent_path, client_id=client_choice)

                    record["submitted_photo"] = permanent_path   # ✅ attach after classification
                    record["client_id"] = client_choice

                if record:
                    # Ensure every record has a unique id
                    if "id" not in record or not record["id"]:
                        record["id"] = uuid.uuid4().hex

                    record["phone_encrypted"] = crypto.encrypt_phone(phone) if phone else None
                    record["phone_hash"] = crypto.hash_phone(phone) if phone else None
                    record["county"] = county_choice
                    ds.add_complaint(record)

                    st.session_state.submitted = True
                    st.session_state.last_id = record.get("id")
                    st.session_state.last_client = client_choice
                    st.rerun()

        else:
            st.success("✅ Thank you! Your complaint has been submitted.")

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("Submit another complaint"):
                    st.session_state.submitted = False
                    st.session_state.last_id = None
                    st.session_state.active_tab = "submit"
                    st.rerun()
            with col2:
                if st.button("View complaints"):
                    st.session_state.active_tab = "public"
                    st.rerun()
            with col3:
                if st.button("Go to Admin Portal"):
                    if st.session_state.is_admin:
                        st.session_state.jump_admin = True
                        st.session_state.active_tab = "admin"
                        st.rerun()
                    else:
                        st.warning("🔒 Admin access required. Please log in from the sidebar.")



# ---------------------------------------------------------------------------
# PUBLIC PORTAL
# ---------------------------------------------------------------------------
with tab_public:
    import urllib.parse
    import os
    import pandas as pd
    import streamlit.components.v1 as components

    st.subheader("Consumer feedback dashboard")

    keys = list(gc.CLIENT_CONFIGS.keys())
    default_client = st.session_state.get("last_client", keys[0])
    if default_client not in keys:
        default_client = keys[0]

    portal_client = st.selectbox(
        "Viewing client",
        keys,
        format_func=lambda k: gc.CLIENT_CONFIGS[k]["display_name"],
        index=keys.index(default_client),
        key="public_client",
    )

    df = ds.load_complaints(client_id=portal_client)
    all_clients_df = ds.load_complaints()  # unfiltered, for the top-level totals

    viewing_single = False
    if st.session_state.get("view_id"):
        single_df = df[df["id"] == st.session_state.view_id]
        if not single_df.empty:
            df = single_df
            viewing_single = True
            st.success("Showing your latest complaint:")
        st.session_state.view_id = None

    if df.empty:
        st.info("No feedback yet for this client.")
    else:
        if not viewing_single:
            col1, col2, col3 = st.columns(3)
            col1.metric("Total reports (all clients)", len(all_clients_df))
            col2.metric("High urgency (open, all clients)", int((all_clients_df["urgency"] == "High").sum()))
            col3.metric(
                "Longest unresolved (all clients)",
                f"{int(all_clients_df['days_unresolved'].max())} days" if not all_clients_df.empty else "0 days",
            )

        counties = ["All"] + sorted(df["county"].dropna().unique().tolist())
        categories = ["All"] + sorted(df["category"].dropna().unique().tolist())
        c1, c2 = st.columns(2)
        county_filter = c1.selectbox("Filter by county", counties, key="public_county_filter")
        category_filter = c2.selectbox("Filter by category", categories, key="public_cat_filter")

        view = df.copy()
        if county_filter != "All":
            view = view[view["county"] == county_filter]
        if category_filter != "All":
            view = view[view["category"] == category_filter]

        dash_col, clock_col = st.columns([1, 1]) if not viewing_single else (None, st)

# -------------------------------------------------------------------
# BUILT-IN BAR CHART BY COUNTY
# -------------------------------------------------------------------
        if not viewing_single:
            with dash_col:
                st.markdown("#### 📊 Complaints Breakdown by County")
                if not view.empty and "county" in view.columns:
                    county_counts = view["county"].value_counts()
                    st.bar_chart(county_counts)
                else:
                    st.info("No data available for selected filters.")

        with (clock_col if not viewing_single else st.container()):
            if not viewing_single:
                st.markdown("#### ⏱️ Responsiveness Clock")
                st.caption("Sorted by urgency, then by how long the issue has gone unaddressed.")

                clock_html = """
                <div style="
                    background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
                    border: 1px solid #334155;
                    border-radius: 10px;
                    padding: 12px 16px;
                    text-align: center;
                    color: #F8FAFC;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.15);
                    margin-bottom: 15px;
                ">
                    <div id="live-time" style="font-size: 1.8rem; font-weight: 700; color: #38BDF8; letter-spacing: 1px;">--:--:--</div>
                    <div id="live-date" style="font-size: 0.85rem; color: #94A3B8; margin-top: 2px;">Loading date...</div>
                </div>
                <script>
                    function updateClock() {
                        const now = new Date();
                        const timeOptions = { hour12: true, hour: '2-digit', minute: '2-digit', second: '2-digit' };
                        const dateOptions = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
                        document.getElementById('live-time').textContent = now.toLocaleTimeString('en-US', timeOptions);
                        document.getElementById('live-date').textContent = now.toLocaleDateString('en-US', dateOptions);
                    }
                    setInterval(updateClock, 1000);
                    updateClock();
                </script>
                """
                components.html(clock_html, height=95)

            status_badge = {"Open": "", "Resolved": "✅ **Resolved**", "Disputed": "⚠️ **Disputed by consumer**"}

            for _, row in view.iterrows():
                urgency_color = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(row.get("urgency"), "⚪")
                badge = status_badge.get(row.get("status"), "")

                st.markdown(
                    f"{urgency_color} **{row.get('category', 'General')}** — {row.get('county', 'Unknown')} {badge}  \n"
                    f"· *{int(row.get('days_unresolved', 0))} days unaddressed*  \n"
                    f"> {row.get('english_summary', 'No summary available.')}"
                )
                # Photo intentionally hidden from the public dashboard -- admins see it in admin_dispute_view.py

                if row.get("status") == "Resolved":
                    with st.expander("🚩 This isn't actually fixed"):
                        dispute_reason = st.text_area(
                            "Why do you think this isn't resolved?",
                            key=f"reason_{row['id']}",
                            placeholder="e.g. I bought the same batch again yesterday, still an issue.",
                        )
                        if st.button("Submit dispute", key=f"dispute_btn_{row['id']}"):
                            if dispute_reason.strip():
                                ds.dispute_resolution(row["id"], dispute_reason.strip())
                                st.rerun()
                            else:
                                st.warning("Please explain why you're disputing this.")

                if row.get("status") in ("Resolved", "Disputed") and row.get("resolution_note"):
                    st.caption(f"Resolution claim: {row['resolution_note']} — reviewed and signed off internally on {row.get('resolved_date', 'N/A')}")

                st.divider()
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