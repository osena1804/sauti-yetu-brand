# create_demo_admins.py / admins.py
#
# Run once to seed demo admin accounts. Set real values via environment
# variables or a .env file before running - never hardcode real credentials.

import os
from dotenv import load_dotenv
import db

# Load local .env variables if present
load_dotenv()

AUDITOR_PHONE = os.environ.get("SAUTI_AUDITOR_PHONE", "+254700000000")
JWANJIRU_PASSWORD = os.environ.get("SAUTI_JWANJIRU_PASSWORD", "ChangeMe-placeholder-1")
KOTIENO_PASSWORD = os.environ.get("SAUTI_KOTIENO_PASSWORD", "ChangeMe-placeholder-2")
CFREVIEWER_PASSWORD = os.environ.get("SAUTI_CFREVIEWER_PASSWORD", "ChangeMe-placeholder-3")

def seed_admin_accounts():
    """Seeds default admin users into the database safely."""
    if AUDITOR_PHONE == "+254700000000":
        print("[create_demo_admins] WARNING: using placeholder phone. Set SAUTI_AUDITOR_PHONE for real SMS delivery.")
    
    if (
        JWANJIRU_PASSWORD.startswith("ChangeMe-placeholder")
        or KOTIENO_PASSWORD.startswith("ChangeMe-placeholder")
        or CFREVIEWER_PASSWORD.startswith("ChangeMe-placeholder")
    ):
        print(
            "[create_demo_admins] WARNING: using placeholder password(s). "
            "Set SAUTI_JWANJIRU_PASSWORD / SAUTI_KOTIENO_PASSWORD / SAUTI_CFREVIEWER_PASSWORD "
            "before relying on these accounts."
        )

    try:
        db.create_admin("cfreviewer", CFREVIEWER_PASSWORD, "CF Reviewer", role="brand_protection")
        print("Created brand_protection: cfreviewer")
    except Exception as e:
        print("cfreviewer:", e)

    try:
        db.create_admin("jwanjiru", JWANJIRU_PASSWORD, "Jane Wanjiru", role="brand_manager")
        print("Created brand_manager: jwanjiru")
    except Exception as e:
        print("jwanjiru:", e)

    try:
        db.create_admin("kotieno", KOTIENO_PASSWORD, "Ken Otieno", role="auditor")
        print("Created auditor: kotieno")
    except Exception as e:
        print("kotieno:", e)

    try:
        db.update_admin_phone("kotieno", AUDITOR_PHONE)
    except Exception as e:
        print("phone update error:", e)


# Allows running directly via `python admins.py`
if __name__ == "__main__":
    seed_admin_accounts()