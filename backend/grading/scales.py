"""Institution-configured grade scale lookups.

Kept free of imports from the results app so results can use these helpers
without a circular dependency.
"""

from decimal import Decimal


def scale_bands(institution):
    """Grade bands sorted highest boundary first: (min_score, grade, points)."""
    bands = [
        (Decimal(str(row["min_score"])), row["grade"], Decimal(str(row["points"])))
        for row in institution.grade_scale
    ]
    bands.sort(key=lambda band: band[0], reverse=True)
    return bands


def grade_for_score(institution, score):
    """(letter, points) for a total score on the institution's scale."""
    score = Decimal(score)
    bands = scale_bands(institution)
    for min_score, letter, points in bands:
        if score >= min_score:
            return letter, points
    min_score, letter, points = bands[-1]
    return letter, points


def points_for_letter(institution, letter):
    for row in institution.grade_scale:
        if row["grade"] == letter:
            return Decimal(str(row["points"]))
    return Decimal("0")
