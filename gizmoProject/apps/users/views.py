import json
import random
import string
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Q, Count, Avg
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Course, Enrolment, GizmoUser, OTPCode


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _json_body(request):
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return {}


def _generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))


def _send_otp_email(user, purpose='signup'):
    OTPCode.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)
    code = _generate_otp()
    OTPCode.objects.create(user=user, code=code, purpose=purpose)
    print(f'\n{"="*40}\n[GEIZMO OTP] {user.email} -> {code}\n{"="*40}\n')
    try:
        from .email_service import send_otp_email
        send_otp_email(user.email, code, user.first_name)
        print('[GEIZMO] Email sent successfully')
    except Exception as e:
        print(f'[GEIZMO] EMAIL FAILED: {type(e).__name__}: {e}')
    return code


def _admin_required(request):
    return request.user.is_authenticated and request.user.role == 'admin'


# ─────────────────────────────────────────────────────────────
#  LANDING
# ─────────────────────────────────────────────────────────────


def api_landing_stats(request):
    """Public endpoint — aggregate platform stats for the landing page."""
    from .models import GizmoUser, Course, PastPaper, Submission, Enrolment, ModelAnswer
    from django.utils import timezone
    from datetime import timedelta
    import json as _j

    total_students    = GizmoUser.objects.filter(role='student', is_active=True).count()
    total_lecturers   = GizmoUser.objects.filter(role='lecturer', is_active=True, is_approved=True).count()
    total_courses     = Course.objects.filter(status='active').count()
    total_papers      = PastPaper.objects.count()
    total_submissions = Submission.objects.count()
    graded_subs       = Submission.objects.filter(score__isnull=False).count()
    total_answers     = ModelAnswer.objects.count()

    # Avg score across all graded submissions (platform-wide)
    graded = Submission.objects.filter(score__isnull=False).select_related('paper', 'answer')
    pct_scores = [_submission_pct(s) for s in graded if _submission_pct(s) is not None]
    avg_score = round(sum(pct_scores) / len(pct_scores), 1) if pct_scores else None

    # New users this week
    week_ago = timezone.now() - timedelta(days=7)
    new_this_week = GizmoUser.objects.filter(created_at__gte=week_ago).count()

    # Top courses by enrolment
    top_courses = []
    for c_obj in Course.objects.filter(status='active').order_by('-enrolled_count')[:3]:
        top_courses.append({
            'code': c_obj.code,
            'name': c_obj.name,
            'enrolled': c_obj.enrolled_count,
        })

    return JsonResponse({
        'total_students':    total_students,
        'total_lecturers':   total_lecturers,
        'total_courses':     total_courses,
        'total_papers':      total_papers,
        'total_submissions': total_submissions,
        'graded_subs':       graded_subs,
        'total_answers':     total_answers,
        'avg_score':         avg_score,
        'new_this_week':     new_this_week,
        'top_courses':       top_courses,
    })

def landing(request):
    return render(request, 'landing/landingPage.html')


# ─────────────────────────────────────────────────────────────
#  SIGNUP — PAGE VIEWS
# ─────────────────────────────────────────────────────────────

def student_signup(request):
    return render(request, 'users/studentSignUp.html')


def lecturer_signup(request):
    return render(request, 'users/lectureSignUp.html')


# ─────────────────────────────────────────────────────────────
#  SIGNUP API — STEP 1
# ─────────────────────────────────────────────────────────────

@require_POST
def api_signup_step1(request):
    data = _json_body(request)

    first_name = data.get('firstName',  '').strip()
    last_name  = data.get('lastName',   '').strip()
    email      = data.get('email',      '').strip().lower()
    student_id = data.get('studentId',  '').strip()
    department = data.get('department', '').strip()
    role       = data.get('role', 'student').strip()

    if not all([first_name, last_name, email]):
        return JsonResponse({'ok': False, 'error': 'All fields are required.'})

    if '@' not in email or '.' not in email.split('@')[-1]:
        return JsonResponse({'ok': False, 'error': 'Please enter a valid email address.'})

    if GizmoUser.objects.filter(email=email).exists():
        return JsonResponse({'ok': False, 'error': 'An account with this email already exists. Please sign in.'})

    if role == 'student' and student_id:
        if GizmoUser.objects.filter(student_id=student_id).exists():
            return JsonResponse({'ok': False, 'error': 'This student ID is already registered.'})

    request.session['signup_pending'] = {
        'first_name': first_name,
        'last_name':  last_name,
        'email':      email,
        'student_id': student_id,
        'department': department,
        'role':       role,
    }
    request.session.modified = True
    return JsonResponse({'ok': True})


# ─────────────────────────────────────────────────────────────
#  SIGNUP API — STEP 2
# ─────────────────────────────────────────────────────────────

@require_POST
def api_signup_step2_send_otp(request):
    pending = request.session.get('signup_pending')
    if not pending:
        return JsonResponse({'ok': False, 'error': 'Session expired. Please start again.'})

    data      = _json_body(request)
    password  = data.get('password', '')
    phone_cc  = data.get('phoneCountry', '')
    phone_num = data.get('phoneNumber',  '')

    if len(password) < 8:
        return JsonResponse({'ok': False, 'error': 'Password must be at least 8 characters.'})

    email = pending['email']

    if GizmoUser.objects.filter(email=email).exists():
        user = GizmoUser.objects.get(email=email)
        if not user.is_email_verified:
            _send_otp_email(user, purpose='signup')
            request.session['signup_user_id'] = user.pk
            request.session.modified = True
            return JsonResponse({'ok': True})
        return JsonResponse({'ok': False, 'error': 'An account with this email already exists. Please sign in.'})

    user = GizmoUser.objects.create_user(
        username          = email,
        email             = email,
        password          = password,
        first_name        = pending['first_name'],
        last_name         = pending['last_name'],
        role              = pending['role'],
        student_id        = pending.get('student_id', ''),
        university_name   = pending.get('department', ''),
        phone_country     = phone_cc,
        phone_number      = phone_num,
        is_active         = True,
        is_email_verified = False,
        is_approved       = pending['role'] == 'student',
    )

    request.session['signup_user_id'] = user.pk
    request.session.modified = True
    _send_otp_email(user, purpose='signup')
    return JsonResponse({'ok': True})


# ─────────────────────────────────────────────────────────────
#  SIGNUP API — VERIFY OTP
# ─────────────────────────────────────────────────────────────

@require_POST
def api_verify_otp(request):
    data    = _json_body(request)
    code    = data.get('code', '').strip()
    purpose = data.get('purpose', 'signup')

    user_id = request.session.get('signup_user_id')
    if not user_id:
        return JsonResponse({'ok': False, 'error': 'Session expired. Please start again.'})

    try:
        user = GizmoUser.objects.get(pk=user_id)
    except GizmoUser.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'User not found.'})

    expiry_cutoff = timezone.now() - timedelta(minutes=10)
    otp = OTPCode.objects.filter(
        user=user, purpose=purpose, is_used=False, created_at__gte=expiry_cutoff,
    ).order_by('-created_at').first()

    if not otp:
        return JsonResponse({'ok': False, 'error': 'Code expired. Please request a new one.'})
    if otp.code != code:
        return JsonResponse({'ok': False, 'error': 'Incorrect code. Please try again.'})

    otp.is_used = True
    otp.save(update_fields=['is_used'])
    user.is_email_verified = True
    user.save(update_fields=['is_email_verified'])
    return JsonResponse({'ok': True})


# ─────────────────────────────────────────────────────────────
#  SIGNUP API — RESEND OTP
# ─────────────────────────────────────────────────────────────

@require_POST
def api_resend_otp(request):
    user_id = request.session.get('signup_user_id')
    if not user_id:
        return JsonResponse({'ok': False, 'error': 'Session expired. Please start over.'})
    try:
        user = GizmoUser.objects.get(pk=user_id)
    except GizmoUser.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'User not found.'})
    _send_otp_email(user, purpose='signup')
    return JsonResponse({'ok': True})


# ─────────────────────────────────────────────────────────────
#  SIGNUP API — COMPLETE  (enrols student in chosen courses)
# ─────────────────────────────────────────────────────────────

@require_POST
def api_signup_complete(request):
    data    = _json_body(request)
    courses = data.get('courses', [])

    user_id = request.session.get('signup_user_id')
    if not user_id:
        return JsonResponse({'ok': False, 'error': 'Session expired. Please start again.'})

    try:
        user = GizmoUser.objects.get(pk=user_id)
    except GizmoUser.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'User not found.'})

    if not user.is_email_verified:
        return JsonResponse({'ok': False, 'error': 'Please verify your email first.'})

    if user.role == 'student' and courses:
        for code in courses:
            course_obj = Course.objects.filter(code=code).first()
            if course_obj:
                Enrolment.objects.get_or_create(student=user, course=course_obj)

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.session.pop('signup_pending', None)
    request.session.pop('signup_user_id', None)

    redirect_url = '/dashboard/student/' if user.role == 'student' else '/pending-approval/'
    return JsonResponse({'ok': True, 'redirect': redirect_url})


# ─────────────────────────────────────────────────────────────
#  SIGNUP API — CHECK EMAIL
# ─────────────────────────────────────────────────────────────

def api_check_email(request):
    email = request.GET.get('email', '').strip().lower()
    exists = GizmoUser.objects.filter(email=email).exists()
    return JsonResponse({'exists': exists})


# ─────────────────────────────────────────────────────────────
#  COURSE API — SEARCH  (used by student signup + dashboard)
# ─────────────────────────────────────────────────────────────

def api_course_search(request):
    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'courses': []})

    qs = Course.objects.filter(
        Q(code__icontains=q) | Q(name__icontains=q) | Q(department__icontains=q),
        status='active'
    ).select_related('lecturer')[:20]

    results = []
    for c in qs:
        lecturer_name = ''
        if c.lecturer:
            lecturer_name = f'{c.lecturer.first_name} {c.lecturer.last_name}'.strip()
        results.append({
            'code':     c.code,
            'name':     c.name,
            'lecturer': lecturer_name,
            'dept':     c.department,
        })
    return JsonResponse({'courses': results})


# ─────────────────────────────────────────────────────────────
#  COURSE API — CREATE  (lecturer only)
# ─────────────────────────────────────────────────────────────

@require_POST
def api_course_create(request):
    if not request.user.is_authenticated or request.user.role not in ('lecturer', 'admin'):
        return JsonResponse({'ok': False, 'error': 'Unauthorised.'}, status=403)

    data = _json_body(request)
    code = data.get('code', '').strip().upper()
    name = data.get('name', '').strip()

    if not code or not name:
        return JsonResponse({'ok': False, 'error': 'Course code and name are required.'})

    if Course.objects.filter(code=code).exists():
        return JsonResponse({'ok': False, 'error': f'Course code {code} already exists.'})

    # For admins creating a course, allow assigning to a specific lecturer
    lecturer = request.user  # default: assign to whoever is creating
    if request.user.role == 'admin':
        lec_id = data.get('lecturerId')
        if lec_id:
            try:
                lecturer = GizmoUser.objects.get(pk=int(lec_id), role='lecturer', is_approved=True)
            except (GizmoUser.DoesNotExist, ValueError):
                pass  # fall back to admin as lecturer

    course = Course.objects.create(
        code          = code,
        name          = name,
        description   = data.get('description', '').strip(),
        department    = data.get('department', getattr(request.user, 'university_name', '')).strip(),
        lecturer      = lecturer,
        semester      = data.get('semester', '').strip(),
        academic_year = data.get('academicYear', '').strip(),
        credit_hours  = int(data.get('creditHours', 3) or 3),
        status        = 'active',
    )
    return JsonResponse({'ok': True, 'course': {'id': course.pk, 'code': course.code, 'name': course.name}})


# ─────────────────────────────────────────────────────────────
#  COURSE API — DELETE  (lecturer or admin, own courses)
# ─────────────────────────────────────────────────────────────

@require_POST
def api_course_delete(request, course_id):
    if not request.user.is_authenticated or request.user.role not in ('lecturer', 'admin'):
        return JsonResponse({'ok': False, 'error': 'Unauthorised.'}, status=403)
    try:
        if request.user.role == 'admin':
            course = Course.objects.get(pk=course_id)
        else:
            course = Course.objects.get(pk=course_id, lecturer=request.user)
        course.delete()
        return JsonResponse({'ok': True})
    except Course.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Course not found or access denied.'})


# ─────────────────────────────────────────────────────────────
#  ENROLMENT API — ENROL / UNENROL  (student only)
# ─────────────────────────────────────────────────────────────

@require_POST
def api_enrol(request):
    if not request.user.is_authenticated or request.user.role != 'student':
        return JsonResponse({'ok': False, 'error': 'Unauthorised.'}, status=403)

    data   = _json_body(request)
    code   = data.get('code', '').strip().upper()
    action = data.get('action', 'enrol')

    try:
        course = Course.objects.get(code=code)
    except Course.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Course not found.'})

    if action == 'unenrol':
        Enrolment.objects.filter(student=request.user, course=course).delete()
        return JsonResponse({'ok': True, 'action': 'unenrolled'})
    else:
        _, created = Enrolment.objects.get_or_create(student=request.user, course=course)
        return JsonResponse({'ok': True, 'action': 'enrolled', 'new': created})


# ─────────────────────────────────────────────────────────────
#  ADMIN API — courses for a specific user  (for click-to-view)
# ─────────────────────────────────────────────────────────────

def api_user_courses(request, user_id):
    if not _admin_required(request):
        return JsonResponse({'ok': False, 'error': 'Unauthorised.'}, status=403)
    try:
        target = GizmoUser.objects.get(pk=user_id)
    except GizmoUser.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'User not found.'}, status=404)

    if target.role == 'lecturer':
        courses = list(Course.objects.filter(lecturer=target).values(
            'code', 'name', 'department', 'semester', 'academic_year', 'status'
        ))
    else:
        courses = list(Course.objects.filter(
            enrolments__student=target
        ).values('code', 'name', 'department', 'semester', 'academic_year', 'status'))

    return JsonResponse({
        'ok': True,
        'user': {
            'name':  f'{target.first_name} {target.last_name}'.strip(),
            'email': target.email,
            'role':  target.role,
        },
        'courses': courses,
    })


# ─────────────────────────────────────────────────────────────
#  ADMIN SETTINGS API
# ─────────────────────────────────────────────────────────────

def api_toggle_setting(request):
    """POST { setting: 'maintenance_mode'|'...', value: true|false }"""
    if not _admin_required(request):
        return JsonResponse({'ok': False, 'error': 'Unauthorised. Are you logged in as admin?'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)

    import json
    from .models import SiteSettings
    from .email_service import send_maintenance_email, send_maintenance_over_email

    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)

    setting = body.get('setting')
    value   = body.get('value')

    site = SiteSettings.get()

    if setting == 'maintenance_mode':
        site.maintenance_mode = bool(value)
        site.save(update_fields=['maintenance_mode'])

        # Get all non-admin users with verified emails
        affected = GizmoUser.objects.filter(
            is_email_verified=True
        ).exclude(role='admin')

        if value:
            # Email blast — maintenance starting
            for u in affected:
                send_maintenance_email(
                    u.email,
                    u.first_name or u.email,
                    site.maintenance_message,
                )
            return JsonResponse({
                'ok': True,
                'message': f'Maintenance mode ON. {affected.count()} users notified by email.'
            })
        else:
            # Email blast — back online
            for u in affected:
                send_maintenance_over_email(u.email, u.first_name or u.email)
            return JsonResponse({
                'ok': True,
                'message': f'Maintenance mode OFF. {affected.count()} users notified.'
            })

    # Other toggle settings (stored in session / future DB fields)
    return JsonResponse({'ok': True, 'message': f'{setting} updated.'})


def student_login(request):
    if request.user.is_authenticated and request.user.role == 'student':
        return redirect('/dashboard/student/')

    if request.method == 'POST':
        email    = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        user = authenticate(request, username=email, password=password)
        if user is None:
            try:
                u = GizmoUser.objects.get(email=email)
                user = authenticate(request, username=u.username, password=password)
            except GizmoUser.DoesNotExist:
                pass

        if user is not None:
            if user.role != 'student':
                messages.error(request, 'This account is not a student account.')
                return render(request, 'users/studentLogin.html')
            if not user.is_email_verified:
                messages.error(request, 'Please verify your email before signing in.')
                return render(request, 'users/studentLogin.html')
            if not user.is_active:
                messages.error(request, 'This account has been deactivated.')
                return render(request, 'users/studentLogin.html')
            login(request, user)
            return redirect('/dashboard/student/')
        else:
            messages.error(request, 'Invalid email or password.')
            return render(request, 'users/studentLogin.html')

    return render(request, 'users/studentLogin.html')


def lecturer_login(request):
    if request.user.is_authenticated and request.user.role == 'lecturer':
        return redirect('/dashboard/lecturer/')

    if request.method == 'POST':
        email    = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        user = authenticate(request, username=email, password=password)
        if user is None:
            try:
                u = GizmoUser.objects.get(email=email)
                user = authenticate(request, username=u.username, password=password)
            except GizmoUser.DoesNotExist:
                pass

        if user is not None:
            if user.role != 'lecturer':
                messages.error(request, 'This account is not a lecturer account.')
                return render(request, 'users/lectureLogin.html')
            if not user.is_email_verified:
                messages.error(request, 'Please verify your email before signing in.')
                return render(request, 'users/lectureLogin.html')
            if not user.is_approved:
                login(request, user)
                return redirect('/pending-approval/')
            login(request, user)
            return redirect('/dashboard/lecturer/')
        else:
            messages.error(request, 'Invalid email or password.')
            return render(request, 'users/lectureLogin.html')

    return render(request, 'users/lectureLogin.html')


def admin_login(request):
    if request.user.is_authenticated and request.user.role == 'admin':
        return redirect('/dashboard/admin/')

    context = {
        'total_users':    GizmoUser.objects.count(),
        'total_courses':  Course.objects.filter(status='active').count(),
    }

    if request.method == 'POST':
        email    = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        user = authenticate(request, username=email, password=password)
        if user is None:
            try:
                u = GizmoUser.objects.get(email=email)
                user = authenticate(request, username=u.username, password=password)
            except GizmoUser.DoesNotExist:
                pass

        if user is not None and user.role == 'admin':
            login(request, user)
            return redirect('/dashboard/admin/')
        else:
            messages.error(request, 'Invalid credentials or insufficient permissions.')
            return render(request, 'users/adminLogin.html', context)

    return render(request, 'users/adminLogin.html', context)


# ─────────────────────────────────────────────────────────────
#  LOGOUT
# ─────────────────────────────────────────────────────────────

def logout_view(request):
    logout(request)
    return redirect('/')


# ─────────────────────────────────────────────────────────────
#  PENDING APPROVAL
# ─────────────────────────────────────────────────────────────

@login_required
def pending_approval(request):
    if request.user.role == 'lecturer' and request.user.is_approved:
        return redirect('/dashboard/lecturer/')
    return render(request, 'users/pending_approval.html', {'user': request.user})


# ─────────────────────────────────────────────────────────────
#  DASHBOARDS
# ─────────────────────────────────────────────────────────────

@login_required
def student_dashboard(request):
    if request.user.role != 'student':
        return redirect('/')

    enrolled = Enrolment.objects.filter(
        student=request.user
    ).select_related('course', 'course__lecturer')

    context = {
        'user':             request.user,
        'enrolled_courses': [e.course for e in enrolled],
    }
    return render(request, 'dashboards/studentDashboard.html', context)


@login_required
def lecturer_dashboard(request):
    if request.user.role != 'lecturer':
        return redirect('/')
    if not request.user.is_approved:
        return redirect('/pending-approval/')

    from .models import PastPaper, Submission, Enrolment
    my_courses = Course.objects.filter(lecturer=request.user)
    total_students = Enrolment.objects.filter(
        course__lecturer=request.user
    ).values('student').distinct().count()
    total_papers = PastPaper.objects.filter(
        course__lecturer=request.user
    ).count()
    total_submissions = Submission.objects.filter(
        paper__course__lecturer=request.user
    ).count()
    pending = Submission.objects.filter(
        paper__course__lecturer=request.user, score__isnull=True
    ).count()

    context = {
        'user':                  request.user,
        'my_courses':            my_courses,
        'total_students':        total_students,
        'total_courses':         my_courses.count(),
        'total_papers':          total_papers,
        'total_submissions':     total_submissions,
        'pending_verifications': pending,
    }
    return render(request, 'dashboards/lectureDashboard.html', context)


@login_required
def admin_dashboard(request):
    if request.user.role != 'admin':
        return redirect('/')

    from .models import SiteSettings
    site = SiteSettings.get()

    all_courses = Course.objects.select_related('lecturer').order_by('-created_at')

    context = {
        'user':              request.user,
        'total_users':       GizmoUser.objects.count(),
        'total_students':    GizmoUser.objects.filter(role='student').count(),
        'total_lecturers':   GizmoUser.objects.filter(role='lecturer', is_approved=True).count(),
        'total_admins':      GizmoUser.objects.filter(role='admin').count(),
        'suspended_users':   GizmoUser.objects.filter(is_active=False).count(),
        'pending_lecturers': GizmoUser.objects.filter(
            role='lecturer', is_approved=False, is_email_verified=True
        ).count(),
        'total_courses':          all_courses.count(),
        'active_courses_count':   all_courses.filter(status='active').count(),
        'archived_courses_count': all_courses.filter(status='archived').count(),
        'submissions_today': 0,
        'maintenance_mode':  site.maintenance_mode,
        'recent_users':            GizmoUser.objects.order_by('-created_at')[:10],
        'all_users':               GizmoUser.objects.order_by('-created_at'),
        'all_courses':             all_courses,
        'pending_lecturers_list':  GizmoUser.objects.filter(
            role='lecturer', is_approved=False, is_email_verified=True
        ).order_by('-created_at'),
        'approved_lecturers_list': GizmoUser.objects.filter(
            role='lecturer', is_approved=True
        ).order_by('-created_at'),
    }
    return render(request, 'dashboards/adminDashboard.html', context)


# ─────────────────────────────────────────────────────────────
#  ADMIN ACTIONS
# ─────────────────────────────────────────────────────────────

def approve_lecturer(request, user_id):
    if not _admin_required(request):
        return redirect('/login/admin/')
    try:
        lecturer = GizmoUser.objects.get(pk=user_id, role='lecturer')
        lecturer.is_approved = True
        lecturer.save(update_fields=['is_approved'])
        from .email_service import send_approval_email
        send_approval_email(lecturer.email, lecturer.first_name)
    except GizmoUser.DoesNotExist:
        pass
    return redirect('/dashboard/admin/')


def reject_lecturer(request, user_id):
    if not _admin_required(request):
        return redirect('/login/admin/')
    try:
        lecturer = GizmoUser.objects.get(pk=user_id, role='lecturer')
        lecturer.is_active = False
        lecturer.save(update_fields=['is_active'])
    except GizmoUser.DoesNotExist:
        pass
    return redirect('/dashboard/admin/')


def suspend_user(request, user_id):
    if not _admin_required(request):
        return redirect('/login/admin/')
    try:
        user = GizmoUser.objects.get(pk=user_id)
        if user.role != 'admin':
            user.is_active = False
            user.save(update_fields=['is_active'])
    except GizmoUser.DoesNotExist:
        pass
    return redirect('/dashboard/admin/')


def unsuspend_user(request, user_id):
    if not _admin_required(request):
        return redirect('/login/admin/')
    try:
        user = GizmoUser.objects.get(pk=user_id)
        user.is_active = True
        user.save(update_fields=['is_active'])
    except GizmoUser.DoesNotExist:
        pass
    return redirect('/dashboard/admin/')


# ═══════════════════════════════════════════════════════════════
#  TEACHER DASHBOARD APIs
# ═══════════════════════════════════════════════════════════════

def _lecturer_required(request):
    return request.user.is_authenticated and request.user.role == 'lecturer'


def _lecturer_courses(request):
    """Return queryset of courses owned by the logged-in lecturer."""
    from .models import Course
    return Course.objects.filter(lecturer=request.user)


# ── Stats ────────────────────────────────────────────────────

def api_teacher_stats(request):
    if not _lecturer_required(request):
        return JsonResponse({'error': 'Unauthorised'}, status=403)
    from .models import Course, Enrolment, PastPaper, Submission
    courses = _lecturer_courses(request)
    total_students    = Enrolment.objects.filter(course__in=courses).values('student').distinct().count()
    total_papers      = PastPaper.objects.filter(course__in=courses).count()
    total_submissions = Submission.objects.filter(paper__course__in=courses).count()
    # Avg score as percentage of total marks
    graded = Submission.objects.filter(
        paper__course__in=courses, score__isnull=False
    ).select_related('paper', 'answer')
    pct_scores = [_submission_pct(s) for s in graded if _submission_pct(s) is not None]
    avg_score = round(sum(pct_scores) / len(pct_scores), 1) if pct_scores else None
    return JsonResponse({
        'total_students': total_students,
        'students_trend': f'{total_students} enrolled across {courses.count()} courses',
        'total_papers': total_papers,
        'papers_trend': 'Total past papers uploaded',
        'total_submissions': total_submissions,
        'submissions_trend': 'Total student submissions',
        'avg_score': avg_score,
        'avg_trend': 'Class average across graded submissions',
    })


# ── Courses ──────────────────────────────────────────────────

def api_teacher_courses_list(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    courses = _lecturer_courses(request)
    return JsonResponse([{
        'id': c.pk, 'code': c.code, 'name': c.name,
        'status': c.status, 'enrolled': c.enrolled_count,
    } for c in courses], safe=False)


def api_teacher_courses_dashboard(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    from .models import PastPaper, Submission
    courses = _lecturer_courses(request)
    result = []
    for c in courses:
        papers = PastPaper.objects.filter(course=c).count()
        subs   = Submission.objects.filter(paper__course=c).count()
        result.append({
            'id': c.pk, 'code': c.code, 'name': c.name,
            'status': c.get_status_display(),
            'enrolled': c.enrolled_count,
            'papers': papers,
            'submissions': subs,
        })
    return JsonResponse(result, safe=False)


# ── Recent Activity ──────────────────────────────────────────

def api_teacher_activity(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    from .models import Submission, PastPaper
    courses = _lecturer_courses(request)
    recent_subs = Submission.objects.filter(
        paper__course__in=courses
    ).select_related('student', 'paper').order_by('-submitted_at')[:10]
    activities = []
    for s in recent_subs:
        activities.append({
            'title': f'{s.student.get_full_name()} submitted an answer',
            'description': f'{s.paper.course.code} — {s.paper.title}',
            'time': s.submitted_at.strftime('%d %b %Y, %H:%M'),
        })
    return JsonResponse(activities, safe=False)


# ── Students ─────────────────────────────────────────────────

def api_teacher_students(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    from .models import Enrolment, Submission
    courses = _lecturer_courses(request)
    course_filter = request.GET.get('course', '')
    search = request.GET.get('search', '').strip()
    if course_filter:
        enrolments = Enrolment.objects.filter(course__pk=course_filter, course__in=courses)
    else:
        enrolments = Enrolment.objects.filter(course__in=courses)
    student_ids = enrolments.values_list('student_id', flat=True).distinct()
    from .models import GizmoUser
    students = GizmoUser.objects.filter(pk__in=student_ids, role='student')
    if search:
        students = students.filter(
            first_name__icontains=search
        ) | students.filter(
            last_name__icontains=search
        ) | students.filter(
            email__icontains=search
        )
    result = []
    for s in students:
        enrolled_courses = [e.course.code for e in s.enrolments.filter(course__in=courses)]
        subs_count = Submission.objects.filter(student=s, paper__course__in=courses).count()
        graded = Submission.objects.filter(
            student=s, paper__course__in=courses, score__isnull=False
        ).select_related('paper', 'answer')
        if graded.count() > 0:
            pct_scores = [_submission_pct(g) for g in graded if _submission_pct(g) is not None]
            avg = str(round(sum(pct_scores) / len(pct_scores), 1)) + '%' if pct_scores else '—'
        else:
            avg = '—'
        result.append({
            'id': s.pk,
            'full_name': s.get_full_name(),
            'initials': (s.first_name[:1] + s.last_name[:1]).upper(),
            'student_id': s.student_id or '—',
            'email': s.email,
            'courses': enrolled_courses,
            'submissions': subs_count,
            'avg_score': avg,
        })
    return JsonResponse(result, safe=False)


# ── Past Papers ──────────────────────────────────────────────

def api_teacher_papers(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    from .models import PastPaper, ModelAnswer
    courses = _lecturer_courses(request)
    papers = PastPaper.objects.filter(course__in=courses).select_related('course')
    # Optional course filter from frontend dropdown
    course_param = request.GET.get('course', '').strip()
    if course_param:
        papers = papers.filter(course__pk=course_param)
    result = []
    for p in papers:
        # Count from model answers first (most accurate), then num_questions field
        answers_qs = ModelAnswer.objects.filter(paper=p).order_by('question_ref')
        answer_count = answers_qs.count()
        num_q_field  = getattr(p, 'num_questions', 0) or 0
        # Use whichever is higher — model answers are ground truth, file scan is a fallback
        questions_count = max(answer_count, num_q_field)

        # Auto-update num_questions on the paper if model answers exist and count differs
        if answer_count > 0 and num_q_field != answer_count:
            try:
                p.num_questions = answer_count
                p.save(update_fields=['num_questions'])
            except Exception:
                pass

        # Build per-question list for the card tooltip / detail view
        question_list = [{
            'answer_id':    a.pk,
            'question_ref': a.question_ref or f'Q{i+1}',
            'marks':        float(a.marks) if a.marks else None,
            'topic':        a.topic or '',
        } for i, a in enumerate(answers_qs)]

        result.append({
            'id':          p.pk,
            'title':       p.title,
            'course_code': p.course.code,
            'course_name': p.course.name,
            'date':        p.created_at.strftime('%d %b %Y'),
            'duration':    p.duration_mins,
            'marks':       p.total_marks,
            'questions':   questions_count,   # ← correct count
            'question_list': question_list,   # ← per-question breakdown
            'submissions': p.submissions.count(),
            'answers':     answer_count,
            'course_id':   p.course_id,
            'badge':       p.get_period_display() if p.period else 'General',
            'is_recent':   ((__import__('django').utils.timezone.now() - p.created_at).days <= 30),
            'file_url':    p.file.url if p.file else None,
        })
    return JsonResponse(result, safe=False)


def _count_questions_in_file(uploaded_file):
    """
    Try to count questions in an uploaded file by looking for
    patterns like 'Question 1', 'Q1', '1.', '(a)' etc.
    Returns 0 if it can't parse the file.
    """
    import re
    text = ''
    name = uploaded_file.name.lower()
    try:
        if name.endswith('.docx'):
            from docx import Document
            import io
            doc = Document(io.BytesIO(uploaded_file.read()))
            text = '\n'.join(p.text for p in doc.paragraphs)
            uploaded_file.seek(0)
        elif name.endswith('.pdf'):
            try:
                import io
                from pdfminer.high_level import extract_text
                text = extract_text(io.BytesIO(uploaded_file.read()))
                uploaded_file.seek(0)
            except Exception:
                return 0
        else:
            return 0
    except Exception:
        return 0

    if not text.strip():
        return 0

    # Pattern 1: "Question 1", "Question 2" etc (case insensitive)
    q_pattern = re.findall(r'\b[Qq]uestion\s+\d+', text)
    if q_pattern:
        nums = [int(re.search(r'\d+', q).group()) for q in q_pattern]
        return max(nums)

    # Pattern 2: "Q1.", "Q2." standalone
    q_pattern2 = re.findall(r'\bQ(\d+)[\.\):]', text)
    if q_pattern2:
        return max(int(n) for n in q_pattern2)

    # Pattern 3: Numbered lines "1.", "2." etc at start of line
    numbered = re.findall(r'(?m)^\s*(\d+)\.\s+\S', text)
    if numbered:
        nums = [int(n) for n in numbered]
        # Only count if numbers are sequential starting from 1
        if 1 in nums and max(nums) <= 50:
            return max(nums)

    return 0


def _extract_questions_from_file(uploaded_file):
    """
    Extract a structured list of questions with their individual marks.
    Returns a list of dicts: [{number, label, marks, text_preview}]
    Falls back to numbered list if marks not found.
    """
    import re, io
    text = ''
    name = uploaded_file.name.lower() if hasattr(uploaded_file, 'name') else ''

    try:
        if name.endswith('.docx'):
            from docx import Document
            doc = Document(io.BytesIO(uploaded_file.read()))
            text = '\n'.join(p.text for p in doc.paragraphs)
            uploaded_file.seek(0)
        elif name.endswith('.pdf'):
            try:
                from pdfminer.high_level import extract_text
                text = extract_text(io.BytesIO(uploaded_file.read()))
                uploaded_file.seek(0)
            except Exception:
                return []
        else:
            return []
    except Exception:
        return []

    if not text.strip():
        return []

    questions = []

    # Pattern A: "Question 1 [5 marks]" or "Question 1 (5 marks)" or "Question 1 – 5 marks"
    pattern_a = re.compile(
        r'(?i)(?:question|q\.?)\s*(\d+)[^\n]*?'
        r'[\(\[\s–\-]+(\d+(?:\.\d+)?)\s*marks?\s*[\)\]]?',
        re.IGNORECASE
    )
    matches_a = list(pattern_a.finditer(text))

    if matches_a:
        seen = set()
        for m in matches_a:
            n = int(m.group(1))
            if n in seen:
                continue
            seen.add(n)
            marks = float(m.group(2))
            # Grab a short preview of the question text
            snippet_start = m.end()
            snippet = text[snippet_start:snippet_start+120].strip()
            snippet = re.sub(r'\s+', ' ', snippet)[:100]
            questions.append({
                'number': n,
                'label':  f'Question {n}',
                'marks':  marks,
                'preview': snippet,
            })
        if questions:
            questions.sort(key=lambda x: x['number'])
            return questions

    # Pattern B: "Q1 [5]" or "Q1 (5)"
    pattern_b = re.compile(
        r'(?i)\bQ(\d+)[\.\):]?\s*[\(\[]\s*(\d+(?:\.\d+)?)\s*(?:marks?)?\s*[\)\]]'
    )
    matches_b = list(pattern_b.finditer(text))
    if matches_b:
        seen = set()
        for m in matches_b:
            n = int(m.group(1))
            if n in seen:
                continue
            seen.add(n)
            marks = float(m.group(2))
            snippet = text[m.end():m.end()+100].strip()
            snippet = re.sub(r'\s+', ' ', snippet)[:100]
            questions.append({'number': n, 'label': f'Q{n}', 'marks': marks, 'preview': snippet})
        if questions:
            questions.sort(key=lambda x: x['number'])
            return questions

    # Pattern C: Just detect question numbers, no marks found — use equal split
    total_q = _count_questions_from_text(text)
    if total_q > 0:
        return [{'number': i, 'label': f'Question {i}', 'marks': None, 'preview': ''} for i in range(1, total_q + 1)]

    return []


def _count_questions_from_text(text):
    """Helper used by _extract_questions_from_file."""
    import re
    q1 = re.findall(r'\b[Qq]uestion\s+\d+', text)
    if q1:
        return max(int(re.search(r'\d+', q).group()) for q in q1)
    q2 = re.findall(r'\bQ(\d+)[\.\):]', text)
    if q2:
        return max(int(n) for n in q2)
    numbered = re.findall(r'(?m)^\s*(\d+)\.\s+\S', text)
    if numbered:
        nums = [int(n) for n in numbered]
        if 1 in nums and max(nums) <= 50:
            return max(nums)
    return 0


def api_teacher_paper_upload(request):
    if not _lecturer_required(request):
        return JsonResponse({'ok': False, 'error': 'Unauthorised'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    from .models import PastPaper, Course
    course_id = request.POST.get('course')
    title     = request.POST.get('title', '').strip()
    if not course_id or not title:
        return JsonResponse({'ok': False, 'error': 'Course and title are required.'})
    try:
        course = Course.objects.get(pk=course_id, lecturer=request.user)
    except Course.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Course not found.'})

    # Auto-detect question count from file if not manually set
    manual_num_q = int(request.POST.get('num_questions', 0) or 0)
    detected_num_q = 0
    extracted_questions = []
    if 'file' in request.FILES:
        try:
            f = request.FILES['file']
            extracted_questions = _extract_questions_from_file(f)
            detected_num_q = len(extracted_questions) if extracted_questions else 0
            f.seek(0)
        except Exception:
            pass
    detected_num_q = 0
    if 'file' in request.FILES and manual_num_q == 0:
        detected_num_q = _count_questions_in_file(request.FILES['file'])

    paper = PastPaper(
        course=course, uploaded_by=request.user, title=title,
        period=request.POST.get('period', ''),
        academic_year=request.POST.get('academic_year', ''),
        total_marks=int(request.POST.get('total_marks', 100) or 100),
        duration_mins=int(request.POST.get('duration_mins', 120) or 120),
        num_questions=manual_num_q or detected_num_q,
        notes=request.POST.get('notes', ''),
    )
    if 'file' in request.FILES:
        paper.file = request.FILES['file']
    paper.save()
    return JsonResponse({
        'ok': True,
        'id': paper.pk,
        'title': paper.title,
        'num_questions': getattr(paper, 'num_questions', 0) or 0,
        'auto_detected': detected_num_q > 0 and manual_num_q == 0,
    })


def api_teacher_paper_delete(request, paper_id):
    if not _lecturer_required(request):
        return JsonResponse({'ok': False}, status=403)
    from .models import PastPaper
    try:
        paper = PastPaper.objects.get(pk=paper_id, uploaded_by=request.user)
        paper.delete()
        return JsonResponse({'ok': True})
    except PastPaper.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)


# ── Model Answers ────────────────────────────────────────────

def api_teacher_answers(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    from .models import ModelAnswer
    courses = _lecturer_courses(request)
    answers = ModelAnswer.objects.filter(paper__course__in=courses).select_related('paper__course')
    course_param = request.GET.get('course', '').strip()
    if course_param:
        answers = answers.filter(paper__course__pk=course_param)
    result = []
    for a in answers:
        result.append({
            'id': a.pk,
            'question': a.question_ref or 'General',
            'topic': a.topic or a.paper.title,
            'paper_title': f'{a.paper.course.code} — {a.paper.title}',
            'course_code': a.paper.course.code,
            'course_name': a.paper.course.name,
            'paper_id':    a.paper.pk,
            'preview': a.answer_text[:300] + ('…' if len(a.answer_text) > 300 else ''),
            'key_points': [kp.strip() for kp in a.key_points.splitlines() if kp.strip()],
            'marks': a.marks,
            'criteria': a.criteria or '',
            'file_url': a.file.url if a.file else None,
        })
    return JsonResponse(result, safe=False)


def api_teacher_answer_upload(request):
    if not _lecturer_required(request):
        return JsonResponse({'ok': False, 'error': 'Unauthorised'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    from .models import PastPaper, ModelAnswer
    paper_id    = request.POST.get('paper_id') or request.POST.get('paper')
    answer_text = request.POST.get('answer_text', '').strip()
    if not paper_id or not answer_text:
        return JsonResponse({'ok': False, 'error': 'Paper and answer text are required.'})
    try:
        paper_id_int = int(paper_id)
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': f'Invalid paper ID: {paper_id}'})
    try:
        paper = PastPaper.objects.get(pk=paper_id_int, course__in=_lecturer_courses(request))
    except PastPaper.DoesNotExist:
        # Try without course restriction in case of ownership mismatch
        try:
            paper = PastPaper.objects.get(pk=paper_id_int)
        except PastPaper.DoesNotExist:
            return JsonResponse({'ok': False, 'error': f'Paper {paper_id} not found.'})
    try:
        marks_raw = request.POST.get('marks', '0') or '0'
        marks = int(float(marks_raw))
    except (ValueError, TypeError):
        marks = 0
    try:
        ans = ModelAnswer(
            paper=paper,
            question_ref=request.POST.get('question_ref', ''),
            topic=request.POST.get('topic', ''),
            answer_text=answer_text,
            key_points=request.POST.get('key_points', ''),
            marks=marks,
            criteria=request.POST.get('criteria', ''),
        )
        if 'file' in request.FILES:
            ans.file = request.FILES['file']
        ans.save()
        return JsonResponse({'ok': True, 'id': ans.pk})
    except Exception as e:
        import traceback
        return JsonResponse({'ok': False, 'error': f'Save failed: {str(e)}', 'detail': traceback.format_exc()[:500]})


# ── Textbooks ────────────────────────────────────────────────

def api_teacher_textbooks(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    textbooks = request.user.textbooks_uploaded.prefetch_related('courses').all()
    course_param = request.GET.get('course', '').strip()
    if course_param:
        textbooks = textbooks.filter(courses__pk=course_param)
    result = []
    for t in textbooks:
        result.append({
            'id': t.pk,
            'title': t.title,
            'authors': t.authors,
            'edition': t.edition,
            'chapters': t.chapters,
            'courses': [c.code for c in t.courses.all()],
            'file_url': t.file.url if t.file else None,
        })
    return JsonResponse(result, safe=False)


def api_teacher_textbook_upload(request):
    if not _lecturer_required(request):
        return JsonResponse({'ok': False, 'error': 'Unauthorised'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    from .models import Textbook, Course
    title = request.POST.get('title', '').strip()
    if not title:
        return JsonResponse({'ok': False, 'error': 'Title is required.'})
    if 'file' not in request.FILES:
        return JsonResponse({'ok': False, 'error': 'File is required.'})
    try:
        tb = Textbook(
            uploaded_by=request.user,
            title=title,
            authors=request.POST.get('authors', ''),
            edition=request.POST.get('edition', ''),
            isbn=request.POST.get('isbn', ''),
            chapters=request.POST.get('chapters', ''),
            description=request.POST.get('description', ''),
            file=request.FILES['file'],
        )
        tb.save()
        # Accept both 'course_ids' and 'courses' key names
        course_ids = request.POST.getlist('course_ids') or request.POST.getlist('courses')
        if course_ids:
            courses = Course.objects.filter(pk__in=course_ids, lecturer=request.user)
            tb.courses.set(courses)
        return JsonResponse({'ok': True, 'id': tb.pk})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})


def api_teacher_textbook_delete(request, tb_id):
    if not _lecturer_required(request):
        return JsonResponse({'ok': False}, status=403)
    from .models import Textbook
    try:
        tb = Textbook.objects.get(pk=tb_id, uploaded_by=request.user)
        tb.delete()
        return JsonResponse({'ok': True})
    except Textbook.DoesNotExist:
        return JsonResponse({'ok': False}, status=404)


# ── Study Materials ──────────────────────────────────────────

def api_teacher_materials(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    courses = _lecturer_courses(request)
    from .models import StudyMaterial
    materials = StudyMaterial.objects.filter(course__in=courses).select_related('course')
    course_param = request.GET.get('course', '').strip()
    if course_param:
        materials = materials.filter(course__pk=course_param)
    icons = {'lecture': '📊', 'notes': '📝', 'video': '🎥', 'code': '💻', 'other': '📁'}
    result = []
    for m in materials:
        result.append({
            'id': m.pk,
            'title': m.title,
            'type': m.material_type,
            'icon': icons.get(m.material_type, '📁'),
            'course': f'{m.course.code} — {m.course.name}',
            'meta': m.created_at.strftime('%d %b %Y'),
            'action': 'Download',
            'file_url': m.file.url if m.file else None,
        })
    return JsonResponse(result, safe=False)


def api_teacher_material_upload(request):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'Please log in again.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    from .models import StudyMaterial, Course
    # Allow both lecturer and admin
    if request.user.role not in ('lecturer', 'admin'):
        return JsonResponse({'ok': False, 'error': 'Only lecturers can upload materials.'}, status=403)
    course_id = request.POST.get('course')
    title     = request.POST.get('title', '').strip()
    # Auto-fill title from filename if missing
    if not title and 'file' in request.FILES:
        import os
        title = os.path.splitext(request.FILES['file'].name)[0]
    if not course_id:
        return JsonResponse({'ok': False, 'error': 'Please select a course.'})
    if not title:
        return JsonResponse({'ok': False, 'error': 'Please enter a title.'})
    if 'file' not in request.FILES:
        return JsonResponse({'ok': False, 'error': 'Please select a file.'})
    try:
        course = Course.objects.get(pk=course_id, lecturer=request.user)
    except Course.DoesNotExist:
        # Admin fallback
        try:
            course = Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Course not found.'})
    try:
        mat = StudyMaterial(
            course=course, uploaded_by=request.user,
            title=title,
            material_type=request.POST.get('material_type', 'other'),
            description=request.POST.get('description', ''),
            file=request.FILES['file'],
        )
        mat.save()
        return JsonResponse({'ok': True, 'id': mat.pk})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})


def api_teacher_material_delete(request, mat_id):
    if not _lecturer_required(request):
        return JsonResponse({'ok': False}, status=403)
    from .models import StudyMaterial
    try:
        mat = StudyMaterial.objects.get(pk=mat_id, uploaded_by=request.user)
        mat.delete()
        return JsonResponse({'ok': True})
    except StudyMaterial.DoesNotExist:
        return JsonResponse({'ok': False}, status=404)


# ── Submissions ──────────────────────────────────────────────

def api_teacher_submissions(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    from .models import Submission
    courses = _lecturer_courses(request)
    course_filter = request.GET.get('course', '')
    qs = Submission.objects.filter(paper__course__in=courses).select_related(
        'student', 'paper__course', 'answer'
    )
    if course_filter:
        qs = qs.filter(paper__course__pk=course_filter)
    result = []
    for s in qs[:50]:
        paper_total = s.paper.total_marks or 100
        # Use question-level marks if available
        question_marks = float(s.answer.marks) if s.answer and s.answer.marks else None
        out_of = question_marks if question_marks else paper_total
        pct    = round(s.score / out_of * 100, 1) if s.score is not None else None
        result.append({
            'id':           s.pk,
            'student_name': s.student.get_full_name(),
            'initials':     (s.student.first_name[:1] + s.student.last_name[:1]).upper(),
            'course_code':  s.paper.course.code,
            'paper_title':  s.paper.title,
            'question':     s.answer.question_ref if s.answer else 'General',
            'time':         s.submitted_at.strftime('%d %b %Y, %H:%M'),
            'status':       'graded' if s.score is not None else 'pending',
            'score':        round(s.score, 1) if s.score is not None else None,
            'score_pct':    pct,
            'total_marks':  out_of,       # question marks (what score is out of)
            'paper_total':  paper_total,  # full paper total (for context)
            'file_url':     s.file.url if s.file else None,
        })
    return JsonResponse(result, safe=False)


def api_teacher_submission_grade(request, sub_id):
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    import json
    from .models import Submission
    try:
        sub = Submission.objects.get(pk=sub_id, paper__course__in=_lecturer_courses(request))
    except Submission.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
    body = json.loads(request.body)
    sub.score    = float(body.get('score', 0))
    sub.feedback = body.get('feedback', '')
    sub.save(update_fields=['score', 'feedback'])
    return JsonResponse({'ok': True})


# ── Analytics ────────────────────────────────────────────────

def api_teacher_analytics(request):
    if not _lecturer_required(request):
        return JsonResponse({}, status=403)
    from .models import Submission
    courses = _lecturer_courses(request)
    subs = Submission.objects.filter(paper__course__in=courses, score__isnull=False).select_related('paper', 'answer')
    # Optional course filter
    course_param = request.GET.get('course', '').strip()
    if course_param:
        subs = subs.filter(paper__course__pk=course_param)

    # Compute avg using question-level marks as denominator
    pct_scores = [_submission_pct(s) for s in subs if _submission_pct(s) is not None]
    avg_score = round(sum(pct_scores) / len(pct_scores), 1) if pct_scores else 0

    # Top students — by avg percentage score
    from .models import GizmoUser
    top = []
    student_ids = list(subs.values_list('student_id', flat=True).distinct()[:10])
    for sid in student_ids:
        s_subs = subs.filter(student_id=sid)
        s_pcts = [_submission_pct(s) for s in s_subs if _submission_pct(s) is not None]
        s_avg = round(sum(s_pcts) / len(s_pcts), 1) if s_pcts else 0
        try:
            stu = GizmoUser.objects.get(pk=sid)
            top.append({'name': stu.get_full_name(), 'score': s_avg})
        except GizmoUser.DoesNotExist:
            pass
    top.sort(key=lambda x: x['score'], reverse=True)
    top = top[:5]

    return JsonResponse({
        'avg_score': avg_score,
        'top_students': top,
    })


# ── Account Update ───────────────────────────────────────────

def api_teacher_account_update(request):
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    import json
    body = json.loads(request.body)
    user = request.user
    name_parts = body.get('name', '').split(' ', 1)
    user.first_name = name_parts[0]
    user.last_name  = name_parts[1] if len(name_parts) > 1 else ''
    user.university_name = body.get('dept', user.university_name)
    user.save(update_fields=['first_name', 'last_name', 'university_name'])
    return JsonResponse({'ok': True})


# ── Papers for a specific course (for modal dropdown) ────────

def api_teacher_papers_for_course(request):
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    from .models import PastPaper
    course_id = request.GET.get('course_id', '')
    qs = PastPaper.objects.filter(course__in=_lecturer_courses(request))
    if course_id:
        qs = qs.filter(course__pk=course_id)
    return JsonResponse([{
        'id':    p.pk,
        'title': p.title,
        'badge': p.get_period_display() if p.period else 'General',
        'academic_year': p.academic_year or '',
    } for p in qs], safe=False)


# ═══════════════════════════════════════════════════════════════
#  STUDENT DASHBOARD APIs
# ═══════════════════════════════════════════════════════════════

def _student_required(request):
    return request.user.is_authenticated and request.user.role == 'student'


def api_student_stats(request):
    """GET — dashboard stat cards"""
    if not _student_required(request):
        return JsonResponse({'error': 'Unauthorised'}, status=403)
    from .models import Enrolment, Submission
    enrolled_count = Enrolment.objects.filter(student=request.user).count()
    subs = Submission.objects.filter(
        student=request.user, score__isnull=False
    ).select_related('paper', 'answer')
    # Compute avg using question-level marks as denominator
    pct_scores = [_submission_pct(s) for s in subs if _submission_pct(s) is not None]
    avg = round(sum(pct_scores) / len(pct_scores), 1) if pct_scores else None
    total_subs = Submission.objects.filter(student=request.user).count()
    return JsonResponse({
        'enrolled_courses': enrolled_count,
        'avg_score': avg,
        'total_submissions': total_subs,
        'topics_mastered': 0,
    })


def api_student_enrolled_courses(request):
    """GET — list of enrolled courses with lecturer info"""
    if not _student_required(request):
        return JsonResponse([], safe=False)
    from .models import Enrolment
    enrolled = Enrolment.objects.filter(
        student=request.user
    ).select_related('course', 'course__lecturer')
    result = []
    for e in enrolled:
        c = e.course
        result.append({
            'id': c.pk,
            'code': c.code,
            'name': c.name,
            'dept': c.department,
            'semester': c.semester,
            'status': c.status,
            'lecturer': c.lecturer.get_full_name() if c.lecturer else '',
            'enrolled_at': e.enrolled_at.strftime('%d %b %Y'),
        })
    return JsonResponse(result, safe=False)


def api_student_unenrol(request):
    """POST {code} — unenrol from a course"""
    if not _student_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from .models import Enrolment, Course
    data = _json_body(request)
    code = data.get('code', '').strip().upper()
    try:
        course = Course.objects.get(code=code)
        Enrolment.objects.filter(student=request.user, course=course).delete()
        return JsonResponse({'ok': True})
    except Course.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)


def api_student_submit_answer(request):
    """POST multipart — submit an answer for a specific question, then auto-grade with AI."""
    if not _student_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Unauthorised'}, status=403)
    from .models import Submission, PastPaper, Enrolment, ModelAnswer
    paper_id    = request.POST.get('paper_id')
    answer_text = request.POST.get('answer_text', '')
    question_ref = request.POST.get('question_ref', '').strip()
    answer_id    = request.POST.get('answer_id', '').strip()  # pre-selected model answer

    if not paper_id:
        return JsonResponse({'ok': False, 'error': 'Paper is required.'})
    try:
        paper = PastPaper.objects.get(pk=paper_id)
    except PastPaper.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Paper not found.'})
    if not Enrolment.objects.filter(student=request.user, course=paper.course).exists():
        return JsonResponse({'ok': False, 'error': 'You are not enrolled in this course.'})

    # ── Find the specific model answer for this question ─────
    linked_answer = None
    if answer_id:
        try:
            linked_answer = ModelAnswer.objects.get(pk=answer_id, paper=paper)
        except ModelAnswer.DoesNotExist:
            pass
    if not linked_answer and question_ref:
        # Try matching by question_ref text
        linked_answer = ModelAnswer.objects.filter(
            paper=paper, question_ref__iexact=question_ref
        ).first()
        if not linked_answer:
            # Fuzzy: question_ref contains the ref
            linked_answer = ModelAnswer.objects.filter(
                paper=paper, question_ref__icontains=question_ref.split()[0]
            ).first() if question_ref else None
    if not linked_answer:
        # Fall back to first model answer
        linked_answer = ModelAnswer.objects.filter(paper=paper).first()

    # ── Determine marks for THIS question (not the whole paper) ──
    question_marks = float(linked_answer.marks) if linked_answer and linked_answer.marks else None
    if not question_marks:
        question_marks = float(paper.total_marks) if paper.total_marks else None

    sub = Submission(
        student     = request.user,
        paper       = paper,
        answer_text = answer_text,
        answer      = linked_answer,  # pre-link so grader uses the right model answer
    )
    if 'file' in request.FILES:
        sub.file = request.FILES['file']
    sub.save()

    # ── AI AUTO-GRADING ──────────────────────────────────────
    graded = False
    try:
        from gizmo_ai.ai_integration import auto_grade_submission
        graded = auto_grade_submission(sub.pk)
        if graded:
            sub.refresh_from_db()
            # Active Learning flag
            try:
                from gizmo_ai.active_learning import check_and_flag_submission
                check_and_flag_submission(sub.pk)
            except Exception as al_err:
                import logging
                logging.getLogger(__name__).debug(f"Active learning flag skipped: {al_err}")
    except Exception as ai_err:
        import logging
        logging.getLogger(__name__).warning(f"AI grading unavailable: {ai_err}")

    # Return score against question marks (not paper total)
    score = sub.score
    out_of = question_marks  # e.g. 2 for Q1 worth 2 marks

    return JsonResponse({
        'ok':          True,
        'id':          sub.pk,
        'graded':      graded,
        'score':       score,
        'out_of':      out_of,           # question-level marks
        'total_marks': paper.total_marks, # paper total (for context)
        'question_ref': question_ref or (linked_answer.question_ref if linked_answer else ''),
        'preview':     _parse_feedback_preview(sub.feedback) if graded else None,
    })


def _parse_feedback_preview(feedback_json):
    """Extract overall_feedback string from JSON blob."""
    if not feedback_json:
        return None
    try:
        import json as _j
        return _j.loads(feedback_json).get('overall_feedback', '')
    except Exception:
        return feedback_json[:200] if feedback_json else None

def _submission_out_of(submission):
    """
    Returns the correct denominator for a submission's score.
    Uses question-level marks (from linked model answer) if available,
    falls back to paper total marks.
    """
    if submission.answer and submission.answer.marks:
        return float(submission.answer.marks)
    return float(submission.paper.total_marks or 100)


def _submission_pct(submission):
    """Returns score as % of the correct denominator, or None if not graded."""
    if submission.score is None:
        return None
    out_of = _submission_out_of(submission)
    return round(submission.score / out_of * 100, 1) if out_of else 0.0



def api_student_results(request):
    """GET — all submissions with full structured AI feedback."""
    if not _student_required(request):
        return JsonResponse([], safe=False)
    from .models import Submission, StudyMaterial, Textbook
    import json as _j
    subs = Submission.objects.filter(
        student=request.user
    ).select_related('paper__course', 'answer').order_by('-submitted_at')
    result = []
    for s in subs:
        strengths, missing, suggestions, key_points = [], [], [], []
        overall_fb        = ''
        rec_resources     = []
        rec_topics        = []
        similarity_method = 'tfidf'
        overall_sim       = None
        linked_answer     = s.answer   # the model answer this submission was graded against
        total             = s.paper.total_marks or 100

        if s.feedback:
            try:
                d = _j.loads(s.feedback)
                strengths    = d.get('strengths', [])
                missing      = d.get('missing_points', [])
                suggestions  = d.get('improvement_suggestions', [])
                overall_fb   = d.get('overall_feedback', '')
                rec_topics   = d.get('recommended_topics', [])
                similarity_method = d.get('similarity_method', 'tfidf')
                overall_sim  = d.get('overall_similarity')
                key_points   = [
                    {
                        'point':           kp['point_text'],
                        'covered':         kp['covered'],
                        'marks_awarded':   round(kp['marks_awarded'], 1),
                        'marks_available': round(kp['marks_available'], 1),
                        'similarity':      round(kp.get('similarity_score', 0), 2),
                    }
                    for kp in d.get('key_point_results', [])
                ]
                # Enrich recommended_resources with live file URLs
                for r in d.get('recommended_resources', []):
                    rid   = r.get('id')
                    rtype = r.get('type', '')
                    enriched = dict(r)
                    if rid:
                        try:
                            if rtype == 'textbook':
                                t = Textbook.objects.get(pk=rid)
                                enriched['file_url'] = t.file.url if t.file else None
                                enriched['chapters'] = t.relevant_chapters or ''
                            elif rtype == 'material':
                                m = StudyMaterial.objects.get(pk=rid)
                                enriched['file_url'] = m.file.url if m.file else None
                        except Exception:
                            pass
                    rec_resources.append(enriched)
            except Exception:
                overall_fb = s.feedback

        # Compute score against QUESTION marks (not paper total)
        question_marks = float(linked_answer.marks) if linked_answer and linked_answer.marks else None
        out_of = question_marks if question_marks else total
        pct    = round(s.score / out_of * 100, 1) if s.score is not None and out_of else None

        result.append({
            'id':           s.pk,
            'course_code':  s.paper.course.code,
            'course_name':  s.paper.course.name,
            'paper_title':  s.paper.title,
            'total_marks':  total,           # paper total (context only)
            'out_of':       out_of,          # question-level marks — what score is out of
            'question':     s.answer.question_ref if s.answer else 'General',
            'submitted_at': s.submitted_at.strftime('%d %b %Y, %H:%M'),
            'status':       'graded' if s.score is not None else 'pending',
            'score':        round(s.score, 1) if s.score is not None else None,
            'score_pct':    pct,
            'answer_text':  s.answer_text or '',
            'feedback':     overall_fb,
            'strengths':    strengths,
            'missing_points':  missing,
            'improvement_suggestions': suggestions,
            'key_point_results':       key_points,
            'recommended_topics':      rec_topics,
            'recommended_resources':   rec_resources,
            'similarity_method':       similarity_method,
            'overall_similarity':      overall_sim,
            'file_url':     s.file.url if s.file else None,
        })
    return JsonResponse(result, safe=False)



def api_student_delete_submission(request, sub_id):
    """POST — student deletes one of their own submissions."""
    if not _student_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from .models import Submission
    try:
        sub = Submission.objects.get(pk=sub_id, student=request.user)
        sub.delete()
        return JsonResponse({'ok': True})
    except Submission.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)


def api_regrade_submission(request, sub_id):
    """POST — re-run AI grading on an existing submission."""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False}, status=403)
    from .models import Submission
    try:
        sub = Submission.objects.get(pk=sub_id, student=request.user)
    except Submission.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
    try:
        from gizmo_ai.ai_integration import auto_grade_submission
        ok = auto_grade_submission(sub_id)
        sub.refresh_from_db()
        return JsonResponse({'ok': ok, 'score': sub.score})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})


def api_student_papers(request):
    """GET ?course_id= — past papers for a student's enrolled courses"""
    if not _student_required(request):
        return JsonResponse([], safe=False)
    from .models import PastPaper, Enrolment, ModelAnswer
    enrolled_courses = Enrolment.objects.filter(
        student=request.user
    ).values_list('course_id', flat=True)
    course_id = request.GET.get('course_id', '')
    qs = PastPaper.objects.filter(course__in=enrolled_courses).select_related('course')
    if course_id:
        qs = qs.filter(course__pk=course_id)
    result = []
    for p in qs:
        # Build question list from model answers (most accurate source)
        answers = ModelAnswer.objects.filter(paper=p).order_by('question_ref')
        questions = []
        for a in answers:
            questions.append({
                'answer_id':  a.pk,
                'question_ref': a.question_ref or f'Question {a.pk}',
                'topic':      a.topic or '',
                'marks':      a.marks or 0,
            })
        # If no model answers yet, fall back to detected num_questions
        num_q = getattr(p, 'num_questions', 0) or 0
        result.append({
            'id':            p.pk,
            'title':         p.title,
            'course_code':   p.course.code,
            'course_name':   p.course.name,
            'period':        p.get_period_display() if p.period else 'General',
            'academic_year': p.academic_year,
            'total_marks':   p.total_marks,
            'duration_mins': p.duration_mins,
            'file_url':      p.file.url if p.file else None,
            'questions_count': len(questions) if questions else num_q,
            'questions':     questions,  # structured list with per-question marks
            'has_model_answers': len(questions) > 0,
        })
    return JsonResponse(result, safe=False)


def api_student_paper_questions(request, paper_id):
    """
    GET /api/student/paper/<paper_id>/questions/
    Returns the question list with per-question marks for the submit modal.
    Prioritises model answers as the source of truth, falls back to
    scanning the paper file if model answers not yet set.
    """
    if not _student_required(request):
        return JsonResponse({'ok': False}, status=403)
    from .models import PastPaper, Enrolment, ModelAnswer
    try:
        paper = PastPaper.objects.select_related('course').get(pk=paper_id)
    except PastPaper.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Paper not found'}, status=404)
    if not Enrolment.objects.filter(student=request.user, course=paper.course).exists():
        return JsonResponse({'ok': False, 'error': 'Not enrolled'}, status=403)

    # ── Source 1: Model answers (best — lecturer-defined marks) ──
    answers = ModelAnswer.objects.filter(paper=paper).order_by('question_ref')
    if answers.exists():
        questions = []
        for a in answers:
            questions.append({
                'answer_id':    a.pk,
                'question_ref': a.question_ref or f'Q{a.pk}',
                'topic':        a.topic or '',
                'marks':        float(a.marks) if a.marks else None,
                'source':       'model_answer',
            })
        return JsonResponse({
            'ok':          True,
            'paper_id':    paper_id,
            'paper_title': paper.title,
            'total_marks': paper.total_marks,
            'questions':   questions,
            'source':      'model_answers',
        })

    # ── Source 2: Scan the paper file ────────────────────────
    if paper.file:
        try:
            extracted = _extract_questions_from_file(paper.file)
            if extracted:
                # Distribute total marks equally if not detected
                total = paper.total_marks or 0
                for q in extracted:
                    if q['marks'] is None and total and len(extracted) > 0:
                        q['marks'] = round(total / len(extracted), 1)
                    q['source'] = 'file_scan'
                    q['answer_id'] = None
                return JsonResponse({
                    'ok':          True,
                    'paper_id':    paper_id,
                    'paper_title': paper.title,
                    'total_marks': paper.total_marks,
                    'questions':   extracted,
                    'source':      'file_scan',
                })
        except Exception:
            pass

    # ── Source 3: Use num_questions field ────────────────────
    num_q = getattr(paper, 'num_questions', 0) or 0
    if num_q > 0:
        total = paper.total_marks or 0
        marks_each = round(total / num_q, 1) if total and num_q else None
        questions = [{
            'answer_id':    None,
            'question_ref': f'Question {i}',
            'topic':        '',
            'marks':        marks_each,
            'source':       'num_questions_field',
        } for i in range(1, num_q + 1)]
        return JsonResponse({
            'ok': True, 'paper_id': paper_id,
            'paper_title': paper.title, 'total_marks': paper.total_marks,
            'questions': questions, 'source': 'num_questions_field',
        })

    # ── No questions found ────────────────────────────────────
    return JsonResponse({
        'ok': True, 'paper_id': paper_id,
        'paper_title': paper.title, 'total_marks': paper.total_marks,
        'questions': [], 'source': 'none',
        'message': 'No questions detected. The lecturer has not yet added model answers for this paper.',
    })


def api_student_resources(request):
    """GET ?q=search&course_id= — study materials from enrolled courses"""
    if not _student_required(request):
        return JsonResponse([], safe=False)
    from .models import StudyMaterial, Textbook, Enrolment
    enrolled_courses = Enrolment.objects.filter(
        student=request.user
    ).values_list('course_id', flat=True)
    search    = request.GET.get('q', '').strip()
    course_id = request.GET.get('course_id', '').strip()

    materials = StudyMaterial.objects.filter(
        course__in=enrolled_courses
    ).select_related('course')
    textbooks = Textbook.objects.filter(
        courses__in=enrolled_courses
    ).distinct()

    # Filter by course
    if course_id:
        materials = materials.filter(course__pk=course_id)
        textbooks = textbooks.filter(courses__pk=course_id)

    # Filter by search text
    if search:
        materials = materials.filter(title__icontains=search)
        textbooks = textbooks.filter(title__icontains=search)

    icons = {'lecture': '📊', 'notes': '📝', 'video': '🎥', 'code': '💻', 'other': '📁'}
    result = []
    for m in materials:
        result.append({
            'id': m.pk, 'type': 'material',
            'icon': icons.get(m.material_type, '📁'),
            'title': m.title,
            'course': f'{m.course.code} — {m.course.name}',
            'desc': m.get_material_type_display(),
            'file_url': m.file.url if m.file else None,
            'date': m.created_at.strftime('%d %b %Y'),
        })
    for t in textbooks:
        result.append({
            'id': t.pk, 'type': 'textbook',
            'icon': '📚',
            'title': t.title,
            'course': t.authors or 'Reference',
            'desc': t.edition or 'Textbook',
            'file_url': t.file.url if t.file else None,
            'date': t.created_at.strftime('%d %b %Y'),
        })
    return JsonResponse(result, safe=False)


def api_student_progress(request):
    """GET — per-course progress.
    Completion = unique questions attempted / total questions across all papers in course.
    For each question, only the BEST submission is used for avg score.
    """
    if not _student_required(request):
        return JsonResponse([], safe=False)
    from .models import Enrolment, Submission, PastPaper, ModelAnswer
    enrolled = Enrolment.objects.filter(
        student=request.user
    ).select_related('course')
    result = []
    for e in enrolled:
        papers = PastPaper.objects.filter(course=e.course)
        # Total questions = sum of model answers across all papers
        # (num_questions field as fallback per paper)
        total_questions = 0
        for p in papers:
            q_count = ModelAnswer.objects.filter(paper=p).count()
            if q_count == 0:
                q_count = getattr(p, 'num_questions', 0) or 0
            total_questions += q_count

        # Unique questions the student has attempted (deduplicated by answer/question_ref)
        all_subs = Submission.objects.filter(
            student=request.user, paper__course=e.course
        ).select_related('answer', 'paper')

        # Deduplicate: one submission per (paper, question_ref) — pick best score
        best_by_question = {}  # key: (paper_id, question_ref) → submission
        for s in all_subs:
            q_key = (s.paper_id, s.answer.question_ref if s.answer else '_')
            existing = best_by_question.get(q_key)
            if existing is None:
                best_by_question[q_key] = s
            else:
                # prefer graded; among graded, prefer highest pct
                s_pct  = _submission_pct(s)       or 0
                ex_pct = _submission_pct(existing) or 0
                if s.score is not None and (existing.score is None or s_pct > ex_pct):
                    best_by_question[q_key] = s

        unique_attempted = len(best_by_question)
        best_subs = list(best_by_question.values())

        pct_scores = [_submission_pct(s) for s in best_subs if _submission_pct(s) is not None]
        avg = round(sum(pct_scores) / len(pct_scores), 1) if pct_scores else None

        # Completion = unique questions done / total questions in course
        completion_pct = round((unique_attempted / total_questions) * 100) if total_questions else 0
        completion_pct = min(completion_pct, 100)

        result.append({
            'course_code':       e.course.code,
            'course_name':       e.course.name,
            'total_questions':   total_questions,
            'attempted':         unique_attempted,
            'total_papers':      total_questions,   # compat alias
            'submitted':         unique_attempted,  # compat alias
            'progress_pct':      completion_pct,
            'avg_score':         avg,
        })
    return JsonResponse(result, safe=False)


# ═══════════════════════════════════════════════════════════════
#  ANSWER CRUD  (full: create already exists, adding edit/delete)
# ═══════════════════════════════════════════════════════════════

def api_teacher_answer_edit(request, ans_id):
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from .models import ModelAnswer
    try:
        ans = ModelAnswer.objects.get(pk=ans_id, paper__course__in=_lecturer_courses(request))
    except ModelAnswer.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
    ans.question_ref = request.POST.get('question_ref', ans.question_ref)
    ans.topic        = request.POST.get('topic', ans.topic)
    ans.answer_text  = request.POST.get('answer_text', ans.answer_text)
    ans.key_points   = request.POST.get('key_points', ans.key_points)
    ans.marks        = int(request.POST.get('marks', ans.marks) or ans.marks)
    ans.criteria     = request.POST.get('criteria', ans.criteria)
    if 'file' in request.FILES:
        ans.file = request.FILES['file']
    ans.save()
    return JsonResponse({'ok': True})


def api_teacher_answer_delete(request, ans_id):
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from .models import ModelAnswer
    try:
        ans = ModelAnswer.objects.get(pk=ans_id, paper__course__in=_lecturer_courses(request))
        ans.delete()
        return JsonResponse({'ok': True})
    except ModelAnswer.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)


def api_teacher_answer_detail(request, ans_id):
    if not _lecturer_required(request):
        return JsonResponse({}, status=403)
    from .models import ModelAnswer
    try:
        a = ModelAnswer.objects.get(pk=ans_id, paper__course__in=_lecturer_courses(request))
        return JsonResponse({
            'id': a.pk,
            'question_ref': a.question_ref,
            'topic': a.topic,
            'answer_text': a.answer_text,
            'key_points': a.key_points,
            'marks': a.marks,
            'criteria': a.criteria,
            'paper_id': a.paper_id,
            'file_url': a.file.url if a.file else None,
        })
    except ModelAnswer.DoesNotExist:
        return JsonResponse({}, status=404)


# ═══════════════════════════════════════════════════════════════
#  PAPER CRUD  (add edit endpoint)
# ═══════════════════════════════════════════════════════════════

def api_teacher_paper_edit(request, paper_id):
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from .models import PastPaper
    try:
        paper = PastPaper.objects.get(pk=paper_id, uploaded_by=request.user)
    except PastPaper.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
    paper.title         = request.POST.get('title', paper.title)
    paper.period        = request.POST.get('period', paper.period)
    paper.academic_year = request.POST.get('academic_year', paper.academic_year)
    paper.total_marks   = int(request.POST.get('total_marks', paper.total_marks) or paper.total_marks)
    paper.duration_mins = int(request.POST.get('duration_mins', paper.duration_mins) or paper.duration_mins)
    paper.num_questions = int(request.POST.get('num_questions', getattr(paper, 'num_questions', 0)) or getattr(paper, 'num_questions', 0))
    paper.notes         = request.POST.get('notes', paper.notes)
    if 'file' in request.FILES:
        paper.file = request.FILES['file']
    paper.save()
    return JsonResponse({'ok': True})


def api_teacher_paper_detail(request, paper_id):
    if not _lecturer_required(request):
        return JsonResponse({}, status=403)
    from .models import PastPaper
    try:
        p = PastPaper.objects.get(pk=paper_id, uploaded_by=request.user)
        return JsonResponse({
            'id': p.pk, 'title': p.title, 'period': p.period,
            'academic_year': p.academic_year, 'total_marks': p.total_marks,
            'duration_mins': p.duration_mins,
            'num_questions': getattr(p, 'num_questions', 0) or 0,
            'notes': p.notes,
            'course_id': p.course_id,
            'file_url': p.file.url if p.file else None,
        })
    except PastPaper.DoesNotExist:
        return JsonResponse({}, status=404)


def api_teacher_paper_scan_questions(request, paper_id):
    """Scan an already-saved paper file and return detected question count."""
    if not _lecturer_required(request):
        return JsonResponse({'ok': False}, status=403)
    from .models import PastPaper
    try:
        paper = PastPaper.objects.get(pk=paper_id, uploaded_by=request.user)
    except PastPaper.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
    if not paper.file:
        return JsonResponse({'ok': False, 'error': 'No file attached to this paper.'})
    try:
        count = _count_questions_in_file(paper.file)
        if count > 0:
            paper.num_questions = count
            paper.save(update_fields=['num_questions'])
            return JsonResponse({'ok': True, 'count': count})
        else:
            return JsonResponse({'ok': False, 'error': 'Could not detect questions. Please enter the count manually.'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})
    if not _lecturer_required(request):
        return JsonResponse({}, status=403)
    from .models import PastPaper
    try:
        p = PastPaper.objects.get(pk=paper_id, uploaded_by=request.user)
        return JsonResponse({
            'id': p.pk, 'title': p.title, 'period': p.period,
            'academic_year': p.academic_year, 'total_marks': p.total_marks,
            'duration_mins': p.duration_mins, 'num_questions': getattr(p, 'num_questions', 0) or 0,
            'notes': p.notes,
            'course_id': p.course_id,
            'file_url': p.file.url if p.file else None,
        })
    except PastPaper.DoesNotExist:
        return JsonResponse({}, status=404)


# ═══════════════════════════════════════════════════════════════
#  STUDENT EXEMPLAR ANSWERS
# ═══════════════════════════════════════════════════════════════

def api_teacher_exemplars(request):
    """GET ?paper_id= — list all exemplar answers for teacher's papers"""
    if not _lecturer_required(request):
        return JsonResponse([], safe=False)
    from .models import StudentExemplar
    courses = _lecturer_courses(request)
    qs = StudentExemplar.objects.filter(
        paper__course__in=courses
    ).select_related('paper__course')
    paper_id   = request.GET.get('paper_id', '').strip()
    course_param = request.GET.get('course', '').strip()
    if paper_id:
        qs = qs.filter(paper_id=paper_id)
    if course_param:
        qs = qs.filter(paper__course__pk=course_param)
    result = []
    for e in qs:
        result.append({
            'id': e.pk,
            'paper_id': e.paper_id,
            'paper_title': e.paper.title,
            'course_code': e.paper.course.code,
            'student_name': e.student_name or 'Anonymous',
            'year': e.year,
            'question_ref': e.question_ref,
            'content_text': e.content_text,
            'score': e.score,
            'total_marks': e.total_marks,
            'commentary': e.commentary,
            'is_visible': e.is_visible,
            'file_url': e.file.url if e.file else None,
            'created_at': e.created_at.strftime('%d %b %Y'),
        })
    return JsonResponse(result, safe=False)


def api_teacher_exemplar_add(request):
    """POST multipart — add a new exemplar answer"""
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Unauthorised'}, status=403)
    from .models import StudentExemplar, PastPaper
    paper_id = request.POST.get('paper_id')
    if not paper_id:
        return JsonResponse({'ok': False, 'error': 'Paper is required.'})
    try:
        paper = PastPaper.objects.get(pk=paper_id, course__in=_lecturer_courses(request))
    except PastPaper.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Paper not found.'})
    ex = StudentExemplar(
        paper        = paper,
        added_by     = request.user,
        student_name = request.POST.get('student_name', 'Anonymous'),
        year         = request.POST.get('year', ''),
        question_ref = request.POST.get('question_ref', ''),
        content_text = request.POST.get('content_text', ''),
        score        = float(request.POST.get('score', 0) or 0) or None,
        total_marks  = int(request.POST.get('total_marks', 0) or 0),
        commentary   = request.POST.get('commentary', ''),
        is_visible   = request.POST.get('is_visible', 'true').lower() == 'true',
    )
    if 'file' in request.FILES:
        ex.file = request.FILES['file']
    ex.save()
    return JsonResponse({'ok': True, 'id': ex.pk})


def api_teacher_exemplar_edit(request, ex_id):
    """POST multipart — edit an exemplar"""
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from .models import StudentExemplar
    try:
        ex = StudentExemplar.objects.get(pk=ex_id, added_by=request.user)
    except StudentExemplar.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
    ex.student_name = request.POST.get('student_name', ex.student_name)
    ex.year         = request.POST.get('year', ex.year)
    ex.question_ref = request.POST.get('question_ref', ex.question_ref)
    ex.content_text = request.POST.get('content_text', ex.content_text)
    score_raw       = request.POST.get('score')
    ex.score        = float(score_raw) if score_raw else ex.score
    ex.total_marks  = int(request.POST.get('total_marks', ex.total_marks) or ex.total_marks)
    ex.commentary   = request.POST.get('commentary', ex.commentary)
    vis             = request.POST.get('is_visible')
    if vis is not None:
        ex.is_visible = vis.lower() == 'true'
    if 'file' in request.FILES:
        ex.file = request.FILES['file']
    ex.save()
    return JsonResponse({'ok': True})


def api_teacher_exemplar_delete(request, ex_id):
    """POST — delete an exemplar"""
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from .models import StudentExemplar
    try:
        ex = StudentExemplar.objects.get(pk=ex_id, added_by=request.user)
        ex.delete()
        return JsonResponse({'ok': True})
    except StudentExemplar.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)


def api_teacher_exemplar_detail(request, ex_id):
    """GET — get a single exemplar for editing"""
    if not _lecturer_required(request):
        return JsonResponse({}, status=403)
    from .models import StudentExemplar
    try:
        e = StudentExemplar.objects.get(pk=ex_id, added_by=request.user)
        return JsonResponse({
            'id': e.pk, 'paper_id': e.paper_id,
            'student_name': e.student_name, 'year': e.year,
            'question_ref': e.question_ref, 'content_text': e.content_text,
            'score': e.score, 'total_marks': e.total_marks,
            'commentary': e.commentary, 'is_visible': e.is_visible,
            'file_url': e.file.url if e.file else None,
        })
    except StudentExemplar.DoesNotExist:
        return JsonResponse({}, status=404)


# ═══════════════════════════════════════════════════════════════
#  STUDENT-FACING EXEMPLAR API
# ═══════════════════════════════════════════════════════════════

def api_student_exemplars(request):
    """GET ?course_id= — exemplars visible to students"""
    if not _student_required(request):
        return JsonResponse([], safe=False)
    from .models import StudentExemplar, Enrolment
    enrolled = Enrolment.objects.filter(
        student=request.user
    ).values_list('course_id', flat=True)
    qs = StudentExemplar.objects.filter(
        paper__course__in=enrolled, is_visible=True
    ).select_related('paper__course')
    course_id = request.GET.get('course_id')
    if course_id:
        qs = qs.filter(paper__course_id=course_id)
    result = []
    for e in qs:
        result.append({
            'id': e.pk,
            'course_code': e.paper.course.code,
            'course_name': e.paper.course.name,
            'paper_title': e.paper.title,
            'student_name': e.student_name or 'Anonymous',
            'year': e.year,
            'question_ref': e.question_ref,
            'content_text': e.content_text,
            'score': e.score,
            'total_marks': e.total_marks,
            'commentary': e.commentary,
            'file_url': e.file.url if e.file else None,
            'created_at': e.created_at.strftime('%d %b %Y'),
        })
    return JsonResponse(result, safe=False)


# ═══════════════════════════════════════════════════════════════
#  SUBMISSION REVIEW DETAIL  (for teacher grading modal)
# ═══════════════════════════════════════════════════════════════

def api_teacher_submission_detail(request, sub_id):
    if not _lecturer_required(request):
        return JsonResponse({}, status=403)
    from .models import Submission
    try:
        s = Submission.objects.get(
            pk=sub_id, paper__course__in=_lecturer_courses(request)
        )
        return JsonResponse({
            'id': s.pk,
            'student_name': s.student.get_full_name(),
            'student_email': s.student.email,
            'course_code': s.paper.course.code,
            'paper_title': s.paper.title,
            'question': s.answer.question_ref if s.answer else 'General',
            'answer_text': s.answer_text,
            'file_url': s.file.url if s.file else None,
            'submitted_at': s.submitted_at.strftime('%d %b %Y, %H:%M'),
            'score': s.score,
            'feedback': s.feedback,
            'status': 'graded' if s.score is not None else 'pending',
            'total_marks': s.paper.total_marks,
        })
    except Submission.DoesNotExist:
        return JsonResponse({}, status=404)


# ═══════════════════════════════════════════════════════════════
#  TEXTBOOK / MATERIAL EDIT
# ═══════════════════════════════════════════════════════════════

def api_teacher_textbook_edit(request, tb_id):
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from .models import Textbook
    try:
        tb = Textbook.objects.get(pk=tb_id, uploaded_by=request.user)
    except Textbook.DoesNotExist:
        return JsonResponse({'ok': False}, status=404)
    tb.title       = request.POST.get('title', tb.title)
    tb.authors     = request.POST.get('authors', tb.authors)
    tb.edition     = request.POST.get('edition', tb.edition)
    tb.isbn        = request.POST.get('isbn', tb.isbn)
    tb.chapters    = request.POST.get('chapters', tb.chapters)
    tb.description = request.POST.get('description', tb.description)
    if 'file' in request.FILES:
        tb.file = request.FILES['file']
    tb.save()
    return JsonResponse({'ok': True})


def api_teacher_material_edit(request, mat_id):
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from .models import StudyMaterial
    try:
        mat = StudyMaterial.objects.get(pk=mat_id, uploaded_by=request.user)
    except StudyMaterial.DoesNotExist:
        return JsonResponse({'ok': False}, status=404)
    mat.title         = request.POST.get('title', mat.title)
    mat.material_type = request.POST.get('material_type', mat.material_type)
    mat.description   = request.POST.get('description', mat.description)
    if 'file' in request.FILES:
        mat.file = request.FILES['file']
    mat.save()
    return JsonResponse({'ok': True})


# ─────────────────────────────────────────────────────────────
#  ADMIN API — list approved lecturers (for course assignment)
# ─────────────────────────────────────────────────────────────
def api_admin_lecturers_list(request):
    if not request.user.is_authenticated or request.user.role != 'admin':
        return JsonResponse([], safe=False)
    lecturers = GizmoUser.objects.filter(
        role='lecturer', is_approved=True
    ).values('id', 'first_name', 'last_name', 'email')
    result = [{'id': l['id'], 'name': f"{l['first_name']} {l['last_name']}".strip(), 'email': l['email']} for l in lecturers]
    return JsonResponse(result, safe=False)


# ═══════════════════════════════════════════════════════════════
#  AI TRAINING & STATUS API
# ═══════════════════════════════════════════════════════════════

# ── Training state (module-level, shared across requests) ───────────────────
import threading as _threading
_training_lock   = _threading.Lock()
_training_active = False   # True while a training run is in progress


def api_ai_train(request):
    """
    POST /api/ai/train/
    Starts training in a background thread and returns immediately.
    Frontend should poll GET /api/ai/status/ for the result.
    Lecturer/admin only.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'Unauthorised'}, status=403)
    if request.user.role not in ('lecturer', 'admin'):
        return JsonResponse({'ok': False, 'error': 'Lecturer access required'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    global _training_active
    with _training_lock:
        if _training_active:
            # Already running — return current status so frontend can poll
            try:
                from gizmo_ai.gizmo_trainer import GizmoTrainer
                d = GizmoTrainer.get_latest_report_dict()
            except Exception:
                d = {}
            d['ok']      = True
            d['status']  = 'already_running'
            d['message'] = 'Training already in progress — polling for result.'
            return JsonResponse(d)
        _training_active = True

    course_id = request.POST.get('course_id') or None
    if course_id:
        try:    course_id = int(course_id)
        except: course_id = None

    def _run():
        global _training_active
        try:
            from gizmo_ai.gizmo_trainer import GizmoTrainer
            GizmoTrainer.train(course_id=course_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f'Background training failed: {e}')
        finally:
            global _training_active
            _training_active = False

    t = _threading.Thread(target=_run, daemon=True, name='geizmo-train')
    t.start()

    return JsonResponse({
        'ok':      True,
        'status':  'training_started',
        'message': 'Training started in background. Poll /api/ai/status/ for results.',
    })


def api_ai_status(request):
    """
    GET /api/ai/status/
    Returns the latest training report plus live training_in_progress flag.
    Lecturer/admin only.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False}, status=403)

    try:
        from gizmo_ai.gizmo_trainer import GizmoTrainer
        d = GizmoTrainer.get_latest_report_dict()
        d['ok']                 = True
        d['training_in_progress'] = _training_active   # live flag for polling
        # Also add current model info
        try:
            from gizmo_ai.gizmo_engine import _SBERT_AVAILABLE, _sbert_model
            d['sbert_loaded']    = _sbert_model is not None
            d['sbert_available'] = _SBERT_AVAILABLE
        except Exception:
            d['sbert_loaded']    = False
            d['sbert_available'] = False
        return JsonResponse(d)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})


def api_ai_status_public(request):
    """
    GET /api/ai/status/public/
    Returns a minimal status for the student dashboard.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False}, status=403)
    try:
        from gizmo_ai.gizmo_trainer import GizmoTrainer
        d = GizmoTrainer.get_latest_report_dict()
        return JsonResponse({
            'ok': True,
            'confidence_score': d.get('confidence_score', 0),
            'confidence_label': d.get('confidence_label', 'Not trained'),
            'similarity_method': d.get('similarity_method', 'tfidf'),
            'trained_at': d.get('trained_at', ''),
            'n_model_answers': d.get('n_model_answers', 0),
        })
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})


def api_ai_training_history(request):
    """
    GET /api/ai/history/
    Returns the last 10 training runs for the chart on the dashboard.
    """
    if not request.user.is_authenticated or request.user.role not in ('lecturer', 'admin'):
        return JsonResponse([], safe=False, status=403)
    try:
        from .models import AITrainingLog
        logs = AITrainingLog.objects.order_by('-created_at')[:10]
        return JsonResponse([{
            'id':               l.pk,
            'confidence_score': l.confidence_score,
            'confidence_label': l.confidence_label,
            'n_model_answers':  l.n_model_answers,
            'n_key_points':     l.n_key_points,
            'n_exemplars':      l.n_exemplars,
            'n_graded_subs':    l.n_graded_subs,
            'mae':              l.mae,
            'pearson_r':        l.pearson_r,
            'grade_band_acc':   l.grade_band_acc,
            'similarity_method':l.similarity_method,
            'created_at':       l.created_at.strftime('%Y-%m-%d %H:%M'),
        } for l in logs], safe=False)
    except Exception as e:
        return JsonResponse([], safe=False)


def api_student_submission_feedback(request, sub_id):
    """
    GET /api/student/submission/<sub_id>/feedback/
    Returns full structured AI feedback for the student.
    """
    import json as _json
    if not _student_required(request):
        return JsonResponse({}, status=403)
    try:
        from .models import Submission
        sub = Submission.objects.select_related(
            'paper', 'paper__course', 'answer'
        ).get(pk=sub_id, student=request.user)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)

    if not sub.feedback:
        # No feedback yet — try auto-grading now
        try:
            from gizmo_ai.ai_integration import auto_grade_submission
            auto_grade_submission(sub.pk)
            sub.refresh_from_db()
        except Exception:
            pass

    if not sub.feedback:
        return JsonResponse({'ok': False, 'error': 'No AI feedback available yet. Model answer may not exist for this paper.'})

    try:
        data = _json.loads(sub.feedback)
    except Exception:
        data = {'overall_feedback': sub.feedback}

    # Enrich with textbook/resource details from DB
    try:
        from .models import StudyMaterial, Textbook
        rec_resources = data.get('recommended_resources', [])
        enriched = []
        for r in rec_resources:
            rid   = r.get('id')
            rtype = r.get('type', '')
            if rid:
                if rtype == 'material':
                    try:
                        m = StudyMaterial.objects.get(pk=rid)
                        r['file_url'] = m.file.url if m.file else None
                        r['title']    = m.title
                    except Exception: pass
                elif rtype == 'textbook':
                    try:
                        t = Textbook.objects.get(pk=rid)
                        r['file_url'] = t.file.url if t.file else None
                        r['title']    = t.title
                        r['chapters'] = t.relevant_chapters or ''
                    except Exception: pass
            enriched.append(r)
        data['recommended_resources'] = enriched
    except Exception:
        pass

    data['ok'] = True
    data['submission_id'] = sub.pk
    data['score']         = sub.score
    data['total_marks']   = sub.paper.total_marks
    data['paper_title']   = sub.paper.title
    data['submitted_at']  = sub.submitted_at.strftime('%d %b %Y, %H:%M')
    return JsonResponse(data)


def api_student_regrade(request, sub_id):
    """
    POST /api/student/submission/<sub_id>/regrade/
    Re-grades a submission (e.g. after model answer added).
    """
    if not _student_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    try:
        from .models import Submission
        sub = Submission.objects.get(pk=sub_id, student=request.user)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
    try:
        from gizmo_ai.ai_integration import auto_grade_submission
        ok = auto_grade_submission(sub_id)
        sub.refresh_from_db()
        return JsonResponse({
            'ok': ok,
            'score': sub.score,
            'feedback': sub.feedback,
        })
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})


# ═══════════════════════════════════════════════════════════════
#  ACTIVE LEARNING — Dataset Candidate Review
# ═══════════════════════════════════════════════════════════════

def api_dataset_candidates(request):
    """GET /api/ai/dataset/candidates/ — pending flagged submissions."""
    if not _lecturer_required(request):
        return JsonResponse([], safe=False, status=403)
    from gizmo_ai.active_learning import get_pending_candidates, get_dataset_stats
    return JsonResponse({
        'ok':        True,
        'candidates': get_pending_candidates(request.user),
        'stats':      get_dataset_stats(request.user),
    })


def api_dataset_scan(request):
    """
    POST /api/ai/dataset/scan/
    Retroactively scans all existing graded submissions and flags
    any that pass the quality gates but were missed.
    """
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Unauthorised'}, status=403)
    try:
        from gizmo_ai.active_learning import retroactive_scan
        result = retroactive_scan(request.user)
        result['ok'] = True
        return JsonResponse(result)
    except Exception as e:
        import traceback
        return JsonResponse({
            'ok': False,
            'error': str(e),
            'flagged': 0, 'skipped': 0, 'total_scanned': 0,
        })


def api_dataset_approve(request, sub_id):
    """POST /api/ai/dataset/<sub_id>/approve/"""
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    visible = request.POST.get('visible', 'true') != 'false'
    from gizmo_ai.active_learning import approve_submission_for_dataset
    ok, msg = approve_submission_for_dataset(sub_id, request.user, visible_to_students=visible)
    return JsonResponse({'ok': ok, 'message': msg})


def api_dataset_reject(request, sub_id):
    """POST /api/ai/dataset/<sub_id>/reject/"""
    if not _lecturer_required(request) or request.method != 'POST':
        return JsonResponse({'ok': False}, status=403)
    from gizmo_ai.active_learning import reject_submission_for_dataset
    ok, msg = reject_submission_for_dataset(sub_id, request.user)
    return JsonResponse({'ok': ok, 'message': msg})