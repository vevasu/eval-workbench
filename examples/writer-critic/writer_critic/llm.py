"""The only file that talks to a model provider. Agents call LLM.complete(); nothing else knows about HTTP."""
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import config
from .tracing import span


class LLMError(Exception):
    pass


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLM:
    """Plain HTTPS calls to OpenAI or Anthropic. No SDK needed."""

    def __init__(self, provider: str = config.PROVIDER, model: str = config.MODEL) -> None:
        self.provider, self.model = provider, model

    def complete(self, system: str, user: str, *, temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> LLMResponse:
        if self.provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""), "anthropic-version": "2023-06-01"}
            body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                    "messages": [{"role": "user", "content": user}]}
        else:
            key = os.environ.get("OPENAI_API_KEY", "")
            if not key or key.startswith("sk-your"):
                raise LLMError("No API key found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env (see .env.example).")
            url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"  # any OpenAI-compatible API
            headers = {"Authorization": f"Bearer {key}"}
            body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if json_mode:
                body["response_format"] = {"type": "json_object"}

        request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", **headers})
        with span("llm.call", kind="llm", provider=self.provider, model=self.model, temperature=temperature) as s:
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as e:
                try:
                    detail = json.load(e).get("error", {})
                    detail = detail.get("message", detail) if isinstance(detail, dict) else detail
                except Exception:
                    detail = e.reason
                raise LLMError(f"{self.provider} returned an error ({e.code}): {detail}") from None
            except urllib.error.URLError as e:
                raise LLMError(f"Could not reach {self.provider}: {e.reason}") from None

            usage = data.get("usage", {})
            if self.provider == "anthropic":
                text = "".join(block.get("text", "") for block in data["content"])
                tokens = (usage.get("input_tokens", 0), usage.get("output_tokens", 0))
            else:
                text = data["choices"][0]["message"]["content"]
                tokens = (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
            s.set(input_tokens=tokens[0], output_tokens=tokens[1])
        return LLMResponse(text=text.strip(), input_tokens=tokens[0], output_tokens=tokens[1], model=self.model)
