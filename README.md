# 🎙️ Sauti Yetu — Enterprise Brand Risk Telemetry & Fraud Audit Portal

🚀 **Live Demo:** [sauti-yetu-brand.streamlit.app](https://sauti-yetu-brand-djflh9zwtzfpsw6biv6ry6.streamlit.app)

Consumer-voice and brand-risk telemetry for brands in Kenya. Consumers scan a QR code and report a product
problem or a suspected counterfeit on a web form. The platform scores and clusters the reports, raises alerts,
routes counterfeit reports to a restricted review queue, and tracks whether a brand's claimed fix is
confirmed by the people affected.

> **Status: pilot prototype.** Demo data is simulated. Do not collect real consumer data until the DPIA,
> consent wording and hosting are signed off (see "Before real data" below).

## Run it locally

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml     # then edit the values
streamlit run <main file>.py
```

The first start creates `sauti_yetu.db` and, in demo mode, fills it with simulated data.

## Configuration

Set these as environment variables, or in `.streamlit/secrets.toml`, or in Streamlit Cloud under Settings, Secrets.

| Name | What it does |
|---|---|
| `SAUTI_AES_KEY` | Encrypts phone numbers and admin identities |
| `SAUTI_SALT` | Secret for the keyed phone hash. Changing it breaks duplicate counting |
| `SAUTI_JWANJIRU_PASSWORD`, `SAUTI_KOTIENO_PASSWORD` | Demo admin passwords. Never leave the placeholders on a public app |
| `GEMINI_API_KEY` | AI scoring. Without it, or with `SAUTI_OFFLINE=1`, built-in rules are used |
| `SAUTI_OFFLINE` | `1` = rule-based scoring only; nothing is sent to an AI service |
| `SAUTI_DEMO` | `1` (default) = demo data and banner. `0` = real client deployment, starts empty |
| `SAUTI_CLIENT_NAME` | Client name shown in the app |
| `SAUTI_CONTROLLER_NAME`, `SAUTI_PRIVACY_CONTACT` | Used in the consent notice |
| `SAUTI_RETAIN_AFTER_RESOLUTION_DAYS`, `SAUTI_RETAIN_UNTIED_DAYS`, `SAUTI_RETAIN_COUNTERFEIT_DAYS` | Retention periods (defaults 30, 90, 60) |

## Roles

| Role | Can see |
|---|---|
| (not logged in) | Alert Board (counts and brand statements only), report forms |
| `brand_manager` | Internal data, resolution tracker, fraud audit |
| `brand_protection` | Counterfeit review (photos and reports) |
| `auditor` | Everything above, plus Data & Privacy and Brands |

Photos and individual reports are visible to logged-in admins only.

## Brands and clients

Brands are data, not code: add them on the **Brands** screen (auditor). Each brand uses a *rule pack*
(`clustering.py`) that decides which issue clusters it can raise. Each client gets its own deployment and
database, so one client's brands and reports are never visible to another's consumers.

## Data retention

`python retention.py` shows what is due for deletion (a dry run). `python retention.py --apply` deletes it.
Only anonymous counts are kept. The same actions are available to auditors on the Data & Privacy screen.

## Tests

```
python clustering.py          # clustering rules (needs the seeded database)
python retention.py           # dry run of retention
```

## Before real data

- Lawyer-approved consent notice (English and Swahili); set `WORDING_IS_DRAFT = False` in `consent.py`.
- Completed DPIA and processing agreement.
- Production hosting with a persistent database and private photo storage (not local files).
- Real admin passwords, multi-factor login, and keys held in a secrets manager.

## Never commit

Secrets, `*.db`, `uploads/`, `score_cache.json`. They are listed in `.gitignore`.