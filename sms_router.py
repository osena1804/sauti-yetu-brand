import re

import db
import ingestion

# Curated keyword variants per brand — deliberately NOT auto-derived from the
# brand name's first word, since generic words (e.g. "equity") cause false
# matches on unrelated complaint text ("treat customers with more equity").
# If you add a brand to seed_data.py, add its keywords here too, or SMS
# reports mentioning it will fall through to the "couldn't tell which brand"
# reply even though the brand exists in the database.
BRAND_KEYWORDS = {
    "Safaricom": ["safaricom", "mpesa", "m-pesa"],
    "Equity Bank": ["equity bank", "equity account", "equitel"],
    "Naivas": ["naivas"],
    "Bidco Africa": ["bidco"],
    "Brookside Dairy": ["brookside"],
    "Diageo / EABL": ["diageo", "eabl", "east african breweries"],
    "Unilever": ["unilever"],
    "Coca-Cola": ["coca cola", "coca-cola", "coke"],
    "Carrefour": ["carrefour"],
    "Samsung": ["samsung"],
    "KCB Group": ["kcb"],
    "L'Oreal": ["loreal", "l'oreal"],
}

_KEYWORD_PAIRS = None


def _normalize(text):
    return text.lower().replace("'", "").replace("’", "").replace("-", " ")


def _keyword_pairs():
    """Flattens BRAND_KEYWORDS into (normalized_keyword, brand_name) pairs, sorted
    longest-keyword-first so a more specific phrase is tried before a shorter one."""
    global _KEYWORD_PAIRS
    if _KEYWORD_PAIRS is None:
        pairs = [
            (_normalize(keyword), brand_name)
            for brand_name, keywords in BRAND_KEYWORDS.items()
            for keyword in keywords
        ]
        _KEYWORD_PAIRS = sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)

        known = set(BRAND_KEYWORDS)
        seeded = {b["brand_name"] for b in db.list_brands()}
        missing = seeded - known
        if missing:
            print(f"[sms_router] WARNING: no keywords defined for: {sorted(missing)}. "
                  f"SMS reports mentioning them won't be routed. Add entries to BRAND_KEYWORDS.")
    return _KEYWORD_PAIRS


def extract_brand_from_text(text):
    """Returns the matched brand_name, or None if no curated keyword appears as a
    whole word/phrase in the text. Checked longest-keyword-first."""
    normalized = _normalize(text)
    for keyword, brand_name in _keyword_pairs():
        if re.search(rf"\b{re.escape(keyword)}\b", normalized):
            return brand_name
    return None


def extract_county_from_text(text):
    """Returns a matched county, defaulting to Nairobi if none is mentioned.
    DEMO SIMPLIFICATION: SMS senders rarely name their county explicitly: a real
    deployment would need a better signal (e.g. AT's cell-tower location data,
    or a required follow-up prompt) rather than defaulting silently."""
    text_lower = text.lower()
    for county in ingestion.KENYAN_COUNTIES:
        if county.lower() in text_lower:
            return county
    return "Nairobi"


# ---------- Self-test (read-only, no network) ----------

def _self_test():
    cases = [
        ("This company needs to treat customers with more equity and fairness", None),
        ("Naivas needs to treat customers with more equity and fairness", "Naivas"),
        ("My Equity Bank account was charged twice", "Equity Bank"),
        ("Equitel line is down again", "Equity Bank"),
        ("loreal shampoo bottle was leaking", "L'Oreal"),
        ("L'Oreal shampoo bottle was leaking", "L'Oreal"),
        ("M-Pesa app stuck on step 2", "Safaricom"),
        ("Coca-Cola bottle was flat and expired", "Coca-Cola"),
        ("Naivas Ngong Road has no stock", "Naivas"),
        ("Random text with no brand mentioned at all", None),
    ]
    for text, expected in cases:
        result = extract_brand_from_text(text)
        assert result == expected, f"{text!r} -> {result!r}, expected {expected!r}"
        print(f"  OK  {text!r:55} -> {result}")
    print("sms_router tests: all passed.")


if __name__ == "__main__":
    _self_test()