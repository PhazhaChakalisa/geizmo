"""
GIZMO AI Training Pipeline
============================
Guided Intelligent Zone for Marking and Overview

Trains the AI grader on the lecturer's dataset:
  - Past paper questions
  - Model answers + key points
  - Exemplar answers (high-scoring real student answers)
  - Textbooks and study materials (for resource recommendation)
  - Previously graded submissions (for calibration)

Produces a TrainingReport saved to DB for display on
the lecturer/admin dashboards.

Usage (Django management command or direct):
    python manage.py shell
    >>> from gizmo_ai.gizmo_trainer import GizmoTrainer
    >>> report = GizmoTrainer.train()
    >>> print(report.summary())

Or via the API endpoint:
    POST /api/ai/train/
"""

from __future__ import annotations

import os
import sys
import json
import math
import logging
import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  TRAINING REPORT  — persisted to DB, shown on dashboards
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TrainingReport:
    """Full training result shown on lecturer/admin dashboards."""

    # Dataset stats
    n_model_answers   : int = 0
    n_key_points      : int = 0
    n_exemplars       : int = 0
    n_textbooks       : int = 0
    n_materials       : int = 0
    n_graded_subs     : int = 0   # submissions with lecturer scores used for calibration
    n_courses         : int = 0

    # Evaluation metrics (on graded submissions as test set)
    mae               : float = 0.0   # Mean Absolute Error (marks)
    rmse              : float = 0.0   # Root Mean Square Error
    pearson_r         : float = 0.0   # Pearson correlation
    spearman_r        : float = 0.0   # Spearman correlation
    grade_band_acc    : float = 0.0   # % where predicted grade band == actual
    kp_precision      : float = 0.0   # Key-point detection precision
    kp_recall         : float = 0.0   # Key-point detection recall
    kp_f1             : float = 0.0   # Key-point detection F1

    # Confidence score  0–100 computed from metrics
    confidence_score  : int   = 0
    confidence_label  : str   = "Not trained"

    # Baseline comparison (TF-IDF vs SBERT)
    baseline_mae      : float = 0.0
    improvement_pct   : float = 0.0

    # Model info
    similarity_method : str = "tfidf"  # sbert | tfidf | word_overlap
    trained_at        : str = ""
    training_duration_s: float = 0.0

    # Per-course breakdown
    course_metrics    : List[dict] = field(default_factory=list)

    # Warnings / info messages
    messages          : List[str] = field(default_factory=list)

    # Fitted regressor — serialised as base64 pickle, stored in DB
    regressor_b64     : Optional[str] = None

    def confidence_color(self) -> str:
        if self.confidence_score >= 80: return "success"
        if self.confidence_score >= 60: return "warning"
        return "danger"

    def summary(self) -> str:
        lines = [
            f"GIZMO AI Training Report — {self.trained_at}",
            f"Dataset: {self.n_model_answers} model answers, "
            f"{self.n_key_points} key points, "
            f"{self.n_exemplars} exemplars, "
            f"{self.n_graded_subs} graded submissions",
            f"Metrics: MAE={self.mae:.2f} marks, RMSE={self.rmse:.2f}, "
            f"Pearson r={self.pearson_r:.3f}, Grade-band={self.grade_band_acc:.1f}%",
            f"Confidence: {self.confidence_score}% — {self.confidence_label}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "TrainingReport":
        d = json.loads(s)
        d.pop('course_metrics', None)
        d.pop('messages', None)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─────────────────────────────────────────────────────────────────────────────
#  METRICS  (pure Python — no extra deps)
# ─────────────────────────────────────────────────────────────────────────────

def _mae(y_true, y_pred):
    if not y_true: return 0.0
    return sum(abs(a - b) for a, b in zip(y_true, y_pred)) / len(y_true)

def _rmse(y_true, y_pred):
    if not y_true: return 0.0
    return math.sqrt(sum((a - b)**2 for a, b in zip(y_true, y_pred)) / len(y_true))

def _pearson(y_true, y_pred):
    n = len(y_true)
    if n < 2: return 0.0
    mt = sum(y_true) / n
    mp = sum(y_pred) / n
    num = sum((a - mt) * (b - mp) for a, b in zip(y_true, y_pred))
    dt = math.sqrt(sum((a - mt)**2 for a in y_true))
    dp = math.sqrt(sum((b - mp)**2 for b in y_pred))
    if dt == 0 or dp == 0: return 0.0
    return round(num / (dt * dp), 4)

def _spearman(y_true, y_pred):
    def _rank(lst):
        s = sorted(enumerate(lst), key=lambda x: x[1])
        r = [0] * len(lst)
        for rank_val, (i, _) in enumerate(s):
            r[i] = rank_val + 1
        return r
    return _pearson(_rank(y_true), _rank(y_pred))

def _grade_band(pct: float) -> str:
    if pct >= 70: return "pass_high"
    if pct >= 50: return "pass"
    return "fail"

def _band_accuracy(y_true, y_pred, totals) -> float:
    if not y_true: return 0.0
    correct = sum(
        1 for t, p, tot in zip(y_true, y_pred, totals)
        if _grade_band(t / tot * 100 if tot else 0) == _grade_band(p / tot * 100 if tot else 0)
    )
    return round(correct / len(y_true) * 100, 1)

def _f1_metrics(y_true_bin, y_pred_bin):
    tp = sum(1 for t, p in zip(y_true_bin, y_pred_bin) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true_bin, y_pred_bin) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true_bin, y_pred_bin) if t == 1 and p == 0)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return round(prec, 3), round(rec, 3), round(f1, 3)


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIDENCE SCORE  — weighted composite of all metrics
# ─────────────────────────────────────────────────────────────────────────────

def _compute_confidence(report: TrainingReport) -> Tuple[int, str]:
    """
    Returns (0–100 score, label).

    Rebalanced for small academic datasets:

    Component                       Max pts  Notes
    ─────────────────────────────────────────────────────
    1. Model answers (richness)      20      Full at ≥5 answers
    2. Key points (per answer)       20      Full at ≥2 KPs/answer avg
    3. Exemplars                     10      Full at ≥3 exemplars
    4. Resources (books/materials)    5      Full at ≥2 resources
    5. SBERT loaded                  15      Binary — huge quality jump
    6. Calibration accuracy          30      From graded subs (optional)
       — MAE, Pearson, grade-band           0 subs → 0 pts (not penalised)

    Without any graded subs but with good data + SBERT → up to 70%
    With graded subs showing good accuracy → up to 100%
    """
    score = 0.0

    # ── 1. Model answers (20 pts) ─────────────────────────────
    # 1 answer = 8pts, 3 = 15pts, 5+ = 20pts  (diminishing returns)
    n_ma = report.n_model_answers
    if n_ma >= 5:
        score += 20
    elif n_ma >= 3:
        score += 15
    elif n_ma >= 2:
        score += 12
    elif n_ma == 1:
        score += 8
    # 0 = 0pts

    # ── 2. Key points depth (20 pts) ─────────────────────────
    # Want ≥2 key points per model answer on average
    if n_ma > 0:
        kp_ratio = report.n_key_points / n_ma  # avg KPs per answer
        kp_score = min(kp_ratio / 2.0, 1.0) * 20
        score += kp_score
    elif report.n_key_points > 0:
        score += min(report.n_key_points / 5, 1.0) * 20

    # ── 3. Exemplars (10 pts) ────────────────────────────────
    # Exemplars teach the model that there are multiple valid phrasings
    n_ex = report.n_exemplars
    if n_ex >= 5:
        score += 10
    elif n_ex >= 3:
        score += 8
    elif n_ex >= 1:
        score += 5

    # ── 4. Resources (5 pts) ─────────────────────────────────
    n_res = (report.n_textbooks or 0) + (report.n_materials or 0)
    if n_res >= 2:
        score += 5
    elif n_res == 1:
        score += 3

    # ── 5. SBERT loaded (15 pts) ─────────────────────────────
    # SBERT gives a massive quality boost over TF-IDF; reward it
    if report.similarity_method == 'sbert':
        score += 15

    # ── 6. Calibration accuracy (30 pts) ─────────────────────
    # Only applies if we have ≥2 graded submissions to measure against
    if report.n_graded_subs >= 2:
        # MAE component (12 pts): MAE=0→12, MAE=5→0
        mae_pts = max(0.0, 12.0 * (1.0 - report.mae / 5.0))
        score += mae_pts

        # Pearson correlation (10 pts)
        pearson_pts = max(0.0, report.pearson_r) * 10
        score += pearson_pts

        # Grade band accuracy (8 pts)
        band_pts = (report.grade_band_acc / 100.0) * 8
        score += band_pts
    elif report.n_graded_subs == 1:
        # One graded sub — partial credit, can't compute correlation
        score += 5

    # ── Clamp and label ──────────────────────────────────────
    score = min(100, max(0, int(round(score))))

    if score >= 85:
        label = "Excellent — Highly Confident"
    elif score >= 70:
        label = "Good — Confident"
    elif score >= 55:
        label = "Fair — Reasonably Confident"
    elif score >= 35:
        label = "Low — Add More Key Points"
    else:
        label = "Very Low — Add Model Answers & Key Points"

    return score, label


# ─────────────────────────────────────────────────────────────────────────────
#  SBERT WARM-UP  — pre-load model and encode the entire dataset
# ─────────────────────────────────────────────────────────────────────────────

def _warmup_sbert(all_texts: List[str]) -> bool:
    """
    Pre-encodes all model answers and key-points to warm up the cache.
    This makes the first student submission instant.
    Returns True if SBERT is available.
    """
    try:
        from gizmo_ai.gizmo_engine import _get_sbert_model
        model = _get_sbert_model()
        if model is None:
            return False
        if all_texts:
            # Batch-encode all texts — SentenceTransformer caches internally
            model.encode(all_texts, batch_size=32, show_progress_bar=False)
            logger.info(f"SBERT warmed up with {len(all_texts)} texts.")
        return True
    except Exception as e:
        logger.warning(f"SBERT warm-up failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN TRAINER
# ─────────────────────────────────────────────────────────────────────────────

class GizmoTrainer:
    """
    Main training orchestrator.

    Steps:
    1.  Load dataset from DB (model answers, key points, exemplars, resources)
    2.  Warm up SBERT by encoding all texts
    3.  Run evaluation on graded submissions (ground truth)
    4.  Compute metrics (MAE, RMSE, Pearson, Spearman, grade-band, KP F1)
    5.  Compute confidence score
    6.  Build per-course breakdown
    7.  Save TrainingReport to DB (AITrainingLog model)
    8.  Return TrainingReport
    """

    @classmethod
    def train(cls, course_id: Optional[int] = None) -> TrainingReport:
        """
        Run full training pipeline.
        If course_id given, restricts to that course.
        Returns TrainingReport.
        """
        import time
        start = time.time()

        report = TrainingReport()
        report.trained_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            report = cls._run(report, course_id)
        except Exception as e:
            logger.exception(f"Training failed: {e}")
            report.messages.append(f"Training error: {e}")

        report.training_duration_s = round(time.time() - start, 2)
        report.confidence_score, report.confidence_label = _compute_confidence(report)

        # Persist to DB
        cls._save_report(report)
        logger.info(f"Training complete in {report.training_duration_s}s — "
                    f"confidence={report.confidence_score}% ({report.confidence_label})")
        return report

    @classmethod
    def _run(cls, report: TrainingReport, course_id: Optional[int]) -> TrainingReport:
        from apps.users.models import (
            ModelAnswer, PastPaper, Submission,
            StudyMaterial, Textbook, StudentExemplar, Course
        )
        from gizmo_ai.gizmo_engine import GizmoGrader
        from gizmo_ai.ai_integration import _extract_file_text, _get_course_resources

        # ── 1. Load dataset ──────────────────────────────────────
        if course_id:
            courses = Course.objects.filter(pk=course_id)
        else:
            courses = Course.objects.all()

        report.n_courses = courses.count()

        model_answers = ModelAnswer.objects.filter(paper__course__in=courses)
        report.n_model_answers = model_answers.count()

        # Count total key points (each newline-separated point)
        total_kp = 0
        all_texts = []  # for SBERT warm-up
        for ma in model_answers:
            pts = [p.strip() for p in (ma.key_points or "").split('\n') if p.strip()]
            total_kp += len(pts)
            all_texts.append(ma.answer_text or "")
            all_texts.extend(pts)
        report.n_key_points = total_kp

        exemplars = StudentExemplar.objects.filter(paper__course__in=courses)
        report.n_exemplars = exemplars.count()
        for ex in exemplars:
            if ex.content_text:
                all_texts.append(ex.content_text)

        textbooks = Textbook.objects.filter(courses__in=courses).distinct()
        report.n_textbooks = textbooks.count()
        for tb in textbooks:
            all_texts.append(f"{tb.title} {tb.description or ''}")

        materials = StudyMaterial.objects.filter(course__in=courses)
        report.n_materials = materials.count()
        for m in materials:
            all_texts.append(f"{m.title} {m.description or ''}")

        # ── 2. SBERT warm-up ─────────────────────────────────────
        all_texts = [t for t in all_texts if t and len(t.strip()) > 3]
        sbert_ok = _warmup_sbert(all_texts)
        report.similarity_method = "sbert" if sbert_ok else "tfidf"

        if not sbert_ok:
            report.messages.append(
                "Sentence-BERT not available — using TF-IDF. "
                "Install sentence-transformers for higher accuracy."
            )

        if report.n_model_answers == 0:
            report.messages.append(
                "No model answers found. Add model answers with key points "
                "to enable AI grading."
            )
            return report

        if report.n_key_points == 0:
            report.messages.append(
                "Model answers exist but have no key points. "
                "Add key points (one per line) to each model answer for better grading."
            )

        # ── 3. Evaluate on graded submissions ────────────────────
        graded_subs = Submission.objects.filter(
            paper__course__in=courses,
            score__isnull=False,
            answer__isnull=False,
        ).select_related('paper', 'paper__course', 'answer')

        report.n_graded_subs = graded_subs.count()

        y_true, y_pred, y_totals = [], [], []
        kp_true_all, kp_pred_all = [], []
        course_data: Dict[str, dict] = {}

        for sub in graded_subs:
            student_text = sub.answer_text or ""
            if not student_text and sub.file:
                try:
                    student_text = _extract_file_text(sub.file.path)
                except Exception:
                    pass
            if not student_text.strip():
                continue

            try:
                resources = _get_course_resources(sub.paper.course)
                result = GizmoGrader.grade(
                    student_text=student_text,
                    model_answer=sub.answer,
                    available_resources=resources,
                )
                total = float(sub.answer.marks) if sub.answer and sub.answer.marks else (sub.paper.total_marks or 100)
                y_true.append(float(sub.score))
                y_pred.append(float(result.predicted_score))
                y_totals.append(float(total))

                # KP detection — use question-level marks for threshold
                sub_pct = float(sub.score) / float(total) * 100 if total else 0
                for kp in result.key_point_results:
                    kp_pred_all.append(1 if kp.covered else 0)
                    # Approximate ground truth: if sub scored well, assume KPs covered
                    kp_true_all.append(1 if sub_pct >= 50 else 0)

                # Per-course
                code = sub.paper.course.code
                if code not in course_data:
                    course_data[code] = {
                        'course': code,
                        'n': 0, 'y_true': [], 'y_pred': [], 'y_totals': []
                    }
                course_data[code]['n']       += 1
                course_data[code]['y_true'].append(float(sub.score))
                course_data[code]['y_pred'].append(float(result.predicted_score))
                course_data[code]['y_totals'].append(float(total))

            except Exception as e:
                logger.warning(f"Evaluation failed for sub {sub.pk}: {e}")

        # ── 3b. Train learned mark predictor (Ridge regressor) ──
        report.regressor_b64 = None  # will be set if training succeeds
        if len(y_true) >= 3:
            try:
                from gizmo_ai.gizmo_engine import _train_mark_predictor
                reg = _train_mark_predictor(graded_subs)
                if reg is not None:
                    import pickle, base64
                    b64 = base64.b64encode(pickle.dumps(reg)).decode()
                    report.regressor_b64 = b64
                    report.messages.insert(0,
                        f"✓ Mark predictor trained on {len(y_true)} samples using Ridge regression."
                    )
            except Exception as e:
                logger.warning(f"Regressor training failed: {e}")

        # ── 4. Metrics ───────────────────────────────────────────
        if len(y_true) >= 2:
            report.mae    = round(_mae(y_true, y_pred), 3)
            report.rmse   = round(_rmse(y_true, y_pred), 3)
            report.pearson_r  = round(_pearson(y_true, y_pred), 3)
            report.spearman_r = round(_spearman(y_true, y_pred), 3)
            report.grade_band_acc = _band_accuracy(y_true, y_pred, y_totals)
        elif len(y_true) == 1:
            report.messages.append(
                "Only 1 graded submission — need at least 2 for correlation metrics. "
                "Grade more submissions to improve evaluation."
            )
        else:
            report.messages.append(
                "No graded submissions with model answers found. "
                "Grade student submissions to calibrate the AI."
            )

        if kp_true_all and kp_pred_all:
            p, r, f1 = _f1_metrics(kp_true_all, kp_pred_all)
            report.kp_precision = p
            report.kp_recall    = r
            report.kp_f1        = f1

        # ── 5. Baseline comparison (TF-IDF) ──────────────────────
        if len(y_true) >= 2 and sbert_ok:
            # Run TF-IDF-only baseline
            baseline_pred = cls._run_tfidf_baseline(graded_subs)
            if baseline_pred:
                report.baseline_mae = round(_mae(y_true, baseline_pred[:len(y_true)]), 3)
                if report.baseline_mae > 0:
                    report.improvement_pct = round(
                        (report.baseline_mae - report.mae) / report.baseline_mae * 100, 1
                    )

        # ── 6. Per-course breakdown ───────────────────────────────
        for code, cd in course_data.items():
            if len(cd['y_true']) >= 1:
                cm = {
                    'course':      code,
                    'n':           cd['n'],
                    'mae':         round(_mae(cd['y_true'], cd['y_pred']), 2) if len(cd['y_true']) >= 2 else None,
                    'band_acc':    _band_accuracy(cd['y_true'], cd['y_pred'], cd['y_totals']) if len(cd['y_true']) >= 2 else None,
                    'avg_true':    round(sum(cd['y_true']) / len(cd['y_true']), 1),
                    'avg_pred':    round(sum(cd['y_pred']) / len(cd['y_pred']), 1),
                }
                report.course_metrics.append(cm)

        # ── 7. Data quality messages ─────────────────────────────
        if report.n_model_answers == 0:
            report.messages.append(
                "No model answers found. Add at least 1 model answer with key points "
                "to enable AI grading."
            )
        if report.n_key_points == 0 and report.n_model_answers > 0:
            report.messages.append(
                "Model answers have no key points. Open each model answer and add key points "
                "(one per line) — this is the single biggest thing you can do to improve accuracy."
            )
        elif report.n_model_answers > 0:
            avg_kp = report.n_key_points / report.n_model_answers
            if avg_kp < 2:
                report.messages.append(
                    f"Average of {avg_kp:.1f} key points per answer — aim for at least 3–5. "
                    "More key points = better mark prediction and more specific student feedback."
                )
        if report.n_exemplars == 0:
            report.messages.append(
                "No exemplar answers yet. Adding 3–5 real high-scoring student answers helps "
                "the AI understand that the same idea can be phrased in many valid ways."
            )
        if report.n_textbooks == 0 and report.n_materials == 0:
            report.messages.append(
                "No textbooks or study materials uploaded. Upload at least one textbook so "
                "students get specific chapter recommendations when they miss marking points."
            )
        if report.n_graded_subs == 0:
            report.messages.append(
                "No calibration data yet — grade a few student submissions manually so the AI "
                "can measure its own accuracy. Even 3–5 graded submissions improve calibration significantly."
            )
        elif report.n_graded_subs < 5:
            report.messages.append(
                f"Only {report.n_graded_subs} graded submission(s) for calibration. "
                "Aim for 5–10 per course to get reliable accuracy metrics."
            )

        return report

    @classmethod
    def _run_tfidf_baseline(cls, graded_subs) -> List[float]:
        """Run TF-IDF baseline for comparison — patches out SBERT temporarily."""
        try:
            import gizmo_ai.gizmo_engine as engine
            orig = engine._SBERT_AVAILABLE
            engine._SBERT_AVAILABLE = False
            preds = []
            from gizmo_ai.ai_integration import _extract_file_text, _get_course_resources
            for sub in graded_subs:
                text = sub.answer_text or ""
                if not text and sub.file:
                    try: text = _extract_file_text(sub.file.path)
                    except: pass
                if not text.strip(): continue
                try:
                    from gizmo_ai.gizmo_engine import GizmoGrader
                    r = GizmoGrader.grade(
                        student_text=text,
                        model_answer=sub.answer,
                        available_resources=[],
                    )
                    preds.append(r.predicted_score)
                except: pass
            engine._SBERT_AVAILABLE = orig
            return preds
        except Exception as e:
            logger.warning(f"Baseline comparison failed: {e}")
            return []

    @classmethod
    def _save_report(cls, report: TrainingReport):
        """Save report to AITrainingLog model (if it exists)."""
        try:
            from apps.users.models import AITrainingLog
            AITrainingLog.objects.create(
                report_json       = report.to_json(),
                confidence_score  = report.confidence_score,
                confidence_label  = report.confidence_label,
                n_model_answers   = report.n_model_answers,
                n_key_points      = report.n_key_points,
                n_exemplars       = report.n_exemplars,
                n_graded_subs     = report.n_graded_subs,
                mae               = report.mae,
                pearson_r         = report.pearson_r,
                grade_band_acc    = report.grade_band_acc,
                similarity_method = report.similarity_method,
            )
            logger.info("Training report saved to AITrainingLog.")
        except Exception as e:
            logger.warning(f"Could not save training report to DB: {e}")

    @classmethod
    def get_latest_report(cls) -> Optional[TrainingReport]:
        """Load the most recent TrainingReport from DB."""
        try:
            from apps.users.models import AITrainingLog
            log = AITrainingLog.objects.order_by('-created_at').first()
            if log:
                return TrainingReport.from_json(log.report_json)
        except Exception as e:
            logger.warning(f"Could not load training report: {e}")
        return None

    @classmethod
    def get_latest_report_dict(cls) -> dict:
        """Return latest report as dict, or a default 'not trained' dict."""
        report = cls.get_latest_report()
        if report:
            return report.to_dict()
        return TrainingReport().to_dict()