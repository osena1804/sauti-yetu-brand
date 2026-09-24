"""
Sauti-Yetu -- Enterprise Consumer Intelligence
Public Portal (consumer feedback dashboard) + Admin Portal (brand action briefs)
"""
import io
import os
import sys
import tempfile
import uuid
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
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
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            elif attached_photo is not None:
                photos_dir = os.path.join(os.path.dirname(__file__), "data", "submitted_photos")
                os.makedirs(photos_dir, exist_ok=True)

                filename = f"{uuid.uuid4().hex[:8]}.jpg"
                permanent_path = os.path.join(photos_dir, filename)

                try:
                    photo_bytes = attached_photo.getvalue()
                    img = Image.open(io.BytesIO(photo_bytes))

                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")

                    img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                    img.save(permanent_path, "JPEG", quality=75, optimize=True)

                    with st.spinner("Gemma is looking at your photo..."):
                        record = gc.classify_complaint_image(permanent_path, client_id=client_choice)

                    if record:
                        record["submitted_photo"] = permanent_path
                        record["client_id"] = client_choice

                except Exception as err:
                    st.error(f"Error processing image: {str(err)}")
                    record = None

            if record:
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
    all_clients_df = ds.load_complaints()  # unfiltered, for top-level totals

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
            col2.metric("High urgency (open, all clients)", int((all_clients_df.get("urgency", pd.Series()) == "High").sum()) if not all_clients_df.empty else 0)
            
            max_days = int(all_clients_df["days_unresolved"].max()) if (not all_clients_df.empty and "days_unresolved" in all_clients_df.columns) else 0
            col3.metric("Longest unresolved (all clients)", f"{max_days} days")

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

        if not viewing_single:
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
                        st.info("No data available for selected filters.")
                else:
                    st.info("No data available for selected filters.")

            with clock_col:
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

        st.markdown("### 📋 Complaint Stream")
        status_badge = {
            "Open": "🟢 **Open**",
            "Resolved": "✅ **Resolved**",
            "Disputed": "⚠️ **Disputed by consumer**",
            "Quarantined": "☣️ **Quarantined**"
        }

        # Loop over filtered view safely
        for _, row in view.iterrows():
            urgency_color = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(row.get("urgency"), "⚪")
            current_status = row.get("status", "Open")
            badge = status_badge.get(current_status, "")

            st.markdown(
                f"{urgency_color} **{row.get('category', 'General')}** — {row.get('county', 'Unknown')} | {badge}  \n"
                f"· *{int(row.get('days_unresolved', 0))} days unaddressed*  \n"
                f"> {row.get('english_summary', 'No summary available.')}"
            )

            # Resolution display & Dispute section
            if current_status == "Resolved":
                st.caption(f"✅ Marked resolved: {row.get('resolution_note', 'N/A')} — signed off by {row.get('resolved_by', 'Admin')} on {row.get('resolved_date', 'N/A')}")
                
                with st.expander("🚩 This isn't actually fixed"):
                    dispute_reason = st.text_area(
                        "Why do you think this isn't resolved?",
                        key=f"reason_{row['id']}",
                        placeholder="e.g. I bought the same batch again yesterday, still an issue.",
                    )
                    if st.button("Submit dispute", key=f"dispute_btn_{row['id']}", type="primary"):
                        if dispute_reason.strip():
                            ds.dispute_resolution(row["id"], dispute_reason.strip())
                            st.success("Dispute submitted successfully.")
                            st.rerun()
                        else:
                            st.warning("Please explain why you're disputing this.")

            elif current_status == "Disputed":
                st.warning(f"⚠️ **Dispute details**: {row.get('dispute_reasons', 'No reason specified.')}")
                if row.get("resolution_note"):
                    st.caption(f"Previous resolution claim: {row['resolution_note']}")

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
        df_admin = ds.load_complaints(client_id=admin_client)

        if df_admin.empty:
            st.info("No feedback yet for this client.")
        else:
            st.markdown("#### Gap detector — clusters by county & category")
            if "county" in df_admin.columns and "category" in df_admin.columns:
                cluster = (
                    df_admin.groupby(["county", "category"])
                    .agg(count=("category", "size"), max_days_unresolved=("days_unresolved", "max"))
                    .reset_index()
                    .sort_values(by=["count", "max_days_unresolved"], ascending=False)
                )
                st.dataframe(cluster, use_container_width=True, hide_index=True)

            st.markdown("#### One-click Action Brief Generator")
            counties = sorted(df_admin["county"].dropna().unique().tolist()) if "county" in df_admin.columns else []
            if counties:
                chosen_county = st.selectbox("Select county cluster to draft a brief for", counties, key="brief_county_select")

                subset = df_admin[df_admin["county"] == chosen_county]
                st.write(f"{len(subset)} report(s) will be used as evidence for this brief.")

                if st.button("📄 Generate Action Brief", type="primary", key="gen_brief_btn"):
                    with st.spinner("Gemma is drafting the action brief..."):
                        brief = gc.generate_action_brief(subset)
                    st.text_area("Action brief", brief, height=400, key="brief_output_area")
                    st.download_button("Download brief (.txt)", brief, file_name=f"ActionBrief_{chosen_county}.txt", key="download_brief_btn")

        # Wire in Dispute Audit Dashboard scoped to the selected admin client
        st.divider()
        render_admin_dispute_view(client_id=admin_client)