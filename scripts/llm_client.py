#!/usr/bin/env python3
"""Small pluggable LLM client used by generation and evaluation scripts."""

import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional


RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """Raised when a provider cannot return a usable response."""


class LLMProvider(ABC):
    """Provider contract for model-backed scripts."""

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Return model text for a message list."""


class _HttpProvider(LLMProvider):
    def __init__(self, api_base: str, api_key: str, timeout: int = 60, max_retries: int = 3):
        if not api_base:
            raise ValueError("api_base is required")
        if not api_key:
            raise ValueError("API key is required; pass --api-key or configure the provider env var")
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    def _post(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error = None
        for attempt in range(self.max_retries):
            try:
                request = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                last_error = ProviderError("HTTP {}: {}".format(exc.code, detail))
                if exc.code not in RETRYABLE_HTTP_CODES:
                    break
            except Exception as exc:  # pragma: no cover - network-specific failures
                last_error = ProviderError(str(exc))
            if attempt + 1 < self.max_retries:
                time.sleep(2 ** attempt)
        raise last_error or ProviderError("provider request failed")


class OpenAICompatibleProvider(_HttpProvider):
    def generate(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        body = self._post(
            self.api_base + "/chat/completions",
            payload,
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.api_key),
            },
        )
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("invalid OpenAI-compatible response: {}".format(exc))


class GeminiProvider(_HttpProvider):
    def generate(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        system_parts = [item["content"] for item in messages if item.get("role") == "system"]
        contents = []
        for item in messages:
            role = item.get("role")
            if role == "system":
                continue
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": item.get("content", "")}],
            })
        base = self.api_base
        if "/models/" in base:
            url = "{}:generateContent?key={}".format(base, self.api_key)
        else:
            url = "{}/models/{}:generateContent?key={}".format(base, model, self.api_key)
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if response_format and response_format.get("type") == "json_object":
            payload["generationConfig"]["responseMimeType"] = "application/json"
        body = self._post(url, payload, {"Content-Type": "application/json"})
        try:
            return body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("invalid Gemini response: {}".format(exc))


def detect_provider(api_base: str) -> str:
    if "generativelanguage.googleapis.com" in (api_base or ""):
        return "gemini"
    return "openai"


def _load_custom_provider(module_path: str, config: Dict[str, Any]) -> LLMProvider:
    path = Path(module_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("provider module not found: {}".format(path))
    spec = importlib.util.spec_from_file_location("data_augmentation_custom_provider", str(path))
    if spec is None or spec.loader is None:
        raise ValueError("unable to load provider module: {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_provider", None)
    if not callable(factory):
        raise ValueError("custom provider module must expose create_provider(config)")
    provider = factory(dict(config))
    if not hasattr(provider, "generate"):
        raise ValueError("custom provider must expose generate(...)")
    return provider


def create_provider(
    provider_name: str,
    api_base: str = "",
    api_key: str = "",
    api_key_env: str = "",
    provider_module: str = "",
    timeout: int = 60,
    max_retries: int = 3,
    extra_config: Optional[Dict[str, Any]] = None,
) -> LLMProvider:
    """Create a built-in or custom provider without persisting credentials."""
    name = provider_name or "auto"
    if name == "auto":
        name = detect_provider(api_base)
    if not api_base and name == "openai":
        api_base = "https://api.openai.com/v1"
    if not api_base and name == "gemini":
        api_base = "https://generativelanguage.googleapis.com/v1beta"
    key_env = api_key_env or ("GEMINI_API_KEY" if name == "gemini" else "OPENAI_API_KEY")
    resolved_key = api_key or os.environ.get(key_env, "")
    config = {
        "provider": name,
        "api_base": api_base,
        "api_key": resolved_key,
        "timeout": timeout,
        "max_retries": max_retries,
    }
    config.update(extra_config or {})
    if provider_module:
        return _load_custom_provider(provider_module, config)
    if name == "openai":
        return OpenAICompatibleProvider(api_base, resolved_key, timeout, max_retries)
    if name == "gemini":
        return GeminiProvider(api_base, resolved_key, timeout, max_retries)
    raise ValueError("unknown provider '{}'; use openai, gemini, auto, or --provider-module".format(name))


def public_model_config(provider_name: str, model: str, api_key_env: str = "") -> Dict[str, str]:
    """Return the only model metadata safe to persist in run artifacts."""
    result = {"provider": provider_name, "model": model}
    if api_key_env:
        result["api_key_env"] = api_key_env
    return result
