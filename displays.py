"""The display layout, read from and written to mutter over D-Bus.

This is the same interface `gdctl` and GNOME Settings use
(org.gnome.Mutter.DisplayConfig), spoken directly so the layout comes back as
data rather than text to parse. No GTK here, and no app state: a layout goes in
or comes out as a plain dict, the shape `presets.py` stores.

A layout is

    {"logical": [{"x", "y", "scale", "transform", "primary",
                  "monitors": [{"connector", "vendor", "product", "serial", "mode"}]}]}

where a monitor left out of every logical monitor is a monitor turned off.
"""
from gi.repository import Gio, GLib

BUS_NAME = "org.gnome.Mutter.DisplayConfig"
OBJECT_PATH = "/org/gnome/Mutter/DisplayConfig"
INTERFACE = BUS_NAME

# ApplyMonitorsConfig's `method`. Persistent is what GNOME Settings uses: the
# layout is written to monitors.xml, so it survives a replug or a reboot, and
# the shell asks to keep it — reverting on its own if the answer never comes,
# which is the safety net for a preset that no longer fits the hardware.
METHOD_TEMPORARY = 1
METHOD_PERSISTENT = 2

# Mutter's transform enum, in its order. The labels are what a preset's
# summary shows; "normal" is left out of summaries altogether.
TRANSFORMS = ["normal", "90°", "180°", "270°",
              "flipped", "flipped 90°", "flipped 180°", "flipped 270°"]


class DisplayError(Exception):
    """Anything that went wrong talking to mutter, as a user-facing message."""


def _bus():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def _call(method, params=None):
    try:
        return _bus().call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, method, params,
                                None, Gio.DBusCallFlags.NONE, -1, None).unpack()
    except GLib.Error as e:
        Gio.DBusError.strip_remote_error(e)
        raise DisplayError(e.message) from e


def current_state():
    """The raw state, reshaped: (serial, monitors, layout, properties).

    `monitors` is a list of every *connected* monitor, on or off:
    {"connector", "vendor", "product", "serial", "name", "builtin",
     "modes": [mode ids], "current": mode id or None, "preferred": mode id}.
    `layout` is the current layout, in the module's shape.
    """
    serial, raw_monitors, raw_logical, props = _call("GetCurrentState")
    monitors = []
    for (connector, vendor, product, mon_serial), modes, mprops in raw_monitors:
        current = preferred = None
        for mode in modes:
            mode_id, mode_props = mode[0], mode[6]
            if mode_props.get("is-current"):
                current = mode_id
            if mode_props.get("is-preferred"):
                preferred = mode_id
        monitors.append({
            "connector": connector, "vendor": vendor, "product": product,
            "serial": mon_serial,
            "name": mprops.get("display-name", connector),
            "builtin": bool(mprops.get("is-builtin", False)),
            "modes": [m[0] for m in modes],
            "current": current,
            "preferred": preferred or (modes[0][0] if modes else None),
        })
    by_connector = {m["connector"]: m for m in monitors}
    logical = []
    for x, y, scale, transform, primary, specs, _lprops in raw_logical:
        logical.append({
            "x": x, "y": y, "scale": scale, "transform": transform,
            "primary": bool(primary),
            "monitors": [{
                "connector": connector, "vendor": vendor, "product": product,
                "serial": mon_serial,
                "mode": by_connector.get(connector, {}).get("current"),
            } for connector, vendor, product, mon_serial in specs],
        })
    logical.sort(key=lambda lm: (lm["x"], lm["y"]))
    return serial, monitors, {"logical": logical}, dict(props)


def _identity(mon):
    return (mon["vendor"], mon["product"], mon["serial"])


def resolve(layout, monitors):
    """Map every monitor a layout names onto a connected one.

    A monitor is matched by vendor/product/serial first — the same screen on
    another port is still the same screen — and by connector only when that
    fails, since some panels report no useful serial. Answers
    (resolved_layout, missing) where `missing` lists the monitors the layout
    wants that are not connected; the layout can only be applied when it is
    empty.
    """
    by_identity = {}
    for mon in monitors:
        by_identity.setdefault(_identity(mon), mon)
    by_connector = {m["connector"]: m for m in monitors}
    missing, resolved = [], []
    for lm in layout["logical"]:
        mons = []
        for want in lm["monitors"]:
            have = by_identity.get(_identity(want)) or by_connector.get(want["connector"])
            if have is None:
                missing.append(want)
                continue
            mode = want.get("mode")
            if mode not in have["modes"]:
                mode = have["preferred"]
            mons.append({**want, "connector": have["connector"], "mode": mode})
        resolved.append({**lm, "monitors": mons})
    return {"logical": resolved}, missing


def normalized(layout):
    """A comparable form of a layout: what makes two layouts the same screen
    arrangement, ignoring list order and float noise in the scale."""
    return sorted(
        (lm["x"], lm["y"], round(lm["scale"], 3), lm["transform"], lm["primary"],
         tuple(sorted((m["connector"], m["mode"]) for m in lm["monitors"])))
        for lm in layout["logical"]
    )


def is_current(layout, monitors, current_layout):
    """Whether `layout`, resolved onto what is connected, is what is on screen."""
    resolved, missing = resolve(layout, monitors)
    return not missing and normalized(resolved) == normalized(current_layout)


def apply(layout, persistent=True):
    """Put `layout` on screen. Raises DisplayError if a monitor is missing or
    mutter refuses the configuration."""
    serial, monitors, _current, props = current_state()
    resolved, missing = resolve(layout, monitors)
    if missing:
        raise DisplayError("Not connected: " + ", ".join(m["connector"] for m in missing))
    logical = [
        (lm["x"], lm["y"], float(lm["scale"]), lm["transform"], lm["primary"],
         [(m["connector"], m["mode"], {}) for m in lm["monitors"]])
        for lm in resolved["logical"] if lm["monitors"]
    ]
    if not logical:
        raise DisplayError("A preset needs at least one display turned on")
    properties = {}
    if props.get("supports-changing-layout-mode") and "layout-mode" in props:
        properties["layout-mode"] = GLib.Variant("u", props["layout-mode"])
    params = GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (
        serial, METHOD_PERSISTENT if persistent else METHOD_TEMPORARY,
        logical, properties))
    _call("ApplyMonitorsConfig", params)


def summary(layout, monitors):
    """One line describing a layout, e.g. "Built-in display 180° · QHX 27\" (primary)"
    — left to right as they sit. "(primary)" is only said when there is more
    than one display on: with a single one it is primary by necessity."""
    names = {m["connector"]: m["name"] for m in monitors}
    names.update({_identity(m): m["name"] for m in monitors})
    parts = []
    several = sum(len(lm["monitors"]) for lm in layout["logical"]) > 1
    for lm in sorted(layout["logical"], key=lambda lm: (lm["x"], lm["y"])):
        for mon in lm["monitors"]:
            name = names.get(_identity(mon)) or names.get(mon["connector"]) or mon["connector"]
            if lm["transform"]:
                name += " " + TRANSFORMS[lm["transform"]]
            if lm["primary"] and several:
                name += " (primary)"
            parts.append(name)
    return " · ".join(parts)


def watch(callback):
    """Call `callback()` on the main loop whenever the layout or the set of
    connected monitors changes — from this app, GNOME Settings or a cable."""
    return _bus().signal_subscribe(BUS_NAME, INTERFACE, "MonitorsChanged",
                                   OBJECT_PATH, None, Gio.DBusSignalFlags.NONE,
                                   lambda *_: callback())
