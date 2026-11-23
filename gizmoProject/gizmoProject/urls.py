from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from apps.users import views

urlpatterns = [
    # Landing
    path('', views.landing),

    # Signup pages
    path('signup/student/',  views.student_signup),
    path('signup/lecturer/', views.lecturer_signup),

    # Signup API
    path('api/signup/step1/',    views.api_signup_step1),
    path('api/signup/step2/',    views.api_signup_step2_send_otp),
    path('api/signup/verify/',   views.api_verify_otp),
    path('api/signup/complete/', views.api_signup_complete),
    path('api/signup/resend/',   views.api_resend_otp),
    path('api/check-email/',     views.api_check_email),

    # Course API
    path('api/course/search/',              views.api_course_search),
    path('api/course/create/',              views.api_course_create),
    path('api/course/delete/<int:course_id>/', views.api_course_delete),

    # Enrolment API
    path('api/enrol/', views.api_enrol),

    # Admin
    path('api/admin/user/<int:user_id>/courses/', views.api_user_courses),
    path('api/admin/toggle-setting/',            views.api_toggle_setting),
    path('api/admin/lecturers/list/',            views.api_admin_lecturers_list),

    # Login / logout
    path('login/student/',  views.student_login),
    path('login/lecturer/', views.lecturer_login),
    path('login/admin/',    views.admin_login),
    path('logout/',         views.logout_view),

    # Pending approval
    path('pending-approval/', views.pending_approval),

    # Dashboards
    path('dashboard/student/',  views.student_dashboard),
    path('dashboard/lecturer/', views.lecturer_dashboard),
    path('dashboard/admin/',    views.admin_dashboard),

    # Admin actions
    path('dashboard/admin/approve/<int:user_id>/',   views.approve_lecturer),
    path('dashboard/admin/reject/<int:user_id>/',    views.reject_lecturer),
    path('dashboard/admin/suspend/<int:user_id>/',   views.suspend_user),
    path('dashboard/admin/unsuspend/<int:user_id>/', views.unsuspend_user),

    # Student APIs
    path('api/student/stats/',              views.api_student_stats),
    path('api/student/courses/',            views.api_student_enrolled_courses),
    path('api/student/unenrol/',            views.api_student_unenrol),
    path('api/student/submit/',             views.api_student_submit_answer),
    path('api/student/paper/<int:paper_id>/questions/', views.api_student_paper_questions),
    path('api/student/results/',            views.api_student_results),
    path('api/student/submission/<int:sub_id>/regrade/', views.api_regrade_submission),
    path('api/student/submission/<int:sub_id>/delete/',  views.api_student_delete_submission),
    path('api/student/papers/',             views.api_student_papers),
    path('api/student/resources/',          views.api_student_resources),
    path('api/student/progress/',           views.api_student_progress),
    path('api/student/exemplars/',          views.api_student_exemplars),

    # Teacher APIs
    path('api/teacher/stats/',                          views.api_teacher_stats),
    path('api/teacher/courses/list/',                   views.api_teacher_courses_list),
    path('api/teacher/courses/dashboard/',              views.api_teacher_courses_dashboard),
    path('api/teacher/activity/recent/',                views.api_teacher_activity),
    path('api/teacher/students/',                       views.api_teacher_students),

    # Papers
    path('api/teacher/papers/',                         views.api_teacher_papers),
    path('api/teacher/papers/upload/',                  views.api_teacher_paper_upload),
    path('api/teacher/papers/delete/<int:paper_id>/',   views.api_teacher_paper_delete),
    path('api/teacher/papers/for-course/',              views.api_teacher_papers_for_course),
    path('api/teacher/papers/<int:paper_id>/',          views.api_teacher_paper_detail),
    path('api/teacher/papers/<int:paper_id>/edit/',     views.api_teacher_paper_edit),
    path('api/teacher/papers/<int:paper_id>/scan/',     views.api_teacher_paper_scan_questions),

    # Model Answers
    path('api/teacher/answers/',                        views.api_teacher_answers),
    path('api/teacher/answers/upload/',                 views.api_teacher_answer_upload),
    path('api/teacher/answers/<int:ans_id>/',           views.api_teacher_answer_detail),
    path('api/teacher/answers/<int:ans_id>/edit/',      views.api_teacher_answer_edit),
    path('api/teacher/answers/<int:ans_id>/delete/',    views.api_teacher_answer_delete),

    # Exemplars
    path('api/teacher/exemplars/',                      views.api_teacher_exemplars),
    path('api/teacher/exemplars/add/',                  views.api_teacher_exemplar_add),
    path('api/teacher/exemplars/<int:ex_id>/',          views.api_teacher_exemplar_detail),
    path('api/teacher/exemplars/<int:ex_id>/edit/',     views.api_teacher_exemplar_edit),
    path('api/teacher/exemplars/<int:ex_id>/delete/',   views.api_teacher_exemplar_delete),

    # Submissions
    path('api/teacher/submissions/',                    views.api_teacher_submissions),
    path('api/teacher/submission/<int:sub_id>/',        views.api_teacher_submission_detail),
    path('api/teacher/submission/grade/<int:sub_id>/',  views.api_teacher_submission_grade),

    # Textbooks
    path('api/teacher/textbooks/',                      views.api_teacher_textbooks),
    path('api/teacher/textbook/upload/',                views.api_teacher_textbook_upload),
    path('api/teacher/textbook/delete/<int:tb_id>/',    views.api_teacher_textbook_delete),
    path('api/teacher/textbook/<int:tb_id>/edit/',      views.api_teacher_textbook_edit),

    # Study Materials
    path('api/teacher/materials/',                      views.api_teacher_materials),
    path('api/teacher/material/upload/',                views.api_teacher_material_upload),
    path('api/teacher/material/delete/<int:mat_id>/',   views.api_teacher_material_delete),
    path('api/teacher/material/<int:mat_id>/edit/',     views.api_teacher_material_edit),

    # Analytics & Account
    path('api/teacher/analytics/',                      views.api_teacher_analytics),
    path('api/teacher/account/update/',                 views.api_teacher_account_update),


    # ── AI Training & Status ──────────────────────────────────
    path('api/ai/train/',                                   views.api_ai_train),
    path('api/ai/status/',                                  views.api_ai_status),
    path('api/ai/status/public/',                           views.api_ai_status_public),
    path('api/ai/history/',                                 views.api_ai_training_history),

    # ── Active Learning — Dataset Candidates ─────────────────
    path('api/ai/dataset/candidates/',                      views.api_dataset_candidates),
    path('api/ai/dataset/scan/',                            views.api_dataset_scan),
    path('api/ai/dataset/<int:sub_id>/approve/',            views.api_dataset_approve),
    path('api/ai/dataset/<int:sub_id>/reject/',             views.api_dataset_reject),

    # ── Student AI Feedback ───────────────────────────────────
    path('api/student/submission/<int:sub_id>/feedback/',   views.api_student_submission_feedback),
    path('api/student/submission/<int:sub_id>/regrade/',    views.api_student_regrade),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)