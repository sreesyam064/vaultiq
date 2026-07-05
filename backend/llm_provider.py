"""
LLM Provider Factory + Fallback Chain
=======================================
WHY THIS EXISTS:
    rag_service.py used to hardcode `llm = ChatOllama(model=LLM_MODEL)` at
    import time. That works locally but Render's free/standard tiers can't
    run Ollama + a 3B model. For deployment we use OpenRouter — a single
    API gateway to all free-tier LLMs under one key and one OpenAI-compatible
    endpoint.

TWO ENVIRONMENTS:
    Development:  LLM_PROVIDER=ollama      LLM_MODEL=qwen2.5:3b
    Production:   LLM_PROVIDER=openrouter  LLM_MODEL=<primary model>

FALLBACK CHAIN (production only):
    Free models on OpenRouter have daily limits (200 req/day) and can
    go down or lose free status without notice. A fallback chain means:
    if the primary model fails → try backup → try fallback → try emergency.
    The user never sees "service unavailable" just because one model hit
    its daily limit.

    Primary:           google/gemma-4-31b-it:free
    Backup:            openai/gpt-oss-120b:free
    Fallback:          openai/gpt-oss-20b:free
    Emergency:         openrouter/free   (OpenRouter picks any available free model)

WHY THESE MODELS:
    Gemma 4 31B    — 256K context, strong instruction following, excellent
                     for structured RAG prompts (summarize/compare/concepts)
    GPT-OSS 120B   — highest-capacity free model, better on complex multi-doc
    GPT-OSS 20B    — fast MoE (3.6B active params), reliable when others rate-limited
    openrouter/free — OpenRouter auto-picks any available free model — never zero

invoke_with_retry:
    Each model attempt uses retry + exponential backoff for transient errors
    (network timeout, 503). Rate limit errors (429) trigger immediate fallback
    to the next model instead of retrying the same one.
"""
import logging
import time

logger = logging.getLogger(__name__)

# Production fallback chain
# Ordered by preference: best quality first, most reliable last.
# Each entry is (model_id, description) for logging clarity.
OPENROUTER_FALLBACK_CHAIN = [
    ("google/gemma-4-31b-it:free",  "Primary    — Gemma 4 31B (256K ctx, strong instruction following)"),
    ("openai/gpt-oss-120b:free",    "Backup     — GPT-OSS 120B (highest capacity free model)"),
    ("openai/gpt-oss-20b:free",     "Fallback   — GPT-OSS 20B (fast,MoE, reliable)"),
    ("openrouter/free",             "Emergency  — OpenRouter auto-picks any available free model"),
]


def get_llm(provider: str, model_name: str, api_key: str = None, timeout: int = 30):    # Factory Function
    """
    Build and return a langchain chat model client.

    Args:
        provider: "ollama" (local dev)| "openrouter" (production)
        model_name: model identifier for that provider
                    ollama:     "qwen2.5:3b"
                    openrouter: "google/gemma-4-31b-it:free" (or any free model ID)
        
        api_key : required for openrouter except ollama 
        timeout: request timeout in seconds, passed to client itself
                    
    Returns:
        a langchain chata model instance exposing '.invoke()'
        
    Raises:
        ValueError: unknown provider, or missing api_key when required.
    """
    
    provider = provider.lower().strip()
    logger.info(f"Initializing LLM provider='{provider}' model='{model_name}' timeout='{timeout}s'")
    
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model_name, timeout=timeout)
    
    elif provider == "openrouter":
        # Production — single gateway to all free-tier models
        # Uses OpenAI-compatible API format, so ChatOpenAI works directly
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=timeout,
            default_headers={
                # OpenRouter recommends these headers for usage tracking
                "HTTP-Referer": "https://github.com/sreesyam064/vaultiq",
                "X-title": "VaultIQ",
            },
        )
        
    else:
        raise ValueError(f"Unknown LLM_PROVIDER '{provider}'. Expected one of: ollama, openrouter")
    
    
def invoke_with_retry(llm, prompt: str, max_retries: int = 2, base_delay: float = 1.0):
    """
    Call llm.invoke(prompt) with retry + exponential backoff.

    Retries on transient errors (timeout, 503 service unavailable).
    Does NOT retry on rate limit errors (429) — those should trigger
    a model fallback instead (handled by invoke_with_fallback below).

    Args:
        llm:         LangChain chat client from get_llm()
        prompt:      prompt string to send
        max_retries: retries AFTER the first attempt (default 2 = 3 total)
        base_delay:  seconds before first retry; doubles each retry (1s → 2s → 4s)

    Returns:
        Response object with a .content attribute.

    Raises:
        Last exception if all attempts fail.    
    """
    
    last_exception = None
    
    for attempt in range(1, max_retries + 2): # +2: first attempt + retries
        try:
            logger.info(f"LLM invoke attempt {attempt}/{max_retries + 1}")
            response = llm.invoke(prompt)
            if attempt > 1:
                logger.info(f"LLM invoke succeeded on attempt {attempt}")
            return response
        
        except Exception as e:
            last_exception = e
            error_str = str(e).lower()
            
            # Rate limit (429) — no point retrying the same model, caller
            # should fall back to next model in chain
            if "429" in error_str or "rate limit" in error_str or "rate_limit" in error_str:
                logger.warning(f"Rate limit hit on attempt {attempt}: {e}")
                raise   # re-raise immediately so fallback chain trigger
            
            logger.warning(f"LLM invoke attempt {attempt} failed: {e}")
            
            is_last_attempt = attempt == max_retries + 1
            if not is_last_attempt:
                delay = base_delay * (2 ** (attempt - 1))
                logger.info(f"Retrying in {delay:.1f}s...")
                time.sleep(delay)
                
    logger.error(f"LLM invoke failed after {max_retries + 1} attempts: {last_exception}")
    raise last_exception


def invoke_with_fallback(provider:str, api_key:str, prompt:str, primary_model:str, timeout:int=30, max_retries:int=2):
    """
    Try primary model first, then work through the fallback chain if it fails.

    WHY THIS EXISTS:
        Free models on OpenRouter have daily limits (200 req/day per model)
        and can go offline or lose free status without notice. Without a
        fallback chain, hitting the daily limit means the entire app stops
        working until midnight UTC. With a fallback chain, the app degrades
        gracefully: primary fails → backup → fallback → emergency.

    Only used when LLM_PROVIDER=openrouter. Ollama (local dev) uses
    invoke_with_retry directly — no fallback needed for local inference.

    Args:
        provider:      "openrouter" (only provider that uses fallback chain)
        api_key:       OPENROUTER_API_KEY
        prompt:        the prompt string to send
        primary_model: the configured LLM_MODEL from config — used as first
                       attempt; if it's already in the fallback chain it takes
                       its natural position, otherwise it's tried first
        timeout:       per-model request timeout in seconds
        max_retries:   retries per model before moving to the next

    Returns:
        (response, model_used) tuple where model_used is the model ID string
        that actually produced the response. Caller logs which model was used.

    Raises:
        Exception if ALL models in the chain fail.
    """
    if provider != "openrouter":
        raise ValueError("invoke_with_fallback is only for LLM_PROVIDER=openrouter")
    
    # Build ordered list: primary first, then rest of chain deduped so we dont try same model twice
    chain_ids = [m for m, _ in OPENROUTER_FALLBACK_CHAIN]
    if primary_model not in chain_ids:
        # User configured a custom primary model not in default chain
        ordered = [(primary_model, "Primary (custom)")] + OPENROUTER_FALLBACK_CHAIN
    else:
        # Reorder so primary_model is first, rest follow in chain order
        idx = chain_ids.index(primary_model)
        ordered = (
            [OPENROUTER_FALLBACK_CHAIN[idx]]
            + OPENROUTER_FALLBACK_CHAIN[:idx]
            + OPENROUTER_FALLBACK_CHAIN[idx + 1:]
        )
    
    last_exception = None
    
    for model_id, description in ordered:
        logger.info(f"Trying model: {model_id} ({description})")
        try:
            llm = get_llm("openrouter", model_id, api_key, timeout)
            response = invoke_with_retry(llm, prompt, max_retries=max_retries)
            if model_id != primary_model:
                logger.warning(
                    f"Primary model '{primary_model}' failed — "
                    f"answered by fallback: '{model_id}'"
                )
            return response, model_id
        
        except Exception as e:
            logger.warning(f"Model '{model_id}' failed: {e}")
            last_exception = e 
            continue
        
    logger.error(f"All models in fallback chain failed. Last error: {last_exception}")
    raise last_exception
   