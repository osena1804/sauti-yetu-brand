import os
import time

from google import genai
from google.genai import types

# Same model list, time budget, and retry pattern as scoring.py, so voice
# transcription behaves consistently with complaint scoring.
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

TRANSCRIBE_PROMPT = (
    "Transcribe this voice complaint verbatim. The speaker may use English, Swahili, "
    "Sheng, or a mix of these. Output only the transcription in the language(s) spoken "
    "- no translation, no commentary, no added interpretation."
)


def _is_transient(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker.lower() in message for marker in TRANSIENT_MARKERS)


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav"):
    """Transcribes a short voice note via Gemini. Returns (text, error): text is
    None if every model/attempt failed within the time budget, with error holding
    the last failure so the caller can fall back to asking the user to type."""
    deadline = time.monotonic() + AI_BUDGET_SECONDS
    last_error = "no models configured"

    try:
        client = genai.Client(http_options=types.HttpOptions(timeout=int(AI_BUDGET_SECONDS * 1000)))
    except Exception:
        try:
            client = genai.Client()
        except Exception as e:
            return None, f"client setup failed: {e}"

    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)

    for model in MODELS:
        for attempt in range(ATTEMPTS_PER_MODEL):
            if time.monotonic() >= deadline:
                return None, f"time budget exceeded; last error: {last_error}"
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[TRANSCRIBE_PROMPT, audio_part],
                )
                text = (response.text or "").strip()
                if not text:
                    last_error = f"{model}: empty transcription"
                    break
                return text, None
            except Exception as e:
                last_error = f"{model}: {e}"
                if not _is_transient(e):
                    break
                remaining_time = max(0.0, deadline - time.monotonic())
                time.sleep(min(1.5 * (2 ** attempt), remaining_time))

    return None, last_error