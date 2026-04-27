"""Companion drones — mining + combat variants.

Both drones follow the player at a small rotating offset (orbits when
the player is stationary, trails when the player moves) and fire
projectiles into ``gv.projectile_list`` so the existing player-
projectile collision pipelines deliver damage.

- ``MiningDrone`` (75 HP, 0 shield, no shield render) targets the
  nearest asteroid within ``MINING_DRONE_MINING_RANGE`` and fires
  mining-beam projectiles (``mines_rock=True``, 20 HP per hit).  In
  addition, it vacuums any iron / blueprint pickup within
  ``MINING_DRONE_PICKUP_RADIUS`` by force-flagging them ``_flying``
  so the standard fly-to-player loop carries them home.
- ``CombatDrone`` (75 HP, 25 shield, ShieldedAlien-style arc render
  while shielded) targets the nearest live alien / boss within
  ``DRONE_DETECT_RANGE`` and fires combat-laser projectiles
  (``mines_rock=False``, 35 HP per hit).

Only one drone may be deployed at a time.  ``combat_helpers.deploy_drone``
enforces that contract — pressing R again with the same active weapon
is a no-op (no consumable charged), pressing R after switching weapons
swaps the active drone for the matching type.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import arcade

from constants import (
    DRONE_HP, MINING_DRONE_SHIELD, COMBAT_DRONE_SHIELD,
    DRONE_MAX_SPEED, DRONE_FOLLOW_DIST, DRONE_ORBIT_SPEED,
    DRONE_FIRE_COOLDOWN, DRONE_DETECT_RANGE,
    DRONE_BREAK_OFF_DIST,
    DRONE_LASER_RANGE, DRONE_LASER_SPEED,
    MINING_DRONE_LASER_DAMAGE, COMBAT_DRONE_LASER_DAMAGE,
    DRONE_SCALE, DRONE_RADIUS,
    MINING_DRONE_PICKUP_RADIUS, MINING_DRONE_MINING_RANGE,
    MINING_DRONE_PNG, COMBAT_DRONE_PNG,
    SFX_MINING_DRONE_LASER, SFX_COMBAT_DRONE_LASER,
)
from settings import audio
from sprites.projectile import Projectile

if TYPE_CHECKING:
    from game_view import GameView


# Module-level texture cache so each PNG decode happens once per game
# run regardless of how many times the player redeploys a drone.
_TEX_CACHE: dict[str, arcade.Texture] = {}
_SND_CACHE: dict[str, arcade.Sound] = {}


def _load(path: str) -> arcade.Texture:
    tex = _TEX_CACHE.get(path)
    if tex is None:
        tex = arcade.load_texture(path)
        _TEX_CACHE[path] = tex
    return tex


def _load_snd(path: str) -> arcade.Sound:
    snd = _SND_CACHE.get(path)
    if snd is None:
        snd = arcade.load_sound(path)
        _SND_CACHE[path] = snd
    return snd


def _segment_crosses_any_wall(
    ax: float, ay: float, bx: float, by: float,
    walls: list | None,
    samples: tuple[float, ...] = (0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0),
) -> bool:
    """Sample-and-test wall blocker check shared between the slot
    picker (short ≤80 px legs) and the line-of-sight check (longer
    drone-to-enemy legs up to 600 px).  ``samples`` should grow with
    segment length — the default 7-point grid resolves down to ~30 px
    along a 600 px segment, smaller than the maze wall thickness so
    no diagonal can sneak through."""
    if not walls:
        return False
    for t in samples:
        x = ax + (bx - ax) * t
        y = ay + (by - ay) * t
        for w in walls:
            wx, wy, ww, wh = w[0], w[1], w[2], w[3]
            if wx <= x <= wx + ww and wy <= y <= wy + wh:
                return True
    return False


def _walls_from_zone(gv) -> list | None:
    """Return the active zone's wall-rect list, or None if the zone
    doesn't have one (open zones — Zone 1, Zone 2 outside the
    nebula).  Star Maze stores a list of named-tuple ``Rect``s with
    ``.x/.y/.w/.h``; the slot-block test indexes them positionally,
    so any 4-tuple-like sequence works."""
    zone = getattr(gv, "_zone", None)
    if zone is None:
        return None
    return getattr(zone, "_walls", None)


class _BaseDrone(arcade.Sprite):
    """Common follow / attack / damage / shield state for both drones.

    Mode machine (per spec, 2026-04-26):

      * ``_MODE_FOLLOW`` (default) — drone trails the player at one of
        three fixed slots: LEFT (perpendicular-left of heading), RIGHT
        (perpendicular-right), BACK (opposite heading).  Picks LEFT
        first, falls back to RIGHT or BACK if its preferred slot is
        blocked by maze geometry.

      * ``_MODE_ATTACK`` — entered when a target is detected within
        ``DRONE_DETECT_RANGE``.  The drone holds station and fires
        instead of trying to keep up with the player.  Switches back
        to FOLLOW when the player drifts past ``DRONE_BREAK_OFF_DIST``
        away or the target dies / leaves range.

      * ``_MODE_RETURN_HOME`` — entered when the player is more than
        ``DRONE_BREAK_OFF_DIST`` (800 px) away.  The drone ignores
        every enemy, runs the WaypointPlanner's A* room-graph search
        toward the player, and never enters the planner's 5-s freeze
        cooldown — if a plan attempt fails the cooldown is wiped and
        the drone immediately re-tries on the next frame.  Exits to
        FOLLOW once the drone closes back inside the 600-px hysteresis
        threshold so it doesn't ping-pong at exactly 800 px.
    """

    _LABEL: str = "Drone"

    _MODE_FOLLOW = 0
    _MODE_ATTACK = 1
    _MODE_RETURN_HOME = 2
    _SLOT_LEFT = 0
    _SLOT_RIGHT = 1
    _SLOT_BACK = 2

    # Once a drone enters RETURN_HOME at >800 px away, it stays in
    # RETURN_HOME until it's reeled back inside this radius — keeps
    # the mode flag from oscillating at exactly the break-off line.
    _RETURN_HOME_EXIT_DIST = 600.0

    def __init__(
        self,
        sprite_path: str,
        laser_tex: arcade.Texture,
        x: float, y: float,
        *,
        shield: int,
        laser_damage: float,
        mines_rock: bool,
        fire_snd: arcade.Sound | None = None,
    ) -> None:
        super().__init__(path_or_texture=_load(sprite_path),
                         scale=DRONE_SCALE)
        self.center_x = x
        self.center_y = y
        self.hp: int = DRONE_HP
        self.max_hp: int = DRONE_HP
        self.shields: int = shield
        self.max_shields: int = shield
        self.radius: float = DRONE_RADIUS
        # Legacy field kept for save-compat / shield-arc rotation.
        # The follow logic no longer uses orbit motion (slot-based now).
        self._orbit_angle: float = random.uniform(0.0, 360.0)
        # FOLLOW vs ATTACK state.  Drone defaults to FOLLOW; flips to
        # ATTACK when a target appears in range and the player is
        # within DRONE_BREAK_OFF_DIST.
        self._mode: int = self._MODE_FOLLOW
        # Last picked follow slot — sticky so the drone doesn't ping-
        # pong between LEFT and RIGHT every frame when both are clear.
        self._slot: int = self._SLOT_LEFT
        self._fire_cd: float = 0.0
        self._hit_timer: float = 0.0
        self._shield_angle: float = 0.0
        self._laser_tex: arcade.Texture = laser_tex
        self._laser_damage: float = laser_damage
        self._mines_rock: bool = mines_rock
        self._fire_snd: arcade.Sound | None = fire_snd
        # Computed each frame — used by the fire path and the alien
        # AI / collisions to know "which way is forward" for muzzle.
        self._heading: float = 0.0
        self.angle = 0.0
        # Stuck-on-target detection — if the drone has had the same
        # live target in sight for >5 s without making any progress
        # (target HP unchanged, drone physically not closing the
        # distance — typically a wall is blocking the shot or the
        # drone is wedged), abandon the target and just follow the
        # player for a cooldown window so it doesn't grind on
        # geometry forever.
        self._target_acquired_timer: float = 0.0
        self._target_cooldown: float = 0.0
        self._stuck_target = None
        self._stuck_target_hp: int = 0
        # Pathfinder routing the drone toward the player when an
        # orbit position lands across a wall (Star Maze only — the
        # zone hands the rooms+graph to ``update_drone`` via the gv
        # helper).  Defaults to a no-op planner; replaced lazily on
        # first call to ``follow`` once the active zone exposes its
        # geometry.  When the planner gives up (5 s without movement
        # toward the player) the drone freezes in place via the
        # existing ``_target_cooldown`` for the planner's COOLDOWN
        # window — exact same treatment as a stuck weapon target.
        from zones.maze_geometry import WaypointPlanner
        self._follow_planner: WaypointPlanner = WaypointPlanner(None, None)
        self._follow_planner_geom_id: int = 0
        # Latched flag for "drone is currently routing through a
        # waypoint, not the orbit position" so the firing path knows
        # not to fire across a wall (heading would face the waypoint,
        # not the enemy).
        self._routing_to_waypoint: bool = False
        # Shield regen accumulator (fractional shield points carry
        # across frames; integer ``shields`` is bumped when ≥ 1.0).
        self._shield_regen_acc: float = 0.0

    # ── Damage ───────────────────────────────────────────────────────

    def take_damage(self, amount: int) -> None:
        if self.shields > 0:
            absorbed = min(self.shields, amount)
            self.shields -= absorbed
            amount -= absorbed
        if amount > 0:
            self.hp -= amount
        self._hit_timer = 0.15

    @property
    def dead(self) -> bool:
        return self.hp <= 0

    # ── Per-frame update ─────────────────────────────────────────────

    def _slot_position(
        self, slot: int, player_x: float, player_y: float,
        player_heading: float,
    ) -> tuple[float, float]:
        """Return the world-space (x, y) of one of the three follow
        slots relative to the player, oriented to player's heading.

        Heading convention is CW-positive compass (sin, cos forward) —
        same as PlayerShip.  LEFT = perpendicular-left of heading,
        RIGHT = perpendicular-right, BACK = opposite-forward.
        """
        rad = math.radians(player_heading)
        s, c = math.sin(rad), math.cos(rad)
        d = DRONE_FOLLOW_DIST
        if slot == self._SLOT_LEFT:
            return (player_x - c * d, player_y + s * d)
        if slot == self._SLOT_RIGHT:
            return (player_x + c * d, player_y - s * d)
        # BACK
        return (player_x - s * d, player_y - c * d)

    def _slot_blocked(
        self, sx: float, sy: float,
        px: float, py: float,
        walls: list | None,
    ) -> bool:
        """True if the segment from (px, py) → (sx, sy) crosses any
        maze wall AABB.  ``walls`` is the active zone's list of (x, y,
        w, h) tuples or arcade Rects (anything with ``.x/.y/.w/.h`` or
        4-tuple unpacking).  Without walls (open zones), nothing is
        blocked."""
        return _segment_crosses_any_wall(px, py, sx, sy, walls,
                                         samples=(0.4, 0.7, 1.0))

    def _pick_follow_slot(
        self, player, walls: list | None,
    ) -> tuple[float, float]:
        """Return the (x, y) of the highest-priority unblocked slot.

        Priority order: LEFT → RIGHT → BACK.  Sticky preference: if
        the previously chosen slot is still unblocked we keep it, so
        the drone doesn't jitter between LEFT and RIGHT every frame
        in open space.  All blocked → fall back to BACK (the drone
        will sit there even if it overlaps a wall; the post-move
        push-out in update_logic.update_drone scoots it free).
        """
        px, py = player.center_x, player.center_y
        ph = getattr(player, "heading", 0.0)
        order = [self._slot, self._SLOT_LEFT, self._SLOT_RIGHT,
                 self._SLOT_BACK]
        seen: set[int] = set()
        for slot in order:
            if slot in seen:
                continue
            seen.add(slot)
            sx, sy = self._slot_position(slot, px, py, ph)
            if not self._slot_blocked(sx, sy, px, py, walls):
                self._slot = slot
                return sx, sy
        # All blocked — last-resort BACK, even if it sits in a wall.
        self._slot = self._SLOT_BACK
        return self._slot_position(self._SLOT_BACK, px, py, ph)

    def follow(
        self, dt: float, player_x: float, player_y: float,
        player=None, walls: list | None = None,
    ) -> None:
        """Steer toward a fixed slot beside / behind the player.

        Slot selection (per spec): LEFT side of player first; if a
        maze wall blocks, switch to RIGHT; if both are blocked, fall
        back to BACK.  When the maze WaypointPlanner is attached and
        the player sits in a different room than the drone, route
        through the room graph instead of straight at the slot — a
        slot that's behind a wall would otherwise grind the drone
        against geometry forever.

        ``player`` provides the heading; if omitted we treat the
        player as facing north (heading=0) so the legacy two-arg
        signature stays usable from tests / save-restore paths.
        """
        # Pathfinding override — the planner returns either a room-
        # centre waypoint to head toward, or None (same room / no
        # path needed / cooling down).  Runs BEFORE slot picking so
        # we navigate to the correct room first, then settle into the
        # slot once we share a room with the player.
        wp = self._follow_planner.plan(
            dt, self.center_x, self.center_y, player_x, player_y)
        if self._follow_planner.gave_up():
            # Pathfinding gave up — freeze + disable firing for the
            # cooldown window so the drone stops grinding.
            self._target_cooldown = self._follow_planner.COOLDOWN
            self._routing_to_waypoint = False
            return

        if wp is not None:
            target_x, target_y = wp
            self._routing_to_waypoint = True
        else:
            # Inside the player's room (or open zone): slot up.
            self._routing_to_waypoint = False
            if player is not None:
                target_x, target_y = self._pick_follow_slot(player, walls)
            else:
                # Legacy 2-arg call (tests, save-restore): default to
                # LEFT slot of a heading=0 ship — directly west.
                target_x = player_x - DRONE_FOLLOW_DIST
                target_y = player_y

        dx = target_x - self.center_x
        dy = target_y - self.center_y
        dist = math.hypot(dx, dy)
        if dist <= 0.001:
            return
        step = min(DRONE_MAX_SPEED * dt, dist)
        nx = dx / dist
        ny = dy / dist
        self.center_x += nx * step
        self.center_y += ny * step
        # Heading uses the same (sin, cos) convention as the player
        # ship so the projectile flies forward on launch.
        self._heading = math.degrees(math.atan2(nx, ny)) % 360.0
        self.angle = self._heading

    def attach_maze_planner(
        self,
        rooms,
        room_graph,
    ) -> None:
        """Swap in a fresh WaypointPlanner for the supplied maze
        geometry — used by ``update_logic.update_drone`` when the
        drone is inside the Star Maze.  The geometry id check avoids
        re-allocating every frame when the drone stays in the same
        zone.  Pass ``rooms=None`` / ``room_graph=None`` to revert
        the planner to no-op (e.g. exiting the Star Maze)."""
        gid = id(rooms) ^ id(room_graph)
        if gid == self._follow_planner_geom_id:
            return
        from zones.maze_geometry import WaypointPlanner
        self._follow_planner = WaypointPlanner(rooms, room_graph)
        self._follow_planner_geom_id = gid

    def update_visuals(self, dt: float) -> None:
        # Hit-flash tint.
        if self._hit_timer > 0.0:
            self._hit_timer = max(0.0, self._hit_timer - dt)
            self.color = ((255, 80, 80, 255) if self._hit_timer > 0.0
                          else (255, 255, 255, 255))
        # Shield-arc rotation (used only by CombatDrone but cheap
        # to advance unconditionally).
        self._shield_angle = (self._shield_angle + 90.0 * dt) % 360.0
        # Cooldown tick.
        self._fire_cd = max(0.0, self._fire_cd - dt)
        # Target-stuck timers: cooldown counts down whenever active;
        # acquired-timer is reset by ``_aim_and_fire`` on every
        # successful shot, so it only grows when the drone has a
        # target it can't shoot at.
        if self._target_cooldown > 0.0:
            self._target_cooldown = max(0.0, self._target_cooldown - dt)

    def regen_shields(self, dt: float, player) -> None:
        """Match the player ship's shield regen rate.  Player carries
        ``_shield_regen`` (per ship type, e.g. 0.5 pt/s for a Cruiser);
        the drone accumulates fractional shield points and bumps the
        integer ``shields`` counter when it crosses 1.0.  Caller
        passes the player ship from update_drone so the drone doesn't
        need to import GameView."""
        if self.shields >= self.max_shields or self.max_shields <= 0:
            return
        rate = float(getattr(player, "_shield_regen", 0.0))
        if rate <= 0.0:
            return
        self._shield_regen_acc += rate * dt
        if self._shield_regen_acc >= 1.0:
            bump = int(self._shield_regen_acc)
            self._shield_regen_acc -= bump
            self.shields = min(self.max_shields, self.shields + bump)

    def _run_return_home(
        self, dt: float, player_x: float, player_y: float,
        player, walls: list | None,
    ) -> None:
        """RETURN_HOME tick — A* via the existing WaypointPlanner with
        the planner's give-up cooldown forcibly cleared each frame so
        the drone never freezes.  When the planner reports a route
        the drone steers to the next room's centre; when no route
        exists (or the drone shares a room with the player) it falls
        back to a direct straight-line chase past slot picking,
        because slot picking would just stick the drone behind the
        wrong wall again.

        Skips firing entirely — the drone ignores every enemy until
        it's reeled back inside ``_RETURN_HOME_EXIT_DIST``.
        """
        # Forcibly clear the planner's cooldown each frame so it
        # doesn't park the drone in its 5-s freeze while the player
        # is still far away.  ``reset()`` also wipes the stuck
        # tracker so each frame starts fresh.
        if self._follow_planner._cooldown_t > 0.0:
            self._follow_planner._cooldown_t = 0.0
        wp = self._follow_planner.plan(
            dt, self.center_x, self.center_y, player_x, player_y)
        # Discard the gave_up flag — RETURN_HOME never freezes.  We
        # consume it by calling ``gave_up()`` to clear the latch.
        self._follow_planner.gave_up()
        if wp is not None:
            target_x, target_y = wp
        else:
            # Same room or no path — head straight for the player.
            target_x, target_y = player_x, player_y
        dx = target_x - self.center_x
        dy = target_y - self.center_y
        dist = math.hypot(dx, dy)
        if dist <= 0.001:
            return
        step = min(DRONE_MAX_SPEED * dt, dist)
        nx = dx / dist
        ny = dy / dist
        self.center_x += nx * step
        self.center_y += ny * step
        self._heading = math.degrees(math.atan2(nx, ny)) % 360.0
        self.angle = self._heading

    def _update_mode(
        self, player, target, walls: list | None = None,
    ) -> None:
        """Per spec: enter ATTACK when a target sits within
        ``DRONE_DETECT_RANGE`` AND there is no maze wall on the
        line of sight between drone and target.  When a wall blocks
        line of sight, return to FOLLOW (the drone shouldn't
        try to engage a target it can't actually shoot at — it'll
        just grind on the wall).  When the player drifts past
        ``DRONE_BREAK_OFF_DIST`` away, switch to RETURN_HOME — A*
        path-find back to the player while ignoring every enemy
        until the drone has closed the gap.

        Called every frame from ``update_drone`` BEFORE the follow /
        fire branches so the chosen branch matches current state."""
        d_to_player = math.hypot(self.center_x - player.center_x,
                                 self.center_y - player.center_y)
        # Far from the player → enter / stay in RETURN_HOME.  Hysteresis:
        # once we've entered RETURN_HOME we hold it until the drone is
        # back inside ``_RETURN_HOME_EXIT_DIST`` (600 px), so a drone
        # making slow progress at ~800 px doesn't flicker the mode
        # every frame.
        if self._mode == self._MODE_RETURN_HOME:
            if d_to_player > self._RETURN_HOME_EXIT_DIST:
                return
            # Close enough — drop back to normal follow / attack
            # logic below.
        elif d_to_player > DRONE_BREAK_OFF_DIST:
            self._mode = self._MODE_RETURN_HOME
            return
        if target is None:
            self._mode = self._MODE_FOLLOW
            return
        td = math.hypot(target.center_x - self.center_x,
                        target.center_y - self.center_y)
        if td > DRONE_DETECT_RANGE:
            self._mode = self._MODE_FOLLOW
            return
        # Line-of-sight check — if a maze wall sits between drone and
        # target, disengage.  In open zones (walls=None) this is a
        # no-op and the drone always engages.
        if _segment_crosses_any_wall(
                self.center_x, self.center_y,
                target.center_x, target.center_y,
                walls):
            self._mode = self._MODE_FOLLOW
            return
        self._mode = self._MODE_ATTACK

    def has_target_lock(self) -> bool:
        """True iff the drone is currently allowed to engage targets.
        Flips False once the stuck-on-target timer has built up
        beyond 5 s without progress (drone is jammed against a wall
        or the laser is being absorbed by geometry) and stays False
        until the target_cooldown bleeds back to zero (5 s of
        follow-only)."""
        return self._target_cooldown <= 0.0

    def _track_stuck_progress(
        self, dt: float, target,
    ) -> bool:
        """Return True when the drone is "stuck" on this target —
        same target in sight for ≥ 5 s with no HP loss.  Caller
        should drop the target and enter the follow-only cooldown.
        Resets internal state on any progress.
        """
        if target is None:
            self._stuck_target = None
            self._target_acquired_timer = 0.0
            return False
        if target is not self._stuck_target:
            # New target — reset progress markers.
            self._stuck_target = target
            self._stuck_target_hp = int(getattr(target, "hp", 0))
            self._target_acquired_timer = 0.0
            return False
        cur_hp = int(getattr(target, "hp", 0))
        if cur_hp < self._stuck_target_hp:
            # We damaged it — making progress, reset.
            self._stuck_target_hp = cur_hp
            self._target_acquired_timer = 0.0
            return False
        self._target_acquired_timer += dt
        if self._target_acquired_timer >= 5.0:
            self._target_acquired_timer = 0.0
            self._target_cooldown = 5.0
            self._stuck_target = None
            return True
        return False

    # ── Fire ─────────────────────────────────────────────────────────

    def _aim_and_fire(
        self, target_x: float, target_y: float,
    ) -> Projectile | None:
        """Spawn one Projectile aimed at ``(target_x, target_y)`` if
        off cooldown; returns the projectile (or ``None``).  Caller
        appends it to the projectile list."""
        if self._fire_cd > 0.0:
            return None
        dx = target_x - self.center_x
        dy = target_y - self.center_y
        dist = math.hypot(dx, dy)
        if dist > DRONE_LASER_RANGE or dist <= 0.001:
            return None
        heading = math.degrees(math.atan2(dx, dy)) % 360.0
        self._fire_cd = DRONE_FIRE_COOLDOWN
        self._heading = heading
        self.angle = heading
        if self._fire_snd is not None:
            arcade.play_sound(self._fire_snd,
                              volume=audio.sfx_volume * 0.4)
        return Projectile(
            self._laser_tex,
            self.center_x, self.center_y,
            heading,
            DRONE_LASER_SPEED, DRONE_LASER_RANGE,
            scale=0.5,
            mines_rock=self._mines_rock,
            damage=self._laser_damage,
        )


class MiningDrone(_BaseDrone):
    """Mines nearby asteroids and vacuums up dropped loot."""

    _LABEL = "Mining Drone"

    def __init__(self, x: float, y: float) -> None:
        from constants import MINING_DRONE_LASER_PNG
        super().__init__(
            MINING_DRONE_PNG,
            _load(MINING_DRONE_LASER_PNG),
            x, y,
            shield=MINING_DRONE_SHIELD,
            laser_damage=MINING_DRONE_LASER_DAMAGE,
            mines_rock=True,
            fire_snd=_load_snd(SFX_MINING_DRONE_LASER),
        )

    def update_drone(
        self, dt: float, gv: "GameView",
    ) -> Projectile | None:
        """Advance follow + fire + pickup-vacuum logic.  Returns a
        Projectile (or ``None``) for the caller to append to
        ``gv.projectile_list``.

        Mode transitions: with an asteroid in mining range, switch to
        ATTACK and mine; otherwise FOLLOW player at one of the three
        side / back slots.  Mining drones break off if the player
        drifts past ``DRONE_BREAK_OFF_DIST`` so the drone doesn't get
        stranded chasing rocks while the player flies away."""
        self.update_visuals(dt)
        self.regen_shields(dt, gv.player)
        walls = _walls_from_zone(gv)
        # Mode update — target = nearest asteroid.
        target = (self._nearest_asteroid(gv) if self.has_target_lock()
                  else None)
        self._update_mode(gv.player, target, walls)
        if self._mode == self._MODE_RETURN_HOME:
            self._run_return_home(
                dt, gv.player.center_x, gv.player.center_y,
                gv.player, walls)
        elif self._mode == self._MODE_FOLLOW:
            self.follow(dt, gv.player.center_x, gv.player.center_y,
                        player=gv.player, walls=walls)
        # else (ATTACK): hold position while attacking (no movement)
        # Vacuum any iron / blueprint pickup within reach by flagging
        # it as flying — the standard pickup loop in game_view's
        # on_update already pulls it toward the player and credits
        # the inventory on contact.  Runs in both modes.
        for plist in (gv.iron_pickup_list, gv.blueprint_pickup_list):
            for p in plist:
                if getattr(p, "_flying", True):
                    continue
                if math.hypot(p.center_x - self.center_x,
                              p.center_y - self.center_y
                              ) <= MINING_DRONE_PICKUP_RADIUS:
                    p._flying = True
        if self._mode != self._MODE_ATTACK or target is None:
            return None
        # Stuck check: same target with no HP drop for 5 s → bail.
        if self._track_stuck_progress(dt, target):
            return None
        return self._aim_and_fire(target.center_x, target.center_y)

    def _nearest_asteroid(self, gv: "GameView"):
        from itertools import chain
        best = None
        best_d2 = MINING_DRONE_MINING_RANGE * MINING_DRONE_MINING_RANGE
        zone = getattr(gv, "_zone", None)
        # Static asteroid lists for the active zone.
        sources = []
        if hasattr(zone, "_iron_asteroids"):
            sources.append(zone._iron_asteroids)
            sources.append(getattr(zone, "_double_iron", []))
            sources.append(getattr(zone, "_copper_asteroids", []))
        else:
            sources.append(getattr(gv, "asteroid_list", []))
        for a in chain(*sources):
            d2 = ((a.center_x - self.center_x) ** 2
                  + (a.center_y - self.center_y) ** 2)
            if d2 < best_d2:
                best_d2 = d2
                best = a
        return best


class CombatDrone(_BaseDrone):
    """Attacks nearby aliens + boss."""

    _LABEL = "Combat Drone"

    def __init__(self, x: float, y: float) -> None:
        from constants import COMBAT_DRONE_LASER_PNG
        super().__init__(
            COMBAT_DRONE_PNG,
            _load(COMBAT_DRONE_LASER_PNG),
            x, y,
            shield=COMBAT_DRONE_SHIELD,
            laser_damage=COMBAT_DRONE_LASER_DAMAGE,
            mines_rock=False,
            fire_snd=_load_snd(SFX_COMBAT_DRONE_LASER),
        )

    def update_drone(
        self, dt: float, gv: "GameView",
    ) -> Projectile | None:
        self.update_visuals(dt)
        self.regen_shields(dt, gv.player)
        walls = _walls_from_zone(gv)
        target = (self._nearest_enemy(gv) if self.has_target_lock()
                  else None)
        self._update_mode(gv.player, target, walls)
        if self._mode == self._MODE_RETURN_HOME:
            self._run_return_home(
                dt, gv.player.center_x, gv.player.center_y,
                gv.player, walls)
            return None
        elif self._mode == self._MODE_FOLLOW:
            self.follow(dt, gv.player.center_x, gv.player.center_y,
                        player=gv.player, walls=walls)
        # else (ATTACK): hold station and engage
        if self._mode != self._MODE_ATTACK or target is None:
            return None
        # Stuck check: same target with no HP drop for 5 s → bail.
        if self._track_stuck_progress(dt, target):
            return None
        return self._aim_and_fire(target.center_x, target.center_y)

    def _nearest_enemy(self, gv: "GameView"):
        """Pick the nearest live hostile within ``DRONE_DETECT_RANGE``.

        Maze spawners are **priority targets** — if any spawner sits
        in range, the closest one is returned ahead of every other
        enemy class.  Killing a spawner stops its alien drip + ends
        its laser fire, so prioritising them is much more impactful
        than picking off the next maze alien.

        Otherwise walks every enemy sprite list the active zone
        exposes — ``gv.alien_list`` alone isn't enough because the
        Star Maze swaps that reference between ``self._aliens`` (Z2
        aliens outside the maze) and ``self._maze_aliens`` (inside)
        during update, leaving whichever was last assigned visible.
        By scanning the zone's underlying lists directly the drone
        engages every faction (maze aliens, Z2 aliens, stalkers,
        plus both bosses) regardless of which list happens to be on
        ``gv.alien_list`` when this method runs.
        """
        zone = getattr(gv, "_zone", None)
        # Priority pass: maze spawners.  Star Maze stores them on
        # ``zone._spawners`` (an arcade SpriteList).  Each spawner
        # exposes ``hp`` like every other damageable thing; we filter
        # dead ones (hp <= 0) the same way as the alien pass below.
        spawners = getattr(zone, "_spawners", None)
        if spawners:
            best_sp = None
            best_sp_d2 = DRONE_DETECT_RANGE * DRONE_DETECT_RANGE
            for sp in spawners:
                # ``killed`` is the source of truth (spawner respawns
                # after a window — hp can read >0 even while it's
                # still in the dead phase); skip those husks.
                if getattr(sp, "killed", False):
                    continue
                if getattr(sp, "hp", 0) <= 0:
                    continue
                d2 = ((sp.center_x - self.center_x) ** 2
                      + (sp.center_y - self.center_y) ** 2)
                if d2 < best_sp_d2:
                    best_sp_d2 = d2
                    best_sp = sp
            if best_sp is not None:
                return best_sp

        best = None
        best_d2 = DRONE_DETECT_RANGE * DRONE_DETECT_RANGE
        seen: set[int] = set()

        def _candidates():
            # gv.alien_list often aliases one of the zone lists (Zone 2
            # default) or holds a separate stash — yield it before the
            # zone walk so dedupe-by-id catches the overlap.
            for e in (getattr(gv, "alien_list", []) or []):
                yield e
            if zone is not None and hasattr(zone, "iter_enemies"):
                yield from zone.iter_enemies()
            for boss_attr in ("_boss", "_nebula_boss"):
                b = getattr(gv, boss_attr, None)
                if b is not None:
                    yield b

        for e in _candidates():
            eid = id(e)
            if eid in seen:
                continue
            seen.add(eid)
            if getattr(e, "hp", 0) <= 0:
                continue
            d2 = ((e.center_x - self.center_x) ** 2
                  + (e.center_y - self.center_y) ** 2)
            if d2 < best_d2:
                best_d2 = d2
                best = e
        return best

    def draw_shield(self) -> None:
        """Same dashed-blue arc as ShieldedAlien / shielded MazeAlien."""
        if self.shields <= 0:
            return
        cx, cy = self.center_x, self.center_y
        r = DRONE_RADIUS + 12.0
        segments = 8
        arc = 360 / segments * 0.65
        for i in range(segments):
            start = self._shield_angle + i * (360 / segments)
            a1 = math.radians(start)
            a2 = math.radians(start + arc)
            x1 = cx + math.cos(a1) * r
            y1 = cy + math.sin(a1) * r
            x2 = cx + math.cos(a2) * r
            y2 = cy + math.sin(a2) * r
            arcade.draw_line(x1, y1, x2, y2, (80, 160, 255, 180), 2)
