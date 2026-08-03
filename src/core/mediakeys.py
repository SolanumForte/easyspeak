"""Replay multimedia keys through GNOME (Mutter) for native desktop feedback.

This lets the desktop render its own volume OSD and chime rather than imitating them.
Pressing a volume key does not run any command: gnome-settings-daemon grabs the raw
evdev key and handles the volume change, OSD and chime itself. The only way to reproduce
that exactly is to replay the key. We inject it through Mutter's RemoteDesktop
interface, which needs no special privileges. A RemoteDesktop session lives only as long
as the D-Bus connection that created it, so the whole CreateSession -> Start ->
NotifyKeyboardKeycode -> Stop sequence runs on one connection.
"""

import logging

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection

logger = logging.getLogger(__name__)

_BUS = "org.gnome.Mutter.RemoteDesktop"

_REMOTE_DESKTOP = DBusAddress(
    "/org/gnome/Mutter/RemoteDesktop",
    bus_name=_BUS,
    interface=_BUS,
)


def tap_key(keycode):
    """Press and release one evdev keycode via Mutter RemoteDesktop.

    Raises if RemoteDesktop is unavailable (e.g. a non-GNOME session) so the caller can
    fall back to a silent change.
    """
    tap_chord([keycode])


def tap_chord(keycodes):
    """Hold a chord of evdev keycodes together, then release it.

    Keys go down in the order given and come up in reverse, so `[CTRL, V]` is the
    Ctrl+V an application expects rather than two unrelated keypresses. Used for
    pasting dictated text, which is how text reaches an application: every toolkit
    implements paste, whereas accessibility-level insertion is widely stubbed out
    (Chromium-based apps accept it and discard it).

    Raises if RemoteDesktop is unavailable, so the caller can report why.
    """
    conn = open_dbus_connection(bus="SESSION")
    try:
        reply = conn.send_and_get_reply(
            new_method_call(_REMOTE_DESKTOP, "CreateSession")
        )
        session = DBusAddress(
            reply.body[0],
            bus_name=_BUS,
            interface=f"{_BUS}.Session",
        )
        conn.send_and_get_reply(new_method_call(session, "Start"))
        # Synchronous replies guarantee Mutter has processed each event before
        # we move on, so no settling delay is needed before Stop.
        for keycode in keycodes:
            conn.send_and_get_reply(
                new_method_call(session, "NotifyKeyboardKeycode", "ub", (keycode, True))
            )
        for keycode in reversed(keycodes):
            conn.send_and_get_reply(
                new_method_call(
                    session, "NotifyKeyboardKeycode", "ub", (keycode, False)
                )
            )
        conn.send_and_get_reply(new_method_call(session, "Stop"))
    finally:
        conn.close()


KEYS = {
    "enter": 28,
    "tab": 15,
    "escape": 1,
    "backspace": 14,
    "up": 103,
    "down": 108,
    "left": 105,
    "right": 106,
    "home": 102,
    "end": 107,
    "page up": 104,
    "page down": 109,
}

KEY_ALIASES = {
    "delete": "backspace",
    "return": "enter",
    "escape key": "escape",
}

SPOKEN_COUNTS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

MAX_KEY_REPEATS = 200


def parse_key_request(words, bare_allowed):
    """Return (keycode, repeats) for a spoken keystroke command, else None.

    Accepts an optional "press" prefix, one- or two-word key names, and a trailing
    count as digits or a number word. `bare_allowed` names the keys a caller will
    accept without the prefix; every other key needs it, so that words already
    meaning something else in that mode are left alone.
    """
    explicit = bool(words) and words[0] == "press"
    if explicit:
        words = words[1:]
    if not words:
        return None

    for length in (2, 1):
        name = " ".join(words[:length])
        name = KEY_ALIASES.get(name, name)
        if name not in KEYS or (not explicit and name not in bare_allowed):
            continue
        tail = words[length:]
        if not tail:
            return KEYS[name], 1
        if len(tail) > 1:
            return None
        count = int(tail[0]) if tail[0].isdigit() else SPOKEN_COUNTS.get(tail[0])
        if count is None:
            return None
        return KEYS[name], min(count, MAX_KEY_REPEATS)
    return None


def press_key(keycode, repeats=1):
    """Tap `keycode` `repeats` times; True when the keystrokes were delivered."""
    try:
        for _ in range(repeats):
            tap_chord([keycode])
    except (RuntimeError, OSError) as exc:
        logger.warning("Keystrokes need GNOME's RemoteDesktop interface: %s", exc)
        return False
    return True
