import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models

from tenancy.models import TimeStampedUUIDModel
from tenancy.scoping import TenantScopedModel


class Role(models.TextChoices):
    SUPER_ADMIN = "super_admin", "Super Admin"
    SCHOOL_ADMIN = "school_admin", "School Admin"
    DEAN = "dean", "Dean"
    HOD = "hod", "HOD"
    EXAM_OFFICER = "exam_officer", "Exam Officer"
    LECTURER = "lecturer", "Lecturer"
    COURSE_ADVISER = "course_adviser", "Course Adviser"
    SENATE_ADMIN = "senate_admin", "Senate Administrator"
    STUDENT = "student", "Student"
    COURSE_REP = "course_rep", "Course Rep"


class Level(models.IntegerChoices):
    L100 = 100, "100 Level"
    L200 = 200, "200 Level"
    L300 = 300, "300 Level"
    L400 = 400, "400 Level"
    L500 = 500, "500 Level"
    L600 = 600, "600 Level"


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("role", Role.SUPER_ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_verified", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200)
    role = models.CharField(max_length=20, choices=Role.choices)

    institution = models.ForeignKey(
        "tenancy.Institution",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )

    faculty = models.ForeignKey(
        "accounts.Faculty",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    department = models.ForeignKey(
        "accounts.Department",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    identifier = models.CharField(max_length=50, blank=True, default="")

    rank = models.CharField(max_length=100, blank=True, default="")
    current_level = models.PositiveSmallIntegerField(choices=Level.choices, null=True, blank=True)

    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "accounts_user"
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} <{self.email}> ({self.role})"


class AcademicBase(TimeStampedUUIDModel, TenantScopedModel):
    """UUID primary key + timestamps + automatic tenant scoping."""

    class Meta:
        abstract = True


class Faculty(AcademicBase):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20)

    class Meta:
        db_table = "accounts_faculty"
        ordering = ["name"]
        verbose_name = "Faculty"
        verbose_name_plural = "Faculties"
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "code"], name="uniq_faculty_code_per_institution"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Department(AcademicBase):
    faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, related_name="departments")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20)

    class Meta:
        db_table = "accounts_department"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "code"], name="uniq_department_code_per_institution"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Programme(AcademicBase):
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="programmes")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20)
    degree_type = models.CharField(max_length=30, help_text="e.g. B.Eng, B.Ed, B.Sc")

    class Meta:
        db_table = "accounts_programme"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "code"], name="uniq_programme_code_per_institution"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Session(AcademicBase):
    name = models.CharField(max_length=20, help_text='e.g. "2024/2025"')
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_session"
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "name"], name="uniq_session_name_per_institution"
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.end_date <= self.start_date:
            raise ValidationError("Session end date must be after its start date.")


class Semester(AcademicBase):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="semesters")
    name = models.CharField(max_length=20, help_text='e.g. "First", "Second"')
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        db_table = "accounts_semester"
        ordering = ["start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "name"], name="uniq_semester_name_per_session"
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.session.name}"

    def clean(self):
        if self.end_date <= self.start_date:
            raise ValidationError("Semester end date must be after its start date.")


class Course(AcademicBase):
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="courses")
    code = models.CharField(max_length=20, help_text='e.g. "MTH 101"')
    title = models.CharField(max_length=200)
    credit_units = models.PositiveSmallIntegerField()
    # Year the course belongs to. Informational/organizational only; enrolment is
    # deliberately NOT constrained by level (carryovers cross levels).
    level = models.PositiveSmallIntegerField(choices=Level.choices, null=True, blank=True)
    # Null means "inherit the institution's configured default weighting".
    ca_weight = models.PositiveSmallIntegerField(null=True, blank=True)
    exam_weight = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        db_table = "accounts_course"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "code"], name="uniq_course_code_per_institution"
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.title}"

    @property
    def effective_ca_weight(self):
        if self.ca_weight is not None:
            return self.ca_weight
        return self.institution.default_ca_weight

    @property
    def effective_exam_weight(self):
        if self.exam_weight is not None:
            return self.exam_weight
        return self.institution.default_exam_weight

    def clean(self):
        has_ca = self.ca_weight is not None
        has_exam = self.exam_weight is not None
        if has_ca != has_exam:
            raise ValidationError("Provide both CA and exam weight, or neither.")
        if has_ca and self.ca_weight + self.exam_weight != 100:
            raise ValidationError("CA weight and exam weight must sum to 100.")


class Enrolment(AcademicBase):
    student = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="enrolments",
        limit_choices_to={"role": Role.STUDENT},
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="enrolments")
    session = models.ForeignKey(Session, on_delete=models.PROTECT, related_name="enrolments")
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name="enrolments")

    class Meta:
        db_table = "accounts_enrolment"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course", "session", "semester"],
                name="uniq_enrolment_per_student_course_term",
            ),
        ]

    def __str__(self):
        return f"{self.student.full_name} → {self.course.code} ({self.session.name})"


class CourseAssignment(AcademicBase):
    """Links a lecturer to a course they teach in a specific session + semester.

    The results pipeline enforces "a lecturer can only enter results for their
    assigned courses" via ``services.lecturer_can_access_course``.
    """

    lecturer = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="course_assignments",
        limit_choices_to={"role": Role.LECTURER},
    )
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="assignments")
    session = models.ForeignKey(
        Session, on_delete=models.PROTECT, related_name="course_assignments"
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.PROTECT, related_name="course_assignments"
    )

    class Meta:
        db_table = "accounts_course_assignment"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lecturer", "course", "session", "semester"],
                name="uniq_assignment_per_lecturer_course_term",
            ),
        ]

    def __str__(self):
        return f"{self.lecturer.full_name} → {self.course.code} ({self.session.name})"


class ImportJob(AcademicBase):
    class Kind(models.TextChoices):
        STUDENT = "student", "Student"
        COURSE = "course", "Course"
        ASSIGNMENT = "assignment", "Assignment"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    filename = models.CharField(max_length=255, blank=True, default="")
    total_rows = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    # Row-level failures: [{"row": <int>, "errors": [<str>, ...]}, ...]
    errors = models.JSONField(default=list, blank=True)
    message = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )

    class Meta:
        db_table = "accounts_import_job"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind} import ({self.status})"
