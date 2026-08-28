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
  </interface>
</node>
`;

// Raising a window is asynchronous: the client has to process the focus change
// before it will act on input. Keys sent too early land in the previously
// focused app -- which, for Ctrl+W, closes the wrong thing.
const FOCUS_SETTLE_MS = 150;
// Firefox drops keys sent faster than it repaints between them.
const KEY_GAP_MS = 60;

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
};

class VoiceTalkDBusImpl {
  constructor() {
    this._impl = Gio.DBusExportedObject.wrapJSObject(VoiceTalkIface, this);
    this._virtualDevice = null;
    this._timeouts = new Set();
  }

  destroy() {
    // Any pending keystroke would fire into a shell that no longer has this
    // extension loaded, so drop the sources rather than let them run.
    for (const id of this._timeouts) GLib.Source.remove(id);
    this._timeouts.clear();
    this._virtualDevice = null;
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

    if (!this._virtualDevice) {
      const seat = Clutter.get_default_backend().get_default_seat();
      this._virtualDevice = seat.create_virtual_device(
        Clutter.InputDeviceType.KEYBOARD_DEVICE
      );
    }

    const vd = this._virtualDevice;
    // notify_keyval takes microseconds; get_current_event_time is milliseconds.
    const t = Clutter.get_current_event_time() * 1000;

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
