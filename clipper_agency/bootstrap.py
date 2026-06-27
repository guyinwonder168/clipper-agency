"""Central ``.env`` loader — every entry point loads env vars before any
service reads them via ``os.getenv``.

Why this exists
---------------
``load_dotenv()`` used to live ONLY in the CLI entry (``__main__.py``). The
Flask dashboard, retry, and resume paths never loaded ``.env``, so every
service that reads env directly — ElevenLabs, Gemini TTS, Fish Audio, Pexels,
OpenRouter, Firecrawl, ScrapeCreators, Brave, dashboard auth/secret — was
silently misconfigured under those entry points. The observed symptom: Voice
Producer skipped ElevenLabs (``ELEVENLABS_API_KEY`` invisible) and fell back to
Gemini TTS on every dashboard-driven job, so every captured job used fuzzy
proportional timestamps instead of ElevenLabs char-alignment.

This module is imported by every runtime entry point — CLI ``__main__``, Flask
``dashboard.app`` (import-time), and ``Orchestrator.__init__`` — so ``.env`` is
populated exactly once, as early as possible, regardless of how the pipeline is
started. ``load_dotenv`` is idempotent and never overrides real env vars
(``override=False``), so explicit shell exports always win.
"""

from __future__ import annotations

from dotenv import load_dotenv


def load_env() -> None:
    """Populate ``os.environ`` from the project ``.env`` file (idempotent).

    Safe to call from every entry point — already-set env vars are skipped, so
    explicit shell exports always take precedence over ``.env`` values.
    """
    load_dotenv()
