"""
Tier 2 — Integration Tests: RAG Pipeline (Real Chroma, Mocked LLM)
==================================================================
These tests use a REAL Chroma instance (in a temp directory) and a REAL
fixture PDF, but mock the LLM call. This is the most important tier for
a RAG application — it catches retrieval bugs (wrong thresholds, bad
metadata, broken filters) that pure unit tests and route tests would miss.
 
What's tested:
    ingest_pdf()     — chunks created, metadata correct, duplicate guard works
    ask_question()   — broad queries (all 4 types), factual queries,
                       no-documents guard, citation building
"""

import os
import sys
import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


# ingest_pdf()

class TestIngestPdf:
    """
    Tests for ingest_pdf(). Uses a real fixture PDF and a real Chroma
    temp dir (from the chroma_dir fixture in conftest.py)
    """
    
    def test_ingest_returns_chunk_count(self, fixture_pdf, chroma_dir):
        # Ingesting a 3-page PDF should produce > 0 chunks.
        from services import ingest_pdf
        count = ingest_pdf(fixture_pdf, user_id=1, document_id=1)
        assert count > 0, "Expected at least 1 chunk from a 3-page PDF"
        
    def test_ingest_chunk_metadata_fields(self, fixture_pdf, chroma_dir):
        # Every chunk must carry source, user_id, document_id, chunk_index.
        from services.rag_service import ingest_pdf, _get_vectordb
        
        ingest_pdf(fixture_pdf, user_id=42, document_id=42)
        
        vectordb = _get_vectordb()
        result = vectordb.get(where={"user_id": "42"})
        
        assert result["ids"], "No chunks found for user_id=42"        
        
        for meta in result["metadatas"]:
            assert "source" in meta, "Missing 'source' in chunk metadata"
            assert "user_id" in meta, "Missing 'user_id' in chunk metadata"
            assert "document_id" in meta, "Missing 'document_id' in chunk metadata"
            assert "chunk_id" in meta, "Missing 'chunk_id' in chunk metadata"
            assert meta["user_id"] == "42"
            assert meta["source"] == os.path.basename(fixture_pdf)
            
    
    def test_ingest_under_isolation(self, fixture_pdf, chroma_dir):
        """
        Chunks for user A must not appear in queries filtered for user B.
        This is the most critical security property of the multi-user RAG.
        """
        from services.rag_service import ingest_pdf, _get_vectordb
        
        ingest_pdf(fixture_pdf, user_id=1, document_id=1)
        
        vectordb = _get_vectordb()
        user1_data = vectordb.get(where={"user_id": "1"})
        user2_data = vectordb.get(where={"user_id": "2"})
        
        assert len(user1_data["ids"]) > 0, "User 1 should have chunks"
        assert len(user2_data["ids"]) == 0, "User 2 should see no chunks from user 1's upload"
        
    def test_duplicate_ingest_skipped(self, fixture_pdf, chroma_dir):
        """
        Ingesting the same file twice for the same user must return 0
        on the second call and not double the chunk count
        """
        from services.rag_service import ingest_pdf, _get_vectordb
        
        first_count = ingest_pdf(fixture_pdf, user_id=1, document_id=1)
        second_count = ingest_pdf(fixture_pdf, user_id=1, document_id=1)
        
        assert first_count > 0, "First ingest should return chunk count > 0"
        assert second_count == 0, "Second ingest (duplicate) should return 0"
        
        # Verify chunk count didn't double
        vectordb = _get_vectordb()
        all_chunks = vectordb.get(where={"user_id": "1"})
        assert len(all_chunks["ids"]) == first_count, (
            "Chunk count doubles after duplicate ingest — duplicate guard failed"
        )
        
    def test_difference_users_same_file(self, fixture_pdf, chroma_dir):
        # Same filename uploaded by two differnt users — both should be ingested.
        from services.rag_service import ingest_pdf
        
        count_user1 = ingest_pdf(fixture_pdf, user_id=10, document_id=10)
        count_user2 = ingest_pdf(fixture_pdf, user_id=20, document_id=20)
        
        assert count_user1 > 0, "User 10 ingest shoul succeed"
        assert count_user2 > 0, "User 20 ingest should succeed (different user, same file)"
        
    def test_chunk_ids_are_unique(self, fixture_pdf, chroma_dir):
        # All chunk IDs in Chroma must be unique — no silent overwrites.
        from services.rag_service import ingest_pdf, _get_vectordb
        
        ingest_pdf(fixture_pdf, user_id=1, document_id=1)
        result = _get_vectordb().get(where={"user_id": "1"})
        
        ids = result["ids"]
        assert len(ids) == len(set(ids)), "Duplicate chunk IDs found — ingest ID schema broken"
        
        
# ask_question()

class TestAskQuestion:
    # TEsts for ask_question(). All tests use real chroma retrieval
    # but mock the llm call (mock_llm fixture from conftest.py)
    
    @pytest.fixture(autouse=True)
    def set_ingest(self, fixture_pdf, chroma_dir, mock_llm):
        """
        Ingest the fixture PDF before every test in this class.
        autouse=True means this runs automatically without explicitly
        listing it in eacj test's parameters.
        """
        from services.rag_service import ingest_pdf
        ingest_pdf(fixture_pdf, user_id=1, document_id=1)
        
    # Broad query types
    @pytest.mark.parametrize("question, expected_type", [
        ("Summarize the uploaded documents", "summarize"),
        ("Compare the main topics discussed in the documents", "compare"),
        ("Explain the important concepts in the uploaded documents", "concepts"),
        ("Generate interview questions based on the uploaded documents", "interview"),
    ])
    def test_broad_queries_return_answer_and_sources(self, question, expected_type):
        """
        All 4 suggested quetions from welcome.py must return an answer and 
        atleast one source citation. This is the core regression test for bug 
        where these queries returned 'No relevent info'.
        """
        from services.rag_service import ask_question
        result = ask_question(question, user_id=1)
            
        assert "answer" in result
        assert "sources" in result
        assert len(result["answer"]) > 0, f"Empty answer for: '{question}'"
        assert len(result["sources"]) > 0, f"No sources returned for: '{question}'"
            
    def test_summarize_does_not_use_similarity_search(self, monkeypatch):
        """
        Broad queries must bypass similarity search entirely.
        If similarity_search is called for a summarize query, the test fails — 
        that's the original bug (no chunk matches 'summarize my document')
        """
        from services.rag_service import ask_question, _get_vectordb
        from langchain_chroma import Chroma
            
        called = []
            
        original_get = _get_vectordb
            
        def mock_get_vectordb():
            vdb = original_get()
            original_similarity = vdb.similarity_search

            def track_similarity(*args, **kwargs):
                called.append("similarity_search")
                return original_similarity(*args, **kwargs)
                
            vdb.similarity_search = track_similarity
            return vdb
        
        monkeypatch.setattr("services.rag_service._get_vectordb", mock_get_vectordb)
            
        ask_question("Summarize the uploaded documents", user_id=1)
        assert "similarity_search" not in called, (
            "summarize query should NOT call similarity_search — use direct .get() instead"
        )
            
    # factual queries
    def test_factual_query_returns_result(self):
        # A specific question matching document content should return an answer.
        from services.rag_service import ask_question
        result = ask_question("What is backpropagation?", user_id=1)

        assert "answer" in result
        assert "sources" in result
            
        # mock_llm fixture returns a canned str — confirm the pipeline ran
        assert result["answer"] == "This is a mocked LLM answer for testing."
            
    def test_factual_query_builds_citations(self):
        """
        Citations must include the source filename and page number.
        This validates the citation-building logic, not LLM output.
        """
        from services.rag_service import ask_question
        result = ask_question("What are activation functions?", user_id=1)
            
        if result["sources"]:
            for citation in result["sources"]:
                assert "sample.pdf" in citation, f"Expected filename in citation: {citation}"
                assert "Page" in citation, f"Expected 'Page' in citation: {citation}"
                    
        
    # guard: no documents
        
    def test_no_documents_returns_error_message(self, chroma_dir):
        """
        ask_question() for a user with no documents must return a clear error
        message, not raise an exception or return empty strings.
        User ID 999 has never ingested anything.
        """
        from services.rag_service import ask_question
        result = ask_question("What is this document about?", user_id=999)
            
        assert "answer" in result
        assert "sources" in result
        assert len(result["sources"]) == 0
        # Should get the "no documents" message, not a crash
        assert any(phrase in result["answer"].lower() for phrase in [
            "no documents", "please upload", "no relevant"
        ]), f"Unexpected answer for user with no docs: '{result["'answer'"]}'"
            
            
    # LLM failure handling
        
    def test_llm_failure_returns_graceful_message(self, monkeypatch):
        """
        When the LLM call fails after all retries, ask_question() must 
        return a user-friendly error message, not raise an exception.
        a 500 error reaching the Streamlit frontend is a bad user experience.
        """
        from services.rag_service import ask_question
            
        def always_fail(llm, prompt, **kwargs):
            raise ConnectionError("LLM service unavailable")
            
        monkeypatch.setattr("services.rag_service.invoke_with_retry", always_fail)
            
        result = ask_question("What is backpropagation?", user_id=1)
            
        assert "answer" in result
        assert any(phrase in result["answer"].lower() for phrase in [
            "unavailable", "try again", "error",
        ]), f"Expected graceful error message, got: '{result['answer']}'"
            