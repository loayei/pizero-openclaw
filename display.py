import re
import socket
import sys
import os
import threading
import time
import textwrap
from datetime import datetime

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from PIL import Image, ImageDraw, ImageFont

import config
sys.path.append("/home/pi/Whisplay/Driver")
from WhisPlay import WhisPlayBoard  # pyright: ignore[reportMissingImports]

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_PATH_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_EMOJI_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoEmoji-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    os.path.expanduser("~/.fonts/NotoColorEmoji.ttf"),
    "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
]

STATUS_FONT_SIZE = 16
STATUS_SUB_FONT_SIZE = 12
RESPONSE_FONT_SIZE = 17
TITLE_FONT_SIZE = 14
BATTERY_FONT_SIZE = 10
CLOCK_FONT_SIZE = 28
ACCENT_BAR_HEIGHT = 3
POWER_SUPPLY_SYS = "/sys/class/power_supply"
PISUGAR_SOCKET = "/tmp/pisugar-server.sock"


def _load_emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    for path in _EMOJI_FONT_PATHS:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            # e.g. Noto Color Emoji: "invalid pixel size" (fixed-size font)
            continue
    return None


def _is_emoji(c: str) -> bool:
    if not c:
        return False
    cp = ord(c[0])
    return (
        0x2600 <= cp <= 0x26FF  # Misc Symbols
        or 0x2700 <= cp <= 0x27BF  # Dingbats
        or 0x2B50 <= cp <= 0x2B55
        or 0x1F300 <= cp <= 0x1F5FF  # Misc Symbols and Pictographs
        or 0x1F600 <= cp <= 0x1F64F  # Emoticons
        or 0x1F680 <= cp <= 0x1F6FF  # Transport and Map
        or 0x1F900 <= cp <= 0x1F9FF  # Supplemental Symbols
        or 0x1F000 <= cp <= 0x1F02F  # Mahjong etc
        or 0x1F0A0 <= cp <= 0x1F0FF  # Playing cards
        or 0xFE00 <= cp <= 0xFE0F   # Variation selectors
        or cp == 0x200D             # ZWJ
        or 0x1F3FB <= cp <= 0x1F3FF  # Skin tone modifiers
        or 0xE0020 <= cp <= 0xE007F
    )


def _is_emoji_modifier(c: str) -> bool:
    if not c:
        return False
    cp = ord(c[0])
    return cp == 0x200D or 0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF


def _segment_mixed(text: str):
    """Yield (segment, use_emoji_font). Batches consecutive non-emoji chars into one segment."""
    i = 0
    while i < len(text):
        c = text[i]
        if _is_emoji(c):
            start = i
            i += 1
            while i < len(text) and (_is_emoji_modifier(text[i]) or _is_emoji(text[i])):
                i += 1
            yield (text[start:i], True)
        else:
            start = i
            i += 1
            while i < len(text) and not _is_emoji(text[i]):
                i += 1
            yield (text[start:i], False)


_RE_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_RE_CODE = re.compile(r"`(.+?)`")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BULLET = re.compile(r"^[\-\*]\s+", re.MULTILINE)
_RE_NUMLIST = re.compile(r"^\d+[.)]\s+", re.MULTILINE)


def _clean_markdown(text: str) -> str:
    """Strip markdown formatting so LLM responses look clean on a small screen."""
    text = _RE_BOLD.sub(lambda m: m.group(1) or m.group(2), text)
    text = _RE_ITALIC.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _RE_CODE.sub(r"\1", text)
    text = _RE_HEADING.sub("", text)
    text = _RE_BULLET.sub("\u2022 ", text)
    text = _RE_NUMLIST.sub("\u2022 ", text)
    return text


def _wifi_connected() -> bool:
    """Check wlan0 interface state (cheap file read, no subprocess)."""
    try:
        with open("/sys/class/net/wlan0/operstate") as f:
            return f.read().strip() == "up"
    except OSError:
        return False


def _read_pisugar_battery() -> tuple[int | None, str | None]:
    """Read battery from PiSugar server (Unix socket). Returns (pct, status) or (None, None)."""
    if not os.path.exists(PISUGAR_SOCKET):
        return (None, None)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(PISUGAR_SOCKET)
        sock.sendall(b"get battery\n")
        data = sock.recv(64).decode("utf-8", errors="ignore").strip()
        sock.close()
        # Response: "95" or "battery: 95"
        m = re.search(r"(\d+)", data)
        if not m:
            return (None, None)
        pct = max(0, min(100, int(m.group(1))))
        status = None
        try:
            s2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s2.settimeout(0.5)
            s2.connect(PISUGAR_SOCKET)
            s2.sendall(b"get battery_charging\n")
            ch = s2.recv(64).decode("utf-8", errors="ignore").strip().lower()
            s2.close()
            if "true" in ch:
                status = "Charging"
            elif "false" in ch:
                status = "Discharging"
        except (OSError, socket.error):
            pass
        return (pct, status)
    except (OSError, socket.error, ValueError):
        return (None, None)


def _read_battery() -> tuple[int | None, str | None]:
    """Read battery capacity (0–100) and status. Tries PiSugar first, then sysfs. Returns (pct, status) or (None, None)."""
    result = _read_pisugar_battery()
    if result[0] is not None:
        return result
    if not os.path.isdir(POWER_SUPPLY_SYS):
        return (None, None)

    def is_battery_dir(base: str) -> bool:
        type_path = os.path.join(base, "type")
        if os.path.isfile(type_path):
            try:
                with open(type_path) as f:
                    return f.read().strip().upper() == "BATTERY"
            except OSError:
                pass
        return False

    for name in sorted(os.listdir(POWER_SUPPLY_SYS)):
        base = os.path.join(POWER_SUPPLY_SYS, name)
        if not os.path.isdir(base):
            continue
        # Accept BAT*, "battery", or any dir whose type file says Battery
        if not (name.upper().startswith("BAT") or name.lower() == "battery" or is_battery_dir(base)):
            continue
        cap_path = os.path.join(base, "capacity")
        status_path = os.path.join(base, "status")
        energy_now_path = os.path.join(base, "energy_now")
        energy_full_path = os.path.join(base, "energy_full")

        pct = None
        if os.path.isfile(cap_path):
            try:
                with open(cap_path) as f:
                    pct = int(f.read().strip())
            except (ValueError, OSError):
                pass
        if pct is None and os.path.isfile(energy_now_path) and os.path.isfile(energy_full_path):
            try:
                with open(energy_now_path) as f:
                    now = int(f.read().strip())
                with open(energy_full_path) as f:
                    full = int(f.read().strip())
                if full > 0:
                    pct = int(100 * now / full)
            except (ValueError, OSError):
                pass

        if pct is not None:
            pct = max(0, min(100, pct))
            status = None
            if os.path.isfile(status_path):
                try:
                    with open(status_path) as f:
                        status = f.read().strip()
                except OSError:
                    pass
            return (pct, status)
    return (None, None)


class Display:
    def __init__(self, backlight=70):
        self.board = WhisPlayBoard()
        self.board.set_backlight(backlight)

        self._width = self.board.LCD_WIDTH
        self._height = self.board.LCD_HEIGHT

        self._status_font = ImageFont.truetype(_FONT_PATH, STATUS_FONT_SIZE)
        self._status_sub_font = ImageFont.truetype(_FONT_PATH_REGULAR, STATUS_SUB_FONT_SIZE)
        self._response_font = ImageFont.truetype(_FONT_PATH_REGULAR, RESPONSE_FONT_SIZE)
        self._title_font = ImageFont.truetype(_FONT_PATH, TITLE_FONT_SIZE)
        try:
            self._battery_font = ImageFont.truetype(_FONT_PATH_REGULAR, BATTERY_FONT_SIZE)
        except OSError:
            self._battery_font = self._status_sub_font  # fallback so battery corner still draws
        self._clock_font = ImageFont.truetype(_FONT_PATH, CLOCK_FONT_SIZE)
        self._emoji_status = _load_emoji_font(STATUS_FONT_SIZE)
        self._emoji_response = _load_emoji_font(RESPONSE_FONT_SIZE)

        self._response_buf = ""
        self._last_draw_time = 0.0
        fps = max(1, getattr(config, "UI_MAX_FPS", 10))
        self._min_draw_interval = 1.0 / fps

        self._pad_x = 10
        self._pad_y = 8
        self._status_wrap = self._calc_wrap_width(self._status_font, self._pad_x)

        self._default_backlight = backlight
        self._sleeping = False
        self._draw_lock = threading.Lock()
        self._cached_paragraphs: list[str] = []
        self._cached_wrapped: list[list[str]] = []

        self.clear()

    def sleep(self):
        if self._sleeping:
            return
        self._sleeping = True
        self.clear()
        self.board.set_backlight(0)

    def wake(self):
        if not self._sleeping:
            return
        self._sleeping = False
        self.board.set_backlight(self._default_backlight)

    @property
    def is_sleeping(self) -> bool:
        return self._sleeping

    def _draw_mixed(
        self,
        draw: ImageDraw.ImageDraw,
        xy: tuple[int, int],
        text: str,
        text_font: ImageFont.FreeTypeFont,
        emoji_font: ImageFont.FreeTypeFont | None,
        fill: tuple[int, int, int],
    ) -> float:
        """Draw text with emoji fallback (by segment/cluster), returns total width drawn."""
        x, y = xy
        for segment, use_emoji in _segment_mixed(text):
            if use_emoji and emoji_font:
                font = emoji_font
                draw_seg = segment
            else:
                font = text_font
                # No emoji font or regular text: use "?" for emoji so we don’t get empty boxes
                draw_seg = "?" if use_emoji else segment
            try:
                draw.text((x, y), draw_seg, font=font, fill=fill)
                x += font.getlength(draw_seg)
            except Exception:
                try:
                    draw.text((x, y), "?", font=text_font, fill=fill)
                    x += text_font.getlength("?")
                except Exception:
                    x += text_font.getlength("?")
        return x - xy[0]

    def _text_width_mixed(
        self,
        text: str,
        text_font: ImageFont.FreeTypeFont,
        emoji_font: ImageFont.FreeTypeFont | None,
    ) -> float:
        w = 0.0
        for segment, use_emoji in _segment_mixed(text):
            if use_emoji and emoji_font:
                try:
                    w += emoji_font.getlength(segment)
                except Exception:
                    w += text_font.getlength("?")
            else:
                seg = "?" if use_emoji else segment
                w += text_font.getlength(seg)
        return w

    def _calc_wrap_width(self, font: ImageFont.FreeTypeFont, pad_x: int) -> int:
        avg_char_w = font.getlength("M")
        usable_w = self._width - pad_x * 2
        return max(10, int(usable_w / avg_char_w))

    def _wrap_pixels(self, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
        """Word-wrap text to fit within *max_w* pixels (much more accurate than char-count wrapping)."""
        words = text.split(" ")
        lines: list[str] = []
        cur = ""
        for word in words:
            test = f"{cur} {word}" if cur else word
            if font.getlength(test) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                if font.getlength(word) > max_w:
                    # Force-break a very long word
                    buf = ""
                    for ch in word:
                        if font.getlength(buf + ch) > max_w and buf:
                            lines.append(buf)
                            buf = ch
                        else:
                            buf += ch
                    cur = buf
                else:
                    cur = word
        if cur:
            lines.append(cur)
        return lines

    def _image_to_rgb565(self, image: Image.Image) -> list[int]:
        raw = image.tobytes("raw", "RGB")
        if _HAS_NUMPY:
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
            r = arr[:, 0].astype(np.uint16)
            g = arr[:, 1].astype(np.uint16)
            b = arr[:, 2].astype(np.uint16)
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            packed = np.empty(rgb565.shape[0] * 2, dtype=np.uint8)
            packed[0::2] = ((rgb565 >> 8) & 0xFF).astype(np.uint8)
            packed[1::2] = (rgb565 & 0xFF).astype(np.uint8)
            return packed.tolist()
        buf = []
        for i in range(0, len(raw), 3):
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            buf.append((rgb565 >> 8) & 0xFF)
            buf.append(rgb565 & 0xFF)
        return buf

    def _draw_battery(self, draw: ImageDraw.ImageDraw):
        """Draw battery percentage and status in top-right corner (small). Always draws something."""
        pct, status = _read_battery()
        if pct is not None:
            if status == "Charging":
                label = f"↑{pct}%"
            elif status == "Full":
                label = "100%"
            else:
                label = f"{pct}%"
        else:
            label = "—"  # No battery detected; show placeholder so corner is visible
        tw = self._battery_font.getlength(label)
        x = self._width - tw - self._pad_x
        y = self._pad_y
        draw.text((x, y), label, font=self._battery_font, fill=(120, 120, 120))

    def _draw(self, image: Image.Image):
        buf = self._image_to_rgb565(image)
        with self._draw_lock:
            self.board.draw_image(0, 0, self._width, self._height, buf)

    def set_status(
        self,
        text: str,
        color: tuple[int, int, int] = (200, 200, 200),
        subtitle: str | None = None,
        accent_color: tuple[int, int, int] | None = None,
    ):
        """Show a status screen: optional accent bar, main text, optional subtitle."""
        img = Image.new("RGB", (self._width, self._height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        y_offset = 0
        if accent_color is not None:
            draw.rectangle(
                (0, 0, self._width, ACCENT_BAR_HEIGHT),
                fill=accent_color,
            )
            y_offset = ACCENT_BAR_HEIGHT + 6

        wrap_w = self._calc_wrap_width(self._status_font, self._pad_x)
        wrapped = textwrap.fill(text, width=wrap_w)
        lines = wrapped.split("\n")
        line_h = STATUS_FONT_SIZE + 4
        sub_h = STATUS_SUB_FONT_SIZE + 2 if subtitle else 0
        total_h = line_h * len(lines) + sub_h
        y = max(self._pad_y + y_offset, (self._height - total_h) // 2)

        for line in lines:
            tw = self._text_width_mixed(line, self._status_font, self._emoji_status)
            x = int((self._width - tw) / 2)
            self._draw_mixed(draw, (x, y), line, self._status_font, self._emoji_status, color)
            y += line_h
            if y + line_h > self._height:
                break

        if subtitle and y + STATUS_SUB_FONT_SIZE <= self._height:
            sub_w = self._status_sub_font.getlength(subtitle)
            x = int((self._width - sub_w) / 2)
            draw.text((x, y), subtitle, font=self._status_sub_font, fill=(100, 100, 100))

        self._draw_battery(draw)
        self._draw(img)
        self._response_buf = ""
        self._cached_paragraphs = []
        self._cached_wrapped = []

    def set_idle_screen(self):
        """Draw idle screen with clock, date, battery, and wifi status."""
        img = Image.new("RGB", (self._width, self._height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rectangle((0, 0, self._width, ACCENT_BAR_HEIGHT), fill=(40, 40, 40))

        self._draw_battery(draw)

        # Wifi indicator (top-left)
        if _wifi_connected():
            draw.text((self._pad_x, self._pad_y), "\u25cf", font=self._battery_font, fill=(0, 180, 80))
        else:
            draw.text((self._pad_x, self._pad_y), "\u25cb", font=self._battery_font, fill=(180, 60, 60))

        now = datetime.now()

        # Large clock
        time_str = now.strftime("%H:%M")
        tw = self._clock_font.getlength(time_str)
        tx = int((self._width - tw) / 2)
        ty = int(self._height * 0.22)
        draw.text((tx, ty), time_str, font=self._clock_font, fill=(220, 220, 220))

        # Date
        date_str = now.strftime("%a, %b %d")
        dw = self._status_sub_font.getlength(date_str)
        dx = int((self._width - dw) / 2)
        dy = ty + CLOCK_FONT_SIZE + 6
        draw.text((dx, dy), date_str, font=self._status_sub_font, fill=(100, 100, 100))

        # Subtitle
        sub = "Press button to talk"
        sw = self._status_sub_font.getlength(sub)
        sx = int((self._width - sw) / 2)
        sy = self._height - STATUS_SUB_FONT_SIZE - self._pad_y
        draw.text((sx, sy), sub, font=self._status_sub_font, fill=(70, 70, 70))

        self._draw(img)
        self._response_buf = ""
        self._cached_paragraphs = []
        self._cached_wrapped = []

    def start_spinner(self, label: str = "Thinking", color: tuple[int, int, int] = (255, 220, 50)):
        self._spinner_stop = threading.Event()
        t = threading.Thread(target=self._spin_loop, args=(label, color), daemon=True)
        t.start()
        self._spinner_thread = t

    def stop_spinner(self):
        if hasattr(self, "_spinner_stop"):
            self._spinner_stop.set()
        if hasattr(self, "_spinner_thread"):
            self._spinner_thread.join(timeout=2)

    def _spin_loop(self, label: str, color: tuple[int, int, int]):
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i = 0
        while not self._spinner_stop.is_set():
            text = f"{frames[i]}  {label}"
            img = Image.new("RGB", (self._width, self._height), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, self._width, ACCENT_BAR_HEIGHT), fill=color)
            tw = self._text_width_mixed(text, self._status_font, self._emoji_status)
            x = int((self._width - tw) / 2)
            y = (self._height - STATUS_FONT_SIZE) // 2
            self._draw_mixed(draw, (x, y), text, self._status_font, self._emoji_status, color)
            sub = "Getting answer…"
            sub_w = self._status_sub_font.getlength(sub)
            draw.text((int((self._width - sub_w) / 2), y + STATUS_FONT_SIZE + 6), sub, font=self._status_sub_font, fill=(90, 90, 90))
            self._draw_battery(draw)
            self._draw(img)
            i = (i + 1) % len(frames)
            self._spinner_stop.wait(timeout=0.12)

    def set_response_text(self, text: str):
        """Draw full wrapped response text, scrolled to bottom."""
        self._response_buf = text
        self._cached_paragraphs = []
        self._cached_wrapped = []
        self._render_response(force=True)

    def append_response(self, delta: str):
        """Append a streaming delta and redraw (throttled)."""
        was_empty = not self._response_buf
        self._response_buf += delta
        # First token: show immediately; later tokens throttled by _min_draw_interval
        self._render_response(force=was_empty)

    def _render_response(self, force: bool = False):
        now = time.monotonic()
        if not force and (now - self._last_draw_time) < self._min_draw_interval:
            return
        self._last_draw_time = now

        img = Image.new("RGB", (self._width, self._height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rectangle((0, 0, self._width, ACCENT_BAR_HEIGHT), fill=(0, 160, 80))

        line_spacing = 4
        usable_w = self._width - self._pad_x * 2
        content_top = self._pad_y + ACCENT_BAR_HEIGHT + 4
        content_bottom = self._height - self._pad_y

        clean = _clean_markdown(self._response_buf)
        paragraphs = clean.split("\n")

        first_changed = len(paragraphs)
        for i, para in enumerate(paragraphs):
            stripped = para.strip() if para.strip() else ""
            if i >= len(self._cached_paragraphs) or self._cached_paragraphs[i] != stripped:
                first_changed = i
                break

        new_cached_paras: list[str] = []
        new_cached_wrapped: list[list[str]] = []
        all_lines: list[str] = []

        for i, para in enumerate(paragraphs):
            stripped = para.strip()
            if i < first_changed:
                new_cached_paras.append(self._cached_paragraphs[i])
                new_cached_wrapped.append(self._cached_wrapped[i])
                all_lines.extend(self._cached_wrapped[i])
            else:
                if not stripped:
                    wrapped = [""]
                else:
                    wrapped = self._wrap_pixels(stripped, self._response_font, usable_w)
                new_cached_paras.append(stripped)
                new_cached_wrapped.append(wrapped)
                all_lines.extend(wrapped)

        self._cached_paragraphs = new_cached_paras
        self._cached_wrapped = new_cached_wrapped

        line_h = RESPONSE_FONT_SIZE + line_spacing
        max_visible = (content_bottom - content_top) // line_h
        truncated = len(all_lines) > max_visible

        if truncated:
            all_lines = all_lines[-max_visible:]

        text_color = (230, 235, 240)
        y = content_top
        for line in all_lines:
            if not line:
                y += line_h // 2
                continue
            self._draw_mixed(
                draw, (self._pad_x, y), line,
                self._response_font, self._emoji_response, text_color,
            )
            y += line_h

        if truncated:
            indicator = "\u2191"
            iw = self._battery_font.getlength(indicator)
            draw.text(
                (self._width - iw - self._pad_x, content_top),
                indicator, font=self._battery_font, fill=(80, 80, 80),
            )

        self._draw_battery(draw)
        self._draw(img)

    def flush_response(self):
        """Force a final redraw of buffered response text."""
        self._render_response(force=True)

    def update_text(self, text: str):
        """Legacy: draw centred text."""
        self.set_status(text, color=(255, 255, 255))

    def clear(self):
        with self._draw_lock:
            self.board.fill_screen(0x0000)

    def set_backlight(self, level: int):
        self.board.set_backlight(level)

    def cleanup(self):
        try:
            self.clear()
            self.board.set_backlight(0)
        except Exception:
            pass
        try:
            self.board.cleanup()
        except Exception:
            pass
