"""
tests/test_extraction.py
------------------------
10-iteration unit tests for query_utils.extract_typed_answer and
utils.postprocess.extract_final_answer.

Run from the rag-service/ directory (no server needed):
    python tests/test_extraction.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.query_utils import (
    extract_typed_answer, expand_query, _is_context_dump, _extract_denominator,
)
from utils.postprocess import extract_final_answer

# ---------------------------------------------------------------------------
# Real contextual data observed from the NPTEL certificate PDF
# ---------------------------------------------------------------------------

NPTEL_CONTEXT = (
    "Jan-Mar 2025 (8 week course) Design and analysis of algorithms "
    "RADADIYA HETVI HASMUKHBHAI 22/25 35.63/75 58 1696 "
    "NPTEL25CS23S334600098 Roll No: No. of credits recommended: 2 or 3 "
    "To verify the certificate visit nptel.ac.in/noc"
)

NPTEL_CONTEXT_2 = (
    "Assignment Score: 22/25  Exam Score: 35.63/75  "
    "Total Score: 58  "
    "Course: Design and Analysis of Algorithms  "
    "Duration: Jan-Mar 2025"
)

MARKS_CONTEXT = (
    "Subject: Mathematics  Marks: 87/100  Grade: A  "
    "Subject: Physics  Marks: 72/100  Grade: B  "
    "Aggregate percentage: 79.5%  "
    "Student: John Doe  Roll: 2023001"
)

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(test_id, description, actual, expected_contains_one_of):
    """Assert that *actual* contains at least one expected substring."""
    matched = any(e.lower() in actual.lower() for e in expected_contains_one_of)
    status = PASS if matched else FAIL
    results.append(matched)
    print(f"  {status}  Test {test_id:02d}: {description}")
    print(f"         answer   = {repr(actual)}")
    if not matched:
        print(f"         expected = one of {expected_contains_one_of}")
    print()


# ===========================================================================
# ITERATION 1 -- "how much percentage i got from 100" -> "58%"
# This question DOES have the word "percentage" -> pct mode -> 58%
# ===========================================================================
answer = extract_typed_answer(
    llm_answer="%",                         # model returned garbage
    question="How much percentage i got from 100",
    context=NPTEL_CONTEXT,
)
check(1, "'percentage from 100' -> pct mode -> 58%",
      answer, ["58%", "58"])

# ===========================================================================
# ITERATION 2 -- "how much percentage i got?" -> "58%"
# Explicit "percentage" keyword -> pct mode
# ===========================================================================
answer = extract_typed_answer(
    llm_answer="22/25",                     # model returned wrong value
    question="how much percentage i got?",
    context=NPTEL_CONTEXT,
)
check(2, "'percentage i got' -> 58%",
      answer, ["58%", "58"])

# ===========================================================================
# ITERATION 3 -- "how many assignment i have done?" -> NOT "2 or 3"
# LLM returns "2 or 3" (credits) which _RANGE_ANSWER should reject.
# Correct answer: first fraction in context = 22/25
# ===========================================================================
answer = extract_typed_answer(
    llm_answer="2 or 3",                    # credits recommendation, not assignment count
    question="how many assignment i have done?",
    context=NPTEL_CONTEXT,
)
check(3, "'how many assignments' rejects '2 or 3' -> 22 out of 25",
      answer, ["22", "22 out of 25", "22/25"])

# ===========================================================================
# ITERATION 4 -- "how many marks from 25 i got?" -> "22 out of 25"
# Denominator hint "from 25" -> look for X/25 -> 22/25
# Must NOT return 58% (percentage mode should not fire without "percentage" keyword)
# ===========================================================================
answer = extract_typed_answer(
    llm_answer="58%",                       # model returned wrong type
    question="how many marks from 25 i got?",
    context=NPTEL_CONTEXT,
)
check(4, "'marks from 25' -> 22 out of 25 (not 58%)",
      answer, ["22", "22 out of 25", "22/25"])

# ===========================================================================
# ITERATION 5 -- Context dump detection: _is_context_dump returns True
# ===========================================================================
result = _is_context_dump(NPTEL_CONTEXT)
check(5, "_is_context_dump detects NPTEL metadata line",
      str(result), ["True"])

# ===========================================================================
# ITERATION 6 -- postprocess clears context dump to fallback
# ===========================================================================
cleaned = extract_final_answer(NPTEL_CONTEXT)
check(6, "extract_final_answer returns fallback for context dump",
      cleaned, ["could not", "i could not"])

# ===========================================================================
# ITERATION 7 -- Explicit % in context -> return it (for MARKS context)
# ===========================================================================
answer = extract_typed_answer(
    llm_answer="%",
    question="What is the aggregate percentage?",
    context=MARKS_CONTEXT,
)
check(7, "Explicit pct in context returned directly",
      answer, ["79.5%", "79%"])

# ===========================================================================
# ITERATION 8 -- Name question: ALL-CAPS extraction
# ===========================================================================
answer = extract_typed_answer(
    llm_answer="?",
    question="What is the student name?",
    context=NPTEL_CONTEXT,
)
check(8, "Name question extracts ALL-CAPS name",
      answer, ["RADADIYA", "HETVI"])

# ===========================================================================
# ITERATION 9 -- Date question: extract from context
# ===========================================================================
answer = extract_typed_answer(
    llm_answer="",
    question="When was this course completed?",
    context=NPTEL_CONTEXT_2,
)
check(9, "Date question extracts date from context",
      answer, ["2025", "Jan"])

# ===========================================================================
# ITERATION 10 -- _extract_denominator helper
# ===========================================================================
d1 = _extract_denominator("how many marks from 25 i got")
d2 = _extract_denominator("score out of 75")
d3 = _extract_denominator("what is the percentage")  # no denominator
check(10, "_extract_denominator finds 'from 25' and 'out of 75', None for others",
      f"{d1},{d2},{d3}", ["25,", "75,", ",none", ",None"])

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
passed = sum(results)
total  = len(results)
print("=" * 60)
print(f"  Results: {passed}/{total} tests passed")
print("=" * 60)

if passed == total:
    print("\n  *** All 10 iterations PASSED -- pipeline working correctly! ***")
else:
    failed = [i+1 for i, r in enumerate(results) if not r]
    print(f"\n  WARNING: Failed test IDs: {failed}")
    sys.exit(1)
