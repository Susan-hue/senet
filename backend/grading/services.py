"""The GPA/CGPA engine. Quality-points method, all rules from institution
config. This is the most correctness-sensitive code in the system: everything
is Decimal, rounding is explicit (2 dp, half-up), and only results in the
institution's configured source state (senate-ratified by default) count.
"""

from decimal import ROUND_HALF_UP, Decimal

from grading.scales import points_for_letter
from results.models import StudentScore

TWO_DP = Decimal("0.01")

ALL_ATTEMPTS = "ALL_ATTEMPTS"
HIGHEST_ONLY = "HIGHEST_ONLY"


def _round(value):
    return value.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def official_rows(student):
    """The student's official transcript rows: current score rows whose result
    sheet is in the institution's configured GPA source state."""
    institution = student.institution
    return (
        StudentScore.all_objects.filter(
            institution=institution,
            student=student,
            is_current=True,
            result__status=institution.gpa_source_status,
        )
        .select_related("result__course", "result__session", "result__semester")
        .order_by("result__session__start_date", "result__semester__start_date", "created_at")
    )


def _course_line(row, institution):
    course = row.result.course
    points = points_for_letter(institution, row.grade)
    units = course.credit_units
    return {
        "course": str(course.id),
        "course_code": course.code,
        "credit_units": units,
        "total_score": str(row.total),
        "grade": row.grade,
        "grade_points": str(points),
        "quality_points": str(_round(Decimal(units) * points)),
    }


def _totals(rows, institution):
    quality_points = Decimal("0")
    credit_units = 0
    for row in rows:
        units = row.result.course.credit_units
        quality_points += Decimal(units) * points_for_letter(institution, row.grade)
        credit_units += units
    return quality_points, credit_units


def _gpa(quality_points, credit_units):
    if credit_units == 0:
        return None
    return _round(quality_points / Decimal(credit_units))


def term_summary(student, session, semester):
    institution = student.institution
    rows = list(official_rows(student).filter(result__session=session, result__semester=semester))
    quality_points, credit_units = _totals(rows, institution)
    return {
        "session": str(session.id),
        "semester": str(semester.id),
        "courses": [_course_line(row, institution) for row in rows],
        "quality_points": str(_round(quality_points)),
        "credit_units": credit_units,
        "gpa": _gpa(quality_points, credit_units),
    }


def _attempts_by_course(rows):
    attempts = {}
    for row in rows:
        attempts.setdefault(row.result.course_id, []).append(row)
    return attempts


def _best_attempt(attempts, institution):
    return max(
        attempts,
        key=lambda row: (points_for_letter(institution, row.grade), row.total, row.created_at),
    )


def outstanding_carryovers(student):
    """Courses whose best official attempt is still below the carryover pass
    mark — the student's unresolved carryover list."""
    institution = student.institution
    pass_mark = institution.carryover_pass_mark
    outstanding = []
    for attempts in _attempts_by_course(list(official_rows(student))).values():
        best = _best_attempt(attempts, institution)
        if best.total < pass_mark:
            course = best.result.course
            outstanding.append({"code": course.code, "title": course.title})
    outstanding.sort(key=lambda c: c["code"])
    return outstanding


def cumulative_summary(student):
    institution = student.institution
    rows = list(official_rows(student))
    method = institution.carryover_cgpa_method

    if method == HIGHEST_ONLY:
        counted = [
            _best_attempt(attempts, institution) for attempts in _attempts_by_course(rows).values()
        ]
    else:
        counted = rows

    quality_points, credit_units = _totals(counted, institution)
    return {
        "method": method,
        "quality_points": str(_round(quality_points)),
        "credit_units": credit_units,
        "cgpa": _gpa(quality_points, credit_units),
    }


def standing_for(institution, cgpa):
    if cgpa is None:
        return ""
    if cgpa < institution.withdrawal_cgpa_threshold:
        return "withdrawal"
    if cgpa < institution.probation_cgpa_threshold:
        return "probation"
    return "good"


def classify(institution, cgpa):
    """Degree classification plus the Senate-review borderline flag. The flag
    never changes the classification — it only marks the case for review."""
    if cgpa is None:
        return {"name": None, "is_borderline": False, "borderline_band": None}

    bands = sorted(
        (
            (Decimal(str(band["min_cgpa"])), band["name"])
            for band in institution.classification_bands
        ),
        key=lambda band: band[0],
        reverse=True,
    )
    name = "Fail"
    for min_cgpa, band_name in bands:
        if cgpa >= min_cgpa:
            name = band_name
            break

    margin = institution.senate_review_margin
    for min_cgpa, band_name in bands:
        if min_cgpa - margin <= cgpa < min_cgpa:
            return {"name": name, "is_borderline": True, "borderline_band": band_name}
    return {"name": name, "is_borderline": False, "borderline_band": None}


def student_summary(student, session=None, semester=None):
    """Everything the standing endpoints and the department task need."""
    institution = student.institution
    cumulative = cumulative_summary(student)
    cgpa = cumulative["cgpa"]
    classification = classify(institution, cgpa)
    return {
        "student": str(student.id),
        "student_name": student.full_name,
        "term": (
            term_summary(student, session, semester)
            if session is not None and semester is not None
            else None
        ),
        "cumulative": cumulative,
        "standing": standing_for(institution, cgpa),
        "classification": classification,
        "outstanding_carryovers": outstanding_carryovers(student),
    }
