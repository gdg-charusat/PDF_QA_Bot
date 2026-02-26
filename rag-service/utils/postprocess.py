"""
utils/postprocess.py
--------------------
Post-processing utilities for LLM output in the PDF Q&A RAG service.

WHY THIS EXISTS
---------------
Large language models prompted with a template that includes a "Context:" block,
a "Question:" label, and an "Answer:" marker may echo those labels verbatim in
their output.  Without post-processing the API would leak:

  • Prompt instructions  ("You are a precise question-answering assistant...")
  • Retrieved document chunks  (the "Document excerpt:" section)
  • The original question      ("Question: ...")
  • Redundant "Answer:" prefixes

This module provides `extract_final_answer`, a single reusable function that
strips all of the above and returns only the clean, user-facing text.
"""

import re


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_final_answer(llm_output: str) -> str:
    """
    Extract and clean the final answer from raw LLM output.

    This is the primary post-processing entry point.  Call it on every raw
    string that comes back from the model before returning it to the caller.

    Strategy (applied in order):
        1. If the text contains an ``Answer:`` marker, keep only what follows.
        2. Strip any remaining lines that look like prompt echoes or
           retrieved-context headers (``Context:``, ``Question:``, etc.).
        3. Collapse excessive horizontal whitespace and blank lines.
        4. Normalize residual character-level spacing (space-separated letters
           produced by some PDF parsers).
        5. Deduplicate the "Answer:" prefix if it was emitted twice by the
           model (e.g. ``Answer: Answer:`` → strip leading label).
        6. Return a safe fallback message when nothing useful remains.

    Parameters
    ----------
    llm_output:
        The verbatim string produced by ``tokenizer.decode`` or an equivalent
        pipeline output step.

    Returns
    -------
    str
        Clean, user-facing answer text — never an empty string.

    Notes
    -----
    This function is designed to *never* raise an exception regardless of
    what ``llm_output`` contains, including empty strings or ``None``-like
    values coerced to strings.
    """
    # Guard: handle None / non-string inputs without crashing.
    if not isinstance(llm_output, str):
        llm_output = str(llm_output) if llm_output is not None else ""

    raw = llm_output

    # ── Step 1: Extract text after the "Answer:" marker if present ───────────
    # Matches "Answer:", "Answer -", or "Answer" at the start of a line so
    # that we don't accidentally match the word "answer" mid-sentence.
    answer_marker = re.search(
        r'(?:^|\n)\s*Answer\s*[:\-]?\s*\n?(.*)',
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if answer_marker:
        raw = answer_marker.group(1).strip()

    # ── Step 2: Drop lines that are clearly prompt / context echoes ──────────
    # Each pattern anchored with ^ so it only matches line-starts.
    ECHO_PATTERNS = [
        r'^\s*Context\s*[:\-]',
        r'^\s*Question\s*[:\-]',
        r'^\s*Instructions?\s*[:\-]',
        r'^\s*Conversation\s+History\s*[:\-]',
        r'^\s*Document\s+(?:Context|excerpt)\s*[:\-]',
        r'^\s*Current\s+Question\s*[:\-]',
        r'^\s*Previous\s+conversation\s*[:\-]?',
        r'^\s*You are a helpful',
        r'^\s*You are a precise',
        r'^\s*Use the document',
        r'^\s*If the answer is not',
        r'^\s*Keep the answer',
        r'^\s*Base your',
        r'^\s*Do NOT',
        r'^\s*RULES\s*[:\-]',
        r'^\s*Summary\s*\(bullet',
        r'^\s*-\s*Use ONLY',
        r'^\s*-\s*Summarize in',
        r'^\s*-\s*Clearly distinguish',
        r'^\s*-\s*Return clean',
    ]
    echo_re = re.compile('|'.join(ECHO_PATTERNS), re.IGNORECASE)
    lines = raw.splitlines()
    cleaned_lines = [ln for ln in lines if not echo_re.match(ln)]
    raw = '\n'.join(cleaned_lines)

    # ── Step 3: Collapse excessive whitespace ─────────────────────────────────
    raw = re.sub(r'[ \t]{2,}', ' ', raw)   # multiple spaces/tabs → single space
    raw = re.sub(r'\n{3,}', '\n\n', raw)   # triple+ newlines → double newline
    raw = raw.strip()

    # ── Step 4: Normalise residual character-level spacing ───────────────────
    # Some PDF parsers emit "N P T E L" instead of "NPTEL"; fix those here so
    # they do not leak through to the final answer.
    raw = _normalize_spaced_text(raw)

    # ── Step 5: Remove duplicated "Answer:" prefix (hallucination artefact) ──
    # Guard against the model generating "Answer: Answer: <text>" by stripping
    # any leading "Answer[: -]" that the model may have emitted again.
    raw = re.sub(r'(?i)^Answer\s*[:\-]\s*', '', raw).strip()

    # ── Step 6: Safe fallback ─────────────────────────────────────────────────
    return raw if raw else "I could not find a relevant answer in the document."


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_spaced_text(text: str) -> str:
    """
    Fix character-level spaced tokens produced by certain PDF parsers.

    For example, ``"N P T E L"`` → ``"NPTEL"``.

    This is an internal helper; prefer ``extract_final_answer`` externally.
    """
    def _join_spaced(match: re.Match) -> str:
        return match.group(0).replace(' ', '')

    # Match sequences of single letters separated by single spaces (≥ 3 letters).
    pattern = r'\b(?:[A-Za-z] ){2,}[A-Za-z]\b'
    return re.sub(pattern, _join_spaced, text)
