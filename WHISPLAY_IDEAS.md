# Ideas from PiSugar whisplay-ai-chatbot

This project is inspired by [whisplay-ai-chatbot](https://github.com/PiSugar/whisplay-ai-chatbot). Below is what we’ve adopted and what could be added.

## Implemented

- **TTS playback** – Optional spoken responses via OpenAI TTS (like whisplay). Set `ENABLE_TTS=true` in `.env` so the device speaks the assistant response after it’s streamed. Uses existing `tts_openai.py` (OpenAI TTS + aplay). Cancel with the button during playback.
- **Battery display** – Already present: PiSugar socket + sysfs fallback in `display.py` (top-right corner).

## Possible next steps

- **Conversation reset on idle** – Whisplay resets conversation history after 5 minutes with no speech. If OpenClaw gains a session/thread API and a “clear” or “new thread” endpoint, we could add `CONVERSATION_RESET_IDLE_SEC=300` and call it when idle that long so the next query starts fresh.
- **Wake word** – Whisplay supports optional wake word (e.g. “hey Amy”) via [openwakeword](https://github.com/dscripka/openwakeword) and `sox` for continuous mic. We could run a small subprocess that prints `WAKE` on detection; main would then start recording (and use sentence-based or timeout stop). Requires wiring a listener process and VAD/timeouts.
- **Image on screen** – If we add image generation or OpenClaw returns images, we could show them using the same PIL/display path we use for the response (e.g. full-screen image then back to text).
- **Volume control by assistant** – Whisplay lets the AI adjust volume. We could parse responses for volume intent or add a tool that calls `amixer` (lower priority).

## Reference

- Repo: https://github.com/PiSugar/whisplay-ai-chatbot  
- Wake word: `python/wakeword.py` (openwakeword + sox, env: `WAKE_WORD_ENABLED`, `WAKE_WORDS`, etc.)  
- Their Python UI: `python/chatbot-ui.py` (socket server + render thread; we use a single process and our own display flow).
