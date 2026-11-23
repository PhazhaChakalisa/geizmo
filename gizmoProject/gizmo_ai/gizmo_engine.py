"""
GEIZMO AI Engine
================
Guided and Enhanced Intelligent Zone for Marking and Overview

Core AI module that:
1. Computes semantic similarity between student answer and model answer
   using Sentence-BERT (all-MiniLM-L6-v2 — fast & accurate)
2. Detects which marking key-points are covered by the student answer
3. Predicts a mark based on coverage, similarity, and total marks available
4. Generates REAL feedback — referencing the student's actual words,
   finding specific errors via phrase-level diff, and explaining *why*
   something is wrong rather than just saying a key point was missed
5. Recommends textbook topics based on missed key-points

Architecture:
  ┌───────────────────────────────────────────────────────────┐
  │  Student Answer (text / extracted from file)              │
  └──────────────────────┬────────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │  TextPreprocessor   │  tokenize, clean, lowercase
              └──────────┬──────────┘
                         │
         ┌───────────────┼───────────────────┐
         │               │                   │
  ┌──────▼──────┐ ┌──────▼──────┐  ┌────────▼────────┐
  │  Semantic   │ │  Key-Point  │  │  Phrase Diff    │
  │  Similarity │ │  Detector   │  │  Analyser       │
  │  (SBERT)    │ │  (per-point)│  │  (error finder) │
  └──────┬──────┘ └──────┬──────┘  └────────┬────────┘
         │               │                   │
         └───────────────┼───────────────────┘
                         │
              ┌──────────▼──────────┐
              │   Mark Predictor    │  weighted scoring + Ridge
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │  Feedback Generator │  real diff-based, quotes student
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │ Resource Recommender│  topic → textbook/material
              └─────────────────────┘
"""

from __future__ import annotations

import re
import math
import json
import logging
import difflib
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple, Dict

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  OPTIONAL heavy imports — degrade gracefully if not installed
# ─────────────────────────────────────────────────────────────────────────────
try:
    from sentence_transformers import SentenceTransformer, util as st_util
    _SBERT_AVAILABLE = True
    logger.info("Sentence-BERT available — using semantic similarity.")
except ImportError:
    _SBERT_AVAILABLE = False
    logger.warning("sentence-transformers not installed — falling back to TF-IDF similarity.")

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sk_cosine
    import numpy as np
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not installed — using basic word-overlap similarity.")

# Lazy-loaded — one model instance shared across all requests
_sbert_model: Optional[object] = None


def _get_sbert_model():
    """Load Sentence-BERT model once and cache it."""
    global _sbert_model
    if _sbert_model is None and _SBERT_AVAILABLE:
        try:
            _sbert_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Sentence-BERT model loaded.")
        except Exception as e:
            logger.error(f"Could not load SBERT model: {e}")
    return _sbert_model


# ─────────────────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PhraseError:
    """A specific error found by phrase-level diff comparison."""
    student_phrase: str      # what the student actually wrote
    correct_phrase: str      # what it should have been
    explanation: str         # why this matters
    severity: str            # 'critical' | 'significant' | 'minor'
    context: str             # surrounding sentence for readability


@dataclass
class KeyPointResult:
    """Result for a single marking key-point."""
    point_text: str
    covered: bool
    similarity_score: float
    marks_available: float
    marks_awarded: float
    student_snippet: str = ""   # exact student sentence that matched/missed


@dataclass
class GizmoResult:
    """Full AI grading result returned to the Django view."""
    # Scores
    predicted_score: float
    total_marks: float
    predicted_percentage: float
    overall_similarity: float

    # Key-point breakdown
    key_point_results: List[KeyPointResult] = field(default_factory=list)
    points_covered: int = 0
    points_total: int = 0

    # Structured feedback — now referencing actual student text
    strengths: List[str] = field(default_factory=list)
    missing_points: List[str] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    overall_feedback: str = ""

    # Specific errors found (new — phrase-level diff)
    phrase_errors: List[dict] = field(default_factory=list)   # serialised PhraseError list

    # Resource recommendations
    recommended_topics: List[str] = field(default_factory=list)
    recommended_resources: List[dict] = field(default_factory=list)

    # Method used (for transparency)
    similarity_method: str = "tfidf"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json_feedback(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
#  TEXT PREPROCESSOR
# ─────────────────────────────────────────────────────────────────────────────

class TextPreprocessor:
    STOP_WORDS = {
        'a','an','the','is','are','was','were','be','been','being',
        'have','has','had','do','does','did','will','would','could',
        'should','may','might','shall','can','to','of','in','on','at',
        'by','for','with','about','as','into','through','during','before',
        'after','above','below','between','each','both','and','but','or',
        'nor','so','yet','this','that','these','those','it','its','from',
        'up','out','such','which','than','then','when','where','who','how',
        'what','also','not','no','more','most','other','some','i','we',
        'you','he','she','they','them','their','our','your','my','his','her',
    }

    @staticmethod
    def clean(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r'\*\*|__|\\*|_|#+', '', text)
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'[^\w\s\.\,\;\:\(\)\-\']', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @classmethod
    def preprocess(cls, text: str) -> str:
        return cls.clean(text).lower()

    @classmethod
    def tokenise(cls, text: str) -> List[str]:
        text = cls.preprocess(text)
        tokens = re.findall(r'\b[a-z][a-z\-\']*[a-z]\b|\b[a-z]\b', text)
        return [t for t in tokens if t not in cls.STOP_WORDS and len(t) > 1]

    @classmethod
    def word_set(cls, text: str) -> set:
        return set(cls.tokenise(text))

    @staticmethod
    def split_sentences(text: str) -> List[str]:
        """Split text into sentences, preserving non-empty ones."""
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        return [s.strip() for s in sentences if s.strip() and len(s.split()) >= 2]

    @staticmethod
    def tokenise_raw(text: str) -> List[str]:
        """Tokenise preserving case — used for diff display."""
        return re.findall(r'\b\w+\b', text)


# ─────────────────────────────────────────────────────────────────────────────
#  SIMILARITY ENGINE  (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class SimilarityEngine:
    @staticmethod
    def _sbert_similarity(text_a: str, text_b: str) -> float:
        model = _get_sbert_model()
        if model is None:
            return -1.0
        try:
            emb_a = model.encode(text_a, convert_to_tensor=True)
            emb_b = model.encode(text_b, convert_to_tensor=True)
            score = float(st_util.cos_sim(emb_a, emb_b)[0][0])
            return max(0.0, min(1.0, score))
        except Exception as e:
            logger.error(f"SBERT similarity error: {e}")
            return -1.0

    @staticmethod
    def _tfidf_similarity(text_a: str, text_b: str) -> float:
        if not _SKLEARN_AVAILABLE:
            return -1.0
        try:
            clean_a = TextPreprocessor.preprocess(text_a)
            clean_b = TextPreprocessor.preprocess(text_b)
            if not clean_a or not clean_b:
                return 0.0
            vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
            tfidf = vec.fit_transform([clean_a, clean_b])
            score = float(sk_cosine(tfidf[0], tfidf[1])[0][0])
            return max(0.0, min(1.0, score))
        except Exception as e:
            logger.error(f"TF-IDF similarity error: {e}")
            return -1.0

    @staticmethod
    def _word_overlap(text_a: str, text_b: str) -> float:
        set_a = TextPreprocessor.word_set(text_a)
        set_b = TextPreprocessor.word_set(text_b)
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union else 0.0

    @classmethod
    def compute(cls, text_a: str, text_b: str) -> Tuple[float, str]:
        score = cls._sbert_similarity(text_a, text_b)
        if score >= 0:
            return score, "sbert"
        score = cls._tfidf_similarity(text_a, text_b)
        if score >= 0:
            return score, "tfidf"
        return cls._word_overlap(text_a, text_b), "word_overlap"

    @classmethod
    def compute_many(cls, query: str, candidates: List[str]) -> List[Tuple[float, str]]:
        model = _get_sbert_model()
        if model is not None and _SBERT_AVAILABLE:
            try:
                emb_q = model.encode(query, convert_to_tensor=True)
                emb_c = model.encode(candidates, convert_to_tensor=True)
                scores = st_util.cos_sim(emb_q, emb_c)[0].tolist()
                return [(max(0.0, min(1.0, float(s))), "sbert") for s in scores]
            except Exception as e:
                logger.error(f"SBERT batch error: {e}")
        return [cls.compute(query, c) for c in candidates]

    @classmethod
    def word_semantic_relatedness(cls, word_a: str, word_b: str) -> float:
        """
        Check if two individual words are semantically related.
        Used to determine if a substitution is meaningful or a random error.
        Returns 0.0–1.0. Words that are synonyms/related score high.
        Words from completely different domains score very low.
        """
        if word_a.lower() == word_b.lower():
            return 1.0
        score, _ = cls.compute(word_a, word_b)
        return score


# ─────────────────────────────────────────────────────────────────────────────
#  PHRASE DIFF ANALYSER  — the core of real feedback
# ─────────────────────────────────────────────────────────────────────────────

class PhraseDiffAnalyser:
    """
    Finds specific errors in the student answer by comparing it phrase-by-phrase
    to the model answer.

    Approach:
    1. Split both texts into sentences
    2. Match each student sentence to its closest model sentence (by SBERT)
    3. For each matched pair, run word-level diff (difflib.SequenceMatcher)
    4. For each substituted word: check semantic relatedness
       - If relatedness < 0.3 → the student used a completely wrong word/concept
       - Flag it with context and explanation
    5. For missing sentence concepts → note what the student skipped entirely

    This catches the "cows vs computers" case because:
    - The sentences are nearly identical (high overall sim → student gets partial credit)
    - But word-level diff finds "cows" replaced "computers"
    - SBERT semantic relatedness between "cows" and "computers" ≈ 0.05
    - Flag: critical error — student wrote an incorrect concept
    """

    # Below this relatedness, a substituted word is considered a real error
    SEMANTIC_ERROR_THRESHOLD = 0.35

    # Minimum word length to bother checking (ignore articles, prepositions)
    MIN_WORD_LEN = 3

    # Stop words to skip during diff — changes to these rarely matter
    DIFF_STOP = {
        'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'shall', 'can', 'to', 'of',
        'in', 'on', 'at', 'by', 'for', 'with', 'about', 'as', 'into',
        'and', 'but', 'or', 'nor', 'so', 'yet', 'this', 'that',
        'it', 'its', 'from', 'up', 'not', 'no', 'also',
    }

    @classmethod
    def analyse(
        cls,
        student_text: str,
        model_text: str,
        topic: str = "",
    ) -> List[PhraseError]:
        """
        Main entry point. Returns a list of PhraseError objects describing
        specific errors found in the student answer.
        """
        errors: List[PhraseError] = []

        student_sentences = TextPreprocessor.split_sentences(student_text)
        model_sentences   = TextPreprocessor.split_sentences(model_text)

        if not student_sentences or not model_sentences:
            return errors

        # Match each student sentence to the closest model sentence
        matched_pairs = cls._match_sentences(student_sentences, model_sentences)

        for stu_sent, mod_sent, pair_sim in matched_pairs:
            # Only run diff on sentences that are at least somewhat related
            # (sim > 0.25 means the student attempted this concept)
            if pair_sim < 0.25:
                continue

            sentence_errors = cls._diff_sentences(stu_sent, mod_sent, topic)
            errors.extend(sentence_errors)

        # Deduplicate — same student phrase showing up twice
        seen = set()
        unique_errors = []
        for e in errors:
            key = e.student_phrase.lower().strip()
            if key not in seen:
                seen.add(key)
                unique_errors.append(e)

        return unique_errors[:8]   # cap at 8 specific errors — avoid overwhelming

    @classmethod
    def _match_sentences(
        cls,
        student_sents: List[str],
        model_sents: List[str],
    ) -> List[Tuple[str, str, float]]:
        """
        For each student sentence, find the best matching model sentence.
        Returns list of (student_sentence, model_sentence, similarity_score).
        """
        if not student_sents or not model_sents:
            return []

        pairs = []
        # Batch compute all similarities at once
        all_sims = SimilarityEngine.compute_many(
            " ||| ".join(student_sents),
            model_sents
        )

        for stu_sent in student_sents:
            sims = SimilarityEngine.compute_many(stu_sent, model_sents)
            if not sims:
                continue
            best_idx = max(range(len(sims)), key=lambda i: sims[i][0])
            best_sim = sims[best_idx][0]
            pairs.append((stu_sent, model_sents[best_idx], best_sim))

        return pairs

    @classmethod
    def _diff_sentences(
        cls,
        student_sent: str,
        model_sent: str,
        topic: str = "",
    ) -> List[PhraseError]:
        """
        Word-level diff between a matched student/model sentence pair.
        Finds substituted, deleted, or inserted words that indicate errors.
        """
        errors = []

        stu_words = TextPreprocessor.tokenise_raw(student_sent)
        mod_words = TextPreprocessor.tokenise_raw(model_sent)

        if not stu_words or not mod_words:
            return errors

        # Normalise to lowercase for comparison
        stu_lower = [w.lower() for w in stu_words]
        mod_lower = [w.lower() for w in mod_words]

        matcher = difflib.SequenceMatcher(None, stu_lower, mod_lower, autojunk=False)
        opcodes = matcher.get_opcodes()

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == 'replace':
                # Student used different words from the model
                stu_phrase = " ".join(stu_words[i1:i2])
                mod_phrase = " ".join(mod_words[j1:j2])

                # Skip trivial stop-word changes
                if all(w in cls.DIFF_STOP for w in stu_lower[i1:i2]):
                    continue
                if all(w in cls.DIFF_STOP for w in mod_lower[j1:j2]):
                    continue

                # Skip very short words (likely articles)
                if max(len(w) for w in stu_lower[i1:i2]) < cls.MIN_WORD_LEN:
                    continue

                # Check semantic relatedness — is this actually a meaningful error?
                relatedness = SimilarityEngine.word_semantic_relatedness(
                    stu_phrase, mod_phrase
                )

                if relatedness < cls.SEMANTIC_ERROR_THRESHOLD:
                    severity = cls._classify_severity(
                        stu_phrase, mod_phrase, relatedness, i1, i2, j1, j2
                    )
                    explanation = cls._explain_error(
                        stu_phrase, mod_phrase, student_sent, topic, relatedness
                    )
                    errors.append(PhraseError(
                        student_phrase = stu_phrase,
                        correct_phrase = mod_phrase,
                        explanation    = explanation,
                        severity       = severity,
                        context        = student_sent[:200],
                    ))

            elif tag == 'delete':
                # Student omitted words that exist in the model
                deleted = " ".join(mod_words[j1:j2])
                if (len(deleted.split()) >= 2
                        and not all(w in cls.DIFF_STOP for w in mod_lower[j1:j2])):
                    # Only flag meaningful omissions (2+ content words)
                    if not any(w in cls.DIFF_STOP for w in deleted.lower().split()[:1]):
                        errors.append(PhraseError(
                            student_phrase = "(not mentioned)",
                            correct_phrase = deleted,
                            explanation    = (
                                f"Your answer did not include the concept "
                                f"\"{deleted}\" — this is part of the expected explanation."
                            ),
                            severity       = "minor",
                            context        = student_sent[:200],
                        ))

        return errors

    @staticmethod
    def _classify_severity(
        stu_phrase: str,
        mod_phrase: str,
        relatedness: float,
        i1: int, i2: int, j1: int, j2: int,
    ) -> str:
        """
        Classify how serious an error is.
        Critical: completely wrong concept (low relatedness, key position)
        Significant: wrong but related concept
        Minor: small inaccuracy
        """
        if relatedness < 0.10:
            return "critical"    # completely unrelated — like "cows" vs "computers"
        if relatedness < 0.25:
            return "significant"
        return "minor"

    @staticmethod
    def _explain_error(
        student_phrase: str,
        correct_phrase: str,
        context_sentence: str,
        topic: str,
        relatedness: float,
    ) -> str:
        """
        Generate a plain-English explanation of why the substitution is wrong.
        References the student's actual words.
        """
        stu = f'"{student_phrase}"'
        cor = f'"{correct_phrase}"'

        if relatedness < 0.10:
            # Completely unrelated — strong language appropriate
            return (
                f"You wrote {stu} but the correct term is {cor}. "
                f"These concepts are not related{f' in the context of {topic}' if topic else ''}. "
                f"This appears to be an error rather than a paraphrase — "
                f"make sure you understand what {cor} means and why it is central to this answer."
            )
        elif relatedness < 0.25:
            return (
                f"You used {stu} where {cor} was expected. "
                f"While these are not entirely unrelated, {cor} is the precise term "
                f"the marking scheme requires here. "
                f"Using imprecise terminology can cost marks even when the broader idea is correct."
            )
        else:
            return (
                f"You wrote {stu} instead of {cor}. "
                f"This is a close approximation but the wording affects precision. "
                f"In examination marking, precise terminology matters."
            )


# ─────────────────────────────────────────────────────────────────────────────
#  KEY-POINT DETECTOR  (unchanged logic, improved snippet extraction)
# ─────────────────────────────────────────────────────────────────────────────

class KeyPointDetector:
    COVER_THRESHOLD   = 0.38
    PARTIAL_THRESHOLD = 0.22

    @staticmethod
    def parse_key_points(key_points_text: str, total_marks: float) -> List[Tuple[str, float]]:
        lines = [l.strip() for l in key_points_text.strip().splitlines() if l.strip()]
        if not lines:
            return []

        results = []
        explicit_total = 0.0
        parsed = []

        for line in lines:
            line = re.sub(r'^[\•\-\*\d\.]+\s*', '', line).strip()
            if not line:
                continue
            mark = None
            m = re.search(r'\[(\d+(?:\.\d+)?)\]', line)
            if m:
                mark = float(m.group(1))
                line = line[:m.start()].strip()
            else:
                m = re.search(r'\((\d+(?:\.\d+)?)\s*marks?\)', line, re.I)
                if m:
                    mark = float(m.group(1))
                    line = line[:m.start()].strip()

            parsed.append((line, mark))
            if mark is not None:
                explicit_total += mark

        unmarked = [p for p in parsed if p[1] is None]
        remaining = max(0.0, total_marks - explicit_total)
        per_point = (remaining / len(unmarked)) if unmarked else 0.0

        for point_text, mark in parsed:
            allocated = mark if mark is not None else per_point
            results.append((point_text, allocated))

        return results

    @classmethod
    def detect(
        cls,
        student_text: str,
        key_points_text: str,
        model_answer_text: str,
        total_marks: float,
    ) -> List[KeyPointResult]:
        if not key_points_text.strip():
            sim, method = SimilarityEngine.compute(student_text, model_answer_text)
            awarded = round(sim * total_marks, 1)
            return [KeyPointResult(
                point_text       = "Overall answer quality",
                covered          = sim >= cls.COVER_THRESHOLD,
                similarity_score = sim,
                marks_available  = total_marks,
                marks_awarded    = awarded,
                student_snippet  = "",
            )]

        key_points = cls.parse_key_points(key_points_text, total_marks)
        if not key_points:
            return []

        point_texts = [pt for pt, _ in key_points]
        similarities = SimilarityEngine.compute_many(student_text, point_texts)

        results = []
        for (point_text, marks_available), (sim_score, _) in zip(key_points, similarities):
            if sim_score >= cls.COVER_THRESHOLD:
                covered = True
                awarded = marks_available
            elif sim_score >= cls.PARTIAL_THRESHOLD:
                covered = False
                awarded = marks_available * 0.5
            else:
                covered = False
                awarded = 0.0

            snippet = cls._find_best_snippet(student_text, point_text)

            results.append(KeyPointResult(
                point_text       = point_text,
                covered          = covered,
                similarity_score = round(sim_score, 3),
                marks_available  = marks_available,
                marks_awarded    = round(awarded, 1),
                student_snippet  = snippet,
            ))

        return results

    @staticmethod
    def _find_best_snippet(student_text: str, point_text: str, max_len: int = 150) -> str:
        """Return the student sentence most relevant to this key point."""
        sentences = TextPreprocessor.split_sentences(student_text)
        if not sentences:
            return ""
        point_words = TextPreprocessor.word_set(point_text)
        best_sentence = ""
        best_overlap = -1
        for s in sentences:
            s_words = TextPreprocessor.word_set(s)
            overlap = len(s_words & point_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_sentence = s
        return best_sentence[:max_len] + ("…" if len(best_sentence) > max_len else "")


# ─────────────────────────────────────────────────────────────────────────────
#  MARK PREDICTOR  (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class MarkPredictor:
    KP_WEIGHT  = 0.75
    SIM_WEIGHT = 0.15
    LEN_WEIGHT = 0.10
    MIN_WORDS  = 10     # minimum words for length_factor — matches active learning MIN_WORDS

    _regressor = None
    _reg_loaded_at = None

    @classmethod
    def _load_regressor(cls):
        try:
            import json as _j, pickle, base64
            from apps.users.models import AITrainingLog
            latest = AITrainingLog.objects.order_by('-created_at').first()
            if not latest:
                return None
            if cls._reg_loaded_at == latest.pk and cls._regressor is not None:
                return cls._regressor
            d = _j.loads(latest.report_json)
            reg_b64 = d.get('regressor_b64')
            if not reg_b64:
                return None
            reg = pickle.loads(base64.b64decode(reg_b64.encode()))
            cls._regressor = reg
            cls._reg_loaded_at = latest.pk
            return reg
        except Exception:
            return None

    @classmethod
    def _build_features(
        cls,
        key_point_results: List[KeyPointResult],
        overall_similarity: float,
        total_marks: float,
        student_word_count: int,
    ) -> list:
        kp_score = sum(r.marks_awarded for r in key_point_results)
        kp_max   = sum(r.marks_available for r in key_point_results)
        kp_pct   = (kp_score / kp_max) if kp_max > 0 else 0.0
        n_kp     = len(key_point_results) or 1
        covered_frac = sum(1 for r in key_point_results if r.covered) / n_kp
        partial_frac = sum(
            1 for r in key_point_results
            if not r.covered and r.similarity_score >= 0.22
        ) / n_kp
        length_factor = min(1.0, student_word_count / cls.MIN_WORDS)
        sim = max(0.0, min(1.0, overall_similarity))
        return [kp_pct, sim, length_factor, covered_frac, partial_frac]

    @classmethod
    def predict(
        cls,
        key_point_results: List[KeyPointResult],
        overall_similarity: float,
        total_marks: float,
        student_word_count: int,
        phrase_errors: List[PhraseError] = None,
    ) -> float:
        features = cls._build_features(
            key_point_results, overall_similarity,
            total_marks, student_word_count
        )
        kp_pct, sim, length_factor, _, _ = features

        # ── Apply penalty for critical phrase errors ──────────
        # A "cows vs computers" type error should NOT score 90%
        # even if the rest of the sentence matches perfectly.
        error_penalty = 0.0
        if phrase_errors:
            critical_count    = sum(1 for e in phrase_errors if e.severity == 'critical')
            significant_count = sum(1 for e in phrase_errors if e.severity == 'significant')
            # Each critical error reduces the final score significantly
            error_penalty = min(0.5, critical_count * 0.15 + significant_count * 0.07)

        # ── Try learned regressor first ──────────────────────
        reg = cls._load_regressor()
        if reg is not None:
            try:
                raw_pct = float(reg.predict([features])[0])
                raw_pct = max(0.0, min(1.0, raw_pct - error_penalty))
                raw_mark = raw_pct * total_marks * length_factor
                return max(0.0, min(float(total_marks), round(raw_mark * 2) / 2))
            except Exception:
                pass

        # ── Principled fallback formula ───────────────────────
        combined = (cls.KP_WEIGHT * kp_pct) + (cls.SIM_WEIGHT * sim)
        combined = max(0.0, combined - error_penalty)
        combined *= length_factor
        raw_mark = combined * total_marks
        return max(0.0, min(float(total_marks), round(raw_mark * 2) / 2))


def _train_mark_predictor(graded_subs) -> Optional[object]:
    try:
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from gizmo_ai.ai_integration import _extract_file_text, _get_course_resources

        X, y = [], []
        for sub in graded_subs:
            text = sub.answer_text or ""
            if not text and sub.file:
                try: text = _extract_file_text(sub.file.path)
                except: pass
            if not text.strip() or sub.score is None: continue
            try:
                from gizmo_ai.gizmo_engine import GizmoGrader, MarkPredictor
                resources = _get_course_resources(sub.paper.course)
                result = GizmoGrader.grade(
                    student_text=text,
                    model_answer=sub.answer,
                    available_resources=resources,
                )
                q_marks = float(sub.answer.marks) if sub.answer and sub.answer.marks else None
                total   = q_marks or float(sub.paper.total_marks or 100)
                feats = MarkPredictor._build_features(
                    result.key_point_results,
                    result.overall_similarity,
                    total,
                    len(text.split()),
                )
                y_pct = float(sub.score) / float(total)
                X.append(feats)
                y.append(y_pct)
            except Exception as e:
                logger.debug(f"Feature extraction failed for sub {sub.pk}: {e}")

        if len(X) < 3:
            return None

        pipe = Pipeline([
            ('scaler', StandardScaler()),
            ('reg', Ridge(alpha=1.0)),
        ])
        pipe.fit(X, y)
        logger.info(f"Mark predictor fitted on {len(X)} samples.")
        return pipe
    except ImportError:
        return None
    except Exception as e:
        logger.warning(f"_train_mark_predictor failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  FEEDBACK GENERATOR  — rebuilt: quotes student text, explains real errors
# ─────────────────────────────────────────────────────────────────────────────

class FeedbackGenerator:
    """
    Generates feedback that:
    - Quotes the student's actual words
    - Identifies specific wrong phrases (from PhraseDiffAnalyser)
    - Explains WHY something is wrong, not just THAT it's wrong
    - Gives specific improvement advice tied to what was actually written
    - Acknowledges what the student genuinely did well, with their exact phrases
    """

    @staticmethod
    def _grade_label(pct: float) -> str:
        if pct >= 85: return "Excellent"
        if pct >= 70: return "Good"
        if pct >= 60: return "Satisfactory"
        if pct >= 50: return "Pass"
        if pct >= 40: return "Marginal Fail"
        return "Fail"

    @classmethod
    def generate(
        cls,
        student_text: str,
        model_answer_text: str,
        key_point_results: List[KeyPointResult],
        phrase_errors: List[PhraseError],
        predicted_score: float,
        total_marks: float,
        question_ref: str = "",
        topic: str = "",
        criteria: str = "",
    ) -> Tuple[List[str], List[str], List[str], str]:
        """
        Returns (strengths, missing_points, improvement_suggestions, overall_feedback).
        All lists contain real, student-specific text.
        """
        pct     = (predicted_score / total_marks * 100) if total_marks else 0
        grade   = cls._grade_label(pct)
        covered = [r for r in key_point_results if r.covered]
        missed  = [r for r in key_point_results if not r.covered]
        student_sentences = TextPreprocessor.split_sentences(student_text)

        # ── STRENGTHS — quote what the student actually wrote well ──────────
        strengths = cls._build_strengths(covered, student_sentences, phrase_errors)

        # ── MISSING POINTS — specific, not generic ──────────────────────────
        missing_points = cls._build_missing_points(missed, phrase_errors, student_sentences)

        # ── IMPROVEMENT SUGGESTIONS — actionable, student-specific ──────────
        suggestions = cls._build_suggestions(
            student_text, model_answer_text, missed, phrase_errors,
            topic, criteria, pct
        )

        # ── OVERALL FEEDBACK — summary with score context ───────────────────
        overall_fb = cls._build_overall(
            pct, grade, covered, missed, phrase_errors,
            predicted_score, total_marks, question_ref, topic
        )

        return strengths, missing_points, suggestions, overall_fb

    # ── STRENGTHS ─────────────────────────────────────────────────────────────

    @classmethod
    def _build_strengths(
        cls,
        covered: List[KeyPointResult],
        student_sentences: List[str],
        phrase_errors: List[PhraseError],
    ) -> List[str]:
        strengths = []
        error_contexts = {e.context[:80] for e in phrase_errors}

        for r in covered:
            snippet = r.student_snippet.strip()

            # Check if this snippet had a critical error in it — if so, don't praise it
            has_error = any(ec[:80] in snippet for ec in error_contexts) if snippet else False

            if r.similarity_score >= 0.70 and snippet and not has_error:
                strengths.append(
                    f"Your answer correctly addresses \"{r.point_text}\". "
                    f"Your phrasing — \"{snippet}\" — captures the key idea "
                    f"and earns {r.marks_awarded}/{r.marks_available} marks."
                )
            elif r.similarity_score >= 0.50 and snippet:
                strengths.append(
                    f"You touched on \"{r.point_text}\" — specifically where you wrote "
                    f"\"{snippet}\". This earns partial credit ({r.marks_awarded}/{r.marks_available} marks) "
                    f"though the explanation could be more precise."
                )
            elif r.covered:
                strengths.append(
                    f"The concept of \"{r.point_text}\" is present in your answer "
                    f"({r.marks_awarded}/{r.marks_available} marks awarded)."
                )

        if not strengths:
            strengths.append(
                "Your answer attempts to engage with the question. "
                "However, the key marking points are not yet clearly addressed. "
                "See the feedback below to understand what was expected."
            )

        return strengths

    # ── MISSING POINTS ────────────────────────────────────────────────────────

    @classmethod
    def _build_missing_points(
        cls,
        missed: List[KeyPointResult],
        phrase_errors: List[PhraseError],
        student_sentences: List[str],
    ) -> List[str]:
        missing_points = []

        # First: list specific phrase-level errors with explanations
        for err in phrase_errors:
            if err.severity == 'critical':
                missing_points.append(
                    f"Error — you wrote \"{err.student_phrase}\" but the correct concept is "
                    f"\"{err.correct_phrase}\". {err.explanation}"
                )
            elif err.severity == 'significant':
                missing_points.append(
                    f"Inaccuracy — you used \"{err.student_phrase}\" where \"{err.correct_phrase}\" "
                    f"was expected. {err.explanation}"
                )

        # Then: key points the student didn't address at all
        for r in missed:
            # Was this point partially attempted?
            if r.similarity_score >= KeyPointDetector.PARTIAL_THRESHOLD and r.student_snippet:
                missing_points.append(
                    f"Incomplete — you began to address \"{r.point_text}\" "
                    f"(near where you wrote: \"{r.student_snippet}\"), "
                    f"but the explanation is not developed enough to earn full marks. "
                    f"You received {r.marks_awarded} of {r.marks_available} marks for this point — "
                    f"expand your explanation to recover the remaining "
                    f"{r.marks_available - r.marks_awarded:.1f} mark(s)."
                )
            elif r.student_snippet:
                missing_points.append(
                    f"Not addressed — \"{r.point_text}\" was expected but your answer "
                    f"does not cover this. The closest thing you wrote was: "
                    f"\"{r.student_snippet}\" — but this does not demonstrate understanding "
                    f"of the required concept. This costs {r.marks_available:.1f} mark(s)."
                )
            else:
                missing_points.append(
                    f"Missing — \"{r.point_text}\" was not mentioned in your answer. "
                    f"This costs {r.marks_available:.1f} mark(s). "
                    f"Make sure your answer explicitly addresses every part of the question."
                )

        return missing_points

    # ── IMPROVEMENT SUGGESTIONS ───────────────────────────────────────────────

    @classmethod
    def _build_suggestions(
        cls,
        student_text: str,
        model_answer_text: str,
        missed: List[KeyPointResult],
        phrase_errors: List[PhraseError],
        topic: str,
        criteria: str,
        pct: float,
    ) -> List[str]:
        suggestions = []
        word_count = len(student_text.split())

        # Suggest fixing critical errors first
        critical_errors = [e for e in phrase_errors if e.severity == 'critical']
        if critical_errors:
            for err in critical_errors[:2]:
                suggestions.append(
                    f"Correct your use of \"{err.student_phrase}\" — "
                    f"the correct term is \"{err.correct_phrase}\". "
                    f"Review the definition of {err.correct_phrase} and ensure you "
                    f"understand what it means before your next attempt."
                )

        # Length check — specific to their word count
        if word_count < 50:
            suggestions.append(
                f"Your answer is only {word_count} words long. "
                f"For a question like this, aim for at least 80–120 words. "
                f"Each marking point deserves its own sentence or two."
            )
        elif word_count < 30:
            suggestions.append(
                f"Your answer is very short ({word_count} words). "
                f"Expand significantly — you are leaving marks on the table."
            )

        # Missing key point suggestions — specific
        if missed:
            missed_names = [f'"{r.point_text}"' for r in missed[:3]]
            suggestions.append(
                f"Your next revision should focus on: {', '.join(missed_names)}. "
                f"{'These' if len(missed) > 1 else 'This'} "
                f"{'are' if len(missed) > 1 else 'is'} the marking point(s) you did not address."
            )

        # Vocabulary gap — find important words in model not in student
        model_words = TextPreprocessor.word_set(model_answer_text)
        student_words = TextPreprocessor.word_set(student_text)
        important_missing = [
            w for w in model_words - student_words
            if len(w) > 5 and w.isalpha()
        ][:5]
        if important_missing:
            suggestions.append(
                f"Your answer is missing important terminology. "
                f"The following key terms appear in the expected answer but not in yours: "
                f"{', '.join(important_missing)}. "
                f"Understanding these terms and when to use them will improve your marks."
            )

        # High performer nudge
        if pct >= 70 and not critical_errors:
            suggestions.append(
                f"Good work — you are in the {cls._grade_label(pct)} range. "
                f"To push into Distinction (85%+), make sure every point is supported "
                f"with a precise definition or concrete example. Vague statements that "
                f"are directionally correct often receive only partial credit."
            )

        # Marking criteria reminder if set
        if criteria and len(criteria.strip()) > 20:
            suggestions.append(
                f"The marking criteria for this question state: "
                f"\"{criteria.strip()[:250]}{'...' if len(criteria) > 250 else ''}\". "
                f"Re-read your answer against this and check you have addressed each element."
            )

        return suggestions

    # ── OVERALL FEEDBACK ──────────────────────────────────────────────────────

    @classmethod
    def _build_overall(
        cls,
        pct: float,
        grade: str,
        covered: List[KeyPointResult],
        missed: List[KeyPointResult],
        phrase_errors: List[PhraseError],
        predicted_score: float,
        total_marks: float,
        question_ref: str,
        topic: str,
    ) -> str:
        q_ref = f" for {question_ref}" if question_ref else ""
        n_kp  = len(covered) + len(missed)
        n_err  = len([e for e in phrase_errors if e.severity in ('critical', 'significant')])

        # Open with score
        overall = (
            f"Grade: {grade} — Estimated mark: {predicted_score}/{total_marks} "
            f"({pct:.1f}%){q_ref}. "
        )

        # Specific comment on errors found
        if n_err > 0:
            overall += (
                f"The AI found {n_err} specific error(s) in your answer where you used "
                f"incorrect terminology or concepts. These are highlighted in the feedback "
                f"below — fixing them directly will recover marks. "
            )

        # Key-point summary
        if pct >= 70:
            overall += (
                f"You covered {len(covered)} of {n_kp} marking points well. "
                f"The main area to improve is precision in your phrasing."
            )
        elif pct >= 50:
            overall += (
                f"You addressed {len(covered)} of {n_kp} marking points. "
                f"{len(missed)} point(s) were not sufficiently covered — "
                f"focusing on these in revision would improve your score meaningfully."
            )
        else:
            overall += (
                f"Only {len(covered)} of {n_kp} marking points were clearly addressed. "
                f"This answer would not pass under standard marking criteria. "
                f"Revisit the topic{f' of {topic}' if topic else ''} "
                f"and study the recommended resources before your next attempt."
            )

        return overall


# ─────────────────────────────────────────────────────────────────────────────
#  RESOURCE RECOMMENDER  (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class ResourceRecommender:
    @classmethod
    def recommend(
        cls,
        missed_points: List[KeyPointResult],
        topic: str,
        available_resources: List[dict],
        top_n: int = 3,
    ) -> Tuple[List[str], List[dict]]:
        if not missed_points and not topic:
            return [], []

        query_parts = [topic] if topic else []
        for r in missed_points[:5]:
            query_parts.append(r.point_text)
        query = " ".join(query_parts)

        topic_keywords = list(set(TextPreprocessor.tokenise(query)))[:8]

        if not available_resources:
            return topic_keywords, []

        resource_texts = [
            f"{r.get('title','')} {r.get('description','')} {r.get('course','')}"
            for r in available_resources
        ]

        if not resource_texts:
            return topic_keywords, []

        scored = SimilarityEngine.compute_many(query, resource_texts)
        ranked = sorted(
            zip(available_resources, scored),
            key=lambda x: x[1][0],
            reverse=True
        )
        top_resources = [res for res, _ in ranked[:top_n]]
        return topic_keywords, top_resources


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN GRADER  — updated to run PhraseDiffAnalyser
# ─────────────────────────────────────────────────────────────────────────────

class GizmoGrader:
    """
    Main entry point.

    Usage:
        from gizmo_ai.gizmo_engine import GizmoGrader

        result = GizmoGrader.grade(
            student_text    = "Computer science is the study of cows...",
            model_answer    = model_answer_obj,
            available_resources = resources_list,
        )
    """

    @classmethod
    def grade(
        cls,
        student_text: str,
        model_answer,
        available_resources: List[dict] = None,
    ) -> GizmoResult:
        if available_resources is None:
            available_resources = []

        model_text   = model_answer.answer_text or ""
        key_pts_text = model_answer.key_points  or ""
        total_marks  = float(model_answer.marks or model_answer.paper.total_marks or 10)
        criteria     = model_answer.criteria    or ""
        topic        = model_answer.topic       or ""
        question_ref = model_answer.question_ref or ""

        student_clean = TextPreprocessor.clean(student_text)
        word_count    = len(student_clean.split())

        # ── 1. Overall semantic similarity ───────────────────────
        overall_sim, method = SimilarityEngine.compute(student_clean, model_text)

        # ── 2. Key-point detection ───────────────────────────────
        kp_results = KeyPointDetector.detect(
            student_text      = student_clean,
            key_points_text   = key_pts_text,
            model_answer_text = model_text,
            total_marks       = total_marks,
        )

        # ── 3. Phrase-level diff — find specific errors ──────────
        phrase_errors = PhraseDiffAnalyser.analyse(
            student_text = student_clean,
            model_text   = model_text,
            topic        = topic,
        )

        # ── 4. Mark prediction — with error penalty ──────────────
        predicted = MarkPredictor.predict(
            key_point_results  = kp_results,
            overall_similarity = overall_sim,
            total_marks        = total_marks,
            student_word_count = word_count,
            phrase_errors      = phrase_errors,
        )
        pct = round(predicted / total_marks * 100, 1) if total_marks else 0

        # ── 5. Real feedback generation ──────────────────────────
        strengths, missing, suggestions, overall_fb = FeedbackGenerator.generate(
            student_text      = student_clean,
            model_answer_text = model_text,
            key_point_results = kp_results,
            phrase_errors     = phrase_errors,
            predicted_score   = predicted,
            total_marks       = total_marks,
            question_ref      = question_ref,
            topic             = topic,
            criteria          = criteria,
        )

        # ── 6. Resource recommendation ───────────────────────────
        missed_kps = [r for r in kp_results if not r.covered]
        topic_kw, rec_resources = ResourceRecommender.recommend(
            missed_points       = missed_kps,
            topic               = topic,
            available_resources = available_resources,
        )

        # Serialise phrase errors for JSON storage
        phrase_errors_dicts = [
            {
                'student_phrase': e.student_phrase,
                'correct_phrase': e.correct_phrase,
                'explanation':    e.explanation,
                'severity':       e.severity,
                'context':        e.context,
            }
            for e in phrase_errors
        ]

        return GizmoResult(
            predicted_score       = predicted,
            total_marks           = total_marks,
            predicted_percentage  = pct,
            overall_similarity    = round(overall_sim, 3),
            key_point_results     = kp_results,
            points_covered        = sum(1 for r in kp_results if r.covered),
            points_total          = len(kp_results),
            strengths             = strengths,
            missing_points        = missing,
            improvement_suggestions = suggestions,
            overall_feedback      = overall_fb,
            phrase_errors         = phrase_errors_dicts,
            recommended_topics    = topic_kw,
            recommended_resources = rec_resources,
            similarity_method     = method,
        )