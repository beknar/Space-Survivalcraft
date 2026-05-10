"""Self-contained ``_BaseDrone`` per-frame helpers.

Extracted from ``sprites.drone_base`` in the 2026-05-10 split.  Each
helper takes the drone instance as the first argument and operates
on its instance state directly.  ``_BaseDrone`` retains one-line
delegate methods for every helper so external callers + subclasses
keep using the existing
``drone._apply_asteroid_pushout(...) /
``drone._track_stuck_progress(...)`` style call sites unchanged.

The full ``follow`` / ``_run_return_home`` / ``_update_mode``
methods were intentionally left in the class -- they reach into
many instance fields through chained method calls (planner state,
slot picker, heading, mode machine), so the round-trip through
delegate calls would dilute the readability without saving lines.
"""
from __future__ import annotations

import math

from constants import (
    DRONE_MAX_SPEED, DRONE_FIRE_COOLDOWN,
    DRONE_LASER_RANGE, DRONE_LASER_SPEED,
)


def apply_asteroid_pushout(drone, asteroids) -> bool:
    """Push the drone out of any asteroid it overlaps after a
    movement tick.  Returns True iff a push fired this frame."""
    if not asteroids:
        return False
    from constants import ASTEROID_RADIUS
    moved = False
    r_total = drone.radius + ASTEROID_RADIUS + drone._ASTEROID_PUSH_PAD
    r_total_sq = r_total * r_total
    for a in asteroids:
        dx = drone.center_x - a.center_x
        dy = drone.center_y - a.center_y
        d2 = dx * dx + dy * dy
        if d2 >= r_total_sq or d2 == 0.0:
            continue
        d = math.sqrt(d2)
        nx = dx / d
        ny = dy / d
        pen = r_total - d
        drone.center_x += nx * pen
        drone.center_y += ny * pen
        moved = True
    return moved


def asteroid_avoidance(
    drone, asteroids, base_x: float, base_y: float,
) -> tuple[float, float]:
    """Return a steering vector blending the desired ``(base_x,
    base_y)`` direction with a soft repulsion away from nearby
    asteroids."""
    if not asteroids:
        return (base_x, base_y)
    from constants import ASTEROID_RADIUS
    thresh = (drone.radius + ASTEROID_RADIUS
              + drone._ASTEROID_AVOID_RADIUS)
    thresh_sq = thresh * thresh
    sx, sy = base_x, base_y
    for a in asteroids:
        dx = drone.center_x - a.center_x
        dy = drone.center_y - a.center_y
        d2 = dx * dx + dy * dy
        if d2 >= thresh_sq or d2 == 0.0:
            continue
        d = math.sqrt(d2)
        w = 1.0 - d / thresh
        sx += (dx / d) * w
        sy += (dy / d) * w
    mag = math.hypot(sx, sy)
    if mag < 0.001:
        return (base_x, base_y)
    return (sx / mag, sy / mag)


def try_unstick_nudge(
    drone, dt: float, target_x: float, target_y: float,
) -> bool:
    """Safety-net nudge.  When the drone hasn't physically moved
    more than ``_NUDGE_DIST`` over ``_NUDGE_TIME`` seconds while
    trying to steer toward the target, slide one frame's worth of
    motion perpendicular to the steering direction so a wall-corner
    wedge can pop free.  Returns True iff a nudge fired this frame."""
    if drone._nudge_anchor_x is None:
        drone._nudge_anchor_x = drone.center_x
        drone._nudge_anchor_y = drone.center_y
        drone._nudge_timer = 0.0
        drone._nudge_dir = (
            drone._nudge_dir if drone._nudge_dir != 0.0
            else 1.0)
        return False
    moved_sq = (
        (drone.center_x - drone._nudge_anchor_x) ** 2
        + (drone.center_y - drone._nudge_anchor_y) ** 2
    )
    if moved_sq >= drone._NUDGE_DIST * drone._NUDGE_DIST:
        drone._nudge_anchor_x = drone.center_x
        drone._nudge_anchor_y = drone.center_y
        drone._nudge_timer = 0.0
        return False
    drone._nudge_timer += dt
    if drone._nudge_timer < drone._NUDGE_TIME:
        return False
    dx = target_x - drone.center_x
    dy = target_y - drone.center_y
    d = math.hypot(dx, dy)
    if d <= 0.001:
        drone._nudge_timer = 0.0
        return False
    nx = dx / d
    ny = dy / d
    side = drone._nudge_dir
    px = ny * side
    py = -nx * side
    step = drone._NUDGE_IMPULSE * dt
    max_step = DRONE_MAX_SPEED * dt
    if step > max_step:
        step = max_step
    drone.center_x += px * step
    drone.center_y += py * step
    drone._nudge_dir = -side
    drone._nudge_anchor_x = drone.center_x
    drone._nudge_anchor_y = drone.center_y
    drone._nudge_timer = 0.0
    return True


def track_stuck_progress(drone, dt: float, target) -> bool:
    """Return True when the drone is stuck on this target -- same
    target in sight for >= 5 s with no HP loss.  Caller should
    drop the target and enter the follow-only cooldown."""
    if target is None:
        drone._stuck_target = None
        drone._target_acquired_timer = 0.0
        return False
    if target is not drone._stuck_target:
        drone._stuck_target = target
        drone._stuck_target_hp = int(getattr(target, "hp", 0))
        drone._target_acquired_timer = 0.0
        return False
    cur_hp = int(getattr(target, "hp", 0))
    if cur_hp < drone._stuck_target_hp:
        drone._stuck_target_hp = cur_hp
        drone._target_acquired_timer = 0.0
        return False
    drone._target_acquired_timer += dt
    if drone._target_acquired_timer >= 5.0:
        drone._target_acquired_timer = 0.0
        drone._target_cooldown = 5.0
        drone._stuck_target = None
        return True
    return False


def aim_and_fire(drone, target_x: float, target_y: float):
    """Spawn one Projectile aimed at ``(target_x, target_y)`` if
    off cooldown; returns the projectile (or ``None``).  Caller
    appends it to the projectile list."""
    if drone._fire_cd > 0.0:
        return None
    dx = target_x - drone.center_x
    dy = target_y - drone.center_y
    dist = math.hypot(dx, dy)
    if dist > DRONE_LASER_RANGE or dist <= 0.001:
        return None
    heading = math.degrees(math.atan2(dx, dy)) % 360.0
    drone._fire_cd = DRONE_FIRE_COOLDOWN
    drone._heading = heading
    drone.angle = heading
    if drone._fire_snd is not None:
        import arcade
        from settings import audio
        arcade.play_sound(drone._fire_snd,
                          volume=audio.sfx_volume * 0.4)
    from sprites.projectile import Projectile
    return Projectile(
        drone._laser_tex,
        drone.center_x, drone.center_y,
        heading,
        DRONE_LASER_SPEED, DRONE_LASER_RANGE,
        scale=0.5,
        mines_rock=drone._mines_rock,
        damage=drone._laser_damage,
    )
