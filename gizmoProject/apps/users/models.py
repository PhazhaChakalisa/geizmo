from django.contrib.auth.models import AbstractUser
from django.db import models


ROLE_CHOICES = [
    ('student',  'Student'),
    ('lecturer', 'Lecturer'),
    ('admin',    'Admin'),
]


class GizmoUser(AbstractUser):
    email             = models.EmailField(unique=True)
    role              = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    student_id        = models.CharField(max_length=20, blank=True)
    phone_country     = models.CharField(max_length=10, blank=True)
    phone_number      = models.CharField(max_length=20, blank=True)
    is_approved       = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    profile_photo     = models.ImageField(upload_to='profiles/', blank=True, null=True)
    university_name   = models.CharField(max_length=200, blank=True)  # stores department for lecturers
    created_at        = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']


class OTPCode(models.Model):
    user       = models.ForeignKey(GizmoUser, on_delete=models.CASCADE, related_name='otp_codes')
    code       = models.CharField(max_length=6)
    purpose    = models.CharField(max_length=20, default='signup')
    created_at = models.DateTimeField(auto_now_add=True)
    is_used    = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']


class Course(models.Model):
    STATUS_CHOICES = [('active', 'Active'), ('archived', 'Archived')]

    code        = models.CharField(max_length=20, unique=True)
    name        = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    department  = models.CharField(max_length=200, blank=True)
    lecturer    = models.ForeignKey(
        GizmoUser, on_delete=models.SET_NULL, null=True,
        related_name='courses_taught', limit_choices_to={'role': 'lecturer'}
    )
    semester    = models.CharField(max_length=50, blank=True)
    academic_year = models.CharField(max_length=20, blank=True)
    credit_hours  = models.PositiveSmallIntegerField(default=3)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} — {self.name}'

    @property
    def enrolled_count(self):
        return self.enrolments.count()


class Enrolment(models.Model):
    student   = models.ForeignKey(
        GizmoUser, on_delete=models.CASCADE, related_name='enrolments',
        limit_choices_to={'role': 'student'}
    )
    course    = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrolments')
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'course')
        ordering = ['-enrolled_at']

    def __str__(self):
        return f'{self.student.email} → {self.course.code}'


class SiteSettings(models.Model):
    """Singleton model — always use SiteSettings.get()"""
    maintenance_mode = models.BooleanField(default=False)
    maintenance_message = models.TextField(
        default='GIZMO is currently undergoing scheduled maintenance. We will be back shortly.'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Site Settings'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f'Site Settings (maintenance={self.maintenance_mode})'


# ─────────────────────────────────────────────────────────────
#  TEACHER CONTENT MODELS
# ─────────────────────────────────────────────────────────────

class PastPaper(models.Model):
    PERIOD_CHOICES = [
        ('midterm1', 'Midterm 1'), ('midterm2', 'Midterm 2'),
        ('final', 'Final Exam'), ('supplementary', 'Supplementary'),
    ]
    course       = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='papers')
    uploaded_by  = models.ForeignKey(GizmoUser, on_delete=models.CASCADE, related_name='papers_uploaded')
    title        = models.CharField(max_length=200)
    period       = models.CharField(max_length=20, choices=PERIOD_CHOICES, blank=True)
    academic_year = models.CharField(max_length=20, blank=True)
    total_marks  = models.PositiveIntegerField(default=100)
    duration_mins = models.PositiveIntegerField(default=120)
    num_questions = models.PositiveIntegerField(default=0)   # number of questions in the paper
    notes        = models.TextField(blank=True)
    file         = models.FileField(upload_to='papers/', blank=True, null=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.course.code} — {self.title}'


class ModelAnswer(models.Model):
    paper        = models.ForeignKey(PastPaper, on_delete=models.CASCADE, related_name='answers')
    question_ref = models.CharField(max_length=100, blank=True)  # e.g. "Q1(a)"
    topic        = models.CharField(max_length=200, blank=True)
    answer_text  = models.TextField()
    key_points   = models.TextField(blank=True)   # newline-separated
    marks        = models.PositiveIntegerField(default=0)
    criteria     = models.TextField(blank=True)
    file         = models.FileField(upload_to='answers/', blank=True, null=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Textbook(models.Model):
    courses   = models.ManyToManyField(Course, related_name='textbooks', blank=True)
    uploaded_by = models.ForeignKey(GizmoUser, on_delete=models.CASCADE, related_name='textbooks_uploaded')
    title     = models.CharField(max_length=300)
    authors   = models.CharField(max_length=300, blank=True)
    edition   = models.CharField(max_length=100, blank=True)
    isbn      = models.CharField(max_length=30, blank=True)
    chapters  = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    file      = models.FileField(upload_to='textbooks/')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class StudyMaterial(models.Model):
    TYPE_CHOICES = [
        ('lecture', 'Lecture Slides'), ('notes', 'Notes'),
        ('video', 'Video'), ('code', 'Code'), ('other', 'Other'),
    ]
    course      = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='materials')
    uploaded_by = models.ForeignKey(GizmoUser, on_delete=models.CASCADE, related_name='materials_uploaded')
    title       = models.CharField(max_length=200)
    material_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='other')
    description = models.TextField(blank=True)
    file        = models.FileField(upload_to='materials/')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Submission(models.Model):
    student     = models.ForeignKey(GizmoUser, on_delete=models.CASCADE, related_name='submissions')
    paper       = models.ForeignKey(PastPaper, on_delete=models.CASCADE, related_name='submissions')
    answer      = models.ForeignKey(ModelAnswer, on_delete=models.SET_NULL, null=True, blank=True, related_name='submissions')
    answer_text = models.TextField(blank=True)
    file        = models.FileField(upload_to='submissions/', blank=True, null=True)
    score       = models.FloatField(null=True, blank=True)
    feedback    = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    # ── Active Learning fields ────────────────────────────────
    flagged_for_dataset  = models.BooleanField(default=False)  # AI flagged as high-quality
    dataset_approved     = models.BooleanField(null=True, blank=True)  # None=pending, True=approved, False=rejected
    dataset_reviewed_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-submitted_at']


class StudentExemplar(models.Model):
    """A real past student answer that the teacher marks as exemplary."""
    paper        = models.ForeignKey(PastPaper,   on_delete=models.CASCADE, related_name='exemplars')
    answer_ref   = models.ForeignKey('ModelAnswer', on_delete=models.SET_NULL, null=True, blank=True, related_name='exemplars')
    added_by     = models.ForeignKey(GizmoUser,   on_delete=models.CASCADE, related_name='exemplars_added')
    student_name = models.CharField(max_length=200, blank=True)  # anonymised display name
    year         = models.CharField(max_length=20, blank=True)
    question_ref = models.CharField(max_length=100, blank=True)
    content_text = models.TextField(blank=True)
    file         = models.FileField(upload_to='exemplars/', blank=True, null=True)
    score        = models.FloatField(null=True, blank=True)   # mark awarded
    total_marks  = models.PositiveIntegerField(default=0)
    commentary   = models.TextField(blank=True)  # teacher notes on why this is good
    is_visible   = models.BooleanField(default=True)  # toggle student visibility
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Exemplar: {self.paper.course.code} — {self.question_ref}'


class AITrainingLog(models.Model):
    """Persists each training run result — shown on dashboards."""
    report_json       = models.TextField()
    confidence_score  = models.IntegerField(default=0)
    confidence_label  = models.CharField(max_length=100, blank=True)
    n_model_answers   = models.IntegerField(default=0)
    n_key_points      = models.IntegerField(default=0)
    n_exemplars       = models.IntegerField(default=0)
    n_graded_subs     = models.IntegerField(default=0)
    mae               = models.FloatField(default=0.0)
    pearson_r         = models.FloatField(default=0.0)
    grade_band_acc    = models.FloatField(default=0.0)
    similarity_method = models.CharField(max_length=30, default='tfidf')
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"AI Training — {self.created_at.strftime('%Y-%m-%d %H:%M')} — {self.confidence_score}% confidence"