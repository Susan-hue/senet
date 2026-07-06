from celery import shared_task

from accounts.models import Department, Role, Semester, Session, User
from grading.models import AcademicStanding
from grading.services import student_summary


@shared_task
def compute_department_standing(department_id, session_id, semester_id):
    """Compute and persist GPA/CGPA/standing for every student in a department
    for a term. Heavy by design, so it runs on the worker, not in the request."""
    department = Department.all_objects.select_related("institution").get(pk=department_id)
    institution = department.institution
    session = Session.all_objects.get(pk=session_id, institution=institution)
    semester = Semester.all_objects.get(pk=semester_id, institution=institution)

    computed = 0
    students = User.objects.filter(
        institution=institution, department=department, role=Role.STUDENT, is_active=True
    )
    for student in students.iterator():
        summary = student_summary(student, session, semester)
        term = summary["term"]
        cumulative = summary["cumulative"]
        classification = summary["classification"]
        AcademicStanding.all_objects.update_or_create(
            student=student,
            session=session,
            semester=semester,
            defaults={
                "institution": institution,
                "term_quality_points": term["quality_points"],
                "term_credit_units": term["credit_units"],
                "gpa": term["gpa"],
                "cumulative_quality_points": cumulative["quality_points"],
                "cumulative_credit_units": cumulative["credit_units"],
                "cgpa": cumulative["cgpa"],
                "standing": summary["standing"],
                "classification": classification["name"] or "",
                "is_borderline": classification["is_borderline"],
                "borderline_band": classification["borderline_band"] or "",
                "outstanding_carryovers": summary["outstanding_carryovers"],
            },
        )
        computed += 1
    return computed
