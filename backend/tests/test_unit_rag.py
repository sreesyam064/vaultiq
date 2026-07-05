"""
Tier 1 — Unit Tests: Query-Type Detection & Prompt Building
===========================================================
These tests have ZERO external dependencies — no DB, no Chroma, no LLM.
They run in milliseconds and cover pure logic inside rag_service.py

whats tested:
    _detect_query_type()  —  all 4 broad types _ factual fallback
    PROMPT_INSTRUCTIONS   —  every type has a non-empty instructions
    invoke_with_retry     —  retry logic with a mocked LLM client
    get_llm()             —  provider factory validation errors
"""

import pytest 
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
    
# _detect_query_type()

class TestDetectQueryType:
    """
    Parameterized table-driven tests for _detect_query_type().
    
    Each tuple is (input_question, expected_type). This pattern means adding
    a new keyword or type is just adding one more row to table — no new test func needed.
    """
    from services.rag_service import _detect_query_type

    @pytest.mark.parametrize("question, expected", [
        # Summarize
        ("Summarize the uploaded documents", "summarize"),
        ("Summarize my document", "summarize"),
        ("Give me an overview of the document", "summarize"),
        ("What is this document about?", "summarize"),
        ("What does this paper say?", "summarize"),
        ("Tell me about this document", "summarize"),
        ("Explain this paper to me", "summarize"),
        
        # Compare
        ("Compare the main topics discussed", "compare"),
        ("What is the comparison between the ideas?", "compare"),
        ("Contrast the methods used", "compare"),
        ("What are the similarities between them?", "compare"),
        
        # Concepts
        ("Explain the important concepts", "concepts"),
        ("What are the key concepts in this paper?", "concepts"),
        ("List the main concepts", "concepts"),
        ("What are the core concepts here?", "concepts"),
        
        # interview
        ("Generate interview questions", "interview"),
        ("Generate interview questions based on the uploaded documents", "interview"),
        ("Quiz me on the material", "interview"),
        ("Test my knowledge of this document", "interview"),
        
        # factual fallback
        ("What is the transformer architecture?", "factual"),
        ("How does backpropagation work?", "factual"),
        ("Who wrote this paper?", "factual"),
        ("What year was this published?", "factual"),
        ("", "factual"),    # empty str
    ])
    
    def test_detect_query_type(self, question, expected):
        from services.rag_service import _detect_query_type
        result = _detect_query_type(question)
        assert result == expected, (
            f"Query: '{question}'\n"
            f"Expected type:    '{expected}'\n"
            f"Got:              '{result}'"
        )
        
    def test_case_insensitive(self):
        # Detection must be case-insensitive.
        from services.rag_service import _detect_query_type
        assert _detect_query_type("SUMMARIZE THE DOCUMENT") == "summarize"
        assert _detect_query_type("GENERATE INTERVIEW QUESTIONS") == "interview"
        assert _detect_query_type("KEY CONCEPTS") == "concepts"
            
    def test_leading_trailing_whitespace(self):
        # String whitespace before matching.
        from services.rag_service import _detect_query_type
        assert _detect_query_type("  summarize my document  ") == "summarize"
            
            
# PROMPT_INSTRUCTIONS

class TestPromptInstructions:
    
    def test_all_types_have_instructions(self):
        # Every query must have a non-empty instruction string.
        from services.rag_service import PROMPT_INSTRUCTIONS, BROAD_CHUNK_COUNTS
        
        expected_types = set(BROAD_CHUNK_COUNTS.keys()) | {"factual"}
        for query_type in expected_types:
            assert query_type in PROMPT_INSTRUCTIONS, (
                f"Missing PROMPT_INSTRUCTIONS entry for  type: '{query_type}'"
            )
            assert len(PROMPT_INSTRUCTIONS[query_type].strip()) > 20, (
                f"PROMPT_INSTRUCTIONS['{query_type}'] is suspiciously short"
            )
            
    def test_broad_chunk_counts_positive(self):
        # All broad query types must request at least 1 chunk.
        from services.rag_service import BROAD_CHUNK_COUNTS
        for query_type, count in BROAD_CHUNK_COUNTS.items():
            assert count > 0, f"BROAD_CHUNK_COUNTS['{query_type}'] = {count}, must be > 0"
            
    def test_factual_not_in_broad_chunk_counts(self):
        # 'factual' must NOT be in BROAD_CHUNK_COUNTS — it uses MMR retrieval.
        from services.rag_service import BROAD_CHUNK_COUNTS
        assert "factual" not in BROAD_CHUNK_COUNTS
        

# invoke_with_retry()

class TestInvokeWithRetry:
    """ 
    Tests for the retry logic in llm_provider.invoke_with_retry()
    Uses a mock LLM — no Ollama or API needed.
    """
    
    def test_succeeds_on_first_attempt(self):
        # Happy path — LLM responds immediately.
        from unittest.mock import MagicMock
        from llm_provider import invoke_with_retry
        
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = "Answer"
        
        result = invoke_with_retry(mock_llm, "prompt", max_retries=2)
        assert result.content == "Answer"
        assert mock_llm.invoke.call_count == 1
        
    def test_retries_on_transient_failure(self):
        # Should retry and succeed on second attempt.
        from unittest.mock import MagicMock, patch
        from llm_provider import invoke_with_retry
        
        mock_llm = MagicMock()
        success_response = MagicMock()
        success_response.content = "Retry succeeded"
        
        # Fail once, then succeed
        mock_llm.invoke.side_effect = [
            ConnectionError("timeout"),
            success_response, 
        ]
        
        with patch("llm_provider.time.sleep"):  # don't actually wait in tests
            result = invoke_with_retry(mock_llm, "prompt", max_retries=2, base_delay=0)
            
        assert result.content == "Retry succeeded"
        assert mock_llm.invoke.call_count == 2
        
    def test_raises_after_all_retries_exhausted(self):
        # Should raise the last exception when all retries fail.
        from unittest.mock import MagicMock, patch
        from llm_provider import invoke_with_retry
        
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ConnectionError("service down")
        
        with patch("llm_provider.time.sleep"):
            with pytest.raises(ConnectionError, match="service down"):
                invoke_with_retry(mock_llm, "prompt", max_retries=2, base_delay=0)
            
        # max_retries=2 means 3 total attempts (1 initial + 2 retries)
        assert mock_llm.invoke.call_count == 3
        
    def test_zero_retries_raises_immediately(self):
        # max_retries=0 means only one attempt, no retry.
        from unittest.mock import MagicMock, patch
        from llm_provider import invoke_with_retry
        
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ValueError("bad input")
        
        with patch("llm_provider.time.sleep"):
            with pytest.raises(ValueError):
                invoke_with_retry(mock_llm, "prompt", max_retries=0)
            
        assert mock_llm.invoke.call_count == 1
        
        
# get_llm() provider factory

class TestGetLlm:
    
    def test_unknown_provider_raises(self):
        # Any provider other than ollama/openrouter must raise ValueError.
        from llm_provider import get_llm
        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            get_llm(provider="nonexistent", model_name="some-model")
            
    def test_old_providers_now_rejected(self):
        # gemini/groq/openai are no longer valid — openrouter replaces them.
        from llm_provider import get_llm
        for old_provider in ("gemini", "groq", "openai"):
            with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
                get_llm(provider=old_provider, model_name="some-model", api_key="key")
                
                
    def test_openrouter_without_api_key_raises(self):
        # openrouter with no API key must raise ValueError immediately.
        from llm_provider import get_llm
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            get_llm(provider="openrouter", model_name="google/gemini-2.0-flash-exp:free", api_key=None)
                
                

# _extract_source_filter()

class TestExtractSourceFilter:
    """
    Uses a mock vectordb so no real Chroma instance needed.
    """
    def _make_mock_vectordb(self, sources: list):
        # Build a mock vectordb.get() that returns given source filenames.
        from unittest.mock import MagicMock
        mock_vdb = MagicMock()
        mock_vdb.get.return_value = {
            "metadatas": [{"source": source, "user_id": "1"} for source in sources],
            "documents": ["chunk"] * len(sources),
            "ids": [str(i) for i in range(len(sources))]
        }
        return mock_vdb
    
    def test_detects_full_filename_in_question(self):
        # 'tell me about my resume' should match 'resume.pdf'
        from services import _extract_source_filter
        vdb = self._make_mock_vectordb(["resume.pdf", "notes.pdf"])
        result = _extract_source_filter("tell me about the resume.pdf document", vdb, 1)
        assert result == "resume.pdf"
        
    def test_detects_stem_without_extension(self):
        # 'tell me about my resume' should match 'resume.pdf'
        from services import _extract_source_filter
        vdb = self._make_mock_vectordb(["resume.pdf", "notes.pdf"])
        result = _extract_source_filter("tell me about my resume", vdb, 1)
        assert result == "resume.pdf"
        
    def test_no_match_returns_none(self):
        # Query with no filename mention returns None — no filter applied.
        from services import _extract_source_filter
        vdb = self._make_mock_vectordb(["resume.pdf", "notes.pdf"])
        result = _extract_source_filter("what is backpropagation?", vdb, 1)
        assert result is None
        
    def test_case_insensitive_match(self):
        from services import _extract_source_filter
        vdb = self._make_mock_vectordb(["Resume.pdf"])
        result = _extract_source_filter("summarize the resume", vdb, 1)
        assert result == "Resume.pdf"
        
    def test_empty_sources_returns_none(self):
        # User with no uploaded documents — returns None gracefully.
        from services import _extract_source_filter
        vdb = self._make_mock_vectordb([])
        result = _extract_source_filter("tell me about resume.pdf", vdb, 1)
        assert result is None
        
    def test_vectordb_exception_returns_none(self):
        # If vectordb.get() fails, return None instead of crashing.
        from unittest.mock import MagicMock
        from services import _extract_source_filter
        mock_vdb = MagicMock()
        mock_vdb.get.side_effect = Exception("Chroma unavailable")
        result = _extract_source_filter("tell me about the resume.pdf", mock_vdb, 1)
        assert result is None
        
    def test_multiple_docs_selected_correct_one(self):
        # With 3 docs uploaded, the right one is extracted.
        from services import _extract_source_filter
        vdb = self._make_mock_vectordb([
            "resume.pdf", 
            "data_structures.pdf", 
            "attention_is_all_you_need.pdf"
        ])
        result = _extract_source_filter("explain the attention is all you need paper", vdb, 1)
        assert result == "attention_is_all_you_need.pdf"
        
        
# Adaptive threshold + Dynamic K logic

class TestAdaptiveThreshold:
    """
    Tests for the adaptive MIN_RELEVANCE calculation.
    These are pure arithmetic tests — no Chroma, no LLM needed.
    The formula: threshold = mean + (max - mean) * 0.5, bounded [0.10, 0.40]
    """
    
    def _compute_threshold(self, scores: list):
        if not scores:
            return 0.10
        max_score  = max(scores)
        mean_score = sum(scores) / len(scores)
        threshold  = mean_score + (max_score - mean_score) * 0.5
        return max(0.10, min(0.40, threshold))
    
    def test_small_doc_floored_at_0_10(self):
        """
        1-page doc: all scores very low (0.02-0.08)
        mean=0.05, max=0.08 → raw threshold=0.065 → floored to 0.10.
        Without the floor, we'd discard the only vaguely relevant chunk.
        """
        scores = [0.02, 0.04, 0.06, 0.08]
        threshold = self._compute_threshold(scores)
        assert threshold == 0.10, f"Expected 0.10 (floor), got {threshold:.3f}"
        
    def test_large_doc_filters_noise(self):
        """
        128-page doc: scores spread 0.08–0.55.
        mean≈0.276, max=0.55 → threshold≈0.413 → capped at 0.40.
        Without adaptive threshold (fixed 0.10), all 5 chunks would pass.
        With adaptive, only truly relevant chunks (0.45, 0.55) pass.
        """
        scores = [0.08, 0.10, 0.12, 0.45, 0.55]
        threshold = self._compute_threshold(scores)
        assert 0.25 <= threshold <= 0.40, f"Large doc threshold should be 0.25-0.40, got {threshold:.3f}"
        # Verify noisy chunks (0.08, 0.10, 0.12) are filtered out
        passing = [s for s in scores if s >= threshold]
        assert all(s >= 0.25 for s in passing), (
            f"Noisy chunks should be filtered: {[s for s in scores if s < 0.25]}"
        )
        
    def test_medium_doc_balanced(self):
        """
        10-page doc: scores 0.20–0.50.
        mean=0.34, max=0.50 → threshold=0.42 → capped at 0.40.
        Keeps top chunks, filters lower-scoring ones.
        """
        scores = [0.20, 0.28, 0.35, 0.42, 0.50]
        threshold = self._compute_threshold(scores)
        assert 0.30 <= threshold <= 0.40, f"Medium doc threshold should be 0.30-0.40, got {threshold:.3f}"
        
    def test_ceiling_at_0_40(self):
        # Very high scoring collection shouldn't over-filter.
        # Scores 0.70–0.95 → raw threshold ≈ 0.825 → capped at 0.40.
        scores = [0.71, 0.80, 0.90, 0.95]
        threshold = self._compute_threshold(scores)
        assert threshold == 0.40, f"Expected 0.40 (ceiling), got {threshold:.3f}"
        
    def test_empty_scores_returns_floor(self):
        # Edge case: no scores -> default to floor 0.10
        threshold = self._compute_threshold([])
        assert threshold == 0.10
        
    def test_single_score_above_floor(self):
        # Simple chunk returned — that score's midpoint with itself = itself
        scores = [0.30]
        threshold = self._compute_threshold(scores)
        # mean = max = 0.30 -> threshold = 0.30
        assert threshold == 0.30
        
class TestDynamicK:
    """
    Tests for dynamic_k and the tiny-doc shortcut.

    TINY_DOC_THRESHOLD = 15:
        Collections with ≤ 15 chunks bypass similarity search entirely
        and fetch all chunks directly. Dynamic K only applies to
        collections > 15 chunks.

    Dynamic K formula: min(10, max(3, total_chunks // 30))
    """
    
    TINY_DOC_THRESHOLD = 15
    
    def _compute_k(self, total_chunks, retrieval_k=5):
        if total_chunks <= 0:
            return retrieval_k
        return min(10, max(3, total_chunks // 30))
    
    def _is_tiny(self, total_chunks):
        return 0 < total_chunks <= self.TINY_DOC_THRESHOLD
    
    # Tiny doc shortcut tests
    def test_tiny_doc_uses_shortcut(self):
        """
        1-page doc (3–5 chunks) must use the tiny-doc shortcut.
        WHY: all-MiniLM-L6-v2 produces all-negative scores on sparse
        5-chunk collections. After clamping, max=0 → adaptive threshold=0.10
        → nothing passes. The shortcut bypasses this by fetching all chunks
        directly and letting the LLM determine relevance.
        """
        for chunks in [3, 5, 10, 15]:
            assert self._is_tiny(chunks), f"{chunks} chunks should trigger tiny-doc shortcut"
            
    def test_boundary_16_uses_similarity_search(self):
        # Exactly 16 chunks — just above threshold, uses similarity search
        assert not self._is_tiny(16), "16 chunks should NOT trigger tiny-doc shortcut"
        
    def test_zero_chunks_not_tiny(self):
        assert not self._is_tiny(0)
        
    # Dynamic K tests (only relevant for total_chunks > 15)
    def test_small_collection_gets_floor(self):
        assert self._compute_k(16) == 3
        assert self._compute_k(26) == 3
        assert self._compute_k(89) == 3     # 89//30=2, floored to 3
        assert self._compute_k(89) == max(3, 89 // 30) 
        
    def test_medium_doc(self):
        assert self._compute_k(150) == 5
    
    def test_large_doc(self):
        assert self._compute_k(223) == 7
        
    def test_very_large_doc_capped(self):
        #  500+ chunks -> k= (cap, never exceeded)
        assert self._compute_k(500) == 10
        assert self._compute_k(1000) == 10
        
    def test_zero_chunks_fall_back_to_config(self):
        # Empty collection falls back to RETRIEVAL_K from config
        assert self._compute_k(0, retrieval_k=5) == 5
        
    def test_k_scales_monotonically(self):
        # K must never decreases as chunk count increases
        prev_k = 0
        for chunks in [30, 60, 90, 120, 150, 180, 210, 240, 270, 300]:
            k = self._compute_k(chunks)
            assert k >= prev_k, f"k decreased at {chunks} chunks: {k} < {prev_k}"
            prev_k = k
            
            
# invoke_with_fallback()
    
class TestInvokeWithFallback:
    """
    Tests for the OpenRouter fallback chain in llm_provider.py.
    All LLM clients are mocked — no real API calls.
    """

    def _make_llm(self, response_content=None, raises=None):
        """Build a mock LLM client that either returns or raises."""
        from unittest.mock import MagicMock
        mock = MagicMock()
        if raises:
            mock.invoke.side_effect = raises
        else:
            mock.invoke.return_value.content = response_content or "answer"
        return mock

    def test_primary_succeeds_no_fallback_needed(self, monkeypatch):
        """Happy path — primary model responds, no fallback triggered."""
        from unittest.mock import patch
        from llm_provider import invoke_with_fallback

        call_log = []

        def mock_get_llm(provider, model_name, api_key, timeout):
            call_log.append(model_name)
            return self._make_llm(response_content="primary answer")

        with patch("llm_provider.get_llm", side_effect=mock_get_llm):
            response, model_used = invoke_with_fallback(
                provider="openrouter",
                api_key="test-key",
                prompt="test prompt",
                primary_model="google/gemma-4-31b-it:free",
            )

        assert response.content == "primary answer"
        assert model_used == "google/gemma-4-31b-it:free"
        assert call_log[0] == "google/gemma-4-31b-it:free"
        assert len(call_log) == 1   # only primary was called

    def test_primary_rate_limited_falls_to_backup(self, monkeypatch):
        """
        When primary hits rate limit (429), backup model is tried.
        Rate limits should NOT be retried on the same model.
        """
        from unittest.mock import patch
        from llm_provider import invoke_with_fallback

        call_log = []

        def mock_get_llm(provider, model_name, api_key, timeout):
            call_log.append(model_name)
            if model_name == "google/gemma-4-31b-it:free":
                return self._make_llm(raises=Exception("429 rate limit exceeded"))
            else:
                return self._make_llm(response_content="backup answer")

        with patch("llm_provider.get_llm", side_effect=mock_get_llm), \
             patch("llm_provider.time.sleep"):
            response, model_used = invoke_with_fallback(
                provider="openrouter",
                api_key="test-key",
                prompt="test prompt",
                primary_model="google/gemma-4-31b-it:free",
            )

        assert response.content == "backup answer"
        assert model_used == "openai/gpt-oss-120b:free"
        assert "google/gemma-4-31b-it:free" in call_log
        assert "openai/gpt-oss-120b:free" in call_log

    def test_primary_and_backup_fail_fallback_used(self, monkeypatch):
        """When primary and backup both fail, third model (fallback) is used."""
        from unittest.mock import patch
        from llm_provider import invoke_with_fallback

        call_log = []
        failing   = {"google/gemma-4-31b-it:free", "openai/gpt-oss-120b:free"}

        def mock_get_llm(provider, model_name, api_key, timeout):
            call_log.append(model_name)
            if model_name in failing:
                return self._make_llm(raises=Exception("429 rate limit"))
            else:
                return self._make_llm(response_content="fallback answer")

        with patch("llm_provider.get_llm", side_effect=mock_get_llm), \
             patch("llm_provider.time.sleep"):
            response, model_used = invoke_with_fallback(
                provider="openrouter",
                api_key="test-key",
                prompt="test prompt",
                primary_model="google/gemma-4-31b-it:free",
            )

        assert response.content == "fallback answer"
        assert model_used == "openai/gpt-oss-20b:free"

    def test_all_models_fail_raises_exception(self, monkeypatch):
        """If every model in the chain fails, raise the last exception."""
        from unittest.mock import patch
        from llm_provider import invoke_with_fallback
        import pytest

        def mock_get_llm(provider, model_name, api_key, timeout):
            return self._make_llm(raises=Exception("all down"))

        with patch("llm_provider.get_llm", side_effect=mock_get_llm), \
             patch("llm_provider.time.sleep"):
            with pytest.raises(Exception, match="all down"):
                invoke_with_fallback(
                    provider="openrouter",
                    api_key="test-key",
                    prompt="test prompt",
                    primary_model="google/gemma-4-31b-it:free",
                )

    def test_custom_primary_not_in_chain_tried_first(self, monkeypatch):
        """
        If LLM_MODEL is a custom model not in the default chain,
        it should still be tried first, then the default chain as fallback.
        """
        from unittest.mock import patch
        from llm_provider import invoke_with_fallback

        call_log = []

        def mock_get_llm(provider, model_name, api_key, timeout):
            call_log.append(model_name)
            if model_name == "custom/my-model:free":
                return self._make_llm(raises=Exception("custom model down"))
            return self._make_llm(response_content="chain answer")

        with patch("llm_provider.get_llm", side_effect=mock_get_llm), \
             patch("llm_provider.time.sleep"):
            response, model_used = invoke_with_fallback(
                provider="openrouter",
                api_key="test-key",
                prompt="test",
                primary_model="custom/my-model:free",
            )

        assert call_log[0] == "custom/my-model:free"   # custom tried first
        assert model_used != "custom/my-model:free"    # fell back to chain

    def test_ollama_not_allowed(self):
        """invoke_with_fallback is openrouter-only — raises on other providers."""
        from llm_provider import invoke_with_fallback
        import pytest

        with pytest.raises(ValueError, match="openrouter"):
            invoke_with_fallback(
                provider="ollama",
                api_key=None,
                prompt="test",
                primary_model="qwen2.5:3b",
            )

    def test_fallback_chain_order(self):
        """Verify the default chain order matches documentation."""
        from llm_provider import OPENROUTER_FALLBACK_CHAIN

        ids = [m for m, _ in OPENROUTER_FALLBACK_CHAIN]
        assert ids[0] == "google/gemma-4-31b-it:free",   "Primary should be Gemma 4 31B"
        assert ids[1] == "openai/gpt-oss-120b:free",     "Backup should be GPT-OSS 120B"
        assert ids[2] == "openai/gpt-oss-20b:free",      "Fallback should be GPT-OSS 20B"
        assert ids[3] == "openrouter/free",               "Emergency should be openrouter/free"
        assert len(ids) == 4,                             "Chain should have exactly 4 models"