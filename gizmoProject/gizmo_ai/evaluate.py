"""
GIZMO AI Evaluation Script
============================
Evaluates AI grading accuracy against lecturer-assigned marks.
Reports MAE, RMSE, Pearson/Spearman correlation, and key-point F1.

Run from your Django project root:
    python gizmo_ai/evaluate.py

Or with Django shell:
    python manage.py shell < gizmo_ai/evaluate.py
"""

import os
import sys
import json
import math
import logging

# ── Django setup ─────────────────────────────────────────────
if 'DJANGO_SETTINGS_MODULE' not in os.environ:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gizmoProject.settings')
    try:
        import django
        django.setup()
    except Exception:
        pass

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('gizmo_eval')


# ─────────────────────────────────────────────────────────────
#  METRICS
# ─────────────────────────────────────────────────────────────

def mean_absolute_error(y_true, y_pred):
    return sum(abs(a - b) for a, b in zip(y_true, y_pred)) / len(y_true)

def root_mean_square_error(y_true, y_pred):
    return math.sqrt(sum((a - b)**2 for a, b in zip(y_true, y_pred)) / len(y_true))

def pearson_correlation(y_true, y_pred):
    n = len(y_true)
    if n < 2:
        return 0.0
    mean_t = sum(y_true) / n
    mean_p = sum(y_pred) / n
    num = sum((a - mean_t) * (b - mean_p) for a, b in zip(y_true, y_pred))
    den_t = math.sqrt(sum((a - mean_t)**2 for a in y_true))
    den_p = math.sqrt(sum((b - mean_p)**2 for b in y_pred))
    if den_t == 0 or den_p == 0:
        return 0.0
    return num / (den_t * den_p)

def spearman_correlation(y_true, y_pred):
    """Rank-based correlation."""
    def rank(lst):
        sorted_lst = sorted(enumerate(lst), key=lambda x: x[1])
        ranks = [0] * len(lst)
        for rank_val, (orig_idx, _) in enumerate(sorted_lst):
            ranks[orig_idx] = rank_val + 1
        return ranks
    r_t = rank(y_true)
    r_p = rank(y_pred)
    return pearson_correlation(r_t, r_p)

def classification_metrics(y_true_binary, y_pred_binary):
    """Precision, Recall, F1 for binary classification (covered / not covered)."""
    tp = sum(1 for t, p in zip(y_true_binary, y_pred_binary) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true_binary, y_pred_binary) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true_binary, y_pred_binary) if t == 1 and p == 0)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


# ─────────────────────────────────────────────────────────────
#  EVALUATION RUNNER
# ─────────────────────────────────────────────────────────────

def evaluate_against_db(limit: int = 100):
    """
    Evaluate AI grading against all Submissions that have:
    - A lecturer-assigned score (ground truth)
    - A linked model answer
    - Non-empty answer_text or file

    Reports metrics to stdout.
    """
    print("\n" + "="*60)
    print("  GIZMO AI — Evaluation Report")
    print("="*60)

    try:
        from apps.users.models import Submission
        from gizmo_ai.gizmo_engine import GizmoGrader
        from gizmo_ai.ai_integration import _extract_file_text, _get_course_resources
    except ImportError as e:
        print(f"Import error: {e}")
        print("Make sure you run this from the Django project root.")
        return

    # Only evaluate submissions that have BOTH a lecturer score AND a model answer
    graded_subs = Submission.objects.filter(
        score__isnull=False,
        answer__isnull=False,
    ).select_related('paper', 'paper__course', 'answer')[:limit]

    if not graded_subs.exists():
        print("No submissions with lecturer scores + model answers found.")
        print("Grade some submissions manually first, then run this evaluation.")
        return

    y_true, y_pred = [], []
    errors = []
    similarity_methods = {}

    print(f"\nEvaluating {graded_subs.count()} submission(s)...\n")

    for sub in graded_subs:
        student_text = sub.answer_text or ""
        if not student_text and sub.file:
            student_text = _extract_file_text(sub.file.path)

        if not student_text.strip():
            continue

        try:
            resources = _get_course_resources(sub.paper.course)
            result = GizmoGrader.grade(
                student_text        = student_text,
                model_answer        = sub.answer,
                available_resources = resources,
            )
            y_true.append(float(sub.score))
            y_pred.append(float(result.predicted_score))
            method = result.similarity_method
            similarity_methods[method] = similarity_methods.get(method, 0) + 1

        except Exception as e:
            errors.append(f"Sub {sub.pk}: {e}")

    if len(y_true) < 2:
        print(f"Not enough valid results to compute metrics ({len(y_true)} processed).")
        if errors:
            print("Errors:", errors[:5])
        return

    # ── Print metrics ─────────────────────────────────────────
    mae   = mean_absolute_error(y_true, y_pred)
    rmse  = root_mean_square_error(y_true, y_pred)
    r_p   = pearson_correlation(y_true, y_pred)
    r_s   = spearman_correlation(y_true, y_pred)

    print(f"Submissions evaluated : {len(y_true)}")
    print(f"Similarity methods    : {similarity_methods}")
    print()
    print("── Mark Prediction Accuracy ─────────────────────────")
    print(f"  MAE   (mean abs error)   : {mae:.3f} marks")
    print(f"  RMSE  (root mean sq err) : {rmse:.3f} marks")
    print(f"  Pearson correlation      : {r_p:.3f}  (1.0 = perfect)")
    print(f"  Spearman correlation     : {r_s:.3f}  (rank-based)")
    print()

    # Grade band accuracy
    def band(score, total=100):
        pct = score / total * 100 if total else 0
        if pct >= 70: return 'Pass++'
        if pct >= 50: return 'Pass'
        return 'Fail'

    # Use a fixed total — or get from submission
    band_correct = sum(
        1 for t, p in zip(y_true, y_pred)
        if band(t) == band(p)
    )
    print(f"  Grade band accuracy      : {band_correct}/{len(y_true)} ({band_correct/len(y_true)*100:.1f}%)")

    # Distribution of predictions vs actual
    print()
    print("── Score Distribution ───────────────────────────────")
    print(f"  True scores  — mean: {sum(y_true)/len(y_true):.2f}, "
          f"min: {min(y_true):.1f}, max: {max(y_true):.1f}")
    print(f"  Pred scores  — mean: {sum(y_pred)/len(y_pred):.2f}, "
          f"min: {min(y_pred):.1f}, max: {max(y_pred):.1f}")

    # Error analysis
    large_errors = [(t, p, abs(t-p)) for t, p in zip(y_true, y_pred) if abs(t-p) > 5]
    if large_errors:
        print()
        print(f"── Error Analysis (|error| > 5 marks) ───────────────")
        print(f"  Count: {len(large_errors)}")
        for t, p, err in sorted(large_errors, key=lambda x: -x[2])[:5]:
            direction = "overestimated" if p > t else "underestimated"
            print(f"    True={t:.1f}, Pred={p:.1f}, Error={err:.1f} ({direction})")

    if errors:
        print(f"\n  Skipped {len(errors)} submission(s) due to errors.")

    print("\n" + "="*60)
    print("  Interpretation:")
    if mae < 2:
        print("  Excellent — MAE < 2 marks. AI grading is highly accurate.")
    elif mae < 4:
        print("  Good — MAE < 4 marks. Reasonable for automated grading.")
    elif mae < 7:
        print("  Fair — consider fine-tuning with more training data.")
    else:
        print("  Needs improvement — add more model answers and key-points.")
    print("="*60 + "\n")


def run_quick_test():
    """
    Quick test without Django — tests the engine with synthetic data.
    Run: python gizmo_ai/evaluate.py --test
    """
    print("\n── Quick Offline Test ───────────────────────────────")
    from gizmo_ai.gizmo_engine import (
        GizmoGrader, TextPreprocessor, SimilarityEngine,
        KeyPointDetector, FeedbackGenerator
    )

    # Synthetic model answer
    class FakeModelAnswer:
        answer_text  = (
            "A neural network is a computational model inspired by the human brain, "
            "consisting of layers of interconnected nodes (neurons). "
            "Backpropagation is the algorithm used to train neural networks by computing "
            "the gradient of the loss function with respect to each weight. "
            "Activation functions such as ReLU and sigmoid introduce non-linearity."
        )
        key_points = (
            "Define neural network and its structure [3]\n"
            "Explain backpropagation algorithm [4]\n"
            "Describe role of activation functions [3]"
        )
        marks        = 10
        criteria     = "Award marks for: accurate definition, algorithm steps, function examples."
        topic        = "Neural Networks"
        question_ref = "Question 1(a)"
        class paper:
            total_marks = 10

    # Test cases
    test_cases = [
        (
            "A neural network is a system of nodes inspired by the brain. "
            "Backpropagation computes gradients to update weights during training. "
            "ReLU is a common activation function that adds non-linearity.",
            "Strong student answer",
            8.0
        ),
        (
            "Neural networks are made of neurons and they learn from data.",
            "Weak student answer",
            3.0
        ),
        (
            "The backpropagation algorithm adjusts weights by computing the gradient "
            "of the loss function. ReLU and sigmoid are activation functions.",
            "Medium student answer — missing definition",
            6.0
        ),
        (
            "",
            "Empty answer",
            0.0
        ),
    ]

    model = FakeModelAnswer()
    print(f"{'Case':<30} {'Expected':>8} {'Predicted':>9} {'|Error|':>8} {'Method':<12}")
    print("-" * 75)

    for student_text, label, expected in test_cases:
        result = GizmoGrader.grade(
            student_text=student_text,
            model_answer=model,
            available_resources=[],
        )
        error = abs(result.predicted_score - expected)
        print(f"{label:<30} {expected:>8.1f} {result.predicted_score:>9.1f} {error:>8.1f} {result.similarity_method:<12}")

    print("\nKey-point breakdown for 'Strong student answer':")
    result = GizmoGrader.grade(
        student_text=test_cases[0][0],
        model_answer=model,
        available_resources=[],
    )
    for kp in result.key_point_results:
        status = "✓" if kp.covered else "✗"
        print(f"  {status} [{kp.similarity_score:.2f}] {kp.point_text[:50]} — {kp.marks_awarded}/{kp.marks_available} marks")

    print(f"\nFeedback preview:")
    print(f"  Overall: {result.overall_feedback}")
    print(f"  Strengths: {result.strengths[0][:80] if result.strengths else 'none'}")
    print(f"  Missing:   {result.missing_points[0][:80] if result.missing_points else 'none'}")
    print()


if __name__ == '__main__':
    if '--test' in sys.argv:
        run_quick_test()
    else:
        evaluate_against_db()