"""
admin_dispute_view.py

Streamlit view for Brand Managers & System Admin to:
  1. Review and resolve open consumer feedback records.
  2. Audit disputed resolutions and handle customer escalation loops.
  3. Quarantined & Fraud Audit: Inspect AI-flagged synthetic reports, bad-faith slander, 
     and low-authenticity scores before they affect public sentiment analytics.
"""

import streamlit as st
import pandas as pd
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
                    f"[{row['urgency']}] {row['category']} - {row['county']} ({row['id']})"
                ):
                    st.write(f"**Summary:** {row['english_summary']}")
                    st.write(f"**Raw Consumer Input:** {row['raw_text']}")
                    st.caption(f"Reported On: {row['timestamp']} | Days Open: {row['days_unresolved']}")

                    with st.form(key=f"resolve_form_{row['id']}"):
                        note = st.text_area("Resolution Note / Action Taken", key=f"note_{row['id']}")
                        resolved_by = st.text_input("Manager Name / Admin ID", key=f"admin_{row['id']}")
                        photo_url = st.text_input("Evidence Photo URL (Optional)", key=f"photo_{row['id']}")
                        
                        submit = st.form_submit_button("Mark as Resolved")
                        if submit:
                            if not note or not resolved_by:
                                st.error("Please provide both a resolution note and your name/ID.")
                            else:
                                mark_resolved(
                                    complaint_id=row['id'],
                                    note=note,
                                    resolved_by=resolved_by,
                                    photo_path=photo_url
                                )
                                st.success(f"Complaint {row['id']} resolved successfully!")
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
                with st.expander(f"⚠️ Dispute Escalation - {row['category']} ({row['id']})"):
                    st.write(f"**Original Summary:** {row['english_summary']}")
                    st.write(f"**Previous Resolution Note:** {row['resolution_note']}")
                    st.warning(f"**Dispute Reasons & Feedback:** {row['dispute_reasons']}")
                    st.caption(f"Dispute Count: {row['dispute_count']}")

                    with st.form(key=f"re_resolve_form_{row['id']}"):
                        new_note = st.text_area("Updated Action Plan", key=f"dispute_note_{row['id']}")
                        admin_name = st.text_input("Re-Resolving Manager", key=f"dispute_admin_{row['id']}")
                        
                        resolve_btn = st.form_submit_button("Re-Resolve & Close Escalation")
                        if resolve_btn:
                            if not new_note or not admin_name:
                                st.error("Please provide updated details before closing.")
                            else:
                                mark_resolved(
                                    complaint_id=row['id'],
                                    note=f"[Re-Resolved] {new_note}",
                                    resolved_by=admin_name
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
                # Extract anti-fraud flags safely
                auth_score = float(row.get("authenticity_score", 0.0))
                is_synthetic = str(row.get("is_flagged_synthetic", "False")).lower() == "true"
                defamation = str(row.get("defamation_flag", "False")).lower() == "true"

                # Styling header by risk severity
                risk_label = "☣️ HIGH FRAUD RISK" if (is_synthetic or defamation) else "⚠️ SUSPICIOUS AUTHENTICITY"
                
                with st.expander(f"{risk_label}: {row['category']} - {row['county']} ({row['id']})"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Authenticity Score", f"{auth_score:.2f}")
                    with col2:
                        st.metric("Synthetic/AI Flag", "True" if is_synthetic else "False")
                    with col3:
                        st.metric("Defamation Flag", "True" if defamation else "False")

                    st.markdown("---")
                    st.write(f"**English Summary:** {row['english_summary']}")
                    st.write(f"**Raw Text:** {row['raw_text']}")
                    st.caption(f"Ingested Timestamp: {row['timestamp']}")

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
    df = pd.read_csv(DATA_PATH)
    df = _coerce_dtypes(df)
    idx = df.index[df["id"] == complaint_id]
    
    if len(idx) > 0:
        df.loc[idx, "status"] = new_status
        _save_df_atomic(df)