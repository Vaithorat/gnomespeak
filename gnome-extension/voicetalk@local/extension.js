/* Window control extension for GNOME Shell 45+.

   Exports a D-Bus interface on org.gnome.Shell.Extensions.VoiceTalk
   that lists open windows and allows focusing/closing them.
*/

import Gio from "gi://Gio";
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
  </interface>
</node>
`;

class VoiceTalkDBusImpl {
  constructor() {
    this._impl = Gio.DBusExportedObject.wrapJSObject(VoiceTalkIface, this);
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
      });
    }

    return JSON.stringify(windows);
  }

  Focus(id) {
    const workspace = global.workspace_manager.get_active_workspace();
    for (const w of global.get_window_actors()) {
      const meta = w.get_meta_window();
      if (meta && meta.get_stable_sequence() === id) {
        meta.activate(global.get_current_time());
        return;
      }
    }
  }

  Close(id) {
    for (const w of global.get_window_actors()) {
      const meta = w.get_meta_window();
      if (meta && meta.get_stable_sequence() === id) {
        meta.delete(global.get_current_time());
        return;
      }
    }
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
      this._service = null;
    }
  }
}
