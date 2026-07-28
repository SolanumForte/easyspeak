"""Replay multimedia keys through GNOME (Mutter) for native desktop feedback.

This lets the desktop render its own volume OSD and chime rather than imitating them.
Pressing a volume key does not run any command: gnome-settings-daemon grabs the raw
evdev key and handles the volume change, OSD and chime itself. The only way to reproduce
that exactly is to replay the key. We inject it through Mutter's RemoteDesktop
interface, which needs no special privileges. A RemoteDesktop session lives only as long
as the D-Bus connection that created it, so the whole CreateSession -> Start ->
NotifyKeyboardKeycode -> Stop sequence runs on one connection.
"""

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection

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
