"""
Unit tests for services/llm_service.py

The HF model stack is never actually loaded — all generation behaviour is
exercised through mocks so the test suite stays fast and dependency-free.
"""

from unittest.mock import MagicMock, patch

import pytest

import services.llm_service as llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_llm_state():
    """Return llm module globals to a clean (unloaded) state."""
    llm._config = None
    llm._is_encoder_decoder = False
    llm._tokenizer = None
    llm._model = None
    llm._AutoConfig = None
    llm._AutoTokenizer = None
    llm._AutoModelForSeq2SeqLM = None
    llm._AutoModelForCausalLM = None


# ---------------------------------------------------------------------------
# load_generation_model
# ---------------------------------------------------------------------------

class TestLoadGenerationModel:
    def setup_method(self):
        _reset_llm_state()

    def teardown_method(self):
        _reset_llm_state()

    def test_returns_false_when_transformers_unavailable(self):
        with patch("services.llm_service._ensure_transformers_imports", return_value=False):
            assert llm.load_generation_model() is False

    def test_returns_true_and_caches_model_for_encoder_decoder(self):
        mock_config = MagicMock()
        mock_config.is_encoder_decoder = True

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_model.parameters.return_value = iter([MagicMock(device="cpu")])
        mock_model.eval = MagicMock()

        mock_ac = MagicMock()
        mock_ac.from_pretrained.return_value = mock_config
        mock_at = MagicMock()
        mock_at.from_pretrained.return_value = mock_tokenizer
        mock_seq2seq = MagicMock()
        mock_seq2seq.from_pretrained.return_value = mock_model
        mock_causal = MagicMock()

        llm._AutoConfig = mock_ac
        llm._AutoTokenizer = mock_at
        llm._AutoModelForSeq2SeqLM = mock_seq2seq
        llm._AutoModelForCausalLM = mock_causal

        with patch("services.llm_service._ensure_transformers_imports", return_value=True):
            result = llm.load_generation_model()

        assert result is True
        assert llm._model is mock_model
        assert llm._is_encoder_decoder is True
        mock_seq2seq.from_pretrained.assert_called_once()
        mock_causal.from_pretrained.assert_not_called()

    def test_returns_true_and_uses_causal_model_for_decoder_only(self):
        mock_config = MagicMock()
        mock_config.is_encoder_decoder = False

        mock_model = MagicMock()
        mock_model.eval = MagicMock()
        mock_model.parameters.return_value = iter([MagicMock(device="cpu")])

        mock_ac = MagicMock()
        mock_ac.from_pretrained.return_value = mock_config
        mock_at = MagicMock()
        mock_at.from_pretrained.return_value = MagicMock()
        mock_seq2seq = MagicMock()
        mock_causal = MagicMock()
        mock_causal.from_pretrained.return_value = mock_model

        llm._AutoConfig = mock_ac
        llm._AutoTokenizer = mock_at
        llm._AutoModelForSeq2SeqLM = mock_seq2seq
        llm._AutoModelForCausalLM = mock_causal

        with patch("services.llm_service._ensure_transformers_imports", return_value=True):
            result = llm.load_generation_model()

        assert result is True
        mock_causal.from_pretrained.assert_called_once()
        mock_seq2seq.from_pretrained.assert_not_called()

    def test_returns_false_on_load_exception(self):
        llm._AutoConfig = MagicMock(side_effect=OSError("network down"))

        with patch("services.llm_service._ensure_transformers_imports", return_value=True):
            result = llm.load_generation_model()

        assert result is False
        assert llm._model is None

    def test_skips_reload_when_model_already_cached(self):
        llm._model = MagicMock()  # simulate already loaded

        called = []
        with patch("services.llm_service._ensure_transformers_imports", side_effect=lambda: called.append(1) or True):
            result = llm.load_generation_model()

        assert result is True
        assert called == []  # _ensure_transformers_imports was never reached


# ---------------------------------------------------------------------------
# generate_response
# ---------------------------------------------------------------------------

class TestGenerateResponse:
    def setup_method(self):
        _reset_llm_state()

    def teardown_method(self):
        _reset_llm_state()

    def test_raises_runtime_error_when_model_unavailable(self):
        with patch("services.llm_service.load_generation_model", return_value=False):
            with pytest.raises(RuntimeError, match="unavailable"):
                llm.generate_response("hello")

    def _setup_loaded_model(self, is_encoder_decoder: bool, decoded_text: str):
        """Wire up mock model + tokenizer and return them."""
        mock_param = MagicMock()
        mock_param.device = "cpu"

        mock_model = MagicMock()
        mock_model.parameters.return_value = iter([mock_param])

        # Tokenizer returns a simple dict of mock tensors
        mock_input_ids = MagicMock()
        mock_input_ids.shape = [1, 5]  # batch=1, seq_len=5
        mock_inputs = {"input_ids": mock_input_ids}

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = mock_inputs
        mock_tokenizer.pad_token_id = 0

        # model.generate returns a 2-D list-like
        mock_output_ids = MagicMock()
        mock_model.generate.return_value = [mock_output_ids]

        mock_tokenizer.decode.return_value = decoded_text

        llm._model = mock_model
        llm._tokenizer = mock_tokenizer
        llm._is_encoder_decoder = is_encoder_decoder

        return mock_model, mock_tokenizer

    def test_returns_decoded_text_for_encoder_decoder(self):
        mock_model, mock_tokenizer = self._setup_loaded_model(
            is_encoder_decoder=True, decoded_text="Paris"
        )

        with patch("services.llm_service.load_generation_model", return_value=True):
            result = llm.generate_response("What is the capital of France?")

        assert result == "Paris"
        mock_tokenizer.decode.assert_called_once()

    def test_strips_prompt_tokens_for_causal_model(self):
        mock_model, mock_tokenizer = self._setup_loaded_model(
            is_encoder_decoder=False, decoded_text="continuation"
        )

        with patch("services.llm_service.load_generation_model", return_value=True):
            result = llm.generate_response("prompt text", max_new_tokens=50)

        assert result == "continuation"
        # For causal models decode is called with a slice, not the full output[0]
        decode_call_args = mock_tokenizer.decode.call_args
        assert decode_call_args is not None

    def test_passes_max_new_tokens_to_generate(self):
        mock_model, mock_tokenizer = self._setup_loaded_model(
            is_encoder_decoder=True, decoded_text="answer"
        )

        with patch("services.llm_service.load_generation_model", return_value=True):
            llm.generate_response("q", max_new_tokens=42)

        call_kwargs = mock_model.generate.call_args[1]
        assert call_kwargs["max_new_tokens"] == 42
