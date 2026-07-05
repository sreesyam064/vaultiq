"""
Tier 1 — Unit Tests: Config Validation
======================================
Tests for config.validate_config() — startup guard that fails fast when required
env vars are missing or LLM provider is misconfigured.

Two valid prroviders: "ollama" and "openrouter"
"""

import os
import sys
import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
    
class TestValidConfig:
        
    def test_valid_ollama_config_passes(self, monkeypatch):
        # Ollama needs no API key - justSECRET_KEY + JWT_SECRET_KEY
        import config
        monkeypatch.setattr(config, "SECRET_KEY", "s")
        monkeypatch.setattr(config, "JWT_SECRET_KEY", "j")
        monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
        monkeypatch.setattr(config, "OPENROUTER_API_KEY", None)
        monkeypatch.setattr(config, "_PROVIDER_API_KEYS", {"ollama": None, "openrouter": None})
        config.validate_config()    # must not raise or sys.exit()
            
    def test_valid_openrouter_config_passes(self, monkeypatch):
        # Openrouter with a key set must pass validation
        import config
        monkeypatch.setattr(config, "SECRET_KEY", "s")
        monkeypatch.setattr(config, "JWT_SECRET_KEY", "j")
        monkeypatch.setattr(config, "LLM_PROVIDER", "openrouter")
        monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-real-key")
        monkeypatch.setattr(config, "_PROVIDER_API_KEYS", {"ollama": None, "openrouter": "sk-or-real-key"})
        config.validate_config()    # must not raise 
        
    def test_missing_secret_key_exits(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "SECRET_KEY", None)
        monkeypatch.setattr(config, "JWT_SECRET_KEY", "j")
        monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
        monkeypatch.setattr(config, "OPENROUTER_API_KEY", None)
        monkeypatch.setattr(config, "_PROVIDER_API_KEYS", {"ollama": None, "openrouter": None})
        with pytest.raises(SystemExit):
            config.validate_config()
            
    def test_missing_jwt_secret_key_exits(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "SECRET_KEY", "s")
        monkeypatch.setattr(config, "JWT_SECRET_KEY", None)
        monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
        monkeypatch.setattr(config, "OPENROUTER_API_KEY", None)
        monkeypatch.setattr(config, "_PROVIDER_API_KEYS", {"ollama": None, "openrouter": None})
        with pytest.raises(SystemExit):
            config.validate_config()
            
    def test_invalid_provider_exits(self, monkeypatch):
        # Any provider name outside ollama/openrouter must exit
        import config
        monkeypatch.setattr(config, "SECRET_KEY", "s")
        monkeypatch.setattr(config, "JWT_SECRET_KEY", "j")
        monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")   # no longer valid
        monkeypatch.setattr(config, "OPENROUTER_API_KEY", None)
        monkeypatch.setattr(config, "_PROVIDER_API_KEYS", {"ollama": None, "openrouter": None})
        with pytest.raises(SystemExit):
            config.validate_config()
            
    def test_openrouter_without_api_key_exits(self, monkeypatch):
        # openrouter with no key set must exit with a clear message.
        import config
        monkeypatch.setattr(config, "SECRET_KEY", "s")
        monkeypatch.setattr(config, "JWT_SECRET_KEY", "j")
        monkeypatch.setattr(config, "LLM_PROVIDER", "openrouter")
        monkeypatch.setattr(config, "OPENROUTER_API_KEY", None)
        monkeypatch.setattr(config, "_PROVIDER_API_KEYS", {"ollama": None, "openrouter": None})
        with pytest.raises(SystemExit):
            config.validate_config()