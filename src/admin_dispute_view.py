"""
admin_dispute_view.py

Streamlit view for Brand Managers & System Admin to:
  1. Review and resolve open consumer feedback records.
  2. Audit disputed resolutions and handle customer escalation loops.
  3. Quarantined & Fraud Audit: Inspect AI-flagged synthetic reports, bad-faith slander, 
     and low-authenticity scores before they affect public sentiment analytics.
"""

import os
import streamlit as st
import pandas as pd

import crypto_utils as crypto
import sms_client as sms
from data_store import load_complaints, mark_resolved, _save_df_atomic, _coerce_dtypes, DATA_PATH

try:
    from crypto_utils import decrypt_name
except ImportError:
    def decrypt_name(token: str) -> str:
        return token if token else "Unknown"


def render_admin_dispute_view(client_id: str = "default"):
    st.title("🛡️ Admin Resolution & Fraud Audit Portal")
    st.caption(f"Active Client Scope: **{client_id}**")

    # Fetch all complaints for this client
    df_all = load_complaints(client_id=client_id)

    # Tab layout
    tab_open, tab_disputed, tab_quarantine = st.tabs(
        ["📋 Open Complaints", "⚠️ Disputed Resolutions", "☣️ Quarantined & Fraud Audit"]
    )

    # ---------------------------------------------------------------------------
    # TAB 1: OPEN COMPLAINTS
    # ---------------------------------------------------------------------------
    with tab_open:
        open_df = df_all[df_all["status"] == "Open"].copy()
        st.subheader(f"Open Action Items ({len(open_df)})")

        if open_df.empty:
            st.success("No open complaints requiring resolution!")
        else:
            for idx, row in open_df.iterrows():
                with st.expander(
                    f"[{row.get('urgency', 'Medium')}] {row.get('category', 'General')} - {row.get('county', 'N/A')} ({row['id']})"
                ):
                    # Check and display consumer photo
                    photo_path = str(row.get("submitted_photo", "")).strip()
                    if photo_path and os.path.exists(photo_path):
                        st.image(photo_path, caption="Consumer-submitted photo evidence", width=350)

                    st.write(f"**Summary:** {row.get('english_summary', 'No summary available')}")
                    st.write(f"**Raw Consumer Input:** {row.get('raw_text', 'N/A')}")
                    st.caption(f"Reported On: {row.get('timestamp', 'N/A')} | Days Open: {row.get('days_unresolved', 0)}")

                    with st.form(key=f"resolve_form_{row['id']}"):
                        note = st.text_area("Resolution Note / Action Taken", key=f"note_{row['id']}")
                        resolved_by = st.text_input("Manager Name / Admin ID", key=f"admin_{row['id']}")
                        evidence_photo = st.file_uploader(
                            "Attach resolution evidence photo (optional)", 
                            type=["jpg", "jpeg", "png"], 
                            key=f"photo_{row['id']}"
                        )

                        submit = st.form_submit_button("Mark as Resolved")
                        if submit:
                            if not note.strip() or not resolved_by.strip():
                                st.error("Please provide both a resolution note and your name/ID.")
                            else:
                                res_photo_path = ""
                                if evidence_photo is not None:
                                    os.makedirs("data", exist_ok=True)
                                    res_photo_path = os.path.join("data", f"resolved_{row['id']}.jpg")
                                    with open(res_photo_path, "wb") as f:
                                        f.write(evidence_photo.getbuffer())

                                resolved_row = mark_resolved(
                                    complaint_id=row['id'],
                                    note=note.strip(),
                                    resolved_by=resolved_by.strip(),
                                    photo_path=res_photo_path,
                                )

                                real_phone = crypto.decrypt_phone(resolved_row.get("phone_encrypted", ""))
                                sms_sent = sms.send_resolution_alert(
                                    real_phone, 
                                    resolved_row.get("category", "General"), 
                                    resolved_row.get("county", "N/A")
                                )
                                
                                if real_phone:
                                    st.success(f"Complaint resolved by {resolved_by}. SMS alert {'sent' if sms_sent else 'mocked — check logs'}.")
                                else:
                                    st.success(f"Complaint resolved by {resolved_by}. No phone on file, no SMS sent.")
                                st.rerun()

    # ---------------------------------------------------------------------------
    # TAB 2: DISPUTED RESOLUTIONS
    # ---------------------------------------------------------------------------
    with tab_disputed:
        disputed_df = df_all[df_all["status"] == "Disputed"].copy()
        st.subheader(f"Escalated Disputes ({len(disputed_df)})")

        if disputed_df.empty:
            st.info("No active disputes pending escalation.")
        else:
            for idx, row in disputed_df.iterrows():
                with st.expander(f"⚠️ Dispute Escalation - {row.get('category', 'General')} ({row['id']})"):
                    # Check and display consumer photo
                    photo_path = str(row.get("submitted_photo", "")).strip()
                    if photo_path and os.path.exists(photo_path):
                        st.image(photo_path, caption="Original consumer-submitted photo evidence", width=350)

                    st.write(f"**Original Summary:** {row.get('english_summary', 'N/A')}")
                    st.write(f"**Previous Resolution Note:** {row.get('resolution_note', 'N/A')}")
                    st.warning(f"**Dispute Reasons & Feedback:** {row.get('dispute_reasons', 'N/A')}")
                    st.caption(f"Dispute Count: {row.get('dispute_count', 1)}")

                    with st.form(key=f"re_resolve_form_{row['id']}"):
                        new_note = st.text_area("Updated Action Plan", key=f"dispute_note_{row['id']}")
                        admin_name = st.text_input("Re-Resolving Manager", key=f"dispute_admin_{row['id']}")

                        resolve_btn = st.form_submit_button("Re-Resolve & Close Escalation")
                        if resolve_btn:
                            if not new_note.strip() or not admin_name.strip():
                                st.error("Please provide updated details before closing.")
                            else:
                                resolved_row = mark_resolved(
                                    complaint_id=row['id'],
                                    note=f"[Re-Resolved] {new_note.strip()}",
                                    resolved_by=admin_name.strip(),
                                )
                                real_phone = crypto.decrypt_phone(resolved_row.get("phone_encrypted", ""))
                                sms.send_resolution_alert(
                                    real_phone, 
                                    resolved_row.get("category", "General"), 
                                    resolved_row.get("county", "N/A")
                                )
                                st.success("Dispute escalation closed!")
                                st.rerun()

    # ---------------------------------------------------------------------------
    # TAB 3: QUARANTINED & FRAUD AUDIT
    # ---------------------------------------------------------------------------
    with tab_quarantine:
        quarantine_df = df_all[df_all["status"] == "Quarantined"].copy()
        st.subheader(f"Quarantined Records ({len(quarantine_df)})")
        st.caption(
            "Items in quarantine are isolated from brand sentiment metrics. "
            "Inspect flags for synthetic content, AI personas, or smear campaigns below."
        )

        if quarantine_df.empty:
            st.success("No items currently in quarantine.")
        else:
            for idx, row in quarantine_df.iterrows():
                auth_score = float(row.get("authenticity_score", 0.0))
                is_synthetic = str(row.get("is_flagged_synthetic", "False")).lower() == "true"
                defamation = str(row.get("defamation_flag", "False")).lower() == "true"

                risk_label = "☣️ HIGH FRAUD RISK" if (is_synthetic or defamation) else "⚠️ SUSPICIOUS AUTHENTICITY"

                with st.expander(f"{risk_label}: {row.get('category', 'General')} - {row.get('county', 'N/A')} ({row['id']})"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Authenticity Score", f"{auth_score:.2f}")
                    with col2:
                        st.metric("Synthetic/AI Flag", "True" if is_synthetic else "False")
                    with col3:
                        st.metric("Defamation Flag", "True" if defamation else "False")

                    st.markdown("---")
                    
                    # Display consumer-submitted photo in quarantine view if present
                    photo_path = str(row.get("submitted_photo", "")).strip()
                    if photo_path and os.path.exists(photo_path):
                        st.image(photo_path, caption="Quarantined Photo Submission", width=350)

                    st.write(f"**English Summary:** {row.get('english_summary', 'N/A')}")
                    st.write(f"**Raw Text:** {row.get('raw_text', 'N/A')}")
                    st.caption(f"Ingested Timestamp: {row.get('timestamp', 'N/A')}")

                    st.markdown("### Manager Override & Audit Actions")
                    col_approve, col_reject = st.columns(2)

                    with col_approve:
                        if st.button("✅ Override & Move to Open", key=f"approve_{row['id']}"):
                            _update_complaint_status(row['id'], new_status="Open")
                            st.success(f"Record {row['id']} verified as genuine. Moved to Open Complaints.")
                            st.rerun()

                    with col_reject:
                        if st.button("🗑️ Confirm Fraud & Archive", key=f"reject_{row['id']}"):
                            _update_complaint_status(row['id'], new_status="Archived Fraud")
                            st.warning(f"Record {row['id']} permanently archived as fraud.")
                            st.rerun()


def _update_complaint_status(complaint_id: str, new_status: str):
    """Helper function to update status of a record directly in the CSV store."""
    if not os.path.exists(DATA_PATH):
        return

    df = pd.read_csv(DATA_PATH)
    df = _coerce_dtypes(df)
    idx = df.index[df["id"] == complaint_id]

    if len(idx) > 0:
        df.loc[idx, "status"] = new_status
        _save_df_atomic(df)


def render_dispute_audit_dashboard(client_id: str = "default"):
    """Backward compatibility alias for app.py."""
    render_admin_dispute_view(client_id=client_id)