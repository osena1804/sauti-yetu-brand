"""
gemma_client.py

Wraps all Gemma 4 / Gemini interactions for Sauti-Yetu (Enterprise Consumer Intelligence):
  1. classify_complaint()        -> Structures raw consumer text feedback into 
                                    {category, urgency, county, english_summary, 
                                     authenticity_score, is_flagged_synthetic, defamation_flag}
                                    using dynamic function calling.
  2. classify_complaint_audio() -> Processes voice notes directly using multimodal input.
  3. classify_complaint_image() -> Processes product/on-shelf photo reports.
  4. generate_action_brief()    -> Generates a formal brand response & action brief
                                    from aggregated consumer records.
"""

import os
import json
from datetime import datetime, timezone
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma-4-it")
FORCE_MOCK = os.getenv("FORCE_MOCK", "0") == "1"

# ---------------------------------------------------------------------------
# CLIENT CONFIGURATION & TAXONOMY
# ---------------------------------------------------------------------------
CLIENT_CONFIGS = {
    "default": {
        "display_name": "General Consumer Feedback",
        "categories": [
            "Product Quality",
            "Pricing",
            "Availability",
            "Customer Service",
            "Packaging",
            "Other",
        ],
    },
    "fmcg_beverage": {
        "display_name": "Beverage Brand Client",
        "categories": [
            "Taste/Formulation",
            "Packaging Leakage/Damage",
            "Stockout/Availability",
            "Price Inconsistency",
            "Counterfeit Suspected",
            "Other",
        ],
    },
    "retail_chain": {
        "display_name": "Supermarket/Retail Client",
        "categories": [
            "Long Checkout Queues",
            "Expired Stock",
            "Mislabeled Pricing",
            "Staff Behavior",
            "Facility Cleanliness",
            "Other",
        ],
    },
}

URGENCY_LEVELS = ["High", "Medium", "Low"]

KENYA_COUNTIES = [
    "Mombasa", "Kwale", "Kilifi", "Tana River", "Lamu", "Taita-Taveta",
    "Garissa", "Wajir", "Mandera", "Marsabit", "Isiolo", "Meru",
    "Tharaka-Nithi", "Embu", "Kitui", "Machakos", "Makueni", "Nyandarua",
    "Nyeri", "Kirinyaga", "Murang'a", "Kiambu", "Turkana", "West Pokot",
    "Samburu", "Trans Nzoia", "Uasin Gishu", "Elgeyo-Marakwet", "Nandi",
    "Baringo", "Laikipia", "Nakuru", "Narok", "Kajiado", "Kericho",
    "Bomet", "Kakamega", "Vihiga", "Bungoma", "Busia", "Siaya",
    "Kisumu", "Homa Bay", "Migori", "Kisii", "Nyamira", "Nairobi",
]

_KENYA_COUNTIES_SORTED = sorted(KENYA_COUNTIES, key=len, reverse=True)

_TRANSLATION_HINTS = {
    "bei": "price", "ghali": "expensive", "haribika": "damaged/spoiled",
    "mbaya": "bad", "hakuna": "out of stock/missing", "duka": "store/shop",
    "dawa": "medicine", "watoto": "children", "afya": "health/safety",
    "kuhara": "diarrhea/illness", "chupa": "bottle", "vunjika": "broken",
    "fake": "counterfeit", "mwizi": "theft/overcharging",
}


def get_client_config(client_id: str = "default") -> dict:
    """Returns the category taxonomy for a given client, falling back to default."""
    return CLIENT_CONFIGS.get(client_id, CLIENT_CONFIGS["default"])


def _extract_county(text: str) -> str:
    """Extracts a Kenyan county from text using simple rule matching."""
    text_lower = text.lower()
    for county in _KENYA_COUNTIES_SORTED:
        if county.lower() in text_lower:
            return county
    return "Unspecified"


def _get_client():
    """Lazily creates the Google GenAI client. Returns None if key missing -> triggers mock mode."""
    if FORCE_MOCK or not GOOGLE_API_KEY:
        return None
    try:
        from google import genai
        return genai.Client(api_key=GOOGLE_API_KEY)
    except Exception as e:
        print(f"[gemma_client] Could not init Gemma client, falling back to mock mode: {e}")
        return None


def _build_system_prompt(client_config: dict) -> str:
    categories_str = ", ".join(client_config["categories"])
    return f"""You are an organic consumer voice structuring and fraud detection engine for enterprise market research in Kenya.
Consumers submit unsolicited audio, text, or visual feedback regarding product experiences.

Your job: read the input and call the `structure_complaint` function with:
- category: must be strictly chosen from this client's taxonomy: [{categories_str}]
- urgency: 'High' (health/safety/quality risk, severe brand hazard), 'Medium', or 'Low'
- county: the Kenyan county or major town mentioned (if none, use 'Unspecified')
- english_summary: a crisp, neutral, single-sentence English summary suitable for an executive dashboard.
- authenticity_score: a float between 0.0 and 1.0 evaluating human origin. Look for local context, conversational Swahili/Sheng, natural imperfections, or specific details.
- is_flagged_synthetic: boolean set to True if the input appears to be generated by an AI persona, synthetic script, or overly polished corporate boilerplate lacking genuine human markers.
- defamation_flag: boolean set to True if the feedback consists of unverified, exaggerated slander or coordinated smear language lacking verifiable details like store name, purchase receipt, or batch.
"""


def _get_function_schema(client_config: dict) -> dict:
    """Dynamically builds the function declaration schema based on client categories and anti-fraud fields."""
    return {
        "name": "structure_complaint",
        "description": "Structures raw consumer feedback into a standard record with fraud/authenticity signals.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": client_config["categories"],
                },
                "urgency": {
                    "type": "string",
                    "enum": URGENCY_LEVELS,
                },
                "county": {"type": "string"},
                "english_summary": {"type": "string"},
                "authenticity_score": {
                    "type": "number",
                    "description": "Score between 0.0 (synthetic/AI) and 1.0 (authentic human input).",
                },
                "is_flagged_synthetic": {
                    "type": "boolean",
                    "description": "True if likely produced by an AI persona or automated script.",
                },
                "defamation_flag": {
                    "type": "boolean",
                    "description": "True if likely bad-faith slander or paid product defamation.",
                },
            },
            "required": [
                "category", "urgency", "county", "english_summary", 
                "authenticity_score", "is_flagged_synthetic", "defamation_flag"
            ],
        },
    }


def _looks_degenerate(text: str) -> bool:
    """Detects repetition-loop garbage output."""
    words = text.split()
    if len(words) < 8:
        return False
    _, count = Counter(words).most_common(1)[0]
    return count / len(words) > 0.3


def _rough_translate(text: str) -> str:
    words = text.split()
    translated = [_TRANSLATION_HINTS.get(w.strip(".,!").lower(), w) for w in words]
    summary = " ".join(translated)[:200].strip()
    return summary if summary else "Consumer feedback submitted for review."


def _mock_classify(raw_text: str, client_id: str = "default") -> dict:
    """Rule-based stand-in for Gemma when live API access is unavailable."""
    config = get_client_config(client_id)
    text_lower = raw_text.lower()
    categories = config["categories"]

    if any(w in text_lower for w in ["bei", "price", "expensive", "cost"]):
        category = "Pricing" if "Pricing" in categories else categories[0]
    elif any(w in text_lower for w in ["haribika", "damaged", "broken", "quality", "taste", "smell", "photo", "image"]):
        category = "Product Quality" if "Product Quality" in categories else categories[0]
    elif any(w in text_lower for w in ["hakuna", "out of stock", "missing", "store", "voice"]):
        category = "Availability" if "Availability" in categories else categories[0]
    else:
        category = "Other" if "Other" in categories else categories[-1]

    urgency = "High" if any(w in text_lower for w in ["danger", "sick", "fake", "emergency"]) else "Medium"
    
    # Mock detection rules
    is_synthetic = "as an ai" in text_lower or (len(raw_text) > 300 and "furthermore" in text_lower)
    defamation = "worst product ever made" in text_lower or ("do not buy" in text_lower and "scam" in text_lower)
    auth_score = 0.25 if is_synthetic else (0.40 if defamation else 0.88)

    return {
        "category": category,
        "urgency": urgency,
        "county": _extract_county(raw_text),
        "english_summary": _rough_translate(raw_text),
        "authenticity_score": auth_score,
        "is_flagged_synthetic": is_synthetic,
        "defamation_flag": defamation,
    }


def _invoke_gemma_classification(client, contents, client_config: dict) -> dict | None:
    """Shared execution helper for calling Gemma function calling safely."""
    try:
        from google.genai import types

        schema = _get_function_schema(client_config)
        tool = types.Tool(function_declarations=[types.FunctionDeclaration(**schema)])
        config = types.GenerateContentConfig(
            system_instruction=_build_system_prompt(client_config),
            tools=[tool],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY
                )
            ),
            temperature=0.2,
            max_output_tokens=400,
        )
        response = client.models.generate_content(
            model=GEMMA_MODEL,
            contents=contents,
            config=config,
        )

        if response.function_calls:
            result = dict(response.function_calls[0].args)
            if _looks_degenerate(result.get("english_summary", "")):
                print("[gemma_client] Degenerate output detected, falling back to mock")
                return None
            return result
        else:
            print("[gemma_client] No function call returned by model, falling back to mock.")
            return None

    except Exception as e:
        print(f"[gemma_client] Live classification failed: {e}")
        return None


def _apply_quarantine_rules(result: dict) -> dict:
    """Quarantines suspicious AI persona complaints or bad-faith slander records."""
    is_synthetic = result.get("is_flagged_synthetic", False)
    defamation = result.get("defamation_flag", False)
    auth_score = float(result.get("authenticity_score", 1.0))

    if is_synthetic or defamation or auth_score < 0.45:
        result["status"] = "Quarantined"
    else:
        result.setdefault("status", "Open")

    return result


def classify_complaint(raw_text: str, client_id: str = "default") -> dict:
    client = _get_client()
    client_config = get_client_config(client_id)
    result = None

    if client is not None:
        result = _invoke_gemma_classification(client, raw_text, client_config)

    if result is None:
        result = _mock_classify(raw_text, client_id)

    result.update({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_text": raw_text,
        "client_id": client_id,
    })
    return _apply_quarantine_rules(result)


def classify_complaint_audio(audio_path: str, client_id: str = "default") -> dict:
    client = _get_client()
    client_config = get_client_config(client_id)
    result = None

    if client is not None:
        uploaded = None
        try:
            uploaded = client.files.upload(file=audio_path)
            result = _invoke_gemma_classification(client, [uploaded], client_config)
        finally:
            if uploaded is not None:
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:
                    pass

    if result is None:
        result = _mock_classify("Voice note submission regarding product quality and retail availability.", client_id)

    result.update({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_text": f"[voice note: {os.path.basename(audio_path)}]",
        "client_id": client_id,
    })
    return _apply_quarantine_rules(result)


def classify_complaint_image(image_path: str, client_id: str = "default") -> dict:
    client = _get_client()
    client_config = get_client_config(client_id)
    result = None

    if client is not None:
        uploaded = None
        try:
            uploaded = client.files.upload(file=image_path)
            result = _invoke_gemma_classification(client, [uploaded], client_config)
        finally:
            if uploaded is not None:
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:
                    pass

    if result is None:
        result = _mock_classify("Image report showing product packaging and shelf display issues.", client_id)

    result.update({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_text": f"[photo report: {os.path.basename(image_path)}]",
        "client_id": client_id,
    })
    return _apply_quarantine_rules(result)


def _mock_action_brief(df) -> str:
    county = df["county"].mode().iloc[0] if not df.empty and "county" in df.columns else "Unspecified"
    category = df["category"].mode().iloc[0] if not df.empty and "category" in df.columns else "General"
    count = len(df)
    summaries = "\n".join(f"- {s}" for s in df["english_summary"].head(5))

    return f"""EXECUTIVE BRAND ACTION BRIEF

To: Quality Assurance & Brand Insights Team
County Focus: {county}
Primary Alert Category: {category}
Date: {datetime.now(timezone.utc).strftime('%d %B %Y')}

1. EXECUTIVE SUMMARY
This real-time feedback summary is generated from {count} organic consumer report(s) 
ingested via the Sauti-Yetu streaming engine, pointing to an active {category.lower()} pattern in {county} county.

2. CONSUMER EVIDENCE LOG
{summaries}

3. RECOMMENDED ACTIONS
- Initiate direct outreach or QA investigation at point-of-sale in {county}.
- Monitor social/voice sentiment over the next 48 hours for escalation.

[Auto-generated via Sauti-Yetu Streaming Engine]"""


def generate_action_brief(feedback_df) -> str:
    """Generates an executive brand response brief from aggregated consumer feedback."""
    client = _get_client()
    if client is None or feedback_df.empty:
        return _mock_action_brief(feedback_df)

    try:
        records = feedback_df[["category", "county", "urgency", "english_summary"]].to_dict("records")
        prompt = (
            "Using the consumer feedback records below, generate a formal Executive Brand Action Brief "
            "suitable for brand managers and market research teams. Include sections: "
            "Executive Summary, Consumer Evidence Log, and Recommended Actions.\n\n"
            f"Records:\n{json.dumps(records, indent=2)}"
        )
        response = client.models.generate_content(model=GEMMA_MODEL, contents=prompt)
        return response.text
    except Exception as e:
        print(f"[gemma_client] Live action brief generation failed, using mock: {e}")
        return _mock_action_brief(feedback_df)