"""Distance-attenuated SFX + alien-fire helpers.

Extracted from ``update_logic.py`` so the spatial-audio dispatch
sits in its own module.  Every helper takes ``gv`` as its first
argument (matching the rest of update_logic) so the original
public signatures are preserved when re-exported.

The sound-player tracking + ``arcade.play_sound`` monkey-patch
stay in ``update_logic.py`` itself — they run at module load time
and changing the load order risks the FPS-regression backstop in
``_tracked_play_sound``.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import arcade

if TYPE_CHECKING:
    from game_view import GameView


# Throttle: the alien-laser SFX (and the missile-launch variant)
# can fire dozens of times per second during a swarm; without a
# global cooldown they pile into a wall of audio that distorts
# the mix and burns Player allocations.
_ALIEN_LASER_SND_INTERVAL: float = 0.12  # max one play per ~120 ms


def play_sfx_at(
    gv: "GameView",
    snd,
    x: float,
    y: float,
    base_volume: float = 1.0,
) -> None:
    """Play an in-world SFX with linear distance attenuation toward
    the player.  Sounds further than ``SOUND_HEARING_RADIUS`` away
    are silenced entirely (no media player created).  Inside the
    radius the volume scales as ``base_volume * (1 - d / radius)``.

    UI sounds (button clicks, menu confirms, music) should bypass
    this helper and call ``arcade.play_sound`` directly — they have
    no spatial source and the user expects them at full slider
    volume.

    ``snd is None`` is a no-op (safe for soak-test stubs)."""
    from constants import SOUND_HEARING_RADIUS
    if snd is None:
        return
    player = getattr(gv, "player", None)
    if player is None:
        # No spatial reference — fall back to unattenuated play so
        # things like the death-screen explosion still register.
        arcade.play_sound(snd, volume=base_volume)
        return
    d = math.hypot(x - player.center_x, y - player.center_y)
    if d >= SOUND_HEARING_RADIUS:
        return
    falloff = 1.0 - d / SOUND_HEARING_RADIUS
    arcade.play_sound(snd, volume=base_volume * falloff)


def _nearest_alien_to_player(gv: "GameView") -> tuple[float, float] | None:
    """Return the (x, y) of the alien closest to the player so the
    throttled alien-laser SFX falls off from the most-likely-fired
    source.  Walks the active zone's alien lists; returns ``None``
    if no aliens are present."""
    player = getattr(gv, "player", None)
    if player is None:
        return None
    px, py = player.center_x, player.center_y
    best = None
    best_d2 = float("inf")
    seen: set[int] = set()

    def _candidates():
        for a in (getattr(gv, "alien_list", None) or []):
            yield a
        zone = getattr(gv, "_zone", None)
        if zone is not None and hasattr(zone, "iter_enemies"):
            yield from zone.iter_enemies()

    for a in _candidates():
        aid = id(a)
        if aid in seen:
            continue
        seen.add(aid)
        d2 = (a.center_x - px) ** 2 + (a.center_y - py) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best = (a.center_x, a.center_y)
    return best


def _play_throttled_alien_sfx(
    gv: "GameView", snd_attr: str, base_mult: float,
) -> None:
    """Shared body for ``play_alien_laser_sound`` +
    ``play_missile_launch_sound`` — both share the same throttle
    counter (so total alien audio output stays bounded) and the
    same nearest-alien spatial source.  Differ only in WHICH sound
    they play and the per-source volume mix."""
    snd = getattr(gv, snd_attr, None)
    if snd is None:
        return
    if getattr(gv, "_alien_laser_snd_cd", 0.0) > 0.0:
        return
    gv._alien_laser_snd_cd = _ALIEN_LASER_SND_INTERVAL
    pos = _nearest_alien_to_player(gv)
    if pos is None:
        return
    from settings import audio
    play_sfx_at(gv, snd, pos[0], pos[1],
                base_volume=audio.sfx_volume * base_mult)


def play_alien_laser_sound(gv: "GameView") -> None:
    """Play the alien-laser fire SFX with a global throttle (so
    dozens of simultaneous shots don't pile into a wall of audio)
    AND distance attenuation toward the player.  The throttle
    counter decays via ``update_timers``."""
    _play_throttled_alien_sfx(gv, "_alien_laser_snd", 0.4)


def play_missile_launch_sound(gv: "GameView") -> None:
    """Play the player's missile-launch SFX (used for stalker fires)
    with the same global throttle + distance attenuation the alien
    laser uses.  Distance is measured from the nearest alien-side
    sprite, so a stalker volley far from the player drops in volume
    instead of blasting at full slider level."""
    _play_throttled_alien_sfx(gv, "_missile_launch_snd", 0.5)


def emit_alien_shots(
    gv: "GameView", projectile_list, fired, *,
    use_missile_sound: bool = False,
) -> None:
    """Append every projectile in ``fired`` (a list, possibly empty,
    or a single projectile) to ``projectile_list`` and trigger one
    throttled fire SFX.  Skips both the append loop and the SFX
    when ``fired`` is falsy.

    Replaces the four-line ``if fired: for p in fired: list.append;
    play_alien_laser_sound(gv)`` pattern that was open-coded at five
    sites across update_logic + zone2 + star_maze.  Stalker-style
    callers pass ``use_missile_sound=True`` for the missile-launch
    SFX variant."""
    if not fired:
        return
    if isinstance(fired, list):
        for p in fired:
            projectile_list.append(p)
    else:
        projectile_list.append(fired)
    if use_missile_sound:
        play_missile_launch_sound(gv)
    else:
        play_alien_laser_sound(gv)
