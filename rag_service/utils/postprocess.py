"""
utils/postprocess.py
--------------------
Post-processing utilities for LLM output in the PDF Q&A RAG service.

WHY THIS EXISTS
---------------
Small seq2seq models (e.g. flan-t5-base) sometimes echo the entire prompt
back verbatim, or interleave retrieved document chunks with their answer.
This module strips ALL of that before the API returns anything to the client.

Public API
----------
extract_final_answer(llm_output)   → clean answer string
extract_final_summary(llm_output)  → clean summary string
extract_comparison(llm_output)     → clean comparison string

All three call the shared _clean() pipeline and only differ in the marker
they look for ("Answer:" / "Summary:" / "Comparison:") and their fallback
message.

CLEANING PIPELINE (applied in order by _clean)
-----------------------------------------------
 1. Whole-prompt echo guard  — if the output starts with instruction text,
    split on the terminal marker ("Answer:" / "Summary:" / "Comparison:") and
    keep only what follows.
 2. Marker split             — extract text after the first matching marker.
 3. Line-level echo filter   — remove any remaining lines that match known
    instruction / context-header patterns.
 4. Sentence-level filter    — remove sentences that ARE the instruction text
    (catches models that inline instructions instead of putting them on their
    own line).
 5. Whitespace normalisation — collapse runs of spaces/tabs and triple+ blank
    lines.
 6. Character-spacing fix    — join space-separated single letters produced by
    some PDF parsers (e.g. "N P T E L" → "NPTEL").
 7. Duplicate-marker strip   — remove a leading "Answer:" etc. that the model
    may have emitted again inside its answer.
 8. Safe fallback            — if nothing useful survives, return a clear
    "not found" message.
"""

import re
from typing import Optional

__all__ = ["extract_final_answer", "extract_final_summary", "extract_comparison"]


# ---------------------------------------------------------------------------
# Marker definitions
# Each entry: (compiled regex to FIND the marker, plain label for stripping)
# ---------------------------------------------------------------------------

_MARKER_ANSWER      = re.compile(r'(?:^|\n)\s*Answer\s*[:\-]?\s*\n?', re.IGNORECASE)
_MARKER_SUMMARY     = re.compile(r'(?:^|\n)\s*Summary\s*[:\-]?\s*\n?', re.IGNORECASE)
_MARKER_COMPARISON  = re.compile(r'(?:^|\n)\s*Comparison\s*[:\-]?\s*\n?', re.IGNORECASE)

# Strip a stray leading marker that the model echoed inside its own answer
_LEADING_ANSWER_RE      = re.compile(r'(?i)^Answer\s*[:\-]\s*')
_LEADING_SUMMARY_RE     = re.compile(r'(?i)^Summary\s*[:\-]\s*')
_LEADING_COMPARISON_RE  = re.compile(r'(?i)^Comparison\s*[:\-]\s*')


# ---------------------------------------------------------------------------
# Echo patterns — lines that are clearly from the prompt / system, not the
# answer.  Add new patterns here whenever a new instruction phrase is found
# leaking through.
# ---------------------------------------------------------------------------

_ECHO_PATTERNS: list[str] = [
    # ── Section headers ──────────────────────────────────────────────────────
    r'^\s*Context\s*[:\-]',
    r'^\s*Question\s*[:\-]',
    r'^\s*Document\s*[:\-]',
    r'^\s*Document\s+(?:Context|excerpt|below)\s*[:\-]?',
    r'^\s*Instructions?\s*[:\-]',
    r'^\s*Conversation\s+History\s*[:\-]',
    r'^\s*Current\s+Question\s*[:\-]',
    r'^\s*Previous\s+conversation\s*[:\-]?',
    r'^\s*History\s*[:\-]',
    r'^\s*Doc\d+\s*[:\-]',              # Doc1: / Doc2: comparison headers
    r'^\s*RULES\s*[:\-]',

    # ── Instruction sentences ─────────────────────────────────────────────────
    r'^\s*You are a (?:helpful|precise|document)',
    r'^\s*Answer the question using',
    r'^\s*Use the document',
    r'^\s*Use only the (?:provided|document)',
    r'^\s*Read the document',
    r'^\s*If the answer is not',
    r'^\s*If (?:you )?cannot find',
    r'^\s*Keep the answer',
    r'^\s*Be brief',
    r'^\s*Be concise',
    r'^\s*Base your',
    r'^\s*Do NOT',
    r'^\s*Do not',
    r'^\s*Your response must',
    r'^\s*Your answer (?:must|should)',
    r'^\s*Never (?:include|repeat|add)',
    r'^\s*Only (?:use|return|output)',
    r'^\s*Respond (?:with|using|only)',
    r'^\s*Return (?:only|a|the)',
    r'^\s*Provide (?:a (?:short|brief|concise))',
    r'^\s*Give a (?:short|brief|one-line)',
    r'^\s*Compare the documents',
    r'^\s*Summarize the document',
    r'^\s*In \d+[\-–]?\d* (?:bullet|key)',

    # ── Bullet-point instruction lines ────────────────────────────────────────
    r'^\s*[-•*]\s*Use ONLY',
    r'^\s*[-•*]\s*Summarize in',
    r'^\s*[-•*]\s*Clearly distinguish',
    r'^\s*[-•*]\s*Return clean',
    r'^\s*[-•*]\s*Do NOT',
    r'^\s*[-•*]\s*list key',
    r'^\s*[-•*]\s*Give a',

    # ── Flan-T5 specific echo artefacts ──────────────────────────────────────
    r'^\s*Summary\s*\(bullet',
    r'^\s*Answer\s*\(brief\)',
    r'^\s*question-answering assistant',
    r'^\s*document comparison assistant',
]

_ECHO_RE = re.compile("|".join(_ECHO_PATTERNS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Sentence-level instruction filter
# Catches models that output instruction text as inline sentences rather than
# on their own lines.
# ---------------------------------------------------------------------------

_SENTENCE_ECHO_PATTERNS: list[str] = [
    r'Use (?:only|ONLY) the (?:provided|document) (?:text|information|context)',
    r'(?:Do NOT|Do not|Never) (?:repeat|include|add|invent)',
    r'Answer the question using only',
    r'Be brief and direct',
    r'If the answer is not (?:in|found in) the document',
    r'based (?:solely|only) on the (?:provided|document)',
]

_SENTENCE_ECHO_RE = re.compile(
    "|".join(_SENTENCE_ECHO_PATTERNS),
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal pipeline
# ---------------------------------------------------------------------------

def _split_on_marker(text: str, marker_re: re.Pattern) -> str:
    """
    Return only the text AFTER the last occurrence of *marker_re*.
    If the marker is not found, return *text* unchanged.
    """
    # finditer gives us all matches; we want the LAST one so the model's
    # own "Answer: ..." production inside a long echo is used.
    matches = list(marker_re.finditer(text))
    if not matches:
        return text
    last = matches[-1]
    return text[last.end():].strip()


def _filter_echo_lines(text: str) -> str:
    """Remove lines that match known instruction / context-header patterns."""
    lines = text.splitlines()
    kept = [ln for ln in lines if not _ECHO_RE.match(ln)]
    return "\n".join(kept)


def _filter_echo_sentences(text: str) -> str:
    """
    Remove sentences that ARE instruction text inlined by the model.
    Splits on sentence-ending punctuation to identify and drop them.
    """
    # Split into rough sentences on  .  ?  !  (followed by space or end)
    parts = re.split(r'(?<=[.?!])\s+', text)
    kept = [s for s in parts if not _SENTENCE_ECHO_RE.search(s)]
    return " ".join(kept)


def _normalize_spaced_text(text: str) -> str:
    """
    Fix character-level spaced tokens produced by certain PDF parsers.
    E.g. ``"N P T E L"`` → ``"NPTEL"``.
    """
    def _join(m: re.Match) -> str:
        return m.group(0).replace(" ", "")

    return re.sub(r'\b(?:[A-Za-z] ){2,}[A-Za-z]\b', _join, text)


def _clean(
    llm_output: str,
    marker_re: re.Pattern,
    leading_marker_re: re.Pattern,
    fallback: str,
) -> str:
    """
    Shared cleaning pipeline used by all three public functions.

    Parameters
    ----------
    llm_output:
        Raw string from the generation model.
    marker_re:
        Compiled regex that matches the terminal prompt marker
        (``Answer:``, ``Summary:``, or ``Comparison:``).
    leading_marker_re:
        Compiled regex that strips a stray marker the model emitted at the
        very start of its output (e.g. ``"Answer: Answer: <text>"``).
    fallback:
        Message returned when nothing useful survives cleaning.
    """
    # Guard: handle None / non-string inputs.
    if not isinstance(llm_output, str):
        llm_output = str(llm_output) if llm_output is not None else ""

    raw = llm_output.strip()

    # ── Step 1 & 2: Split on terminal marker ─────────────────────────────────
    # Using _split_on_marker (last occurrence) handles the common pattern where
    # flan-t5 echoes the entire prompt and then produces "Answer: <text>" at
    # the end of the echo.
    raw = _split_on_marker(raw, marker_re)

    # ── Step 3: Line-level echo filter ───────────────────────────────────────
    raw = _filter_echo_lines(raw)

    # ── Step 4: Sentence-level instruction filter ─────────────────────────────
    raw = _filter_echo_sentences(raw)

    # ── Step 5: Whitespace normalisation ─────────────────────────────────────
    raw = re.sub(r'[ \t]{2,}', ' ', raw)    # multiple spaces/tabs → one space
    raw = re.sub(r'\n{3,}', '\n\n', raw)    # triple+ blank lines → double
    raw = raw.strip()

    # ── Step 6: Character-spacing normalisation ───────────────────────────────
    raw = _normalize_spaced_text(raw)

    # ── Step 7: Strip stray leading marker (model echoed it again) ───────────
    raw = leading_marker_re.sub("", raw).strip()

    # ── Step 8: Safe fallback ─────────────────────────────────────────────────
    return raw if raw else fallback


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_final_answer(llm_output: str) -> str:
    """
    Strip all prompt/context leakage and return only the clean answer.

    Call this on every raw string that comes back from the generation model
    before returning it through the ``/ask`` endpoint.

    Parameters
    ----------
    llm_output:
        Verbatim string produced by ``tokenizer.decode`` (or equivalent).

    Returns
    -------
    str
        Clean, user-facing answer text.  Never an empty string.
    """
    return _clean(
        llm_output,
        marker_re=_MARKER_ANSWER,
        leading_marker_re=_LEADING_ANSWER_RE,
        fallback="I could not find a relevant answer in the document.",
    )


def extract_final_summary(llm_output: str) -> str:
    """
    Strip all prompt/context leakage and return only the clean summary.

    Call this on every raw string that comes back from the generation model
    before returning it through the ``/summarize`` endpoint.

    Parameters
    ----------
    llm_output:
        Verbatim string produced by ``tokenizer.decode`` (or equivalent).

    Returns
    -------
    str
        Clean, user-facing summary text.  Never an empty string.
    """
    return _clean(
        llm_output,
        marker_re=_MARKER_SUMMARY,
        leading_marker_re=_LEADING_SUMMARY_RE,
        fallback="I could not generate a summary for this document.",
    )


def extract_comparison(llm_output: str) -> str:
    """
    Strip all prompt/context leakage and return only the clean comparison.

    Call this on every raw string that comes back from the generation model
    before returning it through the ``/compare`` endpoint.

    Parameters
    ----------
    llm_output:
        Verbatim string produced by ``tokenizer.decode`` (or equivalent).

    Returns
    -------
    str
        Clean, user-facing comparison text.  Never an empty string.
    """
    return _clean(
        llm_output,
        marker_re=_MARKER_COMPARISON,
        leading_marker_re=_LEADING_COMPARISON_RE,
        fallback="I could not generate a comparison for these documents.",
    )
