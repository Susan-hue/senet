import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


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
    department_id = models.UUIDField(null=True, blank=True)
    faculty_id = models.UUIDField(null=True, blank=True)
    identifier = models.CharField(max_length=50, blank=True, default="")

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
