"""Sound-player tracking + cleanup helpers extracted from update_logic.

arcade.play_sound() returns a pyglet.media.Player. Pyglet's internal
event system holds a strong reference to every Player, and Player.playing
stays True even AFTER the source is exhausted. So finished players are
never freed -- even by gc.collect(). Over minutes of continuous combat,
hundreds of dead Players accumulate and degrade FPS.

Fix: track each player with a creation timestamp, then .delete() any
player older than _SOUND_MAX_AGE seconds. All game SFX are < 2 s long,
so 3 s is a safe upper bound.

Module layout: this file owns the tracking globals (``_sound_players``,
``_SOUND_MAX_AGE``, ``_SOUND_HARD_CAP``, ``_MAX_DELETES_PER_TICK``) and
the two functions that read/write them (``_tracked_play_sound``,
``_cleanup_finished_sounds``).  The monkey-patch of ``arcade.play_sound``
also runs here at import time so any module importing this (directly or
via update_logic) gets the tracking behaviour.
"""
from __future__ import annotations

import time as _time

import arcade


# ── Sound player cleanup ──────────────────────────────────────────────────
# arcade.play_sound() returns a pyglet.media.Player. Pyglet's internal
# event system holds a strong reference to every Player, and Player.playing
# stays True even AFTER the source is exhausted. So finished players are
# never freed — even by gc.collect(). Over minutes of continuous combat,
# hundreds of dead Players accumulate and degrade FPS.
#
# Fix: track each player with a creation timestamp, then .delete() any
# player older than _SOUND_MAX_AGE seconds. All game SFX are < 2 s long,
# so 3 s is a safe upper bound.

_SOUND_MAX_AGE = 3.0  # seconds — all game SFX finish within this
_sound_players: list[tuple[float, object]] = []  # (creation_time, Player)

_real_play_sound = arcade.play_sound


# ═══ GC + sound cleanup ═══════════════════════════════════════════════════


_SOUND_HARD_CAP = 200  # backlog ceiling — see _tracked_play_sound below


def _tracked_play_sound(*args, **kwargs):
    """Wrapper around arcade.play_sound that tracks the returned Player
    with a creation timestamp.

    Hard cap: if ``_sound_players`` already holds ``_SOUND_HARD_CAP``
    entries, evict + ``.delete()`` the OLDEST one synchronously before
    appending the new player.  This bounds the list's worst-case
    length even when the periodic ``_cleanup_finished_sounds`` timer
    can't keep up (e.g. tests that run the update loop faster than
    real time, where the wall-clock ``_SOUND_MAX_AGE`` check sees
    every entry as still-fresh).  Without the cap, sustained combat
    soaks let the list grow into the thousands and pyglet's per-frame
    Player iteration collapsed FPS from 75 → 2 (Boss-soak regression
    confirmed 2026-04-25).

    Exception shield: ``arcade.play_sound`` can raise when pyglet's
    audio backend fails (resource exhaustion, missing audio device,
    failed decode) — and arcade's own warning-log path has a
    ``%``-format bug that turns the original failure into a confusing
    TypeError ("not all arguments converted during string formatting").
    Caught from 2026-05-05 full-suite cycle: random GameView-creating
    tests crashed mid-init when the 1700+-test run exhausted the
    audio backend.  Treat any exception the same as ``play_sound``
    already does for a missing/None sound — return None.  Existing
    callers already handle None returns."""
    if len(_sound_players) >= _SOUND_HARD_CAP:
        _, oldest = _sound_players.pop(0)
        try:
            oldest.delete()
        except Exception:
            pass
    try:
        player = _real_play_sound(*args, **kwargs)
    except Exception:
        return None
    if player is not None:
        _sound_players.append((_time.perf_counter(), player))
    return player


# Monkey-patch arcade.play_sound at module load time
arcade.play_sound = _tracked_play_sound


_MAX_DELETES_PER_TICK = 4  # spread pyglet Player.delete over frames


def _cleanup_finished_sounds() -> None:
    """Delete pyglet Players older than ``_SOUND_MAX_AGE`` seconds.

    ``Player.delete`` releases native OpenAL + FFmpeg resources and
    can stall 20–40 ms each — with 10+ stale players piling up
    during a combat burst, the original "delete everything at once"
    pass caused the 150–200 ms mid-session spikes seen in
    fps_drops.log.

    But rate-limiting to 4 deletes per 5-s tick falls *catastrophically*
    behind sustained combat: 30 aliens at 60 fps generate ~5 sound
    players/sec, but we'd only delete 4 every 5 s = 0.8/sec, leaving
    +4 players/sec of permanent backlog.  Pyglet's clock then iterates
    every live (or dead-but-not-deleted) Player on every frame, so a
    boss-soak that ran 90 s of combat saw the backlog hit 481 players
    and FPS collapse from 75 → 20 → 2 (measured 2026-04-25).

    Fix: scale deletes-per-tick with the current backlog so the
    delete rate always matches or exceeds the creation rate.  At
    backlog ≤ 30 we keep the original 4/tick budget (stays cheap when
    nothing's wrong); above that we accelerate up to 32/tick, which
    is still well under the 150 ms spike threshold (32 × 30 ms / 5 s
    ≈ 0.96 s, spread across many frames since cleanup runs only once
    per 5-s tick).
    """
    now = _time.perf_counter()
    backlog = len(_sound_players)
    if backlog > 100:
        deletes_remaining = 32
    elif backlog > 30:
        deletes_remaining = 12
    else:
        deletes_remaining = _MAX_DELETES_PER_TICK
    alive: list[tuple[float, object]] = []
    for created_at, p in _sound_players:
        if now - created_at < _SOUND_MAX_AGE or deletes_remaining <= 0:
            alive.append((created_at, p))
        else:
            deletes_remaining -= 1
            try:
                p.delete()
            except Exception:
                pass
    _sound_players.clear()
    _sound_players.extend(alive)
