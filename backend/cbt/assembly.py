"""Per-student exam assembly.

Called once, when a student starts an attempt, to draw the configured number of
questions from the exam's banks and fix a per-student order — both question order
and (for choice questions) option order. The result is persisted as
``AttemptQuestion`` rows so the paper is identical on every reload.

Randomness uses ``secrets.SystemRandom`` rather than the ``random`` module: exam
ordering is an integrity concern, and an unpredictable source is both safer and
keeps static analysis clean.
"""

import secrets

from rest_framework.exceptions import ValidationError

from cbt.models import AttemptQuestion, Question

_rng = secrets.SystemRandom()


def bank_question_pool(exam):
    """All questions available to ``exam`` across its banks, as a stable list.

    Uses ``all_objects`` with an explicit join (``bank__exams``) rather than the
    scoped ``exam.banks`` accessor, so the pool resolves correctly off the request
    path (Celery, tests) where no tenant is bound to the thread."""
    return list(
        Question.all_objects.filter(institution_id=exam.institution_id, bank__exams=exam).order_by(
            "created_at", "id"
        )
    )


def assemble_attempt_questions(attempt, exam):
    """Draw and persist the frozen paper for ``attempt``.

    Selection is always a random sample of ``num_questions`` from the pool (that
    is the point of a bank). ``shuffle_questions`` controls whether the drawn set
    is presented in random order or a canonical one; ``shuffle_options`` controls
    per-question option order. Idempotent per attempt: rows are only created if the
    attempt has none yet.
    """
    if AttemptQuestion.all_objects.filter(attempt=attempt).exists():
        return

    pool = bank_question_pool(exam)
    if len(pool) < exam.num_questions:
        raise ValidationError(
            {
                "num_questions": (
                    f"This exam needs {exam.num_questions} questions but its banks "
                    f"only hold {len(pool)}."
                )
            }
        )

    drawn = _rng.sample(pool, exam.num_questions)
    if not exam.shuffle_questions:
        drawn.sort(key=lambda q: (q.created_at, str(q.id)))

    rows = []
    for position, question in enumerate(drawn):
        rows.append(
            AttemptQuestion(
                institution_id=attempt.institution_id,
                attempt=attempt,
                question=question,
                position=position,
                option_order=_option_order(question, exam.shuffle_options),
            )
        )
    AttemptQuestion.all_objects.bulk_create(rows)


def _option_order(question, shuffle_options):
    """Display->original index map for a question's options.

    Identity order for non-choice questions or when shuffling is off; a random
    permutation of the option indices otherwise.
    """
    if not question.is_choice:
        return []
    order = list(range(len(question.options or [])))
    if shuffle_options:
        _rng.shuffle(order)
    return order
