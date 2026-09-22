# 🎙️ Sauti Yetu — Real-Time Feedback & Fraud Audit Portal

🚀 **Live Demo:** [sauti-yetu-brand.streamlit.app](https://sauti-yetu-brand-djflh9zwtzfpsw6biv6ry6.streamlit.app)

**Sauti Yetu** ("Our Voice") is an AI-powered feedback ingestion, classification, and brand sentiment platform. It captures consumer input in real time, routes severe grievances, isolates synthetic or bad-faith reports through an AI fraud quarantine, and synthesizes action briefs for brand managers and administrators.

---

## 🌟 Key Features

- **📱 Multilingual & Localized Ingestion:** Supports English, Swahili, and Sheng inputs with automatic English summarization and county-level geospatial tagging across Kenya.
- **🛡️ AI Fraud & Quarantine Shield:** Automatically calculates authenticity scores for incoming reports and isolates synthetic AI personas, spam, or defamatory content before it skews analytics.
- **📊 Real-Time Public & Executive Dashboards:** Interactive visualization of urgency tiers, category breakdowns, and resolution progress unpolluted by quarantined reports.
- **📋 Admin Resolution Workflow:** Complete dispute management interface with escalation loops, photo evidence attachments, and manager override tools for quarantined entries.
- **📄 Automated Executive Briefs:** One-click generation of structured action briefs for brand directors and stakeholders.

---

## 🛠️ Architecture & Tech Stack

- **Frontend & Dashboard:** Streamlit
- **Backend & Data Processing:** Python 3.10+, Pandas, NumPy
- **Intelligence Layer:** Google Gemini / Gemma API (Structured classification, sentiment analysis, and synthetic text detection)
- **Data Persistence:** Atomic CSV/JSON file-backed store (Easily extensible to PostgreSQL / MongoDB)

---

## 🚀 Quickstart Guide

### 1. Prerequisites

Ensure you have Python 3.10 or higher installed:

```bash
python --version