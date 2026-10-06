import os
import webbrowser

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
MENU = "&Evidence Mapper"


class EvidenceMapperPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.wizard = None

    def _add(self, text, callback, icon=None, toolbar=False):
        act = QAction(QIcon(icon) if icon else QIcon(), text, self.iface.mainWindow())
        act.triggered.connect(callback)
        self.iface.addPluginToMenu(MENU, act)
        if toolbar:
            self.iface.addToolBarIcon(act)
        self.actions.append((act, toolbar))
        return act

    def initGui(self):
        icon = os.path.join(PLUGIN_DIR, "icon.png")
        self._add("Create study distribution map…", self.run, icon, toolbar=True)
        self._add("Open sample data folder", self.open_samples)
        self._add("Help / documentation", self.open_help)
        self._add("About", self.about)

    def unload(self):
        for act, tb in self.actions:
            self.iface.removePluginMenu(MENU, act)
            if tb:
                self.iface.removeToolBarIcon(act)
        self.actions = []

    def run(self):
        try:
            from .gui.wizard import EvidenceWizard
            self.wizard = EvidenceWizard(self.iface)
            self.wizard.exec_()
        except Exception as exc:
            import traceback
            box = QMessageBox(self.iface.mainWindow())
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle("Evidence Mapper")
            box.setText("Evidence Mapper could not start: %s" % exc)
            box.setDetailedText(traceback.format_exc())
            box.exec_()

    def open_samples(self):
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(PLUGIN_DIR, "sample_data")))

    def open_help(self):
        webbrowser.open("file:///" + os.path.join(PLUGIN_DIR, "help", "index.html").replace("\\", "/"))

    def about(self):
        QMessageBox.about(self.iface.mainWindow(), "Evidence Mapper",
                          "<b>Evidence Mapper</b><br>Publication-ready study-distribution maps for "
                          "literature reviews, systematic reviews and evidence-gap maps.<br><br>"
                          "Boundaries: Natural Earth (public domain). Geocoding: OpenStreetMap Nominatim. "
                          "Basemaps © their respective providers.<br>Licence: GPL-2.0-or-later.")
