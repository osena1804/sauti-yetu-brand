import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ---------- AES-256-GCM key (reversible fields: admin identity) ----------
# Generate a real key before any live use:
#   python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
# Set it as SAUTI_AES_KEY. Rotating this key makes every previously encrypted
# value permanently undecryptable - back up the key, not just the DB.
_DEV_AES_KEY = base64.urlsafe_b64encode(b"dev-only-aes-key-change-me-now!!").decode()
_AES_KEY_B64 = os.environ.get("SAUTI_AES_KEY", _DEV_AES_KEY)
if _AES_KEY_B64 == _DEV_AES_KEY:
    print("[crypto_utils] WARNING: using dev AES key. Set SAUTI_AES_KEY for anything beyond local testing.")
_AES_KEY = base64.urlsafe_b64decode(_AES_KEY_B64)

# Separate secret from ingestion.py's phone SALT, so admin badges and phone
# hashes are cryptographically independent of each other.
_DEV_BADGE_SALT = "dev-only-badge-salt-change-me"
BADGE_SALT = os.environ.get("SAUTI_BADGE_SALT", _DEV_BADGE_SALT)


def encrypt_field(plaintext: str) -> str:
    """AES-256-GCM encrypt. Returns base64(nonce || ciphertext) as one string,
    so it fits a single TEXT column. A fresh random nonce every call - reusing
    a nonce with the same key would break GCM's security guarantees."""
    aesgcm = AESGCM(_AES_KEY)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_field(token: str) -> str:
    """Reverses encrypt_field. Raises if the token is malformed or the key is wrong -
    callers should only invoke this from an explicit, on-demand audit action."""
    raw = base64.urlsafe_b64decode(token.encode("utf-8"))
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_AES_KEY)
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def generate_public_badge(real_identity: str) -> str:
    """Deterministic, ONE-WAY masked badge for public display (mirrors ingestion.py's
    hash_phone pattern). Same admin always yields the same badge, but the badge
    cannot be reversed back to the real identity - that only comes from
    decrypt_field() on the separately stored encrypted value."""
    digest = hmac.new(
        BADGE_SALT.encode(), real_identity.strip().lower().encode(), hashlib.sha256
    ).hexdigest()
    badge_number = int(digest[:8], 16) % 9000 + 1000  # stable 4-digit badge
    return f"Officer #{badge_number}"


def mask_phone_display(phone_e164: str) -> str:
    """0712****78-style masking for any public-facing phone display."""
    digits = phone_e164.lstrip("+")
    if len(digits) < 6:
        return "*" * len(digits)
    return f"{digits[:4]}{'*' * (len(digits) - 6)}{digits[-2:]}"


# ---------- Password hashing (admin accounts) ----------

def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random per-password salt, stored as
    'salt_hex$hash_hex' in a single TEXT column."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return hmac.compare_digest(actual, expected)


# ---------- Self-test ----------

def _self_test():
    secret = "Jane Wanjiru, EMP-2291"
    token = encrypt_field(secret)
    assert token != secret
    assert decrypt_field(token) == secret

    badge1 = generate_public_badge(secret)
    badge2 = generate_public_badge("jane wanjiru, emp-2291")  # case/space-insensitive
    assert badge1 == badge2, "same identity must yield the same badge"
    assert badge1 != generate_public_badge("Different Officer")
    assert secret not in badge1 and "EMP-2291" not in badge1

    assert mask_phone_display("+254712345678") == "2547******78"

    pw_hash = hash_password("Sup3rSecret!")
    assert verify_password("Sup3rSecret!", pw_hash)
    assert not verify_password("wrong", pw_hash)

    print("crypto_utils: all tests passed.")
    print("Example ->", secret, "-> badge:", badge1, "| token:", token[:24] + "...")


if __name__ == "__main__":
    _self_test()