"""
GEIZMO Active Learning Pipeline
================================
Automatically grows the training dataset from student submissions.

Flow:
  1. Student submits answer
  2. AI grades it (score ≥ THRESHOLD and quality checks pass)
  3. Submission is flagged: flagged_for_dataset=True, dataset_approved=None
  4. Lecturer sees a "Dataset Candidates" panel — one-click Approve / Reject
  5. On Approve → answer is saved as a new StudentExemplar automatically
  6. AI retrains silently in the background
  7. Confidence score rises over time

Quality checks before flagging (prevents poisoning):
  - Score percentage ≥ QUALITY_THRESHOLD (default 90%)
  - Answer length ≥ MIN_WORDS (min 10 words — supports short-answer questions)
  - Similarity to existing exemplars < DUPLICATE_THRESHOLD (not a copy)
  - Not already flagged/approved for this paper+question
"""

from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────

QUALITY_THRESHOLD   = 90.0   # minimum % score to be considered
MIN_WORDS           = 10     # minimum word count (supports short-answer questions)
DUPLICATE_THRESHOLD = 0.92   # if >92% similar to an existing exemplar → skip (it's basically a copy)
MAX_FLAGS_PER_QUESTION = 10  # don't flood lecturer with too many candidates per question


# ─────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT — call this right after auto_grade_submission
# ─────────────────────────────────────────────────────────────

def check_and_flag_submission(submission_id: int) -> bool:
    """
    Evaluate whether a graded submission is good enough to be a dataset candidate.
    If yes, sets submission.flagged_for_dataset = True.
    Returns True if flagged, False otherwise.
    """
    try:
        from apps.users.models import Submission, StudentExemplar
        import json as _j

        sub = Submission.objects.select_related(
            'paper', 'paper__course', 'answer', 'student'
        ).get(pk=submission_id)

        # ── Already reviewed? (handle missing field gracefully) ──
        try:
            if sub.flagged_for_dataset or sub.dataset_approved is not None:
                return False
        except AttributeError:
            # Migration 0008 not run yet — field doesn't exist on this DB
            # We'll still try to flag it; save will fail gracefully below
            pass

        # ── Must be graded with a score ──────────────────────
        if sub.score is None or not sub.answer_text:
            return False

        # ── Score threshold using question marks ─────────────
        if sub.answer and sub.answer.marks:
            out_of = float(sub.answer.marks)
        else:
            out_of = float(sub.paper.total_marks or 100)
        pct = (sub.score / out_of) * 100
        if pct < QUALITY_THRESHOLD:
            logger.debug(f"Sub {submission_id}: {pct:.1f}% < {QUALITY_THRESHOLD}% — not flagged")
            return False

        # ── Minimum word count ────────────────────────────────
        word_count = len(sub.answer_text.split())
        if word_count < MIN_WORDS:
            logger.debug(f"Sub {submission_id}: too short ({word_count} words) — not flagged")
            return False

        # ── Duplicate check ───────────────────────────────────
        if _is_duplicate_of_existing_exemplar(sub):
            logger.debug(f"Sub {submission_id}: duplicate of existing exemplar — not flagged")
            return False

        # ── Queue cap ─────────────────────────────────────────
        try:
            existing_flags = Submission.objects.filter(
                paper=sub.paper,
                answer=sub.answer,
                flagged_for_dataset=True,
                dataset_approved=None,
            ).count()
            if existing_flags >= MAX_FLAGS_PER_QUESTION:
                return False
        except Exception:
            pass  # field missing — skip cap check

        # ── Flag it ───────────────────────────────────────────
        try:
            sub.flagged_for_dataset = True
            sub.save(update_fields=['flagged_for_dataset'])
        except Exception as save_err:
            logger.warning(
                f"Sub {submission_id}: could not save flagged_for_dataset — "
                f"migration 0008 may not be applied. Error: {save_err}"
            )
            return False

        logger.info(
            f"Submission {submission_id} flagged: {pct:.1f}% "
            f"({sub.score}/{out_of}), {word_count} words, "
            f"course={sub.paper.course.code}"
        )
        return True

    except Exception as e:
        logger.exception(f"check_and_flag_submission({submission_id}) failed: {e}")
        return False


def _is_duplicate_of_existing_exemplar(sub) -> bool:
    """
    Returns True if the submission is too similar to any existing approved exemplar
    for the same paper/question — prevents near-copies from being added.
    """
    try:
        from apps.users.models import StudentExemplar
        from gizmo_ai.gizmo_engine import SimilarityEngine

        existing = StudentExemplar.objects.filter(
            paper=sub.paper,
        ).values_list('content_text', flat=True)

        if not existing:
            return False

        for ex_text in existing:
            if not ex_text:
                continue
            sim, _ = SimilarityEngine.compute(sub.answer_text, ex_text)
            if sim >= DUPLICATE_THRESHOLD:
                return True

        return False
    except Exception as e:
        logger.warning(f"Duplicate check failed: {e}")
        return False  # if check fails, don't block flagging


# ─────────────────────────────────────────────────────────────
#  APPROVE — lecturer clicks Approve
# ─────────────────────────────────────────────────────────────

def approve_submission_for_dataset(
    submission_id: int,
    approved_by_user,
    visible_to_students: bool = True,
) -> tuple[bool, str]:
    """
    Convert a flagged submission into a StudentExemplar.
    Returns (success, message).
    """
    import datetime
    try:
        from apps.users.models import Submission, StudentExemplar

        sub = Submission.objects.select_related(
            'paper', 'answer', 'student'
        ).get(pk=submission_id)

        if not sub.flagged_for_dataset:
            return False, "Submission was not flagged for dataset."

        if sub.dataset_approved is True:
            return False, "Already approved."

        total = sub.paper.total_marks or (sub.answer.marks if sub.answer else 0) or 0

        # Create exemplar — anonymised
        ex = StudentExemplar.objects.create(
            paper        = sub.paper,
            answer_ref   = sub.answer,
            added_by     = approved_by_user,
            student_name = "Anonymous",
            year         = str(sub.submitted_at.year),
            question_ref = sub.answer.question_ref if sub.answer else "",
            content_text = sub.answer_text,
            score        = sub.score,
            total_marks  = int(total),
            commentary   = f"Auto-flagged by AI ({(sub.score/total*100) if total else 0:.1f}%) — approved by lecturer.",
            is_visible   = visible_to_students,
        )

        # Mark submission as approved
        sub.dataset_approved    = True
        sub.dataset_reviewed_at = datetime.datetime.now()
        sub.save(update_fields=['dataset_approved', 'dataset_reviewed_at'])

        logger.info(
            f"Submission {submission_id} approved → Exemplar {ex.pk} created "
            f"({sub.paper.course.code}, score={sub.score}/{total})"
        )

        # ── Silent background retrain ─────────────────────────
        try:
            from gizmo_ai.gizmo_trainer import GizmoTrainer
            import threading
            t = threading.Thread(target=GizmoTrainer.train, daemon=True)
            t.start()
            logger.info("Background retrain triggered after dataset approval.")
        except Exception as re:
            logger.warning(f"Background retrain failed to start: {re}")

        return True, f"Approved ✓ — saved as Exemplar #{ex.pk} and retraining in background."

    except Exception as e:
        logger.exception(f"approve_submission_for_dataset({submission_id}) failed: {e}")
        return False, str(e)


def reject_submission_for_dataset(submission_id: int, rejected_by_user) -> tuple[bool, str]:
    """
    Lecturer rejects — mark as reviewed so it stops appearing in the queue.
    """
    import datetime
    try:
        from apps.users.models import Submission
        sub = Submission.objects.get(pk=submission_id)
        sub.dataset_approved    = False
        sub.dataset_reviewed_at = datetime.datetime.now()
        sub.save(update_fields=['dataset_approved', 'dataset_reviewed_at'])
        logger.info(f"Submission {submission_id} rejected for dataset.")
        return True, "Rejected — submission will not be added to dataset."
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────
#  STATS — for the dashboard panel
# ─────────────────────────────────────────────────────────────

def get_dataset_stats(lecturer_user) -> dict:
    """
    Returns counts for the active learning dashboard panel.
    Scoped to courses taught by this lecturer.
    """
    try:
        from apps.users.models import Submission, Course

        courses = Course.objects.filter(lecturer=lecturer_user)

        base_qs = Submission.objects.filter(
            paper__course__in=courses,
            flagged_for_dataset=True,
        )

        return {
            'pending':  base_qs.filter(dataset_approved=None).count(),
            'approved': base_qs.filter(dataset_approved=True).count(),
            'rejected': base_qs.filter(dataset_approved=False).count(),
            'total':    base_qs.count(),
        }
    except Exception as e:
        logger.warning(f"get_dataset_stats failed: {e}")
        return {'pending': 0, 'approved': 0, 'rejected': 0, 'total': 0}


def get_pending_candidates(lecturer_user, limit: int = 20) -> list:
    """
    Returns pending flagged submissions for lecturer review.
    """
    try:
        from apps.users.models import Submission, Course
        import json as _j

        courses = Course.objects.filter(lecturer=lecturer_user)

        subs = Submission.objects.filter(
            paper__course__in=courses,
            flagged_for_dataset=True,
            dataset_approved=None,
        ).select_related('paper', 'paper__course', 'answer', 'student').order_by('-submitted_at')[:limit]

        result = []
        for s in subs:
            # Use question-level marks as denominator (same fix as views.py)
            if s.answer and s.answer.marks:
                out_of = float(s.answer.marks)
            else:
                out_of = float(s.paper.total_marks or 100)
            pct = round(s.score / out_of * 100, 1) if s.score is not None else None

            # Get AI feedback summary
            overall_fb = ''
            kp_covered = 0
            kp_total   = 0
            if s.feedback:
                try:
                    d = _j.loads(s.feedback)
                    overall_fb = d.get('overall_feedback', '')
                    kps = d.get('key_point_results', [])
                    kp_covered = sum(1 for k in kps if k.get('covered'))
                    kp_total   = len(kps)
                except Exception:
                    pass

            result.append({
                'id':           s.pk,
                'course_code':  s.paper.course.code,
                'paper_title':  s.paper.title,
                'question':     s.answer.question_ref if s.answer else 'General',
                'answer_text':  s.answer_text[:600] + ('…' if len(s.answer_text) > 600 else ''),
                'score':        s.score,
                'total_marks':  out_of,
                'score_pct':    pct,
                'word_count':   len(s.answer_text.split()),
                'kp_covered':   kp_covered,
                'kp_total':     kp_total,
                'feedback':     overall_fb,
                'submitted_at': s.submitted_at.strftime('%d %b %Y, %H:%M'),
            })
        return result
    except Exception as e:
        logger.warning(f"get_pending_candidates failed: {e}")
        return []


def retroactive_scan(lecturer_user) -> dict:
    """
    Scans ALL existing graded submissions for this lecturer's courses
    and flags any that pass the quality gates but were never flagged.
    Handles missing DB fields gracefully (e.g. migration not yet run).
    Returns {'flagged': N, 'skipped': M, 'total_scanned': K}
    """
    try:
        from apps.users.models import Submission, Course

        courses = Course.objects.filter(lecturer=lecturer_user)

        # Broad filter — only require a score and course match
        # Do NOT filter on flagged_for_dataset here — that field may not exist
        all_graded = Submission.objects.filter(
            paper__course__in=courses,
            score__isnull=False,
        ).select_related('paper', 'paper__course', 'answer')

        flagged = 0
        skipped = 0
        total   = 0

        for sub in all_graded:
            if not sub.answer_text or not sub.answer_text.strip():
                continue
            total += 1

            # Safely check if already processed
            try:
                if sub.flagged_for_dataset or sub.dataset_approved is not None:
                    skipped += 1
                    continue
            except AttributeError:
                # Field doesn't exist yet — migration not run, proceed anyway
                pass

            if check_and_flag_submission(sub.pk):
                flagged += 1
            else:
                skipped += 1

        logger.info(
            f"Retroactive scan: {flagged} flagged, {skipped} skipped "
            f"of {total} text submissions for {lecturer_user}"
        )
        return {'flagged': flagged, 'skipped': skipped, 'total_scanned': total}
    except Exception as e:
        logger.exception(f"retroactive_scan failed: {e}")
        return {'flagged': 0, 'skipped': 0, 'total_scanned': 0, 'error': str(e)}