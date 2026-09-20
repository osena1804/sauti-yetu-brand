"""
crypto_utils.py

Handles sensitive data privacy:
  - encrypt_phone() / decrypt_phone(): Reversible Fernet encryption for SMS routing.
  - encrypt_name() / decrypt_name(): Reversible encryption for Admin Signatures on public complaints.
  - hash_phone(): One-way salted HMAC-SHA256 hash for deduplication/analytics.
"""

import os
import re
import hmac
import hashlib
from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken

load_dotenv()

_fernet_phone = None
_fernet_admin = None


def normalize_phone(phone: str) -> str:
    """
    Standardizes phone numbers into E.164 format (+254XXXXXXXXX).
    Supports Kenya prefixes (+254, 254, 07XX, 01XX).
    """
    clean = (phone or "").strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not clean:
        return ""

    if clean.startswith("+"):
        return clean

    # Handle 2547XXXXXXXX or 2541XXXXXXXX (12 digits)
    if clean.startswith("254") and len(clean) == 12:
        return f"+{clean}"

    # Handle 07XXXXXXXX or 01XXXXXXXX (10 digits)
    if clean.startswith("0") and len(clean) == 10:
        return f"+254{clean[1:]}"

    # Handle 7XXXXXXXX or 1XXXXXXXX (9 digits raw)
    if len(clean) == 9 and clean[0] in ("7", "1"):
        return f"+254{clean}"

    return clean


def _get_fernet_instance(env_var_name: str, cache_attr: str) -> Fernet | None:
    """Helper to lazily load and cache Fernet instances per configuration key."""
    key = os.getenv(env_var_name) or os.getenv("PHONE_ENCRYPTION_KEY")
    if not key:
        print(f"[crypto_utils] WARNING: {env_var_name} not set. Encryption disabled.")
        return None
    try:
        return Fernet(key.encode())
    except Exception as e:
        print(f"[crypto_utils] Invalid key for {env_var_name}: {e}")
        return None


def _get_phone_fernet() -> Fernet | None:
    global _fernet_phone
    if _fernet_phone is None:
        _fernet_phone = _get_fernet_instance("PHONE_ENCRYPTION_KEY", "_fernet_phone")
    return _fernet_phone


def _get_admin_fernet() -> Fernet | None:
    global _fernet_admin
    if _fernet_admin is None:
        _fernet_admin = _get_fernet_instance("ADMIN_ENCRYPTION_KEY", "_fernet_admin")
    return _fernet_admin


# ---------------------------------------------------------------------------
# PHONE ENCRYPTION & DECRYPTION
# ---------------------------------------------------------------------------

def encrypt_phone(phone: str) -> str:
    """Returns Fernet encrypted token for raw phone number. Fails closed (empty string)."""
    normalized = normalize_phone(phone)
    if not normalized:
        return ""

    f = _get_phone_fernet()
    if f is None:
        return ""  # Fail-closed

    return f.encrypt(normalized.encode()).decode()


def decrypt_phone(token: str) -> str:
    """Decrypts phone token back to real E.164 phone string."""
    token = (token or "").strip()
    if not token:
        return ""

    f = _get_phone_fernet()
    if f is None:
        return ""

    try:
        return f.decrypt(token.encode()).decode()
    except (InvalidToken, Exception) as e:
        print(f"[crypto_utils] Failed to decrypt phone token: {e}")
        return ""


# ---------------------------------------------------------------------------
# ADMIN NAME OBFUSCATION
# ---------------------------------------------------------------------------

def encrypt_name(name: str) -> str:
    """
    Encrypts the resolving admin's identity for public storage.
    Only decryptable by authorized internal admins.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        return ""

    f = _get_admin_fernet()
    if f is None:
        return ""  # Fail-closed

    return f.encrypt(clean_name.encode()).decode()


def decrypt_name(token: str) -> str:
    """Decrypts an admin resolution signature token back to original name."""
    token = (token or "").strip()
    if not token:
        return ""

    f = _get_admin_fernet()
    if f is None:
        return ""

    try:
        return f.decrypt(token.encode()).decode()
    except (InvalidToken, Exception) as e:
        print(f"[crypto_utils] Failed to decrypt admin signature: {e}")
        return ""


# ---------------------------------------------------------------------------
# ONE-WAY ANONYMOUS HASHING
# ---------------------------------------------------------------------------

def hash_phone(phone: str) -> str:
    """
    One-way HMAC-SHA256 hash for caller deduplication and analytics.
    Never reversible.
    """
    normalized = normalize_phone(phone)
    if not normalized:
        return ""

    salt = os.getenv("PHONE_HASH_SALT", "")
    if not salt:
        print("[crypto_utils] WARNING: PHONE_HASH_SALT is empty. Fallback to unsalted hash.")

    hashed = hmac.new(salt.encode(), normalized.encode(), hashlib.sha256).hexdigest()
    # Retain 32 chars (128-bit entropy) to prevent hash collision in analytics
    return f"anon_{hashed[:32]}"