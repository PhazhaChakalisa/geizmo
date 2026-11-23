"""
GIZMO AI Integration Layer
===========================
Django views/utilities that connect the AI engine to the database.

Add these to apps/users/views.py OR keep as a separate file and import.

Key entry point:
    auto_grade_submission(submission_id)
    — called after a student submits an answer
"""

from __future__ import annotations
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN AUTO-GRADER  — call this after saving a Submission
# ─────────────────────────────────────────────────────────────────────────────

def auto_grade_submission(submission_id: int) -> bool:
    """
    Load a Submission, run the AI grader, save result back to DB.

    Returns True if grading succeeded, False on error.

    Call from view after sub.save():
        from apps.users.ai_integration import auto_grade_submission
        auto_grade_submission(sub.pk)
    """
    try:
        from apps.users.models import Submission, ModelAnswer, StudyMaterial, Textbook

        sub = Submission.objects.select_related(
            'paper', 'paper__course', 'answer'
        ).get(pk=submission_id)

        # ── Get student answer text ───────────────────────────
        student_text = sub.answer_text or ""
        if not student_text and sub.file:
            student_text = _extract_file_text(sub.file.path)

        if not student_text or not student_text.strip():
            logger.warning(f"Submission {submission_id}: no text to grade.")
            return False

        # ── Find best model answer ─────────────────────────────
        model_answer = _find_model_answer(sub)
        if model_answer is None:
            logger.info(f"Submission {submission_id}: no model answer — skipping AI grade.")
            return False

        # ── Build resources list ──────────────────────────────
        course = sub.paper.course
        resources = _get_course_resources(course)

        # ── Run AI grader ─────────────────────────────────────
        from gizmo_ai.gizmo_engine import GizmoGrader
        result = GizmoGrader.grade(
            student_text        = student_text,
            model_answer        = model_answer,
            available_resources = resources,
        )

        # ── Save results to submission ────────────────────────
        sub.score    = result.predicted_score
        sub.feedback = result.to_json_feedback()
        sub.answer   = model_answer   # link to the model answer used
        sub.save(update_fields=['score', 'feedback', 'answer'])

        logger.info(
            f"Submission {submission_id} graded: {result.predicted_score}/"
            f"{result.total_marks} ({result.predicted_percentage}%) "
            f"via {result.similarity_method}"
        )
        return True

    except Exception as e:
        logger.exception(f"auto_grade_submission({submission_id}) failed: {e}")
        return False


def _extract_file_text(file_path: str) -> str:
    """Extract text from the uploaded file."""
    try:
        from gizmo_ai.file_extractor import extract_text
        return extract_text(file_path)
    except Exception as e:
        logger.error(f"File extraction failed: {e}")
        return ""


def _find_model_answer(submission):
    """
    Find the most appropriate ModelAnswer for this submission.
    Priority:
      1. Already linked answer (sub.answer)
      2. Best match by question_ref from the same paper
      3. First available answer for this paper
    """
    from apps.users.models import ModelAnswer

    if submission.answer_id:
        return submission.answer

    answers = ModelAnswer.objects.filter(paper=submission.paper)
    if not answers.exists():
        return None

    # If only one, use it
    if answers.count() == 1:
        return answers.first()

    # Try to match by question_ref from submission metadata
    # (In future: student could select which question they're answering)
    return answers.first()


def _get_course_resources(course) -> list:
    """
    Return a flat list of resource dicts for the recommender.
    Includes both StudyMaterial and Textbooks.
    """
    from apps.users.models import StudyMaterial, Textbook
    resources = []

    materials = StudyMaterial.objects.filter(course=course)
    for m in materials:
        resources.append({
            'id':          m.pk,
            'type':        'material',
            'title':       m.title,
            'description': m.description or m.get_material_type_display(),
            'course':      f"{course.code} — {course.name}",
            'file_url':    m.file.url if m.file else None,
        })

    textbooks = Textbook.objects.filter(courses=course)
    for t in textbooks:
        resources.append({
            'id':          t.pk,
            'type':        'textbook',
            'title':       t.title,
            'description': t.description or f"{t.authors} — {t.edition}",
            'course':      f"{course.code} — {course.name}",
            'file_url':    t.file.url if t.file else None,
        })

    return resources


# ─────────────────────────────────────────────────────────────────────────────
#  DJANGO VIEW — API endpoint to re-grade a submission on demand
# ─────────────────────────────────────────────────────────────────────────────

def api_regrade_submission(request, sub_id: int):
    """
    POST /api/student/submission/<sub_id>/regrade/
    Allows a student to request re-grading (e.g. after a model answer is added).
    """
    from django.http import JsonResponse
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'Unauthorised'}, status=403)

    try:
        from apps.users.models import Submission
        sub = Submission.objects.get(pk=sub_id, student=request.user)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)

    success = auto_grade_submission(sub_id)
    if success:
        sub.refresh_from_db()
        return JsonResponse({
            'ok': True,
            'score': sub.score,
            'feedback': sub.feedback,
        })
    return JsonResponse({'ok': False, 'error': 'Grading failed or no model answer available.'})


def api_submission_feedback(request, sub_id: int):
    """
    GET /api/student/submission/<sub_id>/feedback/
    Returns the full structured AI feedback for a submission.
    """
    import json
    from django.http import JsonResponse
    if not request.user.is_authenticated:
        return JsonResponse({}, status=403)

    try:
        from apps.users.models import Submission
        sub = Submission.objects.get(pk=sub_id, student=request.user)
    except Exception:
        return JsonResponse({}, status=404)

    if not sub.feedback:
        return JsonResponse({'ok': False, 'error': 'No feedback yet.'})

    try:
        data = json.loads(sub.feedback)
        data['ok'] = True
        return JsonResponse(data)
    except Exception:
        # Old-style plain text feedback
        return JsonResponse({'ok': True, 'overall_feedback': sub.feedback})