import re

import db

UNCLASSIFIED = "unclassified"

# Demo-tier clustering: a deterministic lookup, NOT semantic embeddings.
# A complaint joins a cluster only if it matches at least one SYMPTOM pattern
# (what went wrong) AND at least one CONTEXT pattern (what it's about).
# Patterns are regexes, matched case-insensitively, so dialect variants
# are caught by their stems.
#
# RULE PACKS: each brand (set on the Brands screen) uses one rule pack, so a new
# client's brands work as soon as they are keyed in, with no code change.
# A new sector (food, banking, telecom ...) needs a new pack written and tested here.
#
# BRAND NAME HANDLING: the brand's own name is removed from the text before matching,
# so a name like "Dark & Lovely" or "White Star" can never trigger a symptom or context
# word by itself. A cluster marked brand_context=True counts a mention of the brand's
# own name as one context hit.

_BEAUTY_RULES = {
    # RED-alert cluster: bad skin or scalp reactions after using a product
    "skin_reaction": {
        "brand_context": True,
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
        ],
    },
    # AMBER-alert cluster: white or ashy film on deep skin tones
    "white_cast_deep_skin": {
        "brand_context": False,
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
        ],
    },
    # PATTERN cluster: hair breakage or hair loss after a hair product.
    # Safety first: if a text mentions BOTH a burn and breakage, skin_reaction wins
    # (it is listed first, and ties go to the first cluster).
    "hair_damage": {
        "brand_context": False,
        "symptoms": [
            r"breakage|breaking|break(s)? off|broke off|snapp(ed|ing)",
            r"brittle",
            r"hair ?loss|losing (my |her |his )?hair|falling out|fell out|thinning|\bbald",
            r"katika|nyonyok|dondok",
        ],
        "context": [
            r"hair|nywele",
            r"relaxer|\bdye\b|shampoo|conditioner|hair ?treatment|\bperm\b|scalp",
        ],
    },
}

RULE_PACKS = {
    "beauty": _BEAUTY_RULES,
    "none": {},   # brand is stored, but its reports are never clustered or alerted
}
RULE_PACK_INFO = {
    "beauty": "Beauty and personal care: skin reaction, white cast on deep skin, hair damage",
    "none": "No clustering: reports are stored but never raise alerts",
}
DEFAULT_PACK = "beauty"

# Compile once at import time
_COMPILED = {
    pack: {
        cluster: {
            "brand_context": bool(rule.get("brand_context")),
            "symptoms": [re.compile(p, re.IGNORECASE) for p in rule["symptoms"]],
            "context": [re.compile(p, re.IGNORECASE) for p in rule["context"]],
        }
        for cluster, rule in clusters.items()
    }
    for pack, clusters in RULE_PACKS.items()
}


def _brand_regex(brand_name):
    """Regex matching the brand's own name in a complaint. 'Dark & Lovely' also matches
    'Dark and Lovely'. Returns None if the name has no usable words."""
    words = [w for w in re.findall(r"[A-Za-z0-9'\u2019]+", brand_name or "") if w.lower() != "and"]
    if not words:
        return None
    return re.compile(r"\W+(?:(?:and|&)\W+)?".join(re.escape(w) for w in words), re.IGNORECASE)


def classify(brand_name, text, rule_pack=None):
    """Returns the best-matching cluster_id for this brand, or 'unclassified'.
    The rule pack comes from the brand's setting unless one is passed in.
    If several clusters qualify, the one with the most distinct pattern hits wins."""
    if not text:
        return UNCLASSIFIED
    pack = rule_pack or db.get_brand_rule_pack(brand_name)
    clusters = _COMPILED.get(pack)
    if not clusters:
        return UNCLASSIFIED

    brand_re = _brand_regex(brand_name)
    mentions_brand = bool(brand_re and brand_re.search(text))
    masked = brand_re.sub(" brandname ", text) if brand_re else text

    best_cluster, best_score = UNCLASSIFIED, 0
    for cluster_id, rule in clusters.items():
        symptom_hits = sum(1 for p in rule["symptoms"] if p.search(masked))
        context_hits = sum(1 for p in rule["context"] if p.search(masked))
        if rule["brand_context"] and mentions_brand:
            context_hits += 1
        if symptom_hits >= 1 and context_hits >= 1:
            score = symptom_hits + context_hits
            if score > best_score:
                best_cluster, best_score = cluster_id, score
    return best_cluster


# ---------- Self-test (read-only) ----------

def _self_test():
    # 0. Every brand in the database must have a known rule pack
    brands = db.list_brands(include_inactive=True)
    assert brands, "No brands in the database. Reseed or add brands first."
    for b in brands:
        assert b["rule_pack"] in RULE_PACKS, f"{b['brand_name']!r} has unknown rule pack {b['rule_pack']!r}"
    print(f"  OK  {len(brands)} brands, all with a known rule pack")

    # 1. Every seeded complaint must land in the cluster it was seeded under
    checks = [
        ("Garnier", "white_cast_deep_skin", 15),
        ("Garnier", "skin_reaction", 3),
        ("Dark & Lovely", "hair_damage", 4),
    ]
    for brand, cluster, expected in checks:
        brand_id = db.get_brand_id(brand)
        rows = db.get_complaints_for_cluster(brand_id, cluster)
        assert len(rows) == expected, f"{brand}/{cluster}: found {len(rows)} rows, expected {expected}"
        misses = [r["raw_text_scrubbed"] for r in rows
                  if classify(brand, r["raw_text_scrubbed"], "beauty") != cluster]
        assert not misses, f"{brand}/{cluster} missed {len(misses)}: {misses}"
        print(f"  OK  {brand:14} {cluster:22} {expected}/{expected} classified correctly")

    # 2. Sample texts (the pack is passed in, so these do not depend on the database)
    samples = [
        ("Garnier", "skin_reaction", "Garnier hair dye gave me a rash and my scalp is burning and swollen"),
        ("Garnier", "skin_reaction", "Nilitumia Garnier cream usoni na ngozi yangu imevimba na kuwasha sana"),
        ("Garnier", "white_cast_deep_skin", "The Garnier sunscreen leaves a white cast on my dark skin, I look ashy"),
        ("Dark & Lovely", "skin_reaction", "After using the Dark & Lovely relaxer my scalp got blisters, I went to hospital"),
        ("Dark & Lovely", "skin_reaction", "Relaxer ya Dark and Lovely imeunguza kichwa changu na nywele zimeanza kuchubuka"),
        ("Dark & Lovely", "white_cast_deep_skin", "The Dark & Lovely sunscreen leaves a white cast on my dark skin"),
        ("Dark & Lovely", "hair_damage", "Hair loss after the treatment, it is falling out in clumps"),
        ("Dark & Lovely", "skin_reaction", "The Dark & Lovely relaxer burned my scalp and my hair broke off"),
        ("Nice & Lovely", "skin_reaction", "Nice & Lovely lotion made my skin itchy and red for two days"),
        ("Nice & Lovely", "hair_damage", "Nywele zangu zimekatika baada ya kutumia relaxer"),
        ("Mizani", "skin_reaction", "The Mizani treatment gave me an itchy rash on my scalp"),
        ("Mizani", "hair_damage", "My hair is breaking off after the Mizani relaxer"),
        ("CeraVe", "white_cast_deep_skin", "The CeraVe sunscreen leaves a white cast on my dark skin"),
        ("CeraVe", "skin_reaction", "CeraVe cream gave me a rash on my face"),
        ("Versman", "skin_reaction", "Versman cream gave me an itchy rash on my face"),
        ("Versman", "white_cast_deep_skin", "Sunscreen hii ya Versman inaacha rangi nyeupe kwenye ngozi nyeusi"),
        # A brand added later through the Brands screen works with no code change:
        ("Black Opal", "skin_reaction", "Black Opal foundation gave me an itchy rash on my face"),
        ("Black Opal", "white_cast_deep_skin", "The Black Opal powder leaves a white cast on dark skin"),
    ]
    for brand, expected_cluster, text in samples:
        result = classify(brand, text, "beauty")
        assert result == expected_cluster, f"{brand}/{text!r} -> {result}, expected {expected_cluster}"
    print(f"  OK  {len(samples)} sample texts classified correctly")

    # 3. Things that must NOT be clustered
    negatives = [
        ("Garnier", "beauty", "I love this cream, my skin feels amazing"),
        ("Garnier", "beauty", "The Garnier app keeps crashing at checkout"),
        ("Garnier", "beauty", "Delivery was late and the courier was rude"),
        ("Dark & Lovely", "beauty", "The shop did not have my size in stock"),
        ("Dark & Lovely", "beauty", "The Dark & Lovely shampoo leaves white residue in my hair"),
        ("Dark & Lovely", "beauty", "The Dark & Lovely relaxer left white residue on my scalp"),
        ("Garnier", "beauty", "The Garnier shampoo leaves white residue in my hair"),
        ("Garnier", "beauty", "I love how soft my hair feels after the conditioner"),
        ("Garnier", "beauty", "The bottle broke in my bag"),
        ("Garnier", "beauty", ""),
        ("White Star", "beauty", "White Star shampoo is great, my hair feels deep and soft"),   # brand name alone triggers nothing
        ("Garnier", "none", "Garnier cream gave me a rash on my face"),                         # pack 'none' never clusters
        ("Garnier", "no-such-pack", "Garnier cream gave me a rash on my face"),                 # unknown pack is safe
    ]
    for brand, pack, text in negatives:
        result = classify(brand, text, pack)
        assert result == UNCLASSIFIED, f"False positive: {brand!r}/{pack} / {text!r} -> {result}"
    print(f"  OK  {len(negatives)} negative cases stayed unclassified")

    # 4. Brand-name matching
    assert _brand_regex("Dark & Lovely").search("dark and lovely relaxer")
    assert _brand_regex("Dark & Lovely").search("DARK & LOVELY")
    assert _brand_regex("???") is None
    print("  OK  brand-name matching")

    print("Clustering tests: all passed.")


if __name__ == "__main__":
    _self_test()