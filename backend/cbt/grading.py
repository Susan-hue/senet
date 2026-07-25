"""Pure, server-side scoring for objective questions.

No request, no ORM writes — just ``(question, stored_response) -> outcome`` so the
rules can be unit-tested directly. ``grade_answer`` returns ``None`` for questions
that need a human (short answer); callers queue those for the lecturer.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from cbt.models import QuestionType

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value):
    """Case- and whitespace-insensitive normalization for text matching."""
    if value is None:
        return ""
    return _WHITESPACE.sub(" ", str(value).strip().lower())


@dataclass(frozen=True)
class Outcome:
    is_correct: bool
    awarded_marks: Decimal


def grade_answer(question, response):
    """Grade one objective answer. Returns an ``Outcome`` for objective types, or
    ``None`` if the question must be graded by a human.

    ``response`` is the *stored* answer form (original option indices for choice
    questions), so grading does not depend on the per-student display order. A
    missing/blank ``response`` scores zero, never an exception.
    """
    if question.type == QuestionType.SHORT_ANSWER:
        return None

    marks = Decimal(question.marks)
    correct = _is_correct(question, response)
    return Outcome(is_correct=correct, awarded_marks=marks if correct else Decimal("0"))


def _is_correct(question, response):
    qtype = question.type
    key = question.correct_answer

    if qtype == QuestionType.MCQ:
        return isinstance(response, int) and response == key

    if qtype == QuestionType.MULTI:
        if not isinstance(response, list) or not isinstance(key, list):
            return False
        # Exact set match — every correct option and no incorrect ones.
        return {int(i) for i in response} == {int(i) for i in key}

    if qtype == QuestionType.TRUE_FALSE:
        return isinstance(response, bool) and response is bool(key)

    if qtype == QuestionType.FILL_BLANK:
        accepted = {normalize_text(a) for a in (key or [])}
        return normalize_text(response) in accepted if response not in (None, "") else False

    return False
