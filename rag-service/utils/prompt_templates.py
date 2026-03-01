"""
utils/prompt_templates.py
-------------------------
Centralised prompt builders for the PDF Q&A RAG service.

WHY THIS EXISTS
---------------
Small seq2seq models like flan-t5-base have a limited context window and a
strong tendency to echo the prompt verbatim when the instruction block is too
long.  Keeping the prompt as SHORT as possible (while still directing the model
clearly) dramatically reduces instruction leakage in the generated output.

All builders follow the same contract:
  • Contain NO newlines inside instruction sentences.
  • Use the exact label "Answer:" / "Summary:" / "Comparison:" so that the
    post-processor can split on it reliably.
  • Never include multi-sentence bullet-point rules inside the prompt — those
    are the primary source of echoed instruction text.

IMPORTANT — Why answer_type_hint was removed from build_ask_prompt
------------------------------------------------------------------
An earlier version injected a format hint into the prompt, e.g.:
  "Answer the question … Be brief. Look for a value ending with the % symbol."
Testing proved that flan-t5-base treats this literally and outputs only the
symbol it was told to look for (bare "%" or bare "$").
Numeric disambiguation now happens AFTER generation in
``query_utils.extract_typed_answer`` using regex on the raw context.
"""

__all__ = ["build_ask_prompt", "build_summarize_prompt", "build_compare_prompt"]


# ---------------------------------------------------------------------------
# Token budget (characters) for each section
# flan-t5-base: 512 input tokens ≈ ~2 000 characters
# ---------------------------------------------------------------------------
_MAX_CONTEXT_CHARS = 1_400   # leave room for question + instructions
_MAX_CONV_CHARS    = 400     # history budget


def _truncate(text: str, max_chars: int) -> str:
    """Hard-truncate *text* to *max_chars* characters, adding an ellipsis."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def build_ask_prompt(
    context: str,
    question: str,
    conversation_context: str = "",
) -> str:
    """
    Build the minimal QA prompt.

    Parameters
    ----------
    context:
        Retrieved document chunks joined as a single string.
    question:
        The user's question.
    conversation_context:
        Optional recent chat history (role: content lines).

    Returns
    -------
    str
        A compact prompt string ready to pass to the generation model.

    Notes
    -----
    Deliberately kept to ONE plain instruction sentence with NO format hints.
    Injecting hints like "look for a % value" caused flan-t5-base to echo the
    hint symbol literally (e.g. outputting bare "%").
    Numeric / typed-answer disambiguation is handled AFTER generation by
    ``query_utils.extract_typed_answer``.
    """
    ctx  = _truncate(context, _MAX_CONTEXT_CHARS)
    conv = _truncate(conversation_context.strip(), _MAX_CONV_CHARS) if conversation_context.strip() else ""

    # One plain instruction line — no format hints, no bullet points.
    instruction = "Answer the question using only the document below. Be brief and direct."

    parts = [instruction, ""]

    if conv:
        parts += [f"History: {conv}", ""]

    parts += [
        f"Document: {ctx}",
        "",
        f"Question: {question}",
        "Answer:",
    ]

    return "\n".join(parts)


def build_summarize_prompt(context: str) -> str:
    """
    Build the minimal summarization prompt.

    Parameters
    ----------
    context:
        Retrieved document chunks joined as a single string.

    Returns
    -------
    str
        A compact prompt string ready to pass to the generation model.
    """
    ctx = _truncate(context, _MAX_CONTEXT_CHARS)

    instruction = "Summarize the document below in 3 to 5 key bullet points. Use only the provided text."

    return "\n".join([
        instruction,
        "",
        f"Document: {ctx}",
        "",
        "Summary:",
    ])


def build_compare_prompt(per_doc_contexts: list[str]) -> str:
    """
    Build the minimal document-comparison prompt.

    Parameters
    ----------
    per_doc_contexts:
        List of per-document context strings (one entry per document).

    Returns
    -------
    str
        A compact prompt string ready to pass to the generation model.
    """
    # Each document gets an equal share of the context budget
    budget_each = _MAX_CONTEXT_CHARS // max(len(per_doc_contexts), 1)
    doc_blocks = []
    for i, ctx in enumerate(per_doc_contexts, start=1):
        doc_blocks.append(f"Doc{i}: {_truncate(ctx, budget_each)}")

    instruction = (
        "Compare the documents below. Give a one-line overview of each, "
        "then list key similarities and key differences. Use only the provided text."
    )

    return "\n".join([
        instruction,
        "",
        "\n\n".join(doc_blocks),
        "",
        "Comparison:",
    ])
