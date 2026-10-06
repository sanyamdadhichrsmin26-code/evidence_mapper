def classFactory(iface):
    from .plugin import EvidenceMapperPlugin
    return EvidenceMapperPlugin(iface)
