"""Fish Audio text-to-speech service."""

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CHAR_LIMIT = 5_000


class FishAudioService:
    """Text-to-speech generation via Fish Audio API.

    Fish Audio is a competitive TTS provider with ELO 1,128 (#11),
    80+ languages, and pricing at $15/1M chars (85% cheaper than ElevenLabs).
    """

    BASE_URL = "https://api.fish.audio/v1"

    def __init__(self) -> None:
        self.api_key = os.getenv("FISHAUDIO_API_KEY")

    def generate_voice(
        self, text: str, voice_id: str, output_path: str
    ) -> str:
        """Generate speech audio from text and write to a file.

        Uses the S2-Pro model (best quality) with reference_id for
        voice cloning. Set ``voice_id`` to a Fish Audio model ID (UUID).

        Returns:
            The output file path.
        """
        if not self.api_key:
            raise ValueError("FISHAUDIO_API_KEY not set")

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "FishAudio: TTS request — voice_id=%s text_len=%d",
            voice_id, len(text),
        )
        with httpx.Client(base_url=self.BASE_URL, timeout=120) as client:
            resp = client.post(
                "/tts",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "model": "s2-pro",
                },
                json={
                    "text": text,
                    "reference_id": voice_id,
                    "format": "mp3",
                    "latency": "normal",
                    "prosody": {
                        "speed": 1.0,
                        "volume": 0,
                    },
                },
            )
            resp.raise_for_status()
            path.write_bytes(resp.content)

        logger.info(
            "FishAudio: saved audio to %s (%d bytes)",
            output_path, len(resp.content),
        )
        return str(path)
