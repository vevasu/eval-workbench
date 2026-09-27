"""Story generation logic. Traced when run through the Eval Workbench SDK, a plain function otherwise."""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

try:
    from eval_workbench import span, trace
except ImportError:  # the app works without the SDK installed
    from contextlib import contextmanager

    class _Handle:
        def set(self, **attrs):
            pass

    @contextmanager
    def span(name, kind="other", **attrs):
        yield _Handle()

    def trace(fn=None, **kwargs):
        return fn if callable(fn) else (lambda f: f)

BASE = Path(__file__).parent
MAX_WORDS = 80
# US dollars per million input and output tokens, for the cost shown in Eval Workbench. Edit to match your pricing.
PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00), "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00)}


class StoryError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def load_env() -> None:
    env_file = BASE / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def limit_words(text: str, limit: int = MAX_WORDS) -> str:
    words = text.split()
    if len(words) <= limit:
        return text.strip()
    return " ".join(words[:limit]).rstrip(",;:") + "…"


@trace(name="prompt.build")
def build_messages(prompt: str, genre: str) -> list:
    genre_text = "" if genre == "any" else f" in the {genre} genre"
    return [
        {"role": "system", "content": f"You write very short stories. Never exceed {MAX_WORDS} words. Give a beginning, a turn and an ending. Output only the story."},
        {"role": "user", "content": f"Write a story{genre_text} about: {prompt}"},
    ]


@trace(name="llm.generate", kind="llm")
def call_openai(messages: list) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-your"):
        raise StoryError("OPENAI_API_KEY is not set. Add it to the .env file and restart.", 500)
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    body = {"model": model, "max_tokens": 140, "messages": messages}
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")  # any OpenAI-compatible API
    request = urllib.request.Request(
        f"{base_url}/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    with span("openai.chat.completions", kind="llm", model=model, max_tokens=140) as s:
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = "OpenAI rejected the request."
            try:
                detail = json.load(e).get("error", {}).get("message", detail)
            except Exception:
                pass
            raise StoryError(detail) from None
        except urllib.error.URLError:
            raise StoryError("Could not reach OpenAI. Check your connection.") from None
        usage = data.get("usage", {})
        prompt_tokens, completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        s.set(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
              finish_reason=data["choices"][0].get("finish_reason"))
        price = PRICES.get(model)
        if price and prompt_tokens is not None and completion_tokens is not None:
            s.set(cost_usd=round((prompt_tokens * price[0] + completion_tokens * price[1]) / 1e6, 8))
    return data["choices"][0]["message"]["content"]


@trace(name="response.postprocess")
def postprocess(text: str) -> str:
    story = limit_words(text)
    with span("word_limit", words_before=len(text.split()), words_after=len(story.split()), truncated=story != text.strip()):
        pass
    return story


def generate_story(prompt: str, genre: str = "any") -> str:
    return postprocess(call_openai(build_messages(prompt, genre)))
