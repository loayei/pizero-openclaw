import os
from dotenv import load_dotenv

load_dotenv()


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_TRANSCRIBE_MODEL = os.environ.get(
    "OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"
)
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "alloy")
OPENAI_TTS_SPEED = float(os.environ.get("OPENAI_TTS_SPEED", "2.0"))  # 0.25–4.0, faster = keep up with text
OPENAI_TTS_GAIN_DB = float(os.environ.get("OPENAI_TTS_GAIN_DB", "9"))  # extra dB boost (e.g. 9 ≈ 2.8× louder)

OPENCLAW_BASE_URL = os.environ.get("OPENCLAW_BASE_URL", "http://localhost:18789")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "")

AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "plughw:1,0")
AUDIO_OUTPUT_DEVICE = os.environ.get("AUDIO_OUTPUT_DEVICE", "default")
AUDIO_OUTPUT_CARD = int(os.environ.get("AUDIO_OUTPUT_CARD", "0"))  # ALSA card for amixer
AUDIO_SAMPLE_RATE = int(os.environ.get("AUDIO_SAMPLE_RATE", "16000"))

DRY_RUN = not OPENAI_API_KEY

LCD_BACKLIGHT = int(os.environ.get("LCD_BACKLIGHT", "70"))
UI_MAX_FPS = int(os.environ.get("UI_MAX_FPS", "4"))

# Speak the assistant response via OpenAI TTS (like whisplay-ai-chatbot)
ENABLE_TTS = os.environ.get("ENABLE_TTS", "false").lower() in ("true", "1", "yes")

# Number of past exchanges (user+assistant pairs) to keep for conversation context
CONVERSATION_HISTORY_LENGTH = int(os.environ.get("CONVERSATION_HISTORY_LENGTH", "5"))

# RMS energy threshold below which audio is considered silence (16-bit range: 0–32768)
SILENCE_RMS_THRESHOLD = float(os.environ.get("SILENCE_RMS_THRESHOLD", "200"))


def print_config():
    """Print non-secret config for debugging."""
    print(f"OPENAI_TRANSCRIBE_MODEL = {OPENAI_TRANSCRIBE_MODEL}")
    print(f"OPENAI_TTS_MODEL        = {OPENAI_TTS_MODEL}")
    print(f"OPENAI_TTS_SPEED        = {OPENAI_TTS_SPEED}")
    print(f"OPENAI_TTS_GAIN_DB      = {OPENAI_TTS_GAIN_DB}")
    print(f"OPENCLAW_BASE_URL       = {OPENCLAW_BASE_URL}")
    print(f"AUDIO_DEVICE            = {AUDIO_DEVICE}")
    print(f"AUDIO_OUTPUT_DEVICE     = {AUDIO_OUTPUT_DEVICE}")
    print(f"AUDIO_SAMPLE_RATE       = {AUDIO_SAMPLE_RATE}")
    print(f"DRY_RUN                 = {DRY_RUN}")
    print(f"LCD_BACKLIGHT           = {LCD_BACKLIGHT}")
    print(f"OPENAI_API_KEY set      = {bool(OPENAI_API_KEY)}")
    print(f"OPENCLAW_TOKEN set      = {bool(OPENCLAW_TOKEN)}")
    print(f"ENABLE_TTS              = {ENABLE_TTS}")
    print(f"CONVERSATION_HISTORY    = {CONVERSATION_HISTORY_LENGTH}")
    print(f"SILENCE_RMS_THRESHOLD   = {SILENCE_RMS_THRESHOLD}")
