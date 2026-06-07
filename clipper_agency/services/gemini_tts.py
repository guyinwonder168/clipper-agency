"""Google AI Studio Gemini text-to-speech service."""

import base64
import logging
import os
import re
import time
import wave
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CHAR_LIMIT = 5_000


class GeminiTTSService:
    """Text-to-speech generation via the Gemini API."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    MODEL = "gemini-2.5-flash-preview-tts"
    DEFAULT_SAMPLE_RATE = 24000

    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.voice_name = os.getenv("GEMINI_TTS_VOICE_NAME") or "Kore"
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set")

    def generate_voice(self, text: str, voice_id: str, output_path: str) -> str:
        """Generate speech audio from text and write it as a WAV file."""
        voice_name = voice_id or self.voice_name
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        max_retries = 3
        base_delay = 2.0

        logger.info("GeminiTTS: request — voice=%s text_len=%d", voice_name, len(text))
        for attempt in range(max_retries + 1):
            with httpx.Client(base_url=self.BASE_URL, timeout=120) as client:
                resp = client.post(
                    f"/models/{self.MODEL}:generateContent",
                    headers={
                        "x-goog-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json=self._payload(text, voice_name),
                )
                if resp.status_code == 429 and attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "GeminiTTS: rate limited (429), retry %d/%d in %.1fs",
                        attempt + 1, max_retries, delay,
                    )
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                break

        audio_data = self._extract_audio(resp.json())
        sample_rate = self._sample_rate(audio_data.get("mimeType", ""))
        pcm = base64.b64decode(audio_data["data"])
        self._write_wav(path, pcm, sample_rate)
        logger.info("GeminiTTS: saved audio to %s (%d bytes PCM)", output_path, len(pcm))
        return str(path)

    def _payload(self, text: str, voice_name: str) -> dict:
        return {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice_name},
                    },
                },
            },
        }

    def _extract_audio(self, response: dict) -> dict:
        try:
            part = response["candidates"][0]["content"]["parts"][0]
            return part.get("inlineData") or part["inline_data"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Gemini TTS response did not include audio data") from exc

    def _sample_rate(self, mime_type: str) -> int:
        match = re.search(r"rate=(\d+)", mime_type)
        return int(match.group(1)) if match else self.DEFAULT_SAMPLE_RATE

    def _write_wav(self, path: Path, pcm: bytes, sample_rate: int) -> None:
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
