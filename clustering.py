import re

import db

UNCLASSIFIED = "unclassified"

# Demo-tier clustering: a deterministic lookup, NOT semantic embeddings.
# A complaint joins a cluster only if it matches at least one SYMPTOM pattern
# (what went wrong) AND at least one CONTEXT pattern (what it's about).
# Requiring both keeps "M-Pesa charged me a wrong fee" out of the freeze cluster.
# Patterns are regexes, matched case-insensitively, so dialect variants
# ("imestuck", "inahang", "inafreeze") are caught by their stems.
CLUSTER_RULES = {
    "Safaricom": {
        "app_freeze_step2": {
            "symptoms": [
                r"stuck",
                r"hang|hung",
                r"freez|froze",
                r"crash",
                r"haiendi|haiwork|haifanyi kazi",
                r"does nothing",
            ],
            "context": [
                r"\bapp\b",
                r"screen",
                r"payment|malipo|kulipa|\bpay\b",
                r"\bstep\b",
                r"button",
                r"m-?pesa",
                r"confirm",
            ],
        },
    },
    "Unilever": {
        "oil_seal_leakage": {
            "symptoms": [
                r"seal.{0,30}(broken|open|torn)|(broken|open|torn).{0,30}seal",
                r"contaminat",
                r"leak",
                r"smell|harufu",
                r"tamper",
            ],
            "context": [
                r"\boil\b|mafuta",
                r"batch",
                r"bottle|chupa",
                r"packag|seal",
            ],
        },
    },
    "Equity Bank": {
        "atm_card_retention": {
            "symptoms": [
                r"retent|retain",
                r"swallow|imemeza",
                r"kept (my|the) card|ate my card",
            ],
            "context": [
                r"\batm\b",
                r"\bcard\b|kadi",
            ],
        },
    },
    "Brookside Dairy": {
        "spoiled_milk": {
            "symptoms": [
                r"sour|sour(ed)?",
                r"spoil|spoilt|spoiled",
                r"curdl",
                r"bad smell|harufu mbaya|inanuka",
                r"expired|imeisha muda|expiry",
                r"vomit|kutapika|kuhara|diarrh|tumbo inauma|stomach ache",
            ],
            "context": [
                r"milk|maziwa",
                r"packet|pouch|carton|bottle|chupa",
                r"brookside",
            ],
        },
    },
    "KCB Group": {
        "failed_transaction": {
            "symptoms": [
                r"declin",
                r"failed|fail(ure)?",
                r"reversal|haijarudi",
                r"not received|haijafika|haijaingia",
                r"double debit|charged twice|deducted twice|imekatwa mara mbili",
            ],
            "context": [
                r"\bkcb\b",
                r"transaction|malipo|transfer",
                r"account|akaunti",
                r"mobile banking|app",
            ],
        },
    },
    "Naivas": {
        "stockout_and_pricing": {
            "symptoms": [
                r"out of stock|hakuna stock|imeisha stock|no stock",
                r"wrong price|bei tofauti|overcharg|different price",
                r"expired (product|item)|imeisha muda",
                r"rude|huduma mbaya|poor service",
            ],
            "context": [
                r"naivas",
                r"shelf|till|checkout|receipt|risiti",
                r"store|branch|duka",
            ],
        },
    },
}

# Compile once at import time
_COMPILED = {
    brand: {
        cluster: {
            kind: [re.compile(p, re.IGNORECASE) for p in patterns]
            for kind, patterns in rule.items()
        }
        for cluster, rule in clusters.items()
    }
    for brand, clusters in CLUSTER_RULES.items()
}


def classify(brand_name, text):
    """Returns the best-matching cluster_id for this brand, or 'unclassified'.
    If several clusters qualify, the one with the most distinct pattern hits wins."""
    clusters = _COMPILED.get(brand_name)
    if not clusters or not text:
        return UNCLASSIFIED

    best_cluster, best_score = UNCLASSIFIED, 0
    for cluster_id, rule in clusters.items():
        symptom_hits = sum(1 for p in rule["symptoms"] if p.search(text))
        context_hits = sum(1 for p in rule["context"] if p.search(text))
        if symptom_hits >= 1 and context_hits >= 1:
            score = symptom_hits + context_hits
            if score > best_score:
                best_cluster, best_score = cluster_id, score
    return best_cluster


# ---------- Self-test (read-only) ----------

def _self_test():
    # 1. Every seeded complaint must land in the cluster it was seeded under
    checks = [
        ("Safaricom", "app_freeze_step2", 15),
        ("Unilever", "oil_seal_leakage", 2),
        ("Equity Bank", "atm_card_retention", 1),
    ]
    for brand, cluster, expected in checks:
        brand_id = db.get_brand_id(brand)
        rows = db.get_complaints_for_cluster(brand_id, cluster)
        assert len(rows) == expected, f"{brand}/{cluster}: found {len(rows)} rows, expected {expected}"
        misses = [r["raw_text_scrubbed"] for r in rows if classify(brand, r["raw_text_scrubbed"]) != cluster]
        assert not misses, f"{brand}/{cluster} missed {len(misses)}: {misses}"
        print(f"  OK  {brand:12} {cluster:20} {expected}/{expected} classified correctly")

    # 2. Things that must NOT be clustered
    negatives = [
        ("Safaricom", "Network iko poa leo, nashukuru"),
        ("Safaricom", "M-Pesa charged me a wrong fee on my transfer"),
        ("Safaricom", "ATM machine retention without reversal notification"),
        ("Equity Bank", "The app freezes on step 2"),
        ("Naivas", "The app freezes on step 2"),
        ("Brookside Dairy", "The milk was great today, thank you"),
        ("KCB Group", "The milk I bought was sour"),
        ("Naivas", "My KCB transaction was declined at the till"),
    ]
    for brand, text in negatives:
        result = classify(brand, text)
        assert result == UNCLASSIFIED, f"False positive: {brand!r} / {text!r} -> {result}"
    print(f"  OK  {len(negatives)} negative cases stayed unclassified")

    # 3. New brands: no seed data yet, so test classify() directly against
    # representative sample texts rather than rows already in the database.
    samples = [
        ("Brookside Dairy", "spoiled_milk", "Nimenunua maziwa ya Brookside na ni sour, inanuka vibaya"),
        ("Brookside Dairy", "spoiled_milk", "The milk packet was curdled and past its expiry date"),
        ("KCB Group", "failed_transaction", "My KCB mobile banking transaction was declined but money imekatwa"),
        ("KCB Group", "failed_transaction", "Transfer failed twice and the app shows no reversal"),
        ("Naivas", "stockout_and_pricing", "Naivas Ngong Road hakuna stock ya sugar since last week"),
        ("Naivas", "stockout_and_pricing", "The receipt showed a different price than the shelf tag"),
    ]
    for brand, expected_cluster, text in samples:
        result = classify(brand, text)
        assert result == expected_cluster, f"{brand}/{text!r} -> {result}, expected {expected_cluster}"
    print(f"  OK  {len(samples)} new-brand sample texts classified correctly (Brookside Dairy, KCB Group, Naivas)")

    print("Clustering tests: all passed.")


if __name__ == "__main__":
    _self_test()