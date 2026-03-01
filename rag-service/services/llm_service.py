"""
services/llm_service.py
~~~~~~~~~~~~~~~~~~~~~~~
Handles lazy loading of the Hugging Face generation model and tokenizer,
and exposes a single :func:`generate_response` helper used by route handlers.

All heavy ML imports are deferred to first use so that the module can be safely
imported in test environments that do not have ``torch`` / ``transformers``
installed.
"""

import logging

from core.config import HF_GENERATION_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import placeholders
# ---------------------------------------------------------------------------
_AutoConfig = None
_AutoTokenizer = None
_AutoModelForSeq2SeqLM = None
_AutoModelForCausalLM = None

# ---------------------------------------------------------------------------
# Module-level state (effectively a singleton)
# ---------------------------------------------------------------------------
_config = None
_is_encoder_decoder: bool = False
_tokenizer = None
_model = None


def _ensure_transformers_imports() -> bool:
    """Import transformers classes on first call. Returns False if unavailable."""
    global _AutoConfig, _AutoTokenizer, _AutoModelForSeq2SeqLM, _AutoModelForCausalLM
    if _AutoConfig is not None:
        return True
    try:
        from transformers import (  # type: ignore
            AutoConfig,
            AutoTokenizer,
            AutoModelForSeq2SeqLM,
            AutoModelForCausalLM,
        )
        _AutoConfig = AutoConfig
        _AutoTokenizer = AutoTokenizer
        _AutoModelForSeq2SeqLM = AutoModelForSeq2SeqLM
        _AutoModelForCausalLM = AutoModelForCausalLM
        return True
    except Exception as exc:  # noqa: BLE001 – broken transitive deps can raise NameError etc.
        logger.warning("Could not import transformers: %s", exc)
        return False


def load_generation_model() -> bool:
    """
    Lazily load the HF generation model and tokenizer.

    Returns
    -------
    bool
        ``True`` when the model is ready, ``False`` if loading failed.
    """
    global _config, _is_encoder_decoder, _tokenizer, _model

    if _model is not None:
        return True

    if not _ensure_transformers_imports():
        return False

    try:
        _config = _AutoConfig.from_pretrained(HF_GENERATION_MODEL)
        _is_encoder_decoder = bool(getattr(_config, "is_encoder_decoder", False))
        _tokenizer = _AutoTokenizer.from_pretrained(HF_GENERATION_MODEL)

        if _is_encoder_decoder:
            _model = _AutoModelForSeq2SeqLM.from_pretrained(HF_GENERATION_MODEL)
        else:
            _model = _AutoModelForCausalLM.from_pretrained(HF_GENERATION_MODEL)

        # Move to CUDA if available; fall back to CPU gracefully
        try:
            import torch as _torch  # type: ignore

            if getattr(_torch, "cuda", None) and _torch.cuda.is_available():
                _model.to("cuda")
        except (ImportError, RuntimeError, OSError) as exc:
            logger.debug("CUDA unavailable, using CPU: %s", exc)

        _model.eval()
        logger.info("LLM loaded: %s (encoder-decoder=%s)", HF_GENERATION_MODEL, _is_encoder_decoder)
        return True

    except Exception as exc:
        logger.error("Failed to load generation model: %s", exc)
        _model = None
        _tokenizer = None
        return False


def generate_response(prompt: str, max_new_tokens: int = 200) -> str:
    """
    Generate a text response for *prompt* using the loaded LLM.

    Parameters
    ----------
    prompt:
        The full prompt string to send to the model.
    max_new_tokens:
        Maximum number of tokens the model may generate.

    Returns
    -------
    str
        The generated text (decoded, special tokens stripped).

    Raises
    ------
    RuntimeError
        If the generation model is unavailable (not installed or failed to load).
    """
    if not load_generation_model():
        raise RuntimeError("Generation model unavailable")

    device = next(_model.parameters()).device
    inputs = _tokenizer(
        prompt, return_tensors="pt", truncation=True, max_length=2048
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    output = _model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=_tokenizer.pad_token_id or _tokenizer.eos_token_id,
    )

    if _is_encoder_decoder:
        return _tokenizer.decode(output[0], skip_special_tokens=True)

    # For causal (decoder-only) models, strip the echoed prompt tokens
    return _tokenizer.decode(
        output[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )
