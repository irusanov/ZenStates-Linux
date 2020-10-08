import gi
import config as cfg

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

builder = Gtk.Builder()
builder.add_from_file("gtk.glade")

oc_mode_checkbox = builder.get_object("ocModeCheckbox")
frequency_input = builder.get_object("frequencyInput")
voltage_input = builder.get_object("voltageInput")

class App:
    def init_values():
        _oc_mode = getOcMode()
        if _oc_mode:
            _default_vid = getCurrentVid()
            _ratio = getRatio(0xC0010293)
        else:
            _default_vid = getPstateVid(0)
            _ratio = getRatio(PSTATES[0])

        _current_freq = int(_ratio * 100)
        _current_voltage = vidToVolts(_default_vid)

        oc_mode_checkbox.set_active(_oc_mode)
        frequency_input.set_value(_current_freq)
        voltage_input.set_value(_current_voltage)


class Handler:
    def onDestroy(self, *args):
        Gtk.main_quit()

    def onRefreshButtonClicked(self):
        App.init_values()

builder.connect_signals(Handler)

App.init_values()

window = builder.get_object("appWindow")
window.set_title(cfg.APP_NAME + " v" + cfg.APP_VERSION);
window.show_all()

Gtk.main()
