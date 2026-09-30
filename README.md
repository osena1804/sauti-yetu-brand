# 🎙️ Sauti Yetu — Enterprise Brand Risk Telemetry & Fraud Audit Portal

🚀 **Live Demo:** [sauti-yetu-brand.streamlit.app](https://sauti-yetu-brand-djflh9zwtzfpsw6biv6ry6.streamlit.app)

**Sauti Yetu** ("Our Voice") is an enterprise-grade consumer incident management and brand risk telemetry platform. Built for zero-trust environments, it captures multi-channel consumer complaints in real time, routes high-severity risks, quarantines bad-faith or prompt-injection attacks through an AI Fraud Audit Shield, and unmasks encrypted PII on-demand for dispute reviews.

---

## 🌟 Key Features

- **📱 Multimodal & Localized Ingestion:** Processes multi-channel inputs (Swahili, Sheng, English, voice transcripts, and visual image evidence) with automatic PII scrubbing and geospatial tagging across Kenyan market hubs.
- **🔐 Zero-Trust Security & PII Encryption:** 
  - **AES-256 Symmetric Encryption:** Sensitive complainant identity details (phone numbers, full names) and admin signatures are encrypted at rest.
  - **HMAC-SHA256 Irreversible Indexing:** Deterministic hash lookup for outbound SMS routing without exposing raw PII.
  - **On-Demand Unmasking:** Decryption restricted to authenticated admin dispute review triggers.
- **🛡️ AI Fraud & Quarantine Shield:** Automatically filters prompt-injection attacks, defamatory content, and synthetic spam out of executive analytics into a dedicated **Fraud Audit Portal**.
- **📊 Public & Workspace Dashboards:** Clean real-time telemetry tracking incident clusters, severity scores, and urgency tiers unpolluted by quarantined entries.
- **📋 Dispute Resolution Workflow:** Complete dispute manager interface with escalation loops, manager override toggles, and photo-verified audit trail generation.
- **☁️ Cloud Auto-Seeding:** Autonomous database startup initialization to populate 39 enterprise complaints and active alerts on fresh Streamlit Cloud deployments.

---

## 🛠️ Architecture & Tech Stack

- **Frontend & Visualization:** Streamlit
- **Core Processing:** Python 3.10+, SQLite3, Pandas
- **Intelligence Layer:** Google Gemini API & Anthropic Claude API (Structured classification, image verification, and streaming intelligence)
- **Security & Cryptography:** `cryptography` (Fernet AES-256), `hashlib` (HMAC-SHA256)
- **Messaging Gateway:** Africa's Talking API & Twilio integration

---

## 🚀 Quickstart Guide

### 1. Prerequisites

Ensure you have Python 3.10 or higher installed:

```bash
python --version