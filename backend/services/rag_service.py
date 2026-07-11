"""
RAG Service
============
Phase 1: PDF loading, chunking, embedding, ChromaDB, retrieval, LLM 
Phase 2: Metadata per chunk, persistent DB, citations, sources
Phase 3: Per-user document isolation, chat history, auth integration
Phase 4: Duplicate ingestion guard, MMR(Maximal Marginal Relevance) retrieval,
         relevance-score filter, improved prompt
Phase 5: 4-type query router — summarize / compare / concepts / interview / 
         factual — each with tailored chunk count & prompt
Phase 6: LLM provider abstraction (Ollama dev / Openrouter prod),
         retry + timeout on LLM calls, structures logging
Phase 7: Eager model warm-up via wsgi.py + gunicorn preload_app — duplicate
         model loading across workers and slow first requests
"""

import os
import uuid
import logging

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from config import (
    CHROMA_DB_PATH,
    LLM_PROVIDER,
    LLM_MODEL,
    LLM_TIMEOUT_SECONDS,
    LLM_MAX_RETRIES,
    EMBEDDING_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    RETRIEVAL_K,
    get_llm_api_key
)

from llm_provider import get_llm, invoke_with_retry, invoke_with_fallback

logger = logging.getLogger(__name__)

"""
Lazy Singletons
WHY LAZY:
  Module-level `embedding_model = HuggingFaceEmbeddings(...)` and
  `llm = get_llm(...)` run at *import time*. That means:
    1. Any test that imports rag_service (even for pure logic like
       _detect_query_type) triggers a model download — breaking unit
       tests in CI where HuggingFace is not reachable.
    2. App startup fails immediately if the embedding model is
       unavailable, even for routes that never touch the RAG pipeline.
  Lazy init defers construction to the first actual RAG call, so:
    - Unit tests import rag_service freely with zero network calls.
    - Tests mock these functions before the first real call, so
      integration tests never hit the real model either (unless wanted).
    - In production, the model loads on the first request, not at boot, 
        UNLESS wsgi.py explicitly calls these functions at import time
        (which it does — see wsgi.py). Combined with gunicorn's preload_app=True,
        this means model loads exactly ONCE in master process before forking, and 
        workers share it via copy-on-write memory instead of each loading their own copy.
"""

_embedding_model = None
_llm = None

def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from langchain_huggingface import HuggingFaceEmbeddings
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _embedding_model = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _embedding_model


def _get_llm():
    global _llm
    if _llm is None:
        logger.info(f"Initializing LLM provider={LLM_PROVIDER} model={LLM_MODEL}")
        _llm = get_llm(
            provider=LLM_PROVIDER,
            model_name=LLM_MODEL,
            api_key=get_llm_api_key(),
            timeout=LLM_TIMEOUT_SECONDS,
        )
    return _llm

"""
Query-Type Router

Broad/document-wide queries (summarize, compare, concepts, interview) CANNOT use
similarity search — no chunk say "compare main topics" so the search return nothing useful.

Instead we detect intent and:
  1. Fetch the first N chunks directly from ChromaDB (no vector search).
  2. Use a task-specific prompt that tells the LLM exactly what to produce.

Only "factual" queries (specific questions) go through the normal
MMR + revelence-source retrieval pipeline.
"""

QUERY_TYPES = {
    "summarize": [
        "summarize", "summarise", "summary", "overview", 
        "what is this document", "what is this paper",
        "what does this document", "what does this paper",
        "tell me about this document", "tell me about this paper",
        "tell me about the", "tell me abouut my",
        "what is in this", "what is in my",
        "explain this document", "explain this paper",
        "explain my document", "what is the document",
        "describe this document", "describe my document",
        "give me a summary", "give me overview",
        "summarize the uploaded", "summarise the uploaded",
    ],
    "compare": [
        "compare", "comparison", "contrast", "difference between",
        "similarities between", "main topics", "compare the main", 
        "topics discussed", 
    ],
    "concepts": [
        "important concepts", "key concepts", "explain the important", 
        "explain concepts", "main concepts", "core concepts", 
        "explain important",
    ], 
    "interview": [
        "interview questions", "generate interview", "generate questions", 
        "quiz me", "test my knowledge", "based on the uploaded",
    ],
}

# How many chunks to fetch directly for each broad query type.
# More chunks = broader document coverage for document-wide tasks.
BROAD_CHUNK_COUNTS = {
    "summarize": 6, # intro / abstract / opening — enough for a summary
    "compare": 10,  # needs wide coverage to find multiple topics
    "concepts": 8,  # concept-dense sections spread across the doc
    "interview": 8, # broad coverage to form varied questions
}

# Task-specific prompt instructions injected per query type.
PROMPT_INSTRUCTIONS = {
    "summarize": (
        "Write a well-structured summary of the document. "
        "Include: (1) Main topic or purpose, (2) key arguments or findings, "
        "(3) Methodology if mentioned, (4) Conclusions or outcomes."
    ),
    "compare":(
        "Identify and compare the main topics discussed in the provided context. "
        "Group related ideas together. Highlight similarities and differences "
        "between concepts, sections, or arguments. Use clear headings."
    ),
    "concepts": (
        "List and explain all important concepts found in the provided context. "
        "For each concept provide: (1) Name, (2) Clear definition, "
        "(3) Why it is significant in this document."
    ),
    "interview":(
        "Generate 6 interview questions with detailed answers "
        "based strictly on the provided context. "
        "Cover different aspects of the document. "
        "Format each as:\nQ: <question>\nA: <detailed answer>"
    ),
    "factual": (
        "Answer the question directly and concisely using only the provided context. "
        "If the answer is partially present, share what is available and note what is missing. "
        "If the context is completely unrelated, say: "
        "'I could not find that information in the uploaded documents.'"
    ),
}

def _detect_query_type(question):
    """
    Returns one of: 'summarize' | 'compare' | 'concepts' | 'interview' | 'factual'
    
    Checks each keyword list in QUERY_TYPES in order.
    Falls back to 'factual' if no broad-query keyword is found.    
    """
    q = question.lower().strip()
    for query_type, keywords in QUERY_TYPES.items():
        if any(kw in q for kw in keywords):
            return query_type
    return "factual"


def _extract_source_filter(question, vectordb, user_id):
    """
    Check if the user's question explicitly names one of their uploaded files.
    If so, return that filename so retrieval can be restricted to that doc only.

    By detecting the filename in the question and filtering to that source,
    retrieval only searches the right document — even with a low relevance score.
    """
    q = question.lower()

    # Get all unique source filenames this user has uploaded
    try:
        all_chunks = vectordb.get(where={"user_id": str(user_id)})
        sources = set()
        for meta in all_chunks.get("metadatas", []):
            src = meta.get("source", "")
            if src:
                sources.add(src)
    except Exception:
        return None

    if not sources:
        return None

        # Check if any filename (or its stem without extension) appears in the question.
    # Three matching strategies, tried in order:
    #   1. Full filename:  "resume.pdf"              in question
    #   2. Stem as-is:     "resume"                  in question
    #   3. Stem humanized: "attention is all you need" in question
    #      (underscores/hyphens replaced with spaces, for multi-word filenames)
    for source in sources:
        source_lower = source.lower()
        stem = source_lower.rsplit(".", 1)[0]
        stem_humanized = stem.replace("_", " ").replace("-", " ")
        
        if source_lower in q or stem_humanized in q:
            return source
        
        import re
        pattern = rf"\b{re.escape(stem)}\b"
        if re.search(pattern, q):
            return source
    
    return None


# ChromaDB Helper
def _get_vectordb():
    """Returns a Chroma client pointed at the persistent store."""
    from langchain_chroma import Chroma as _Chroma
    return _Chroma(
        persist_directory=CHROMA_DB_PATH,
        embedding_function=_get_embedding_model()
    )
    
    
def ingest_pdf(pdf_path, user_id):
    """
    Load a PDF, split into chunks, embed and store in ChromaDB.
    Returns the no.of chunks added (0 if already ingested).
    
    Duplicate guard: checks ChromaDB before adding anything.
    The upload route also checks the SQL Document table — this is a
    second layer that keeps the vector store clean independently.
    """
    
    filename = os.path.basename(pdf_path)
    
    # Duplicate guard
    if os.path.exists(CHROMA_DB_PATH):
        vectordb = _get_vectordb()
        existing = vectordb.get(
            where={"$and": [{"user_id": str(user_id)}, {"source": filename}]},
            limit=1,
        )
        if existing and existing.get("ids"):
            logging.info(f"'{filename}' already ingested for user {user_id}. Skipping.")
            return 0
        
    # Load PDF
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()
    logger.info(f"Loaded '{filename}' — {len(documents)} pages.")
    
    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    
    # Attach metadata to every chunk
    document_id = str(uuid.uuid4())
    for i, chunk in enumerate(chunks):
        chunk.metadata["source"] = filename
        chunk.metadata["user_id"] = str(user_id)
        chunk.metadata["document_id"] = document_id
        chunk.metadata["chunk_id"] = i
        chunk.metadata["total_chunks"] = len(chunks)
        
    # Unique ID per chunk — prevents duplicates if ingest run twice
    ids = [f"{user_id}_{document_id}_{i}" for i in range(len(chunks))]
    
    # Store in ChromaDB
    if os.path.exists(CHROMA_DB_PATH):
        vectordb = _get_vectordb()
        vectordb.add_documents(documents=chunks, ids=ids)
    else:
        from langchain_chroma import Chroma as _Chroma
        _Chroma.from_documents(
            documents=chunks,
            embedding=_get_embedding_model(),
            persist_directory=CHROMA_DB_PATH,
            ids=ids,
        )
        
    logger.info(f"Added {len(chunks)} chunks to ChromaDB for '{filename}'.")
    return len(chunks)


def ask_question(question, user_id):
    """
    Route the question to the right retrieval strategy, build context,
    inject a task-specific prompt, call the LLM, and return the answer.
    
    Returns:
        {
            "answer": str,
            "sources": ["filename.pdf (Page N)", ...]
        }
    
    Query routing
    —————————————
    Broad queries (summarize, compare, concepts, interview):
        -> Fetch the first N chunks directly from ChromaDB (no vector search).
           These queries have no semantically matching chunk so similarity
           search is useless. Direct fetch gives the LLM broad document
           coverage it needs.
           
    Factual queries (everything else):
        -> MMR retrieval + revelance score filter.
           MMR diversifies results; the score filter drops off-topic chunks. 
    """
    
    logger.info(f"User {user_id} | Query: {question}")
    
    vectordb = _get_vectordb()
    user_filter = {"user_id": str(user_id)}
    
    # source-aware filter
    # If the user names a specific file in their question
    # (e.g. "tell me about the resume.pdf document"), extract that filename
    # and restrict retrieval to chunks from that file only.
    # This prevents cross-document score pollution when multiple docs are uploaded.
    source_filter = _extract_source_filter(question, vectordb, user_id)
    if source_filter:
        logger.info(f"Source filter detected: restricting to '{source_filter}'")
        user_filter = {"$and": [{"user_id": str(user_id)}, {"source": source_filter}]}
    
    # Detect intent
    query_type = _detect_query_type(question)
    logger.info(f"Detected query type: '{query_type}'")
     
    # Branch A: broad document-wide query
    if query_type in BROAD_CHUNK_COUNTS:
        
        chunk_limit = BROAD_CHUNK_COUNTS[query_type]
        logger.info(f"Broad query — fetching first {chunk_limit} chunks directly.")
        
        raw = vectordb.get(
            where=user_filter,
            limit=chunk_limit,
        )
        
        if not raw or not raw.get("documents"):
            return {
                "answer": "No documents found. Please upload a PDF first.",
                "sources": [],
            }
            
        docs = [
            Document(page_content=text, metadata=meta)
            for text, meta in zip(raw["documents"], raw["metadatas"])
        ]
        
    # Branch B: factual / specific query
    else:

        # Count chunks for this filter scope
        try:
            total_chunks = len(vectordb.get(where=user_filter)["ids"])
        except Exception:
            total_chunks = 0
            
        # Tiny-doc shortcut
        # WHY THIS EXISTS:
        #   When source_filter is active (user named a specific file) AND that file
        #   is tiny (<= 15 chunks — typically 1-3 pages), similarity search is unreliable.
        #   The embedding model produces near-zero or negative cosine similarities
        #   on sparse collections because there are too few reference vectors for the
        #   space to be meaningful. Every query against a 5-chunk doc returns scores
        #   like [-0.20, -0.15, -0.001] — all clamped to 0. The adaptive threshold then
        #   floors at 0.10, nothing passes,and user gets "I count not find information"
        #   even though content is there ands is what they asked about.
        
        #   Solution: for tiny collections, skip similarity search entirely and fetch
        #   ALL chunks directly — same approach as broad queries. The LLM can handle 5-15 
        #   chunks trivially and figure out relevance itself via prompt. This is far more
        #   reliable than a cosine similarity threshold on a 5-point embedding spave.
        TINY_DOC_THRESHOLD = 15
        
        if total_chunks > 0 and total_chunks <= TINY_DOC_THRESHOLD:
            logger.info(
                f"Tiny doc shortcut: {total_chunks} chunks ≤ {TINY_DOC_THRESHOLD}"
                f" — fetching all chunks directly (skipping similarity search)."
            )
            raw = vectordb.get(where=user_filter)
            if not raw or not raw.get("documents"):
                return {
                    "answer": "No relevant information found in your documents.",
                    "sources": [],
                }
            docs = [
                Document(page_content=text, metadata=meta)
                for text, meta in zip(raw["documents"], raw["metadatas"])
            ]
        else:
            
            # Dynamic K
            # Formula: total_chunks // 30, floored at 3, capped at 10.
            # Examples:
            #   16–89 chunks  (small/medium doc) → k = 3
            #   150 chunks    (40-page doc)       → k = 5
            #   223 chunks    (128-page book)     → k = 7
            #   500+ chunks   (very large)        → k = 10
            try:
                total_chunks = len(vectordb.get(where=user_filter)["ids"])
            except Exception:
                total_chunks = 0
        
            dynamic_k = min(10, max(3, total_chunks // 30)) if total_chunks > 0 else RETRIEVAL_K
            logger.info(f"Dynamic K={dynamic_k} (total_chunks={total_chunks})")
        
        
            # MMR retrieval — diverse, non-redundant chunks
            try:
                docs = vectordb.max_marginal_relevance_search(
                    question,
                    k=dynamic_k,
                    fetch_k=dynamic_k * 3,
                    filter=user_filter,
                )
            except Exception as e:
                # MMK can fail on very small collections — fallback gracefully
                logger.warning(f"MMR failed ({e}), falling back to similarity search.")
                docs = vectordb.similarity_search(
                    question,
                    k=dynamic_k,
                    filter=user_filter,
                )   
            
            if not docs:
                logger.info("No chunks retrieved.")
                return {
                    "answer": "No relevant information found in your documents.",
                    "sources": [],
                }
                
            # Relevance scoring + clamping
            # ChromaDB occasionally returns scores just outside [0, 1] dur to 
            # floating-point cosine distance normalization (relevance = 1 - distance/2).
            # Clamping silences the UserWarning without affecting filtering logic.
            raw_scored = vectordb.similarity_search_with_relevance_scores(
                question,
                k=dynamic_k,
                filter=user_filter,
            )    
            scored = [(doc, max(0.0, min(1.0, score))) for doc, score in raw_scored]
        
            # Log every score for debugging — debug level only so CI stays quiet
            for doc, score in scored:
                logger.debug(
                    f"Score {score:.3f} | {doc.metadata.get('source')} p{doc.metadata.get('page')} | "
                    f"{doc.page_content[:80]!r}"
                    # !r -> tells python to print value using its raw representation method(repr())
                ) 
        
            # Adaptive threshold
            # Midpoint between mean and max — adapts to each query's score
            # distribution instead of using a fixed global value.
            #   threshold = mean + (max - mean) * 0.5
            # Bounds: floor=0.10, ceil=0.40
            
            # Edge case: if max_score == 0 (all raw scores were negative,
            # all clamped to 0), the formula gives threshold=0.10 and
            # nothing passes. This only happens on tiny collections — which
            # are now handled by the tiny-doc shortcut above before we get
            # here. On collections > 15 chunks, genuine near-zero scores
            # mean the query is truly off-topic, so "no info found" is correct.
            scores_only = [s for _, s in scored]
            if scores_only:
                max_score = max(scores_only)
                mean_score = sum(scores_only) / len(scores_only)
                MIN_RELEVANCE = mean_score + (max_score - mean_score) * 0.5
                MIN_RELEVANCE = max(0.10, min(0.40, MIN_RELEVANCE))
            else:
                MIN_RELEVANCE = 0.10
                max_score = 0.0
                mean_score = 0.0
                       
            logger.info(f"Adaptive MIN_RELEVANCE={MIN_RELEVANCE:.3f}"
                        f"(mean={mean_score:.3f}, max={max_score:.3f})")
        
            docs = [doc for doc, score in scored if score >= MIN_RELEVANCE]
        
        if not docs:
            logger.info(f"All chunks below Adaptive MIN_RELEVANCE={MIN_RELEVANCE:.3f}.")
            return {
                "answer": "I could not find information related to your question in the uploaded documents.",
                "sources": [],
            } 
               
    # Build context
    context = "\n\n".join(doc.page_content for doc in docs)
    logger.info(f"Sending {len(docs)} chunks to LLM.")
    
    # Build citations
    sources = []
    for doc in docs:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")  # we can use '?' instead of 'unknown'
        citation = f"{source} (Page {page})"
        if citation not in sources:
            sources.append(citation)
            
    # Build prompt
    # Inject the task-specific instruction for this query type.
    instruction = PROMPT_INSTRUCTIONS[query_type]
    
    prompt = f"""You are a helpful assistant for ValtIQ, a Personal Knowledge Base application.
    A user has uploaded their  documents and is asking questions about them.
    
    Your task: {instruction}
    
    Important rules:
    - Use ONLY the context provided below. Do not use outside knowledge.
    - Do not make up facts or invent information.
    - If the context is insufficient, say what IS available and not the gap.
    
    Context:
    {context}
    
    Question: {question}
    
    Answer:"""    
        
    # Call LLM
    # OpenRouter: uses invoke_with_fallback — tries primary model, then backup, fallback
    # emergency if any fails (rate limit, downtime, etc.)
    # ollama: uses invoke_with_retry directly — no fallback neeed.
    try:
        logger.info(f"Calling LLM (provider={LLM_PROVIDER}, query_type={query_type})...")
        
        logger.info(f"Prompt length: {len(prompt)}")
        logger.info(f"Context length: {len(context)}")
        logger.info(f"Total length (prompt + context): {len(prompt)+len(context)}")
        
        if LLM_PROVIDER =="openrouter":
            from config import get_llm_api_key, LLM_TIMEOUT_SECONDS
            response, model_used = invoke_with_fallback(
                provider    = LLM_PROVIDER,
                api_key     = get_llm_api_key(),
                prompt      = prompt,
                primary_model= LLM_MODEL,
                timeout     = LLM_TIMEOUT_SECONDS,
                max_retries = LLM_MAX_RETRIES
            )
            logger.info(f"LLM call succeeded (model={model_used}).")
        else:
            response = invoke_with_retry(
                _get_llm(), prompt, max_retries=LLM_MAX_RETRIES
            )
            logger.info("LLM call succeeded.")
        
        return {"answer": response.content, "sources": sources}
        
    except Exception as e:
        logger.error(f"LLM call failed after retries: {e}")
        
        return {
            "answer": "VaultIQ's AI service is currently unavailable — "
            "all models are rate-limited or offline. "
            "Please try again in a few minutes."
            ,
            "sources": sources,
            }    
        
            