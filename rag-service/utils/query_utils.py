"""
utils/query_utils.py
---------------------
Query expansion, answer-type-aware chunk re-ranking, and post-generation
answer validation for the RAG service.

WHY THIS EXISTS
---------------
FAISS similarity search ranks chunks purely by semantic cosine similarity.
That is great for topic relevance but completely ignores *what kind of value*
the user is asking for.

Root problems solved here
~~~~~~~~~~~~~~~~~~~~~~~~~
1. Wrong numeric selection
   PDF chunk: "STUDENT 22/25  35.63/75  58  1696  NPTEL25CS23..."
   • 22/25  = assignment score
   • 35.63/75 = exam score
   • 58     = aggregate score (the "percentage")
   Without typed extraction the model returns the first number it sees.

2. Context dump
   When flan-t5-base cannot answer, it copies the entire context chunk.
   ``extract_typed_answer`` detects this and extracts the relevant value
   directly from context using regex, no second LLM call needed.

Public API
----------
  expand_query(question)              → expanded query string
  rerank_docs(docs, question, top_k)  → re-ranked list of Document objects
  extract_typed_answer(llm_answer, question, context) → validated answer str
  get_answer_type_hint(question)      → human-readable hint (log/debug only)
"""

import re
from collections import Counter
from typing import List

__all__ = [
    "expand_query",
    "rerank_docs",
    "extract_typed_answer",
    "get_answer_type_hint",
]


# ---------------------------------------------------------------------------
# Answer-type detectors  (question → what kind of answer is expected)
# ---------------------------------------------------------------------------

# PERCENTAGE: only fire when the user explicitly says "percent", "%", "cgpa",
# "gpa", or "aggregate".  Words like "marks", "score", "grade" are intentionally
# EXCLUDED here because they appear in both fraction questions ("marks from 25")
# and percentage questions ("percentage marks"), creating false positives.
_Q_PERCENTAGE = re.compile(
    r'\b(percent(?:age)?|cgpa|gpa|aggregate)\b'
    r'|(?<![\w/])%(?![\w/])',      # bare % not inside a fraction like 35%ile
    re.IGNORECASE,
)

_Q_DATE = re.compile(
    r'\b(when|date|year|month|day|born|issued|expir(?:y|ed|ation)|valid(?:ity)?)\b',
    re.IGNORECASE,
)

_Q_NAME = re.compile(
    r'\b(who|name|author|issued\s+to|student|candidate|person|'
    r'organization|college|university|institute)\b',
    re.IGNORECASE,
)

_Q_COUNT = re.compile(
    r'\b(how\s+many|how\s+much|count|total\s+number|number\s+of|quantity|amount|'
    r'assignment|submission|complet|marks?|score|grade|result|obtained|got)\b',
    re.IGNORECASE,
)

# FRACTION HINT: "from 25", "out of 25", "in 25 marks" → answer is X/N
# Used to locate a specific X/N fraction rather than a bare %.
_Q_FRACTION_HINT = re.compile(
    r'\b(from|out\s+of|in)\s+(\d+)(?:\s+marks?)?\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Answer-value matchers
# ---------------------------------------------------------------------------

# Explicit percentage: "69%", "92.5 %"
_VAL_PERCENT_EXPLICIT = re.compile(r'\d[\d.,]*\s*%')

# Fraction: 45/75, 22/25, 35.63/75
_VAL_FRACTION         = re.compile(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)')

# Date patterns
_VAL_DATE = re.compile(
    r'\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b'
    r'|\b\d{4}[\/\-]\d{2}[\/\-]\d{2}\b'
    r'|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*[\s,]+\d{4}\b',
    re.IGNORECASE,
)

# Title-Case multi-word proper noun: e.g. "John Doe", "Roll No" (2+ words)
_VAL_PROPER_NOUN  = re.compile(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+')
# ALL-CAPS name sequence: e.g. "RADADIYA HETVI HASMUKHBHAI" (common in NPTEL)
_VAL_ALLCAPS_NAME = re.compile(r'\b[A-Z]{2,}(?:\s+[A-Z]{2,}){1,4}\b')

# "Garbage" response: 1-2 chars with no digits, or only punctuation/whitespace
_GARBAGE_ANSWER = re.compile(r'^\s*[^\w\d]*\s*$')

# "Range" answer like "2 or 3" — NOT a definitive count, comes from credit/recommendation text
_RANGE_ANSWER = re.compile(r'\b\d+\s+or\s+\d+\b', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_denominator(question: str) -> str | None:
    """
    Extract the denominator N from phrases like 'from 25', 'out of 75',
    'in 25 marks' in the question.

    Returns the denominator string, or None if not found.

    Examples
    --------
    >>> _extract_denominator('how many marks from 25 i got')
    '25'
    >>> _extract_denominator('how many marks out of 75')
    '75'
    """
    m = re.search(
        r'\b(?:from|out\s+of|in)\s+(\d+)(?:\s+marks?)?\b',
        question,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _looks_like_garbage(answer: str) -> bool:
    """True when the LLM answer is clearly wrong (bare '%', empty, 1 char)."""
    s = answer.strip()
    if not s:
        return True
    if len(s) <= 2 and not s.isdigit():
        return True
    if _GARBAGE_ANSWER.match(s):
        return True
    return False


def _is_context_dump(text: str) -> bool:
    """
    Return True when *text* looks like raw PDF context rather than a real answer.

    Heuristics
    ----------
    • A long run of words (>20) with no sentence-ending punctuation — the model
      copied a raw data line verbatim, e.g.:
      "STUDENT  22/25  35.63/75  58  1696  NPTEL25CS23S334600098"
    • Contains known certificate / metadata patterns.
    • More than 30 words total (an answer should be short and direct).
    """
    stripped = text.strip()
    if not stripped:
        return False

    word_count = len(stripped.split())

    # Hard cap: a direct answer from this model should be ≤ 30 words
    if word_count > 30:
        return True

    # Long blob of words with NO sentence-ending punctuation
    sentence_endings = len(re.findall(r'[.!?]', stripped))
    if word_count > 15 and sentence_endings == 0:
        return True

    # Certificate / transcript metadata patterns
    METADATA_RE = re.compile(
        r'NPTEL\d+[A-Z0-9]+'                    # NPTEL roll number
        r'|Roll\s+No'                            # "Roll No:"
        r'|To verify.*certificate'               # certificate verification line
        r'|No\.\s*of\s*credits'                  # "No. of credits recommended"
        r'|recommended\s*:\s*\d'                 # "recommended: 2 or 3"
        r'|\b[A-Z]{2,}\d{4}[A-Z]{2}\d+S\w+\b',  # NPTEL code like CS23S...
        re.IGNORECASE,
    )
    if METADATA_RE.search(stripped):
        return True

    return False


def _find_standalone_ints(text: str, min_val: int, max_val: int) -> list:
    """
    Find integers in *text* NOT part of a fraction (X/Y) or decimal.

    Used to locate standalone aggregate scores like "58" inside strings such as:
    "STUDENT  22/25  35.63/75  58  1696  NPTEL..."
    where 58 is the aggregate score (out of 100) and 22/25, 35.63/75 are
    component scores.

    Parameters
    ----------
    min_val, max_val:
        Only return integers in this inclusive range.
    """
    # Mask fractions and decimals so their digits are excluded
    masked = _VAL_FRACTION.sub("FRACTION", text)
    masked = re.sub(r'\d+\.\d+', "DECIMAL", masked)
    results = []
    for m in re.finditer(r'\b(\d+)\b', masked):
        val = int(m.group(1))
        if min_val <= val <= max_val:
            results.append(val)
    return results


def _is_fraction_without_percent(text: str) -> bool:
    return bool(_VAL_FRACTION.search(text)) and not bool(_VAL_PERCENT_EXPLICIT.search(text))


def _score_chunk_for_question(text: str, question: str) -> float:
    score = 1.0

    if _Q_PERCENTAGE.search(question):
        if _VAL_PERCENT_EXPLICIT.search(text):
            score += 3.0
        if _is_fraction_without_percent(text):
            score -= 1.0

    if _Q_DATE.search(question):
        if _VAL_DATE.search(text):
            score += 2.0

    if _Q_NAME.search(question):
        if _VAL_PROPER_NOUN.search(text):
            score += 1.5

    return score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def expand_query(question: str) -> str:
    """
    Expand *question* with related keywords to widen the FAISS search net.

    Examples
    --------
    >>> expand_query("What is the percentage I got?")
    'What is the percentage I got? percentage % score marks grade aggregate'
    """
    expansions: List[str] = []

    if _Q_PERCENTAGE.search(question):
        expansions.append("percentage % score marks grade aggregate total")

    if _Q_DATE.search(question):
        expansions.append("date year month issued valid")

    if _Q_NAME.search(question):
        expansions.append("name person author candidate organization")

    if _Q_COUNT.search(question):
        expansions.append("total number count assignments submissions")

    if expansions:
        return question.rstrip() + " " + " ".join(expansions)
    return question


def rerank_docs(docs: list, question: str, top_k: int = 4) -> list:
    """
    Re-score *docs* for answer-type relevance and return the top *top_k*.
    """
    if not docs:
        return docs

    scored = [
        (doc, _score_chunk_for_question(doc.page_content, question))
        for doc in docs
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [doc for doc, _ in scored[:top_k]]


def extract_typed_answer(llm_answer: str, question: str, context: str) -> str:
    """
    Validate and correct the LLM's answer based on the detected question type.

    WHEN THIS RUNS
    --------------
    After ``extract_final_answer`` (postprocess.py) has already removed prompt
    echoes.  At this point *llm_answer* is either:
      a) A good, short answer  →  returned as-is.
      b) Garbage (bare "%", single char, empty)  →  extract from *context*.
      c) A context dump (model copied the chunk verbatim)  →  extract from *context*.

    PER-TYPE EXTRACTION STRATEGY
    -----------------------------
    Percentage
        1. If *llm_answer* has explicit digit+% → return as-is.
        2. Search *context* for explicit ``\d+%`` patterns → most frequent wins.
        3. No explicit %? Find standalone integers 30–100 NOT part of a fraction
           (e.g. "58" in "22/25  35.63/75  58  1696" = aggregate out of 100).
        4. Fallback: first fraction in context.

    Count  (assignments, submissions, etc.)
        1. If *llm_answer* is short and contains digits → return as-is.
        2. Find first fraction in context (X/Y = "X out of Y").
        3. Fall back to first standalone integer.

    Date
        1. If *llm_answer* contains a date pattern → return as-is.
        2. Extract first date from context.

    Name
        1. If *llm_answer* contains a capitalised proper noun → return as-is.
        2. Extract first proper noun phrase from context.

    General (no specific type)
        If *llm_answer* is a context dump → return first short sentence or
        a safe "could not extract" message.  Otherwise return as-is.

    Parameters
    ----------
    llm_answer: str   — output from extract_final_answer()
    question:   str   — original user question
    context:    str   — joined context chunks sent to the model
    """
    answer = llm_answer.strip()

    # ── Percentage / score questions ──────────────────────────────────────────
    if _Q_PERCENTAGE.search(question):
        # Already a valid %-formatted answer?
        if (not _looks_like_garbage(answer)
                and not _is_context_dump(answer)
                and _VAL_PERCENT_EXPLICIT.search(answer)):
            return answer

        # --- Fallback 1: explicit % value in context ---
        all_pct = _VAL_PERCENT_EXPLICIT.findall(context)
        if all_pct:
            normalised = [m.replace(" ", "") for m in all_pct]
            return Counter(normalised).most_common(1)[0][0]

        # --- Fallback 2: standalone integer 30–100 NOT in a fraction ---
        # Handles NPTEL-style: "22/25  35.63/75  58  1696"
        #   fractions are excluded → standalone ints = [58, 1696]
        #   filtered to 30–100 → [58]  → return "58%"
        standalone = _find_standalone_ints(context, min_val=30, max_val=100)
        if standalone:
            best = Counter(standalone).most_common(1)[0][0]
            return f"{best}%"

        # --- Fallback 3: first fraction ---
        frac = _VAL_FRACTION.search(context)
        if frac:
            return f"{frac.group(1)}/{frac.group(2)}"

        return answer if (answer and not _looks_like_garbage(answer)) \
            else "The percentage could not be found in the document."

    # ── Count / marks / score questions ──────────────────────────────────────
    if _Q_COUNT.search(question):
        # --- Denominator hint: "from 25", "out of 75" → look for X/N ---
        # e.g. "how many marks from 25" → find 22/25 → return "22 out of 25"
        denom = _extract_denominator(question)
        if denom:
            specific = re.search(
                rf'(\d+(?:\.\d+)?)\s*/\s*{re.escape(denom)}\b',
                context,
            )
            if specific:
                return f"{specific.group(1)} out of {denom}"
            # Any fraction as fallback
            frac = _VAL_FRACTION.search(context)
            if frac:
                return f"{frac.group(1)} out of {frac.group(2)}"

        # --- Filter: reject range answers like "2 or 3" (credit recommendations) ---
        if _RANGE_ANSWER.search(answer):
            answer = ""   # force context-extraction below

        # Valid short numeric answer?
        if (re.search(r'\d', answer)
                and not _looks_like_garbage(answer)
                and not _is_context_dump(answer)
                and len(answer.split()) <= 10):
            return answer

        # Fallback: first fraction in context (X/Y → "X out of Y")
        frac = _VAL_FRACTION.search(context)
        if frac:
            return f"{frac.group(1)} out of {frac.group(2)}"

        # Fallback: first standalone integer
        m = re.search(r'\b(\d+)\b', context)
        if m:
            return m.group(1)

        return answer if (answer and not _looks_like_garbage(answer)) \
            else "The count could not be found in the document."


    # ── Date questions ────────────────────────────────────────────────────────
    if _Q_DATE.search(question):
        if (not _looks_like_garbage(answer)
                and not _is_context_dump(answer)
                and _VAL_DATE.search(answer)):
            return answer

        date_match = _VAL_DATE.search(context)
        if date_match:
            return date_match.group(0)

        return answer if (answer and not _looks_like_garbage(answer)) \
            else "The date could not be found in the document."

    # ── Name questions ────────────────────────────────────────────────────────
    if _Q_NAME.search(question):
        if (not _looks_like_garbage(answer)
                and not _is_context_dump(answer)
                and (_VAL_PROPER_NOUN.search(answer) or _VAL_ALLCAPS_NAME.search(answer))):
            return answer

        # Prefer ALL-CAPS sequences (NPTEL names) — pick the LONGEST match
        # so full names like "RADADIYA HETVI HASMUKHBHAI" beat short labels.
        allcaps_matches = _VAL_ALLCAPS_NAME.findall(context)
        if allcaps_matches:
            # Filter out known metadata tokens (roll numbers, course codes)
            _META_TOKEN = re.compile(r'NPTEL\d|[A-Z]\d{4}', re.IGNORECASE)
            real_names = [m for m in allcaps_matches if not _META_TOKEN.search(m)]
            if real_names:
                return max(real_names, key=len)

        # Fallback: Title-Case proper noun
        name_match = _VAL_PROPER_NOUN.search(context)
        if name_match:
            return name_match.group(0)

        return answer if (answer and not _looks_like_garbage(answer)) \
            else "The name could not be found in the document."


    # ── General: guard against context dumps ─────────────────────────────────
    if _is_context_dump(answer):
        # Try to salvage: return first sentence if it's short enough
        sentences = re.split(r'(?<=[.!?])\s+', answer.strip())
        if sentences and len(sentences[0].split()) <= 20:
            return sentences[0]
        return "I found relevant information but could not extract a specific answer."

    return answer if answer else "I could not find a relevant answer in the document."


def get_answer_type_hint(question: str) -> str:
    """
    Human-readable description of detected answer type (logging/debug only).

    NOT injected into LLM prompts — flan-t5-base echoes hint symbols literally.
    """
    if _Q_PERCENTAGE.search(question):
        return "percentage value (e.g. 58%)"
    if _Q_DATE.search(question):
        return "date or year"
    if _Q_NAME.search(question):
        return "person or organization name"
    if _Q_COUNT.search(question):
        return "number or count"
    return ""
