"""
llm_provider.py
Unified interface for LLM calls (OpenAI, LangChain, Gemini, Ollama, etc.)
Add your own backend by subclassing LLMProvider.
"""

import os
from abc import ABC, abstractmethod
from typing import Optional
from dotenv import load_dotenv

# ------------------------------
# Base Interface
# ------------------------------
load_dotenv()
class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""
    @abstractmethod
    # CHANGE 1: Base class updated
    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 1000) -> str:
        """Generate text from prompt."""
        pass


# ------------------------------
# OpenAI / LangChain Provider
# ------------------------------

class OpenAIProvider(LLMProvider):
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set in environment")

    # CHANGE 2: OpenAI Subclass updated to 1000
    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 1000) -> str:
        try:
            import openai
            openai.api_key = self.api_key
            resp = openai.ChatCompletion.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(f"OpenAI generation failed: {e}")


# ------------------------------
# Gemini Provider (Google)
# ------------------------------

class GeminiProvider(LLMProvider):
    def __init__(self, model_name: str = "models/gemini-2.5-flash"):
        self.model_name = model_name
        self.api_key = os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY not set in environment")

    # CHANGE 3: Gemini Subclass updated to 1000
    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 1000) -> str:
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            resp = model.generate_content(prompt)

            if not resp.candidates:
                raise RuntimeError("Gemini returned no candidates. Possibly safety-blocked.")

            cand = resp.candidates[0]

            if cand.finish_reason == 2:
                raise RuntimeError("Gemini blocked the output due to safety filters.")

            parts = cand.content.parts if cand.content else []

            if not parts:
                raise RuntimeError("Gemini returned an empty response.")

            out = "".join([p.text for p in parts if hasattr(p, "text")])

            if not out.strip():
                raise RuntimeError("Gemini returned no usable text output.")

            return out.strip()

        except Exception as e:
            raise RuntimeError(f"Gemini generation failed: {e}")


# ------------------------------
# Ollama Provider (local open-source)
# ------------------------------

class OllamaProvider(LLMProvider):
    def __init__(self, model_name: str = "llama3"):
        self.model_name = model_name

    # CHANGE 4: Ollama Subclass updated to 1000
    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 1000) -> str:
        try:
            import subprocess, json
            cmd = ["ollama", "run", self.model_name, prompt]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr)
            return result.stdout.strip()
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {e}")


# ------------------------------
# Provider Factory
# ------------------------------

def get_llm_provider(name: str) -> LLMProvider:
    """Factory to get an LLM provider by name."""
    name = name.lower()
    if name in ["openai", "langchain"]:
        return OpenAIProvider()
    elif name in ["gemini", "google"]:
        return GeminiProvider()
    elif name in ["ollama", "local"]:
        return OllamaProvider()
    else:
        raise ValueError(f"Unknown LLM provider '{name}'. Supported: openai, gemini, ollama.")