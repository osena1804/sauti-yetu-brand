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
    "L'Oreal": {
        # RED-alert cluster: bad skin or scalp reactions after using a product
        "skin_reaction": {
            "symptoms": [
                r"\brash(es)?\b|vipele",
                r"\bitch(y|ing)?\b|kuwasha|nawashwa",
                r"swell|swollen|vimba",
                r"\bburn(s|ed|t|ing)?\b|ungua|unguza",
                r"blister|malengelenge",
                r"\bhives\b|irritat|allerg|mzio",
                r"peeling|peeled|chubuka",
                r"reaction|reacted",
            ],
            "context": [
                r"skin|ngozi|face|\buso",
                r"scalp|hair|nywele",
                r"cream|lotion|serum|shampoo|conditioner|relaxer|\bdye\b|sunscreen|moisturi[sz]er|foundation|makeup|mascara|lipstick|perfume|deodorant",
                r"l['\u2019]?or[e\u00e9]al|garnier|maybelline|vichy|la roche|cerave",
            ],
        },
        # AMBER-alert cluster: white or ashy film on deep skin tones
        "white_cast_deep_skin": {
            "symptoms": [
                r"white (cast|film|residue|layer|patch(es)?)|whitish",
                r"\bashy\b|chalky",
                r"gr[ae]y(ish)? (cast|look|tinge)|kijivu",
                r"nyeupe|weupe",
            ],
            "context": [
                r"sunscreen|sunblock|\bspf\b",
                r"cream|lotion|moisturi[sz]er|foundation|powder|serum|primer|makeup",
                r"skin|ngozi|face|\buso",
                r"dark|deep|black|nyeusi|\btone",
                r"l['\u2019]?or[e\u00e9]al|garnier|maybelline|vichy|la roche|cerave",
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
        ("L'Oreal", "white_cast_deep_skin", 15),
        ("L'Oreal", "skin_reaction", 3),
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
    # 4. L'Oreal: no seed data yet, so test classify() directly on sample texts.
    loreal_samples = [
        ("skin_reaction", "Nilitumia L'Oreal cream usoni na ngozi yangu imevimba na kuwasha sana"),
        ("skin_reaction", "Garnier hair dye gave me a rash and my scalp is burning and swollen"),
        ("skin_reaction", "After using the L'Oreal relaxer my scalp got blisters, I went to hospital"),
        ("skin_reaction", "L'Or\u00e9al cream gave me an itchy rash on my face"),
        ("white_cast_deep_skin", "The L'Oreal sunscreen leaves a white cast on my dark skin, I look ashy"),
        ("white_cast_deep_skin", "Sunscreen ya L'Oreal inaacha rangi nyeupe usoni, ngozi nyeusi inaonekana ya kijivu"),
        ("white_cast_deep_skin", "This foundation looks chalky and grey on deep skin tones"),
    ]
    for expected_cluster, text in loreal_samples:
        result = classify("L'Oreal", text)
        assert result == expected_cluster, f"L'Oreal / {text!r} -> {result}, expected {expected_cluster}"
    print(f"  OK  {len(loreal_samples)} L'Oreal sample texts classified correctly")

    loreal_negatives = [
        ("L'Oreal", "I love this cream, my skin feels amazing"),
        ("L'Oreal", "The Garnier app keeps crashing at checkout"),
        ("L'Oreal", "Delivery was late and the courier was rude"),
        ("Naivas", "My skin got a rash from the L'Oreal cream"),
        ("Unilever", "My skin got a rash after using the cream"),
    ]
    for brand, text in loreal_negatives:
        result = classify(brand, text)
        assert result == UNCLASSIFIED, f"False positive: {brand!r} / {text!r} -> {result}"
    print(f"  OK  {len(loreal_negatives)} L'Oreal-related negative cases stayed unclassified")

    print("Clustering tests: all passed.")


if __name__ == "__main__":
    _self_test()