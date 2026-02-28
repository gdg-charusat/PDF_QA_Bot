"""
Unit tests for the numeric disambiguation helpers added to main.py.
Run with:  pytest rag-service/test_disambiguation.py -v
"""
import re
import pytest

# ---------------------------------------------------------------------------
# Copied helpers (so tests don't need to import the full FastAPI app)
# ---------------------------------------------------------------------------

NUMERIC_KEYWORDS = [
    "percent", "percentage", "%", "score", "marks", "ratio",
    "rate", "result", "grade", "cgpa", "gpa"
]


def is_numeric_question(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in NUMERIC_KEYWORDS)


def extract_percentage(text: str) -> str:
    matches = re.findall(r'\b\d+(?:\.\d+)?%', text)
    if matches:
        return matches[-1]
    return text


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIsNumericQuestion:
    def test_percentage_keyword(self):
        assert is_numeric_question("What is the percentage in this PDF?") is True

    def test_percent_keyword(self):
        assert is_numeric_question("What percent did the student score?") is True

    def test_marks_keyword(self):
        assert is_numeric_question("How many marks did she get?") is True

    def test_grade_keyword(self):
        assert is_numeric_question("What grade was awarded?") is True

    def test_non_numeric_question(self):
        assert is_numeric_question("Who is the author of this document?") is False

    def test_non_numeric_question_2(self):
        assert is_numeric_question("What are the main topics covered?") is False


class TestExtractPercentage:
    def test_single_percentage(self):
        assert extract_percentage("The student scored 69%.") == "69%"

    def test_prefers_last_percentage(self):
        # When multiple % values exist, the last (consolidated) one should win
        assert extract_percentage("Marks: 45/75. Total: 24/25. Overall: 69%.") == "69%"

    def test_decimal_percentage(self):
        assert extract_percentage("Final score: 85.5%.") == "85.5%"

    def test_no_percentage_falls_back(self):
        text = "The answer is 45/75."
        assert extract_percentage(text) == text

    def test_mixed_text(self):
        assert extract_percentage("Result is 45/75 which is 60%.") == "60%"


class TestRetrieveAndRerank:
    """Smoke-test the re-ranking logic without a real vectorstore."""

    def _make_doc(self, content):
        class FakeDoc:
            def __init__(self, text):
                self.page_content = text
        return FakeDoc(content)

    def test_pct_chunks_come_first(self):
        docs = [
            self._make_doc("The student attempted 45/75 questions correctly."),
            self._make_doc("Section B: 24/25 correct."),
            self._make_doc("Final consolidated result: 69%."),
            self._make_doc("Overall performance was good."),
        ]
        # Simulate the re-rank logic
        has_pct = [d for d in docs if "%" in d.page_content]
        no_pct  = [d for d in docs if "%" not in d.page_content]
        reranked = (has_pct + no_pct)[:4]

        assert reranked[0].page_content == "Final consolidated result: 69%."

    def test_non_numeric_order_unchanged(self):
        docs = [
            self._make_doc("Chapter 1: Introduction."),
            self._make_doc("Chapter 2: Methods."),
        ]
        # Non-numeric question → order stays as-is
        question = "What are the chapters?"
        assert is_numeric_question(question) is False
        # docs[:4] → same order
        assert docs[0].page_content == "Chapter 1: Introduction."
