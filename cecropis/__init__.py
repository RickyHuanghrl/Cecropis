"""Cecropis: local connectome exploration and intervention analysis."""
MODEL_VERSION = 'bounded-propagation-v1'
__all__ = ['MODEL_VERSION', 'Lab', 'Workspace']


def __getattr__(name):
    # Keep importing the root lightweight for preparation and CLI help.
    if name in {'Lab', 'Workspace'}:
        from . import api
        return getattr(api, name)
    raise AttributeError(name)
