"""Settings, read from environment variables (and a .env file next to the project)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

# The provider is picked from whichever key you set. Anthropic wins if both are present.
PROVIDER = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "openai"
MODEL = os.environ.get(
    "ANTHROPIC_MODEL" if PROVIDER == "anthropic" else "OPENAI_MODEL",
    "claude-haiku-4-5-20251001" if PROVIDER == "anthropic" else "gpt-4o-mini",
)

# Critic and Writer go back and forth at most this many times, then the Editor takes over.
MAX_ROUNDS = int(os.environ.get("MAX_REVISION_ROUNDS", "2"))
# The average of the Critic's 1-5 scores that counts as "good enough to publish".
APPROVE_SCORE = float(os.environ.get("APPROVE_SCORE", "4.0"))
