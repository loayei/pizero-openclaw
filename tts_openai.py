"""OpenAI TTS playback: queue sentences, speak via OpenAI API and aplay."""

import queue
import subprocess
import threading

import requests

import config


_SENTINEL = object()


class TTSPlayer:
    """Background worker: consume sentence queue, call OpenAI TTS, pipe WAV to aplay."""

    def __init__(self):
        self._q: queue.Queue[str | object] = queue.Queue()
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, text: str) -> None:
        """Enqueue a sentence for TTS. Drops empty/whitespace-only."""
        t = (text or "").strip()
        if not t:
            return
        if config.DRY_RUN:
            return
        self._q.put(t)

    def flush(self) -> None:
        """Block until all queued sentences have been played."""
        self._q.put(_SENTINEL)
        self._done.wait(timeout=120)
        self._done.clear()

    def cancel(self) -> None:
        """Stop playback and clear queue."""
        self._cancel.set()
        # Drain queue so worker can exit
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self._q.put(_SENTINEL)

    def _run(self) -> None:
        while True:
            try:
                item = self._q.get()
            except Exception:
                break
            if item is _SENTINEL:
                self._cancel.clear()
                self._done.set()
                continue
            if self._cancel.is_set():
                self._cancel.clear()
                self._done.set()
                continue
            text = str(item).strip()
            if not text:
                continue
            self._speak(text)
        self._done.set()

    def _speak(self, text: str) -> None:
        url = "https://api.openai.com/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.OPENAI_TTS_MODEL,
            "voice": config.OPENAI_TTS_VOICE,
            "input": text,
            "response_format": "wav",
            "speed": max(0.25, min(4.0, config.OPENAI_TTS_SPEED)),
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=30)
        except Exception as e:
            print(f"[tts] request failed: {e}")
            return
        if resp.status_code != 200:
            print(f"[tts] API error {resp.status_code}: {resp.text[:200]}")
            return
        try:
            # Always set ALSA playback to 100% on all likely cards
            for card in ("0", "1"):
                for control in ("Master", "PCM", "Headphone", "Speaker"):
                    subprocess.run(
                        ["amixer", "-q", "-c", card, "set", control, "100%"],
                        capture_output=True,
                        check=False,
                    )

            wav_data = b"".join(resp.iter_content(chunk_size=4096))
            if self._cancel.is_set():
                return

            # Apply software gain with sox if available (makes TTS much louder)
            gain_db = config.OPENAI_TTS_GAIN_DB
            if gain_db > 0:
                try:
                    r = subprocess.run(
                        [
                            "sox",
                            "-t", "wav", "-",
                            "-t", "wav", "-",
                            "gain", str(gain_db),
                        ],
                        input=wav_data,
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                    if r.returncode == 0 and r.stdout:
                        wav_data = r.stdout
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass

            if self._cancel.is_set():
                return

            proc = subprocess.Popen(
                [
                    "aplay",
                    "-q",
                    "-D",
                    config.AUDIO_OUTPUT_DEVICE,
                    "-",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.stdin.write(wav_data)
            proc.stdin.close()
            proc.wait(timeout=60)
        except FileNotFoundError:
            print("[tts] aplay not found — install alsa-utils")
        except Exception as e:
            print(f"[tts] playback error: {e}")
