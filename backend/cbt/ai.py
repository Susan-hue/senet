"""AI question generation behind a single, swappable provider interface.

The rest of the app calls ``generate_draft_questions`` / ``get_provider`` and never
touches Grok directly. Only the lecturer's own notes/topic are ever sent — no
student data. Output is DRAFT only: it is never written to a bank here.
"""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from rest_framework.exceptions import ValidationError

from cbt.models import QuestionType
from cbt.services import _validate_question_payload

logger = logging.getLogger(__name__)


class AIProviderError(Exception):
    """Any failure talking to the AI provider — surfaced to the caller as a clean
    error, never a 500, and never allowed to break exam creation."""


class QuestionGenerationProvider:
    def generate(self, *, notes, count, question_types):
        raise NotImplementedError


class GrokProvider(QuestionGenerationProvider):
    def __init__(self, *, api_key, api_url, model, timeout):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.timeout = timeout

    def generate(self, *, notes, count, question_types):
        if not self.api_key:
            raise AIProviderError("AI question generation is not configured.")
        if not self.api_url.startswith("https://"):
            raise AIProviderError("AI provider URL must be https.")
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": _build_messages(notes, count, question_types),
        }
        return _extract_questions(self._post(payload))

    def _post(self, payload):
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise AIProviderError(
                    "The AI provider is rate-limited right now. Please try again shortly."
                ) from exc
            raise AIProviderError(
                "The AI provider returned an error. Please try again later."
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AIProviderError(
                "The AI provider is unavailable. Please try again later."
            ) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise AIProviderError("The AI provider returned an unreadable response.") from exc


def _build_messages(notes, count, question_types):
    types = ", ".join(question_types)
    system = (
        "You are an assessment author. Generate exam questions strictly as JSON. "
        'Return a JSON object {"questions": [...]}. Each question object has: '
        '"type" (one of mcq, multi, true_false, fill_blank, short_answer), '
        '"prompt" (string), "options" (list of strings for mcq/multi, else []), '
        '"correct_answer" (integer index for mcq; list of indices for multi; '
        "boolean for true_false; list of accepted strings for fill_blank; null for "
        'short_answer), and "marks" (number). Base the questions only on the '
        "material provided."
    )
    user = (
        f"Create {count} question(s) of type(s): {types}. "
        f"Base them strictly on this material:\n\n{notes}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _extract_questions(data):
    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AIProviderError("The AI provider returned an unexpected response.") from exc
    questions = parsed.get("questions") if isinstance(parsed, dict) else parsed
    if not isinstance(questions, list):
        raise AIProviderError("The AI provider returned no questions.")
    return questions


def get_provider():
    """The configured provider. Swappable — the app only depends on this factory
    and the ``QuestionGenerationProvider`` interface."""
    return GrokProvider(
        api_key=settings.GROK_API_KEY,
        api_url=settings.GROK_API_URL,
        model=settings.GROK_MODEL,
        timeout=settings.GROK_TIMEOUT_SECONDS,
    )


def generate_draft_questions(*, notes, count, question_types):
    """Return DRAFT questions from the provider, normalized to the bank-question
    shape. Nothing is persisted; malformed drafts are dropped.

    Dropping every draft is a provider failure, not an empty result: the caller
    is told so rather than being handed an empty preview under a success
    message."""
    count = min(count, settings.CBT_AI_MAX_QUESTIONS)
    raw_questions = get_provider().generate(notes=notes, count=count, question_types=question_types)
    drafts = []
    for raw in raw_questions:
        draft = _normalize_draft(raw)
        if draft is not None:
            drafts.append(draft)
    dropped = len(raw_questions) - len(drafts)
    if dropped:
        logger.warning("Dropped %s of %s malformed AI drafts", dropped, len(raw_questions))
    if raw_questions and not drafts:
        raise AIProviderError("The AI provider returned no usable questions. Please try again.")
    return drafts


def _normalize_draft(raw):
    if not isinstance(raw, dict):
        return None
    qtype = raw.get("type")
    prompt = raw.get("prompt")
    if qtype not in QuestionType.values or not prompt:
        return None
    try:
        marks = float(raw.get("marks") or 1)
    except (TypeError, ValueError):
        marks = 1.0
    if marks <= 0:
        marks = 1.0
    try:
        options, correct, requires_manual = _validate_question_payload(
            qtype, raw.get("options") or [], raw.get("correct_answer")
        )
    except ValidationError:
        return None
    return {
        "type": qtype,
        "prompt": str(prompt),
        "options": options,
        "correct_answer": correct,
        "marks": round(marks, 2),
        "requires_manual_grading": requires_manual,
    }
