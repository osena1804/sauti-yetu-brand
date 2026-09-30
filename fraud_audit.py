import os
import time

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

MODELS = [
    m.strip()
    for m in os.environ.get(
        "SAUTI_MODELS", "gemini-2.5-flash,gemini-3.5-flash,gemini-3.6-flash"
    ).split(",")
    if m.strip()
]
AI_BUDGET_SECONDS = float(os.environ.get("SAUTI_AI_BUDGET_SECONDS", "12"))
ATTEMPTS_PER_MODEL = 2

TRANSIENT_MARKERS = (
    "503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded",
    "high demand", "timeout", "timed out", "deadline"
)

SYSTEM_PROMPT = """You inspect a photo submitted as evidence for a consumer complaint in Kenya.
Decide whether the image looks like a genuine photograph of a real product, receipt, or scene,
or whether it shows signs of being AI-generated or synthetically manipulated: unnatural textures,
inconsistent lighting or shadows, warped or nonsensical text/logos, implausible artifacts, or a
"too perfect" generated look.

authenticity_score: 1.0 = clearly a genuine, unedited photograph. 0.0 = clearly AI-generated or
synthetic. Use the full range for ambiguous cases.

Set is_flagged_synthetic to true only when you are reasonably confident the image is synthetic
(authenticity_score at or below 0.4). This flags the item for human review - it does not delete
or reject it.

Write a one-sentence rationale."""


class ImageAuthenticity(BaseModel):
    authenticity_score: float = Field(ge=0.0, le=1.0, description="1.0 genuine photo, 0.0 synthetic/AI-generated")
    is_flagged_synthetic: bool = Field(description="True only when reasonably confident the image is synthetic")
    rationale: str = Field(description="One sentence explaining the assessment")


def _is_transient(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker.lower() in message for marker in TRANSIENT_MARKERS)


def _fail_open(reason: str) -> dict:
    """On any failure, default to NOT flagging the photo. A broken AI check should
    never silently quarantine a genuine complaint - it should just skip this signal."""
    return {
        "authenticity_score": 1.0,
        "is_flagged_synthetic": False,
        "rationale": "AI authenticity check unavailable - not flagged by default.",
        "source": "fallback",
        "error": reason,
    }


def analyze_image_authenticity(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Runs a Gemini vision check for AI-generated/synthetic content. Fails OPEN:
    any error, timeout, or empty response returns a non-flagging result rather than
    quarantining a photo just because the AI check itself broke."""
    deadline = time.monotonic() + AI_BUDGET_SECONDS
    last_error = "no models configured"

    try:
        client = genai.Client(http_options=types.HttpOptions(timeout=int(AI_BUDGET_SECONDS * 1000)))
    except Exception:
        try:
            client = genai.Client()
        except Exception as e:
            return _fail_open(f"client setup failed: {e}")

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    for model in MODELS:
        for attempt in range(ATTEMPTS_PER_MODEL):
            if time.monotonic() >= deadline:
                return _fail_open(f"time budget exceeded; last error: {last_error}")
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[SYSTEM_PROMPT, image_part],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ImageAuthenticity,
                        temperature=0.1,
                    ),
                )
                result = ImageAuthenticity.model_validate_json(response.text)
                is_flagged_synthetic = result.is_flagged_synthetic or result.authenticity_score <= 0.4
                return {
                    "authenticity_score": round(result.authenticity_score, 2),
                    "is_flagged_synthetic": is_flagged_synthetic,
                    "rationale": result.rationale,
                    "source": "gemini",
                    "model": model,
                }
            except Exception as e:
                last_error = f"{model}: {e}"
                if not _is_transient(e):
                    break
                remaining_time = max(0.0, deadline - time.monotonic())
                time.sleep(min(1.5 * (2 ** attempt), remaining_time))

    return _fail_open(last_error)


if __name__ == "__main__":
    print("fraud_audit.py has no offline self-test (needs a real image) - "
          "test it live via the Submit a Report tab with a photo attached.")