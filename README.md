# display-presets

Save GNOME display layouts (which screens are on, position, rotation, scale, primary) and switch between them in one click.
No daemon: it's a normal window that closes itself once a preset is applied.

## Use

- Arrange your displays in Settings, type a name, **Save**.
- Click a preset (or press its number, `1`–`9`) to apply it. The one on screen now is ticked.
- `⋯` on a preset: rename, update to the current layout, delete. Drag a preset to reorder.
- `main.py next` cycles through the presets in list order — bind it to a key (e.g. Super+Shift+P).
- From a shell or a keybinding: `main.py apply "Work"`, `main.py list`.

Presets live in `~/.config/display_presets/presets.json`.

## Requirements

GNOME (mutter) on Wayland or X11, Python 3.12+, PyGObject, GTK 3.

## License

MIT
