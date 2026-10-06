"""Small helpers shared by all modules."""
from qgis.core import Qgis, QgsMessageLog

TAG = "Evidence Mapper"


def log(message, level=None):
    """Write a non-fatal problem to the QGIS log panel (View > Panels > Log Messages)."""
    QgsMessageLog.logMessage(str(message), TAG, Qgis.MessageLevel.Warning if level is None else level)
