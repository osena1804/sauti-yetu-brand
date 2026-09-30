# create_demo_admins.py
#
# Run once to seed two demo admin accounts. Set real values via environment
# variables before running - never hardcode a real phone number or a real
# password directly in this file, since it's the kind of script that tends
# to end up committed to a repo.
#
# PowerShell example:
#   $env:SAUTI_AUDITOR_PHONE = "+254700000000"
#   $env:SAUTI_JWANJIRU_PASSWORD = "some-real-password"
#   $env:SAUTI_KOTIENO_PASSWORD = "some-other-real-password"
#   python create_demo_admins.py
#
# If you don't set these, the script falls back to obviously-fake placeholder
# values so it still runs for local testing without exposing anything real.

import os

import db

AUDITOR_PHONE = os.environ.get("SAUTI_AUDITOR_PHONE", "+254700000000")
JWANJIRU_PASSWORD = os.environ.get("SAUTI_JWANJIRU_PASSWORD", "ChangeMe-placeholder-1")
KOTIENO_PASSWORD = os.environ.get("SAUTI_KOTIENO_PASSWORD", "ChangeMe-placeholder-2")

def seed_admin_accounts():
    """Seeds default admin users into the database safely."""
    try:
        db.update_admin_phone("kotieno", AUDITOR_PHONE)
    except Exception as e:
        print("phone update error:", e)

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

# Allows running directly via `python admins.py`
if __name__ == "__main__":
    seed_admin_accounts()

if AUDITOR_PHONE == "+254700000000":
    print("[create_demo_admins] WARNING: using placeholder phone. Set SAUTI_AUDITOR_PHONE for real SMS delivery.")
if JWANJIRU_PASSWORD.startswith("ChangeMe-placeholder") or KOTIENO_PASSWORD.startswith("ChangeMe-placeholder"):
    print("[create_demo_admins] WARNING: using placeholder password(s). "
          "Set SAUTI_JWANJIRU_PASSWORD / SAUTI_KOTIENO_PASSWORD before relying on these accounts.")

db.update_admin_phone("kotieno", AUDITOR_PHONE)

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