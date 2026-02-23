import os
import requests
import config


def transcribe(wav_path: str) -> str:
    """Transcribe a WAV file using OpenAI Audio Transcriptions API.

    In dry-run mode (no OPENAI_API_KEY), prompts for typed input instead.
    """
    if config.DRY_RUN:
        print("[transcribe] DRY RUN — type your message:")
        try:
            return input("> ").strip()
        except EOFError:
            return ""

    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    file_size = os.path.getsize(wav_path)
    if file_size < 100:
        raise ValueError(f"WAV file too small ({file_size} bytes), likely empty recording")

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}

    with open(wav_path, "rb") as f:
        resp = requests.post(
            url,
            headers=headers,
            files={"file": ("utterance.wav", f, "audio/wav")},
            data={
                "model": config.OPENAI_TRANSCRIBE_MODEL,
                "response_format": "text",
            },
            timeout=30,
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Transcription failed ({resp.status_code}): {resp.text[:300]}"
        )

    transcript = resp.text.strip()
    print(f"[transcribe] result: {transcript[:120]}")
    return transcript
