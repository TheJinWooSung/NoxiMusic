from .automation import CallAutomationMixin
from .base import CallBase
from .controls import CallControlsMixin
from .lifecycle import CallLifecycleMixin
from .playback import CallPlaybackMixin


class Call(
    CallControlsMixin,
    CallPlaybackMixin,
    CallAutomationMixin,
    CallLifecycleMixin,
    CallBase,
):
    pass


__all__ = ["Call"]
