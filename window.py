import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import cairo
from pathlib import Path
import subprocess
import displays
import presets as presets_mod
from design import add_classes

WINDOW_SIZE = (440, 420)

# Rows are only ever dragged within this list, so the target never leaves the
# widget and carries no data: the dragged preset is kept on the window.
ROW_TARGET = Gtk.TargetEntry.new("display-presets/row", Gtk.TargetFlags.SAME_WIDGET, 0)


class PresetsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Display Presets")
        add_classes(self, "ds-window")
        self.set_default_size(*WINDOW_SIZE)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.presets = presets_mod.load()
        self._state = None
        self._load_css()
        self._build_ui()
        self._refresh()
        # A cable, GNOME Settings or this app itself moving the screens all
        # end up here, so the list always marks what is actually on screen.
        self._watch_id = displays.watch(self._refresh)

        self.connect("key-press-event", self._on_key_press)

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).parent / "style.css"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # ---- layout ------------------------------------------------------

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        scroller = add_classes(Gtk.ScrolledWindow(), "ds-transparent")
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = add_classes(Gtk.ListBox(), "ds-transparent")
        self.listbox.set_name("preset-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect("row-activated", self._on_row_activated)
        self._drag_row = None
        self._drop_target = None  # (row, "before" | "after")
        self.listbox.drag_dest_set(0, [ROW_TARGET], Gdk.DragAction.MOVE)
        self.listbox.connect("drag-motion", self._on_drag_motion)
        self.listbox.connect("drag-leave", lambda *_: self._set_drop_target(None))
        self.listbox.connect("drag-drop", self._on_drag_drop)
        self.empty_label = add_classes(Gtk.Label(
            label="No presets yet.\nArrange your displays in Settings,\n"
                  "then save the layout below.",
            justify=Gtk.Justification.CENTER), "ds-text-muted")
        self.empty_label.set_name("empty-label")
        self.listbox.set_placeholder(self.empty_label)
        self.empty_label.show()
        scroller.add(self.listbox)
        root.pack_start(scroller, True, True, 0)

        self.status_label = add_classes(Gtk.Label(xalign=0), "ds-caption", "ds-text-destructive")
        self.status_label.set_name("status-label")
        self.status_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.status_label.set_no_show_all(True)
        root.pack_start(self.status_label, False, False, 0)

        footer = add_classes(Gtk.Box(spacing=6), "ds-bar", "ds-divider-top")
        footer.set_name("footer")

        # The left part is the save flow and takes whatever width is left: at
        # rest a single "Save current layout" button, which turns into a name
        # entry + Save once clicked. A stack keeps the bar the same height in
        # both states.
        self.save_stack = Gtk.Stack()
        self.save_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.save_stack.set_transition_duration(120)
        self.save_stack.set_homogeneous(True)

        btn_start = add_classes(Gtk.Button(label="Save current layout"),
                                "ds-button", "ds-button-accent")
        btn_start.connect("clicked", lambda _: self._open_save_form())
        self.save_stack.add_named(btn_start, "idle")

        form = Gtk.Box(spacing=6)
        self.name_entry = add_classes(Gtk.Entry(), "ds-entry")
        self.name_entry.set_placeholder_text("Preset name")
        self.name_entry.connect("changed", lambda _: self._update_save_button())
        self.name_entry.connect("activate", lambda _: self._save_current())
        form.pack_start(self.name_entry, True, True, 0)
        self.btn_save = add_classes(Gtk.Button(label="Save"), "ds-button", "ds-button-accent")
        self.btn_save.connect("clicked", lambda _: self._save_current())
        form.pack_end(self.btn_save, False, False, 0)
        self.save_stack.add_named(form, "form")
        footer.pack_start(self.save_stack, True, True, 0)

        # Separates the one control that never changes (settings) from the
        # save flow, as in notepanel's bottom bar.
        btn_settings = add_classes(
            Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.SMALL_TOOLBAR),
            "ds-button", "ds-button-icon")
        btn_settings.set_tooltip_text("Open display settings")
        btn_settings.connect("clicked", lambda _: self._open_settings())
        footer.pack_end(btn_settings, False, False, 0)
        bar_separator = add_classes(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL),
                                    "ds-separator")
        bar_separator.set_name("bar-separator")
        footer.pack_end(bar_separator, False, False, 0)
        root.pack_end(footer, False, False, 0)

    def _build_row(self, index, preset, monitors, current_layout):
        resolved, missing = displays.resolve(preset["layout"], monitors)
        active = not missing and displays.normalized(resolved) == displays.normalized(current_layout)

        row = add_classes(Gtk.ListBoxRow(), "ds-card")
        row.set_name("preset-row")
        row.preset = preset
        row.set_activatable(not missing)
        if active:
            add_classes(row, "selected")

        # A ListBoxRow has no window of its own to start a drag from, so the
        # row's content sits in an event box that is the drag source. The
        # menu button inside keeps its press, so it never starts a drag.
        handle = Gtk.EventBox()
        handle.set_visible_window(False)
        handle.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [ROW_TARGET], Gdk.DragAction.MOVE)
        handle.connect("drag-begin", self._on_drag_begin, row)
        handle.connect("drag-end", self._on_drag_end, row)
        row.add(handle)
        box = Gtk.Box(spacing=12)
        handle.add(box)

        # 1-9 apply a preset straight from the keyboard; the number is shown so
        # that is discoverable without a manual.
        key = add_classes(Gtk.Label(label=str(index + 1) if index < 9 else ""),
                          "ds-caption", "ds-text-muted")
        key.set_width_chars(1)
        box.pack_start(key, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        name = add_classes(Gtk.Label(label=preset["name"], xalign=0), "ds-strong")
        name.set_ellipsize(3)
        text.pack_start(name, False, False, 0)
        if missing:
            detail = "Not connected: " + ", ".join(m["connector"] for m in missing)
        else:
            detail = displays.summary(preset["layout"], monitors)
        caption = add_classes(Gtk.Label(label=detail, xalign=0), "ds-caption",
                              "ds-text-destructive" if missing else "ds-text-muted")
        caption.set_ellipsize(3)
        text.pack_start(caption, False, False, 0)
        box.pack_start(text, True, True, 0)

        btn_menu = add_classes(
            Gtk.MenuButton(image=Gtk.Image.new_from_icon_name(
                "view-more-symbolic", Gtk.IconSize.BUTTON)),
            "ds-button-bare", "ds-text-secondary")
        btn_menu.set_relief(Gtk.ReliefStyle.NONE)
        btn_menu.set_name("btn-row-menu")
        btn_menu.set_valign(Gtk.Align.CENTER)
        btn_menu.set_popup(self._row_menu(preset))
        box.pack_end(btn_menu, False, False, 0)

        if active:
            box.pack_end(add_classes(Gtk.Image.new_from_icon_name(
                "object-select-symbolic", Gtk.IconSize.BUTTON), "ds-text-accent"),
                False, False, 0)
        return row

    def _row_menu(self, preset):
        menu = Gtk.Menu()
        for label, handler in (("Rename…", self._rename),
                               ("Update to current layout", self._update),
                               (None, None),
                               ("Delete", self._delete)):
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, h=handler: h(preset))
            menu.append(item)
        menu.show_all()
        return menu

    # ---- state -------------------------------------------------------

    def _refresh(self):
        try:
            self._state = displays.current_state()
        except displays.DisplayError as e:
            self._show_error(str(e))
            return
        _serial, monitors, current_layout, _props = self._state
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        for i, preset in enumerate(self.presets):
            self.listbox.add(self._build_row(i, preset, monitors, current_layout))
        self.listbox.show_all()
        self._update_save_button()

    def _update_save_button(self):
        name = self.name_entry.get_text().strip()
        self.btn_save.set_label("Update" if name and presets_mod.find(self.presets, name) else "Save")
        self.btn_save.set_sensitive(bool(name))

    def _commit(self):
        # A change that went through clears whatever error was showing: the
        # list itself is the confirmation, so success never gets a message.
        self._show_error("")
        try:
            presets_mod.save(self.presets)
        except OSError as e:
            self._show_error(f"Could not save presets: {e.strerror}")
        self._refresh()

    def _show_error(self, text):
        """The status line is for failures only — empty text hides it."""
        self.status_label.set_text(text)
        self.status_label.set_visible(bool(text))

    # ---- actions -----------------------------------------------------

    def _apply(self, preset):
        try:
            displays.apply(preset["layout"])
        except displays.DisplayError as e:
            self._show_error(str(e))
            return
        # Applying is the whole point of opening the window: once it worked,
        # there is nothing left to do here.
        self.close()

    def _on_row_activated(self, _listbox, row):
        # A drag that ends where it began still releases the button on the
        # row, which the list reads as a click — that must not apply it.
        if self._drag_row is not None:
            return
        self._apply(row.preset)

    def _save_current(self):
        name = self.name_entry.get_text().strip()
        if not name or self._state is None:
            return
        layout = self._state[2]
        existing = presets_mod.find(self.presets, name)
        if existing:
            existing["layout"] = layout
        else:
            self.presets.append({"name": name, "layout": layout})
        self._close_save_form()
        self._commit()

    def _open_save_form(self):
        self.name_entry.set_text("")
        self.save_stack.set_visible_child_name("form")
        self.name_entry.grab_focus()

    def _close_save_form(self):
        self.name_entry.set_text("")
        self.save_stack.set_visible_child_name("idle")

    def _update(self, preset):
        if self._state is None:
            return
        preset["layout"] = self._state[2]
        self._commit()

    # ---- reordering --------------------------------------------------

    def _on_drag_begin(self, handle, context, row):
        self._drag_row = row
        # The drag icon is the row itself, grabbed where the pointer took it.
        alloc = row.get_allocation()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, alloc.width, alloc.height)
        row.draw(cairo.Context(surface))
        _win, px, py, _mask = row.get_window().get_device_position(
            context.get_device())
        surface.set_device_offset(-(px - alloc.x), -(py - alloc.y))
        Gtk.drag_set_icon_surface(context, surface)
        add_classes(row, "dragging")

    def _on_drag_end(self, _handle, _context, row):
        row.get_style_context().remove_class("dragging")
        self._set_drop_target(None)
        # Cleared on idle: the button release that ends the drag arrives as
        # row-activated right after this, and has to find the drag still on.
        GLib.idle_add(self._clear_drag_row)

    def _clear_drag_row(self):
        self._drag_row = None
        return False

    def _drop_position(self, y):
        """Where a drop at `y` lands: (row, "before"|"after"), split at the
        row's middle — or after the last row in the space below them all."""
        row = self.listbox.get_row_at_y(y)
        if row is None:
            rows = self.listbox.get_children()
            return (rows[-1], "after") if rows else None
        alloc = row.get_allocation()
        return row, "before" if y < alloc.y + alloc.height / 2 else "after"

    def _set_drop_target(self, target):
        if self._drop_target:
            ctx = self._drop_target[0].get_style_context()
            ctx.remove_class("drop-before")
            ctx.remove_class("drop-after")
        self._drop_target = target
        if target:
            add_classes(target[0], "drop-" + target[1])

    def _on_drag_motion(self, _listbox, context, _x, y, time):
        if self._drag_row is None:
            return False
        self._set_drop_target(self._drop_position(y))
        Gdk.drag_status(context, Gdk.DragAction.MOVE, time)
        return True

    def _on_drag_drop(self, _listbox, context, _x, y, time):
        target = self._drop_position(y)
        moved = False
        if self._drag_row is not None and target:
            moved = self._move(self._drag_row.preset, target[0].preset, target[1])
        Gtk.drag_finish(context, moved, False, time)
        return True

    def _move(self, preset, anchor, where):
        """Put `preset` right before or after `anchor`. Answers whether the
        order actually changed."""
        if preset is anchor:
            return False
        order = [p for p in self.presets if p is not preset]
        i = order.index(anchor) + (1 if where == "after" else 0)
        order.insert(i, preset)
        if order == self.presets:
            return False
        self.presets[:] = order
        self._commit()
        return True

    def _delete(self, preset):
        self.presets.remove(preset)
        self._commit()

    def _rename(self, preset):
        dialog = Gtk.Dialog(title="Rename preset", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Rename", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = add_classes(Gtk.Entry(text=preset["name"]), "ds-entry")
        entry.set_activates_default(True)
        area = dialog.get_content_area()
        area.set_name("rename-body")
        area.add(entry)
        dialog.show_all()
        response = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not name or name == preset["name"]:
            return
        clash = presets_mod.find(self.presets, name)
        if clash and clash is not preset:
            self._show_error(f"There is already a preset called “{clash['name']}”")
            return
        preset["name"] = name
        self._commit()

    def _open_settings(self):
        try:
            subprocess.Popen(["gnome-control-center", "display"])
        except OSError as e:
            self._show_error(f"Could not open Settings: {e.strerror}")

    def _on_key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            # Escape backs out of the save form first, and only then closes.
            if self.save_stack.get_visible_child_name() == "form":
                self._close_save_form()
            else:
                self.close()
            return True
        # Digits apply a preset — unless the user is typing a name.
        if not self.name_entry.has_focus():
            digit = Gdk.keyval_to_unicode(event.keyval)
            if ord("1") <= digit <= ord("9"):
                i = digit - ord("1")
                rows = self.listbox.get_children()
                if i < len(rows) and rows[i].get_activatable():
                    self._apply(rows[i].preset)
                return True
        return False
