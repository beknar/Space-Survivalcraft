"""Global audio settings for Space Survivalcraft.

Runtime-mutable volume levels shared across all views.
"""
from __future__ import annotations


class AudioSettings:
    """Singleton-like container for volume levels."""

    def __init__(self) -> None:
        self.music_volume: float = 0.35   # 0.0 – 1.0
        self.sfx_volume: float = 0.60     # 0.0 – 1.0


# Module-level instance used everywhere
audio = AudioSettings()
