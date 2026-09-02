/* Window control extension for GNOME Shell 45+.

   Exports a D-Bus interface on org.gnome.Shell.Extensions.VoiceTalk
   that lists open windows, focuses/closes them, and synthesizes keystrokes
   into the focused window.

   SendKeys exists because browser tabs are not windows. Nothing in Mutter can
   enumerate or activate a Firefox tab, but Firefox itself answers Alt+1..8
   (jump to tab N), Alt+9 (last tab) and Ctrl+W (close tab). Under Wayland only
   the compositor may inject input, and an extension runs inside it -- which is
   why this lives here rather than in the Python process, where xdotool would
   be ignored.
*/

import Clutter from "gi://Clutter";
import Gio from "gi://Gio";
import Meta from "gi://Meta";
import GLib from "gi://GLib";
import { Extension } from "resource:///org/gnome/shell/extensions/extension.js";

const VoiceTalkIface = `
<node>
  <interface name="org.gnome.Shell.Extensions.VoiceTalk">
    <method name="List">
      <arg type="s" direction="out" name="windows"/>
    </method>
    <method name="Focus">
      <arg type="u" direction="in" name="id"/>
    </method>
    <method name="Close">
      <arg type="u" direction="in" name="id"/>
    </method>
    <method name="SendKeys">
      <arg type="u" direction="in" name="id"/>
      <arg type="s" direction="in" name="keys"/>
    </method>
    <method name="Minimize">
      <arg type="u" direction="in" name="id"/>
    </method>
    <method name="Unminimize">
      <arg type="u" direction="in" name="id"/>
    </method>
    <method name="Maximize">
      <arg type="u" direction="in" name="id"/>
    </method>
    <method name="Unmaximize">
      <arg type="u" direction="in" name="id"/>
    </method>
    <method name="MoveToWorkspace">
      <arg type="u" direction="in" name="id"/>
      <arg type="u" direction="in" name="index"/>
    </method>
    <method name="SwitchWorkspace">
      <arg type="u" direction="in" name="index"/>
    </method>
    <method name="Workspaces">
      <arg type="s" direction="out" name="workspaces"/>
    </method>
    <method name="Pointer">
      <arg type="i" direction="in" name="dx"/>
      <arg type="i" direction="in" name="dy"/>
    </method>
    <method name="Click">
      <arg type="u" direction="in" name="button"/>
      <arg type="b" direction="in" name="double"/>
    </method>
    <method name="Scroll">
      <arg type="i" direction="in" name="dx"/>
      <arg type="i" direction="in" name="dy"/>
    </method>
    <method name="TypeText">
      <arg type="s" direction="in" name="text"/>
    </method>
    <method name="Keys">
      <arg type="s" direction="in" name="keys"/>
    </method>
  </interface>
</node>
`;

// Raising a window is asynchronous: the client has to process the focus change
// before it will act on input. Keys sent too early land in the previously
// focused app -- which, for Ctrl+W, closes the wrong thing.
const FOCUS_SETTLE_MS = 150;
// Firefox drops keys sent faster than it repaints between them.
const KEY_GAP_MS = 60;
// Typed text is one keyval per character, so KEY_GAP_MS would make a pasted
// sentence take six seconds. Apps keep up with this because there are no
// modifiers to latch between characters.
const TYPE_GAP_MS = 12;
// A phone can send an arbitrarily long string; the compositor types it one
// timeout at a time and cannot be interrupted, so cap what one call can queue.
const MAX_TYPE_CHARS = 2000;
// Clutter takes scroll deltas in units of one wheel notch, while the phone
// sends pixels of thumb travel.
const SCROLL_PIXELS_PER_NOTCH = 40;

const MODIFIERS = {
  alt: Clutter.KEY_Alt_L,
  ctrl: Clutter.KEY_Control_L,
  control: Clutter.KEY_Control_L,
  shift: Clutter.KEY_Shift_L,
  super: Clutter.KEY_Super_L,
};

const NAMED_KEYS = {
  tab: Clutter.KEY_Tab,
  page_up: Clutter.KEY_Page_Up,
  page_down: Clutter.KEY_Page_Down,
  home: Clutter.KEY_Home,
  end: Clutter.KEY_End,
  escape: Clutter.KEY_Escape,
  return: Clutter.KEY_Return,
  space: Clutter.KEY_space,
  up: Clutter.KEY_Up,
  down: Clutter.KEY_Down,
  left: Clutter.KEY_Left,
  right: Clutter.KEY_Right,
  backspace: Clutter.KEY_BackSpace,
  delete: Clutter.KEY_Delete,
  // A presentation remote is F5 to start and Escape to end, and the browser
  // full-screen key is F11 -- so the function row is part of the remote, not
  // an extra.
  f1: Clutter.KEY_F1,
  f2: Clutter.KEY_F2,
  f3: Clutter.KEY_F3,
  f4: Clutter.KEY_F4,
  f5: Clutter.KEY_F5,
  f6: Clutter.KEY_F6,
  f7: Clutter.KEY_F7,
  f8: Clutter.KEY_F8,
  f9: Clutter.KEY_F9,
  f10: Clutter.KEY_F10,
  f11: Clutter.KEY_F11,
  f12: Clutter.KEY_F12,
};

class VoiceTalkDBusImpl {
  constructor() {
    this._impl = Gio.DBusExportedObject.wrapJSObject(VoiceTalkIface, this);
    this._virtualDevice = null;
    this._pointerDevice = null;
    this._timeouts = new Set();
  }

  destroy() {
    // Any pending keystroke would fire into a shell that no longer has this
    // extension loaded, so drop the sources rather than let them run.
    for (const id of this._timeouts) GLib.Source.remove(id);
    this._timeouts.clear();
    this._virtualDevice = null;
    this._pointerDevice = null;
  }

  _findWindow(id) {
    for (const actor of global.get_window_actors()) {
      const meta = actor.get_meta_window();
      if (meta && meta.get_stable_sequence() === id) return meta;
    }
    return null;
  }

  List() {
    const windows = [];
    const workspace = global.workspace_manager.get_active_workspace();
    // The focused window lives on the display, not the workspace -- Meta.Workspace
    // has no get_active_window(), and calling it threw a TypeError out over D-Bus.
    const focused = global.display.get_focus_window();

    for (const w of global.get_window_actors()) {
      const meta = w.get_meta_window();
      if (!meta) continue;

      // Filter to current workspace
      if (meta.get_workspace() !== workspace) continue;
      // Skip docks, desktop icons, and other chrome the user cannot act on.
      if (meta.is_skip_taskbar()) continue;

      windows.push({
        id: meta.get_stable_sequence(),
        title: meta.get_title() || "Unknown",
        wm_class: meta.get_wm_class() || "",
        focused: meta === focused,
        workspace: meta.get_workspace().index(),
        minimized: meta.minimized,
        maximized: meta.maximized_horizontally && meta.maximized_vertically,
      });
    }

    return JSON.stringify(windows);
  }

  Focus(id) {
    const meta = this._findWindow(id);
    if (meta) meta.activate(global.get_current_time());
  }

  Close(id) {
    const meta = this._findWindow(id);
    if (meta) meta.delete(global.get_current_time());
  }

  Minimize(id) {
    const meta = this._findWindow(id);
    if (meta) meta.minimize();
  }

  Unminimize(id) {
    const meta = this._findWindow(id);
    if (!meta) return;
    meta.unminimize();
    meta.activate(global.get_current_time());
  }

  Maximize(id) {
    const meta = this._findWindow(id);
    if (meta) meta.maximize(Meta.MaximizeFlags.BOTH);
  }

  Unmaximize(id) {
    const meta = this._findWindow(id);
    if (meta) meta.unmaximize(Meta.MaximizeFlags.BOTH);
  }

  /* Move a window to another workspace and follow it there. Moving without
     following leaves the user looking at the desktop the window just left,
     which reads as "nothing happened". */
  MoveToWorkspace(id, index) {
    const meta = this._findWindow(id);
    if (!meta) return;
    const wm = global.workspace_manager;
    if (index >= wm.get_n_workspaces()) return;
    meta.change_workspace_by_index(index, false);
    wm.get_workspace_by_index(index).activate(global.get_current_time());
  }

  SwitchWorkspace(index) {
    const wm = global.workspace_manager;
    if (index >= wm.get_n_workspaces()) return;
    wm.get_workspace_by_index(index).activate(global.get_current_time());
  }

  /* Workspace count and which one is active. List() only ever reports the
     active workspace's windows, so this is the only way a client can tell
     there are others to switch to. */
  Workspaces() {
    const wm = global.workspace_manager;
    return JSON.stringify({
      count: wm.get_n_workspaces(),
      active: wm.get_active_workspace_index(),
    });
  }

  /* --- remote input ------------------------------------------------------

     Everything below drives whatever currently has focus, rather than a window
     named by id: the phone is acting as a trackpad and keyboard for the
     session, not operating on one window it picked from a list. Under Wayland
     only the compositor may synthesize input, which is why this lives in an
     extension at all -- xdotool is silently ignored there. */

  _pointer() {
    if (!this._pointerDevice) {
      const seat = Clutter.get_default_backend().get_default_seat();
      this._pointerDevice = seat.create_virtual_device(
        Clutter.InputDeviceType.POINTER_DEVICE
      );
    }
    return this._pointerDevice;
  }

  _keyboard() {
    if (!this._virtualDevice) {
      const seat = Clutter.get_default_backend().get_default_seat();
      this._virtualDevice = seat.create_virtual_device(
        Clutter.InputDeviceType.KEYBOARD_DEVICE
      );
    }
    return this._virtualDevice;
  }

  _now() {
    // notify_* takes microseconds; get_current_event_time is milliseconds.
    return Clutter.get_current_event_time() * 1000;
  }

  /* Move the pointer by a delta, the way a trackpad does. Relative, not
     absolute: the phone has no idea where the pointer is or how large the
     screen is, and an absolute jump would fight whoever is using the mouse. */
  Pointer(dx, dy) {
    if (dx === 0 && dy === 0) return;
    this._pointer().notify_relative_motion(this._now(), dx, dy);
  }

  Click(button, double) {
    // 1 left, 2 middle, 3 right -- Clutter's numbering, which is also X11's.
    if (button < 1 || button > 3) return;
    const vd = this._pointer();
    const tap = () => {
      const t = this._now();
      vd.notify_button(t, button, Clutter.ButtonState.PRESSED);
      vd.notify_button(t, button, Clutter.ButtonState.RELEASED);
    };
    tap();
    if (!double) return;
    // A double click is two clicks inside the double-click interval, not one
    // event with a flag, so the second tap is a real second tap.
    const source = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 40, () => {
      this._timeouts.delete(source);
      tap();
      return GLib.SOURCE_REMOVE;
    });
    this._timeouts.add(source);
  }

  Scroll(dx, dy) {
    if (dx === 0 && dy === 0) return;
    this._pointer().notify_scroll_continuous(
      this._now(),
      dx / SCROLL_PIXELS_PER_NOTCH,
      dy / SCROLL_PIXELS_PER_NOTCH,
      Clutter.ScrollSource.FINGER,
      Clutter.ScrollFinishFlags.NONE
    );
  }

  /* Type a literal string into whatever has focus, one character at a time.
     Unicode goes through unicode_to_keyval, so an em dash or an accented
     letter arrives as itself rather than as the ASCII the phone's keyboard
     would have had to fall back to. */
  TypeText(text) {
    const chars = [...String(text).slice(0, MAX_TYPE_CHARS)];
    this._typeNext(chars, 0);
  }

  _typeNext(chars, index) {
    if (index >= chars.length) return;
    const source = GLib.timeout_add(GLib.PRIORITY_DEFAULT, TYPE_GAP_MS, () => {
      this._timeouts.delete(source);
      const keyval = Clutter.unicode_to_keyval(chars[index].codePointAt(0));
      if (keyval) {
        const vd = this._keyboard();
        const t = this._now();
        vd.notify_keyval(t, keyval, Clutter.KeyState.PRESSED);
        vd.notify_keyval(t, keyval, Clutter.KeyState.RELEASED);
      }
      this._typeNext(chars, index + 1);
      return GLib.SOURCE_REMOVE;
    });
    this._timeouts.add(source);
  }

  /* SendKeys without the window: chords go wherever focus already is. This is
     what a presentation remote needs -- the user is looking at their slides,
     and raising a window to type into it would drop them out of full screen. */
  Keys(keys) {
    const chords = keys
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    this._sendChord(chords, 0, 0);
  }

  /* Focus a window, then type a comma-separated list of chords into it.
     "alt+3" jumps Firefox to its third tab; "alt+3,ctrl+w" closes that tab. */
  SendKeys(id, keys) {
    const meta = this._findWindow(id);
    if (!meta) return;

    if (meta.minimized) meta.unminimize();
    meta.activate(global.get_current_time());

    const chords = keys
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    this._sendChord(chords, 0, FOCUS_SETTLE_MS);
  }

  _sendChord(chords, index, delay) {
    if (index >= chords.length) return;
    const source = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
      this._timeouts.delete(source);
      this._tap(chords[index]);
      this._sendChord(chords, index + 1, KEY_GAP_MS);
      return GLib.SOURCE_REMOVE;
    });
    this._timeouts.add(source);
  }

  _keyval(name) {
    if (name.length === 1) {
      // X11 keysyms coincide with ASCII for printable characters, so a single
      // character is already its own keyval.
      return name.charCodeAt(0);
    }
    return NAMED_KEYS[name];
  }

  _tap(chord) {
    const parts = chord.toLowerCase().split("+").map((s) => s.trim());
    const key = parts.pop();
    const keyval = this._keyval(key);
    if (keyval === undefined) {
      logError(new Error(`VoiceTalk: unknown key "${key}" in chord "${chord}"`));
      return;
    }

    const mods = [];
    for (const part of parts) {
      const mod = MODIFIERS[part];
      if (mod === undefined) {
        logError(new Error(`VoiceTalk: unknown modifier "${part}"`));
        return;
      }
      mods.push(mod);
    }

    const vd = this._keyboard();
    const t = this._now();

    for (const mod of mods) vd.notify_keyval(t, mod, Clutter.KeyState.PRESSED);
    vd.notify_keyval(t, keyval, Clutter.KeyState.PRESSED);
    vd.notify_keyval(t, keyval, Clutter.KeyState.RELEASED);
    // Release modifiers in reverse, so a stuck key cannot outlive its chord.
    for (const mod of mods.reverse())
      vd.notify_keyval(t, mod, Clutter.KeyState.RELEASED);
  }
}

export default class VoiceTalkExtension extends Extension {
  enable() {
    this._service = new VoiceTalkDBusImpl();

    // Export first, then claim the name -- a client that races us on the
    // NameOwnerChanged signal must never find the name owned but the object
    // path empty.
    this._service._impl.export(
      Gio.DBus.session,
      "/org/gnome/Shell/Extensions/VoiceTalk"
    );

    this._nameId = Gio.bus_own_name_on_connection(
      Gio.DBus.session,
      "org.gnome.Shell.Extensions.VoiceTalk",
      Gio.BusNameOwnerFlags.NONE,
      null,
      null
    );
  }

  disable() {
    if (this._nameId) {
      Gio.bus_unown_name(this._nameId);
      this._nameId = null;
    }
    if (this._service) {
      this._service._impl.unexport();
      this._service.destroy();
      this._service = null;
    }
  }
}
