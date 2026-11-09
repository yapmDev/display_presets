#!/usr/bin/env python3
"""display-presets: save display layouts and switch between them.

    main.py                 open the window
    main.py next            apply the next preset in list order (Super+Shift+P)
    main.py apply NAME      apply a preset without any UI (for a keybinding)
    main.py list            print the preset names
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

APP_ID = "dev.yapm.DisplayPresets"


def next_preset(saved, monitors, current_layout):
    """The preset `next` should apply, or None to do nothing.

    The list order is the cycle. Starting after the preset on screen (the
    first one that matches, if several do), the next one whose monitors are
    all connected wins, wrapping around. When nothing on screen matches — no
    preset applied yet, or the one applied was edited without saving it back —
    the cycle starts at the top, so the first usable preset is applied even
    if it is the only one. A preset that is already on screen and has no
    usable sibling is left alone.
    """
    import displays
    usable = [not displays.resolve(p["layout"], monitors)[1] for p in saved]
    on_screen = next((i for i, p in enumerate(saved)
                      if usable[i] and displays.is_current(p["layout"], monitors, current_layout)),
                     None)
    start = 0 if on_screen is None else on_screen + 1
    for k in range(len(saved)):
        i = (start + k) % len(saved)
        if usable[i] and i != on_screen:
            return saved[i]
    return None


def _cli(args):
    import displays
    import presets as presets_mod
    saved = presets_mod.load()
    if args[0] == "list":
        for p in saved:
            print(p["name"])
        return 0
    if args[0] == "next":
        try:
            _serial, monitors, current_layout, _props = displays.current_state()
            preset = next_preset(saved, monitors, current_layout)
            if preset is not None:
                displays.apply(preset["layout"])
        except displays.DisplayError as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    if args[0] == "apply" and len(args) == 2:
        preset = presets_mod.find(saved, args[1])
        if preset is None:
            print(f"No preset called {args[1]!r}", file=sys.stderr)
            return 1
        try:
            displays.apply(preset["layout"])
        except displays.DisplayError as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


def _gui():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    from window import PresetsWindow

    # One window at a time: opening the app again while it is up just
    # raises the window that is already there. No process outlives it.
    app = Gtk.Application(application_id=APP_ID)

    def on_activate(app):
        win = app.get_active_window() or PresetsWindow(app)
        win.show_all()
        win.present()

    app.connect("activate", on_activate)
    return app.run(None)


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]) if len(sys.argv) > 1 else _gui())
