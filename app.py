"""
Sauti-Yetu -- Enterprise Consumer Intelligence
Public Portal (consumer feedback dashboard) + Admin Portal (brand action briefs)
"""

import sys
import os
import uuid
import tempfile
from datetime import datetime

# Path setup for src module imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st
import pandas as pd

import gemma_client as gc
import data_store as ds
import sms_client as sms
import crypto_utils as crypto
from admin_dispute_view import render_admin_dispute_view

# Page Configuration
st.set_page_config(page_title="Sauti-Yetu", page_icon="📣", layout="wide")

# Sidebar - Environment & Mode Checks
if gc.FORCE_MOCK or not gc.GOOGLE_API_KEY:
    st.sidebar.warning("⚠️ Running in MOCK mode — no live Gemma connection")
else:
    st.sidebar.success("✅ Live Gemma connected")

# App Header
st.title("📣 Sauti-Yetu")
st.caption("Enterprise Consumer Intelligence — streaming, organic consumer feedback, powered by Gemma.")

# Access Control
admin_param = st.query_params.get("admin", "false").lower() == "true"
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if admin_param and not st.session_state.is_admin:
    st.sidebar.markdown("---")
    pwd = st.sidebar.text_input("Enter Admin Key", type="password")
    if pwd == os.environ.get("ADMIN_KEY", "admin"):
        st.session_state.is_admin = True
        st.sidebar.success("🔒 Administrator Authenticated")
        st.rerun()
    elif pwd:
        st.sidebar.error("Incorrect Admin Key")

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
    raw_text = st.text_input("Type a message", placeholder="e.g. Bidhaa hii ilikuwa mbaya, dukani Kisumu...")
    phone = st.text_input("Phone number (optional — get an SMS when this is resolved)", placeholder="07XXXXXXXX")
    county_choice = st.selectbox("Select your county", sorted(gc.KENYA_COUNTIES))

    col_mic, col_photo = st.columns(2)
    with col_mic:
        st.markdown("🎙️ **Or record a voice note**")
        recorded_audio = st.audio_input("Tap to record")
    with col_photo:
        st.markdown("📎 **Or attach a photo**")
        photo_source = st.radio("Photo source", ["Camera", "Upload"], horizontal=True, label_visibility="collapsed")
        if photo_source == "Camera":
            attached_photo = st.camera_input("Take a photo", label_visibility="collapsed")
        else:
            attached_photo = st.file_uploader("Upload a photo", type=["jpg", "jpeg", "png"], label_visibility="collapsed")

    if st.button("Send report", type="primary"):
        record = None

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
            with open(permanent_path, "wb") as f:
                f.write(attached_photo.getbuffer())

            with st.spinner("Gemma is looking at your photo..."):
                record = gc.classify_complaint_image(permanent_path, client_id=client_choice)
                record["submitted_photo"] = permanent_path
                st.image(attached_photo, caption="Photo submitted", width=300)

        elif raw_text.strip():
            with st.spinner("Gemma is structuring your report..."):
                record = gc.classify_complaint(raw_text, client_id=client_choice)

        else:
            st.warning("Type a message, record a voice note, or attach a photo before sending.")

        if record:
            record["phone_encrypted"] = crypto.encrypt_phone(phone)
            record["phone_hash"] = crypto.hash_phone(phone)            
            record["county"] = county_choice
            ds.add_complaint(record)
            st.success(f"Logged as **{record.get('category', 'General')}** ({record.get('urgency', 'Low')} urgency) — {county_choice}")

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
        col2.metric("High urgency (open)", int((df["urgency"] == "High").sum()))
        col3.metric("Longest unresolved", f"{int(df['days_unresolved'].max())} days")

        counties = ["All"] + sorted(df["county"].dropna().unique().tolist())
        categories = ["All"] + sorted(df["category"].dropna().unique().tolist())
        c1, c2 = st.columns(2)
        county_filter = c1.selectbox("Filter by county", counties)
        category_filter = c2.selectbox("Filter by category", categories)

        view = df.copy()
        if county_filter != "All":
            view = view[view["county"] == county_filter]
        if category_filter != "All":
            view = view[view["category"] == category_filter]

        dash_col, clock_col = st.columns([1, 1])

        with dash_col:
            st.markdown("#### 📊 Feedback Hotspots by County")
            top_n = st.slider("Show top N counties by volume", 5, 20, 10)
            county_totals = view["county"].value_counts().head(top_n).index
            county_view = view[view["county"].isin(county_totals)]
            
            if not county_view.empty:
                county_breakdown = pd.crosstab(county_view["county"], county_view["category"])
                st.bar_chart(county_breakdown, stack=False)
            else:
                st.info("No data available for selected filters.")

        with clock_col:
            st.markdown("#### ⏱️ Responsiveness Clock")
            st.caption("Sorted by urgency, then by how long the issue has gone unaddressed.")

            status_badge = {"Open": "", "Resolved": "✅ **Resolved**", "Disputed": "⚠️ **Disputed by consumer**"}

            for _, row in view.iterrows():
                urgency_color = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(row.get("urgency"), "⚪")
                badge = status_badge.get(row.get("status"), "")

                st.markdown(
                    f"{urgency_color} **{row['category']}** — {row['county']} {badge}  \n"
                    f"· *{int(row['days_unresolved'])} days unaddressed*  \n"
                    f"> {row['english_summary']}"
                )
                if row.get("submitted_photo") and os.path.exists(str(row["submitted_photo"])):
                    st.image(row["submitted_photo"], width=250)

                if row.get("status") == "Resolved":
                    with st.expander("🚩 This isn't actually fixed"):
                        dispute_reason = st.text_area(
                            "Why do you think this isn't resolved?",
                            key=f"reason_{row['id']}",
                            placeholder="e.g. I bought the same batch again yesterday, still an issue.",
                        )
                        if st.button("Submit dispute", key=f"dispute_{row['id']}"):
                            if dispute_reason.strip():
                                ds.dispute_resolution(row["id"], dispute_reason.strip())
                                st.rerun()
                            else:
                                st.warning("Please explain why you're disputing this.")

                if row.get("status") in ("Resolved", "Disputed") and row.get("resolution_note"):
                    st.caption(f"Resolution claim: {row['resolution_note']} — signed off by {row['resolved_by']} on {row['resolved_date']}")

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
            cluster = (
                df.groupby(["county", "category"])
                .agg(count=("category", "size"), max_days_unresolved=("days_unresolved", "max"))
                .reset_index()
                .sort_values(by=["count", "max_days_unresolved"], ascending=False)
            )
            st.dataframe(cluster, use_container_width=True, hide_index=True)

            st.markdown("#### One-click Action Brief Generator")
            counties = sorted(df["county"].dropna().unique().tolist())
            chosen_county = st.selectbox("Select county cluster to draft a brief for", counties)

            subset = df[df["county"] == chosen_county]
            st.write(f"{len(subset)} report(s) will be used as evidence for this brief.")

            if st.button("📄 Generate Action Brief", type="primary"):
                with st.spinner("Gemma is drafting the action brief..."):
                    brief = gc.generate_action_brief(subset)
                st.text_area("Action brief", brief, height=400)
                st.download_button("Download brief (.txt)", brief, file_name=f"ActionBrief_{chosen_county}.txt")

            st.markdown("#### Mark a report resolved")
            open_complaints = df[df["status"] == "Open"]

            if open_complaints.empty:
                st.info("No open reports to resolve.")
            else:
                options = {
                    f"{row['category']} — {row['county']} ({row['english_summary'][:50]}...)": row["id"]
                    for _, row in open_complaints.iterrows()
                }
                chosen_label = st.selectbox("Select report to resolve", list(options.keys()))
                chosen_id = options[chosen_label]
                selected_row = open_complaints[open_complaints["id"] == chosen_id].iloc[0]
                if selected_row.get("submitted_photo") and os.path.exists(selected_row["submitted_photo"]):
                    st.image(selected_row["submitted_photo"], caption="Consumer-submitted photo", width=350)
                st.write(f"**Reported as:** {selected_row['english_summary']}")

                resolution_note = st.text_area(
                    "What was done to resolve it? (required)",
                    placeholder="e.g. Batch recalled and replacement units shipped to Kisumu retailers on 12 August.",
                )
                resolution_photo = st.file_uploader("Attach evidence photo (recommended)", type=["jpg", "jpeg", "png"])
                resolved_by = st.text_input("Your name (required — for accountability sign-off)")
                resolved_date = st.date_input("Date resolved")

                if st.button("✅ Mark Resolved", type="primary"):
                    if not resolution_note.strip():
                        st.warning("Please describe what was done before marking this resolved.")
                    elif not resolved_by.strip():
                        st.warning("Please enter your name to sign off on this resolution.")
                    else:
                        photo_path = ""
                        if resolution_photo is not None:
                            os.makedirs("data", exist_ok=True)
                            photo_path = os.path.join("data", f"resolved_{chosen_id}.jpg")
                            with open(photo_path, "wb") as f:
                                f.write(resolution_photo.getbuffer())

                        resolved_row = ds.mark_resolved(
                            chosen_id,
                            resolution_note.strip(),
                            resolved_by.strip(),
                            photo_path,
                            resolved_date.strftime("%Y-%m-%d"),
                        )

                        real_phone = crypto.decrypt_phone(resolved_row.get("phone_encrypted", ""))
                        sms_sent = sms.send_resolution_alert(
                            real_phone,
                            resolved_row["category"],
                            resolved_row["county"],
                        )
                        if real_phone:
                            if sms_sent:
                                st.success(f"Marked resolved by {resolved_by.strip()} on {resolved_row['resolved_date']}. SMS alert sent.")
                            else:
                                st.success(f"Marked resolved by {resolved_by.strip()} on {resolved_row['resolved_date']}. (SMS mocked — check terminal.)")
                        else:
                            st.success(f"Marked resolved by {resolved_by.strip()} on {resolved_row['resolved_date']}. No phone on file, no SMS sent.")

                        st.rerun()

        # Wire in Dispute Audit Dashboard scoped to the selected admin client
        st.divider()
        render_admin_dispute_view(client_id=admin_client)