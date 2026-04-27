"""Combat, spawning, and progression helpers extracted from GameView."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Optional

import arcade

from constants import (
    WORLD_WIDTH, WORLD_HEIGHT, SHAKE_DURATION, SHAKE_AMPLITUDE,
    ASTEROID_IRON_YIELD, ASTEROID_COUNT, ASTEROID_MIN_DIST,
    ALIEN_COUNT, ALIEN_MIN_DIST,
    RESPAWN_EXCLUSION_RADIUS, SHIELD_RECHARGE_HEAL,
    REPAIR_PACK_HEAL, WORLD_ITEM_LIFETIME,
    MODULE_TYPES, ZONE_GATED_MODULES,
)
from settings import audio
from sprites.explosion import Explosion, HitSpark, FireSpark
from sprites.pickup import IronPickup, BlueprintPickup
from sprites.boss import BossAlienShip

if TYPE_CHECKING:
    from game_view import GameView


def trigger_shake(gv: GameView) -> None:
    """No-op — screen shake on contact with game objects is disabled."""
    return


def apply_damage_to_player(gv: GameView, amount: int) -> None:
    """Apply damage to the player's shields first, then HP."""
    if gv._player_dead:
        return
    if gv.player.shield_absorb > 0 and gv.player.shields > 0:
        amount = max(1, amount - gv.player.shield_absorb)
    if gv.player.shields > 0:
        absorbed = min(gv.player.shields, amount)
        gv.player.shields -= absorbed
        amount -= absorbed
        gv.shield_sprite.hit_flash()
    if amount > 0:
        gv.player.hp = max(0, gv.player.hp - amount)
        gv.fire_sparks.append(
            FireSpark(gv.player.center_x, gv.player.center_y)
        )
        if gv.player.hp <= 0:
            trigger_player_death(gv)
    gv._shake_amp = SHAKE_AMPLITUDE


def flash_game_msg(gv: GameView, msg: str, duration: float = 1.5) -> None:
    """Show a temporary message centered on the play area."""
    gv._flash_msg = msg
    gv._flash_timer = duration


def use_repair_pack(gv: GameView, slot: int) -> None:
    """Try to use a repair pack from the given quick-use slot."""
    if gv.player.hp >= gv.player.max_hp:
        flash_game_msg(gv, "Already at full HP!")
        return
    if gv.inventory.count_item("repair_pack") <= 0:
        return
    heal = int(gv.player.max_hp * REPAIR_PACK_HEAL)
    gv.player.hp = min(gv.player.max_hp, gv.player.hp + heal)
    gv.inventory.remove_item("repair_pack", 1)
    remaining = gv.inventory.count_item("repair_pack")
    if remaining > 0:
        gv._hud.set_quick_use(slot, "repair_pack", remaining)
    else:
        gv._hud.set_quick_use(slot, None, 0)
    # Brief red glow
    gv._use_glow = (255, 80, 80, 160)
    gv._use_glow_timer = 0.4
    # Consuming an item inside a null field breaks the cloak.
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)


def use_shield_recharge(gv: GameView, slot: int) -> None:
    """Try to use a shield recharge from the given quick-use slot."""
    if gv.player.shields >= gv.player.max_shields:
        flash_game_msg(gv, "Shields already full!")
        return
    if gv.inventory.count_item("shield_recharge") <= 0:
        return
    recharge = int(gv.player.max_shields * SHIELD_RECHARGE_HEAL)
    gv.player.shields = min(gv.player.max_shields, gv.player.shields + recharge)
    gv.inventory.remove_item("shield_recharge", 1)
    remaining = gv.inventory.count_item("shield_recharge")
    if remaining > 0:
        gv._hud.set_quick_use(slot, "shield_recharge", remaining)
    else:
        gv._hud.set_quick_use(slot, None, 0)
    # Brief blue glow
    gv._use_glow = (80, 160, 255, 160)
    gv._use_glow_timer = 0.4
    # Consuming an item inside a null field breaks the cloak.
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)


def _drone_item_key_for(drone) -> str:
    """Map an active drone instance back to its inventory item key."""
    return ("mining_drone" if type(drone).__name__ == "MiningDrone"
            else "combat_drone")


_FLEET_ORDER_LABELS: dict[str, str] = {
    "return": "Order: RETURN",
    "attack": "Order: ATTACK",
    "follow_only": "Reaction: FOLLOW ONLY",
    "attack_only": "Reaction: ATTACK ONLY",
}


def apply_fleet_order(gv: GameView, order: str) -> str:
    """Apply a Fleet menu button click to the active drone.

    ``order`` is one of the ``FleetMenu.BTN_*`` values:

      * ``"return"`` — direct order: drone breaks off and A*-paths
        back to the player.  Auto-clears once the drone is close.
      * ``"attack"`` — direct order: drone forces ATTACK on every
        detected enemy until cleared (replaced by another order or
        manually overridden).
      * ``"follow_only"`` — reaction: drone never engages, even
        with targets in range.
      * ``"attack_only"`` — reaction: original autonomy (engages
        targets in range).

    Returns a short status string for the caller to flash on the
    menu (e.g. "Order: RETURN" or "No drone deployed").
    """
    drone = getattr(gv, "_active_drone", None)
    if drone is None:
        return "No drone deployed"
    import drone_telemetry as _tel
    if order == "return":
        drone._direct_order = "return"
        # Header includes drone + player coords for the reader; gv
        # may be a SimpleNamespace stub in tests so we look up the
        # player defensively.
        player = getattr(gv, "player", None)
        if player is not None:
            ply_str = (f"player at ({player.center_x:.0f},"
                       f"{player.center_y:.0f})")
        else:
            ply_str = "player position unknown"
        _tel.start(reason=(
            f"RETURN issued; drone at "
            f"({drone.center_x:.0f},{drone.center_y:.0f}); "
            f"{ply_str}"))
    elif order == "attack":
        drone._direct_order = "attack"
        _tel.stop(reason="ATTACK order issued")
    elif order == "follow_only":
        drone._reaction = "follow"
        # Clear any direct order so the new reaction takes effect
        # immediately rather than after the order auto-clears.
        drone._direct_order = None
        _tel.stop(reason="FOLLOW_ONLY reaction set")
    elif order == "attack_only":
        drone._reaction = "attack"
        drone._direct_order = None
        _tel.stop(reason="ATTACK_ONLY reaction set")
    else:
        return f"Unknown order: {order}"
    return _FLEET_ORDER_LABELS.get(order, "Order applied")


def recall_drone(gv: GameView) -> None:
    """Stash the active drone back into the player's inventory
    without deploying anything new.  Used by the dedicated "put
    away" key (Shift+R) and as the swap helper for ``deploy_drone``
    when the player swaps to the other variant.  No-op when no
    drone is deployed."""
    active = getattr(gv, "_active_drone", None)
    if active is None:
        return
    key = _drone_item_key_for(active)
    gv.inventory.add_item(key, 1)
    active.remove_from_sprite_lists()
    gv._active_drone = None
    import drone_telemetry as _tel
    _tel.stop(reason="drone recalled")
    flash_game_msg(gv, "Drone recalled", 1.2)


def deploy_drone(gv: GameView) -> None:
    """Handle the R key.  Picks the drone variant from the active
    weapon (mining beam → mining drone, basic laser → combat drone)
    and either deploys it (consuming one charge) or swaps the
    currently-active drone for the other variant.  Swapping refunds
    the old drone's charge to the inventory before consuming the new
    one — pressing R while the WRONG drone is out is now a clean
    swap rather than a destructive replacement.

    Behaviour summary:
      * No drone deployed → spawn the matching variant; consume one
        ``mining_drone`` / ``combat_drone`` from the inventory.
      * Same variant already deployed → no-op (no charge consumed).
      * Other variant deployed → recall the active drone (refund 1
        of its variant), spawn the new one, consume 1 of the new
        variant.  Net result: 0 destroyed, 1 swapped.
    """
    if gv._escape_menu.open or gv._player_dead:
        return
    weapon = gv._active_weapon
    is_mining = bool(getattr(weapon, "mines_rock", False))
    item_key = "mining_drone" if is_mining else "combat_drone"
    desired_cls_name = "MiningDrone" if is_mining else "CombatDrone"
    # Already-deployed branch.
    active = getattr(gv, "_active_drone", None)
    if active is not None:
        if type(active).__name__ == desired_cls_name:
            return  # same variant — no-op, no consume
        # Different variant — refund it first (back into inventory),
        # then fall through to the standard deploy path so the new
        # variant is spawned + consumed cleanly.
        old_key = _drone_item_key_for(active)
        gv.inventory.add_item(old_key, 1)
        active.remove_from_sprite_lists()
        gv._active_drone = None
    # Inventory check.
    if gv.inventory.count_item(item_key) <= 0:
        flash_game_msg(gv, f"No {item_key.replace('_', ' ')}s available!")
        return
    # Spawn behind the player so the drone visibly enters the world.
    spawn_x = gv.player.center_x
    spawn_y = gv.player.center_y
    from sprites.drone import MiningDrone, CombatDrone
    drone = MiningDrone(spawn_x, spawn_y) if is_mining \
        else CombatDrone(spawn_x, spawn_y)
    gv._drone_list.append(drone)
    gv._active_drone = drone
    gv.inventory.remove_item(item_key, 1)
    flash_game_msg(gv, f"{drone._LABEL} deployed!", 1.5)
    # Deploying inside a null field breaks the cloak — same rule
    # the other consumable-fire helpers follow.
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)


def fire_missile(gv: GameView, slot: int) -> None:
    """Fire a homing missile from the given quick-use slot."""
    from constants import MISSILE_FIRE_RATE
    from sprites.missile import HomingMissile
    if gv.inventory.count_item("missile") <= 0:
        return
    if hasattr(gv, '_missile_fire_cd') and gv._missile_fire_cd > 0:
        return
    gv._missile_fire_cd = MISSILE_FIRE_RATE
    gv.inventory.remove_item("missile", 1)
    remaining = gv.inventory.count_item("missile")
    if remaining > 0:
        gv._hud.set_quick_use(slot, "missile", remaining)
    else:
        gv._hud.set_quick_use(slot, None, 0)
    m = HomingMissile(gv._missile_tex,
                      gv.player.center_x, gv.player.center_y,
                      gv.player.heading)
    gv._missile_list.append(m)
    arcade.play_sound(gv._missile_launch_snd, volume=0.4)
    # Firing a homing missile from inside a null field breaks the cloak.
    from update_logic import disable_null_field_around_player
    disable_null_field_around_player(gv)


def trigger_player_death(gv: GameView) -> None:
    """Handle player ship destruction.

    On death the player is **always** respawned (no Game Over screen
    in normal play).  The whole ship loadout — every cargo stack,
    every equipped module, every quick-use consumable — drops as
    world pickups at the death site so the player can reclaim them
    on their next pass through the area.  Bosses retreat to their
    spawn point; aliens forget the player and revert to PATROL.
    The actual respawn happens after a 1.5 s death animation
    (driven by ``update_logic.update_death_state`` → ``respawn_player``).
    """
    gv._player_dead = True
    px, py = gv.player.center_x, gv.player.center_y
    exp = Explosion(gv._explosion_frames, px, py, scale=2.5)
    exp.color = (255, 180, 100, 255)
    gv.explosion_list.append(exp)
    for _ in range(5):
        gv.fire_sparks.append(FireSpark(px, py))
    arcade.play_sound(gv._explosion_snd, volume=audio.sfx_volume)
    gv.player.visible = False
    gv.shield_sprite.visible = False
    if gv._thruster_player is not None:
        arcade.stop_sound(gv._thruster_player)
        gv._thruster_player = None
    gv._death_delay = 1.5
    _drop_player_loadout(gv, px, py)
    _send_bosses_home(gv)
    _reset_alien_aggro(gv)


def _drop_player_loadout(gv: GameView, x: float, y: float) -> None:
    """Drop every cargo stack, module, and quick-use consumable as
    world pickups at ``(x, y)``.  Mutates the inventory + slot lists
    in place so the post-respawn ship starts empty."""
    drops: list[tuple[str, int]] = []
    # Cargo — every stack in the 5×5 grid.
    for (_r, _c), (item_type, count) in list(gv.inventory._items.items()):
        if count > 0:
            drops.append((item_type, int(count)))
    gv.inventory._items.clear()
    gv.inventory._mark_dirty()
    # Modules — equipped slots become blueprint pickups.
    module_drops: list[str] = [m for m in gv._module_slots if m is not None]
    for i in range(len(gv._module_slots)):
        gv._module_slots[i] = None
    gv.player.apply_modules(gv._module_slots)
    gv._hud.set_module_count(len(gv._module_slots))
    gv._hud._mod_slots = list(gv._module_slots)
    # Quick-use slots — consumables on the bar drop separately from
    # any duplicates already counted via the cargo grid (each quick-use
    # slot mirrors an inventory item, so the inventory dump above
    # already covers the actual item counts; we just clear the bar).
    qu = getattr(gv, "_hud", None)
    if qu is not None:
        for i in range(len(qu._qu_slots)):
            qu._qu_slots[i] = None
            qu._qu_counts[i] = 0
    # Lay every drop on a scatter ring around the death site so they
    # don't stack into a single hard-to-distinguish blob.
    from collisions import _drop_scatter
    total = len(drops) + len(module_drops)
    if total <= 0:
        return
    positions = _drop_scatter(x, y, total)
    pi = 0
    from sprites.pickup import IronPickup, BlueprintPickup
    for item_type, count in drops:
        ix, iy = positions[pi]; pi += 1
        # Reuse the iron-pickup class for every consumable / resource;
        # it's already generic over ``item_type`` and the inventory's
        # add_item path accepts whatever string is set on the pickup.
        tex = gv._iron_tex
        if item_type == "copper":
            tex = getattr(gv, "_copper_tex", None) or gv._iron_tex
        p = IronPickup(tex, ix, iy, amount=count)
        p.item_type = item_type
        gv.iron_pickup_list.append(p)
    bp_icons = getattr(gv, "_blueprint_drop_tex", {}) or {}
    for mod in module_drops:
        ix, iy = positions[pi]; pi += 1
        tex = bp_icons.get(mod, gv._blueprint_tex)
        gv.blueprint_pickup_list.append(
            BlueprintPickup(tex, ix, iy, module_type=mod))


def _send_bosses_home(gv: GameView) -> None:
    """Flag every live boss to retreat toward its spawn point.  The
    flag clears automatically when the player re-enters priority
    range, so once respawned + within range the boss re-engages."""
    boss = getattr(gv, "_boss", None)
    if boss is not None:
        boss._patrol_home = True
    nb = getattr(gv, "_nebula_boss", None)
    if nb is not None:
        nb._patrol_home = True


def _reset_alien_aggro(gv: GameView) -> None:
    """Drop every alien's pursuit state across every zone so they
    forget the dying player.  Iterating the live zone list plus the
    Zone 1 / Zone 2 / Star Maze stashed lists covers every alien
    sprite the player could possibly be chased by; any alien that
    later detects the respawned player will re-aggro through its
    normal state machine."""
    seen: set[int] = set()

    def _reset_list(lst):
        for a in list(lst):
            if id(a) in seen:
                continue
            seen.add(id(a))
            if hasattr(a, "_state") and hasattr(a, "_STATE_PATROL"):
                a._state = a._STATE_PATROL
                if hasattr(a, "_pick_patrol_target"):
                    a._pick_patrol_target()
                if hasattr(a, "_fire_cd"):
                    a._fire_cd = max(getattr(a, "_fire_cd", 0.0), 0.5)

    _reset_list(getattr(gv, "alien_list", []) or [])
    for z in (getattr(gv, "_main_zone", None),
              getattr(gv, "_zone2", None),
              getattr(gv, "_star_maze", None)):
        if z is None:
            continue
        for attr in ("_aliens", "_maze_aliens", "_alien_list"):
            lst = getattr(z, attr, None)
            if lst is not None:
                _reset_list(lst)


def respawn_player(gv: GameView) -> None:
    """Bring the player back after the death animation finishes.

    Decision tree:

    1. ``gv._last_station_pos`` is set AND a Home Station still
       exists in that zone → soft respawn at that station with
       50 % HP + 50 % shields.  Inventory / modules / level / cargo
       are NOT touched (they were already dropped at the death
       site by ``_drop_player_loadout``).
    2. Otherwise → hard reset to a fresh L1 ship at Zone 1 world
       centre with 25 % HP + 0 shields, level / XP / module slot
       count rolled back to defaults.  Cargo + modules + quick-use
       are already empty from the loadout dump.
    """
    from zones import ZoneID
    target = _resolve_respawn_target(gv)
    if target is not None:
        zone_id, x, y = target
        if zone_id is not gv._zone.zone_id:
            gv._transition_zone(zone_id, entry_side="bottom")
        gv.player.center_x = x
        gv.player.center_y = y
        gv.player.vel_x = gv.player.vel_y = 0.0
        gv.player.hp = max(1, gv.player.max_hp // 2)
        gv.player.shields = gv.player.max_shields // 2
        flash_game_msg(gv, "Respawned at station", 2.5)
    else:
        _full_reset_respawn(gv)
    _restore_player_after_death(gv)


def _resolve_respawn_target(gv: GameView):
    """Return ``(zone_id, x, y)`` for station respawn, or ``None``
    if no Home Station exists anywhere (→ full reset)."""
    from zones import ZoneID
    from sprites.building import HomeStation
    last_pos = getattr(gv, "_last_station_pos", None)
    last_zone = getattr(gv, "_last_station_zone", None)

    def _home_in(buildings) -> tuple[float, float] | None:
        for b in (buildings or []):
            if isinstance(b, HomeStation) and not b.disabled:
                return (b.center_x, b.center_y)
        return None

    def _buildings_for_zone(zone_id):
        if zone_id is gv._zone.zone_id:
            return list(gv.building_list)
        if zone_id is ZoneID.MAIN:
            mz = getattr(gv, "_main_zone", None)
            if mz is not None and hasattr(mz, "_stash"):
                return list(mz._stash.get("building_list") or [])
        if zone_id is ZoneID.ZONE2:
            z2 = getattr(gv, "_zone2", None)
            if z2 is not None and hasattr(z2, "_building_stash"):
                return list(z2._building_stash.get("building_list") or [])
        return []

    if last_zone is not None:
        pos = _home_in(_buildings_for_zone(last_zone))
        if pos is not None:
            return (last_zone, pos[0], pos[1])
    # Fallback: any Home Station in any zone.
    for zid in (ZoneID.MAIN, ZoneID.ZONE2):
        pos = _home_in(_buildings_for_zone(zid))
        if pos is not None:
            return (zid, pos[0], pos[1])
    return None


def _full_reset_respawn(gv: GameView) -> None:
    """No stations exist → drop the player back to a fresh L1 ship
    at Zone 1 centre.  XP, ability meter, module slot count, and
    last-station tracking all reset to first-game defaults."""
    from zones import ZoneID
    from constants import (
        ABILITY_METER_MAX, MODULE_SLOT_COUNT,
    )
    from sprites.player import PlayerShip
    if gv._zone.zone_id is not ZoneID.MAIN:
        gv._transition_zone(ZoneID.MAIN, entry_side="bottom")
    # Build a fresh L1 ship of the player's chosen faction + type.
    new_player = PlayerShip(
        faction=gv._faction, ship_type=gv._ship_type, ship_level=1,
    )
    new_player.center_x = gv._zone.world_width / 2.0
    new_player.center_y = gv._zone.world_height / 2.0
    new_player.vel_x = new_player.vel_y = 0.0
    new_player.hp = max(1, new_player.max_hp // 4)
    new_player.shields = 0
    new_player.world_width = gv._zone.world_width
    new_player.world_height = gv._zone.world_height
    gv.player_list.clear()
    gv.player = new_player
    gv.player_list.append(new_player)
    # Reset progression that survives a soft respawn.
    gv._ship_level = 1
    gv._char_xp = 0
    gv._char_level = 1
    gv._ability_meter_max = ABILITY_METER_MAX
    gv._ability_meter = ABILITY_METER_MAX
    gv._module_slots = [None] * MODULE_SLOT_COUNT
    gv.player.apply_modules(gv._module_slots)
    gv._hud.set_module_count(MODULE_SLOT_COUNT)
    gv._hud._mod_slots = list(gv._module_slots)
    # Weapons reload off the new ship's gun count.
    from world_setup import load_weapons
    gv._weapons = load_weapons(gv.player.guns)
    gv._weapon_idx = 0
    # Reposition the shield bubble onto the new player.
    gv.shield_sprite.center_x = gv.player.center_x
    gv.shield_sprite.center_y = gv.player.center_y
    gv._last_station_pos = None
    gv._last_station_zone = None
    flash_game_msg(gv, "All stations lost — respawning at origin",
                   3.0)


def _restore_player_after_death(gv: GameView) -> None:
    """Common post-respawn cleanup: re-show the ship, clear death
    flags + cooldowns, reset force walls / ability state."""
    gv._player_dead = False
    gv._death_delay = 0.0
    gv.player.visible = True
    gv.shield_sprite.center_x = gv.player.center_x
    gv.shield_sprite.center_y = gv.player.center_y
    gv.shield_sprite.visible = True
    gv.player._collision_cd = 1.0     # brief grace window on respawn
    gv._misty_step_cd = 0.0
    gv._force_wall_cd = 0.0
    gv._broadside_cd = 0.0


def spawn_explosion(gv: GameView, x: float, y: float) -> None:
    """Spawn a one-shot explosion animation at world position (x, y).
    Used for ship, building, alien, and boss destruction."""
    exp = Explosion(gv._explosion_frames, x, y, scale=1.0)
    gv.explosion_list.append(exp)


def spawn_asteroid_explosion(gv: GameView, x: float, y: float) -> None:
    """Asteroid-specific 10-frame explosion (Explo__001..010).  All
    asteroid kill sites (Zone 1 iron, Zone 2 iron / double iron /
    copper / wandering) route here rather than through
    ``spawn_explosion`` so the visual reads differently from ship /
    alien / building deaths."""
    exp = Explosion(gv._asteroid_explosion_frames, x, y, scale=1.0)
    gv.explosion_list.append(exp)


def spawn_iron_pickup(
    gv: GameView,
    x: float,
    y: float,
    amount: int = ASTEROID_IRON_YIELD,
    lifetime: Optional[float] = None,
) -> None:
    """Spawn an iron token at world position (x, y)."""
    pickup = IronPickup(gv._iron_tex, x, y, amount=amount, lifetime=lifetime)
    gv.iron_pickup_list.append(pickup)


def spawn_blueprint_pickup(gv: GameView, x: float, y: float) -> None:
    """Spawn a random blueprint pickup at world position (x, y).

    In Zone 1 the pool is filtered to exclude the Nebula-gated modules
    (rear turret, homing missiles, misty step, force wall, death
    blossom, AI pilot, advanced crafter); those only drop in Zone 2
    and its post-Nebula warp zones.
    """
    from zones import ZoneID
    zone_id = getattr(getattr(gv, "_zone", None), "zone_id", None)
    if zone_id is ZoneID.MAIN:
        pool = [k for k in MODULE_TYPES if k not in ZONE_GATED_MODULES]
    else:
        pool = list(MODULE_TYPES.keys())
    if not pool:
        return
    mod_type = random.choice(pool)
    tex = gv._blueprint_drop_tex.get(mod_type, gv._blueprint_tex)
    bp = BlueprintPickup(tex, x, y, mod_type,
                         lifetime=WORLD_ITEM_LIFETIME)
    gv.blueprint_pickup_list.append(bp)


def _player_owns_blueprint(gv: GameView, key: str) -> bool:
    """A blueprint counts as 'owned' if the player has the pickup
    item in either inventory OR has already unlocked the recipe at
    a crafter (recipe unlocks persist across zone visits)."""
    bp_key = f"bp_{key}"
    inv = getattr(gv, "inventory", None)
    if inv is not None and inv.count_item(bp_key) > 0:
        return True
    sinv = getattr(gv, "_station_inv", None)
    if sinv is not None and sinv.count_item(bp_key) > 0:
        return True
    cm = getattr(gv, "_craft_menu", None)
    if cm is not None and key in getattr(cm, "_unlocked", set()):
        return True
    return False


def spawn_unowned_blueprint_pickup(
    gv: GameView, x: float, y: float,
) -> None:
    """Spawn a blueprint pickup the player has NOT yet received or
    unlocked.  If every blueprint in the post-Nebula pool is already
    owned, fall back to a random one (matches the user spec for the
    fully-collected case).  Used by maze-spawner kills so each
    spawner death meaningfully advances the player's collection.
    """
    pool = list(MODULE_TYPES.keys())
    if not pool:
        return
    unowned = [k for k in pool if not _player_owns_blueprint(gv, k)]
    mod_type = random.choice(unowned) if unowned else random.choice(pool)
    tex = gv._blueprint_drop_tex.get(mod_type, gv._blueprint_tex)
    bp = BlueprintPickup(tex, x, y, mod_type,
                         lifetime=WORLD_ITEM_LIFETIME)
    gv.blueprint_pickup_list.append(bp)


def add_xp(gv: GameView, amount: int) -> None:
    """Add XP and check for level-up; reapply bonuses if leveled."""
    from character_data import level_for_xp
    from world_setup import load_weapons
    from character_data import MAX_XP
    if gv._char_xp >= MAX_XP:
        return
    old_level = gv._char_level
    gv._char_xp = min(gv._char_xp + amount, MAX_XP)
    gv._char_level = level_for_xp(gv._char_xp)
    if gv._char_level > old_level:
        flash_game_msg(gv, f"Level {gv._char_level}!", 2.0)
        gv._weapons = load_weapons(gv.player.guns)
        gv._apply_character_weapon_bonuses()


def try_respawn_asteroids(gv: GameView) -> None:
    """Respawn one asteroid if count < ASTEROID_COUNT, avoiding buildings."""
    if len(gv.asteroid_list) >= ASTEROID_COUNT:
        return
    from sprites.asteroid import IronAsteroid
    margin = 100
    for _ in range(200):
        ax = random.uniform(margin, WORLD_WIDTH - margin)
        ay = random.uniform(margin, WORLD_HEIGHT - margin)
        cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        if math.hypot(ax - cx_world, ay - cy_world) < ASTEROID_MIN_DIST:
            continue
        too_close = any(
            math.hypot(ax - b.center_x, ay - b.center_y)
            < RESPAWN_EXCLUSION_RADIUS
            for b in gv.building_list
        )
        if too_close:
            continue
        gv.asteroid_list.append(IronAsteroid(gv._asteroid_tex, ax, ay))
        gv.hit_sparks.append(HitSpark(ax, ay))
        from update_logic import play_sfx_at
        play_sfx_at(gv, gv._bump_snd, ax, ay, base_volume=0.3)
        return


def try_respawn_aliens(gv: GameView) -> None:
    """Respawn one alien if count < ALIEN_COUNT, avoiding buildings."""
    if len(gv.alien_list) >= ALIEN_COUNT:
        return
    from sprites.alien import SmallAlienShip
    margin = 100
    for _ in range(200):
        ax = random.uniform(margin, WORLD_WIDTH - margin)
        ay = random.uniform(margin, WORLD_HEIGHT - margin)
        cx_world, cy_world = WORLD_WIDTH / 2, WORLD_HEIGHT / 2
        if math.hypot(ax - cx_world, ay - cy_world) < ALIEN_MIN_DIST:
            continue
        too_close = any(
            math.hypot(ax - b.center_x, ay - b.center_y)
            < RESPAWN_EXCLUSION_RADIUS
            for b in gv.building_list
        )
        if too_close:
            continue
        gv.alien_list.append(
            SmallAlienShip(gv._alien_ship_tex, gv._alien_laser_tex, ax, ay)
        )
        gv.hit_sparks.append(HitSpark(ax, ay))
        from update_logic import play_sfx_at
        play_sfx_at(gv, gv._bump_snd, ax, ay, base_volume=0.3)
        return


def check_boss_spawn(gv: GameView) -> None:
    """No-op kept for backward compatibility.

    The Double Star boss is now auto-spawned by
    ``building_manager.place_building`` the moment a Quantum Wave
    Integrator is built.  Previous trigger logic (character level ≥ 5,
    every module slot filled, 5 repair packs stockpiled) was retired
    in favour of a single player-committed trigger — the QWI costs
    1000 iron + 2000 copper, which is itself the commitment gate."""
    return


def spawn_nebula_boss(gv: GameView) -> bool:
    """Summon the Nebula boss via the QWI click-menu button.

    Deducts ``QWI_SPAWN_NEBULA_BOSS_IRON_COST`` from the player's
    ship inventory (falling back to the station inventory if short).
    Spawns a ``NebulaBossShip`` in Zone 2 at the world corner
    furthest from the active Home Station — same placement rule as
    the Double Star boss.  Returns True on success, False when the
    player can't afford it or preconditions fail.
    """
    from constants import QWI_SPAWN_NEBULA_BOSS_IRON_COST
    from sprites.nebula_boss import NebulaBossShip, load_nebula_boss_texture
    from sprites.building import HomeStation

    if getattr(gv, "_nebula_boss", None) is not None:
        return False

    # Resource gate.
    total_iron = gv.inventory.total_iron + gv._station_inv.total_iron
    if total_iron < QWI_SPAWN_NEBULA_BOSS_IRON_COST:
        return False

    # Need an active Home Station to anchor the spawn direction.
    home = next((b for b in gv.building_list
                 if isinstance(b, HomeStation) and not b.disabled), None)
    if home is None:
        return False

    # Deduct iron — shared helper handles ship-first-then-station.
    from inventory_ops import deduct_resources
    deduct_resources(gv, QWI_SPAWN_NEBULA_BOSS_IRON_COST)

    best = _furthest_corner_from(home.center_x, home.center_y)

    # Roll a random row of the second column of
    # ``faction_6_monsters_128x128.png`` so each Nebula boss spawn
    # gets its own appearance from the 8 monster variants.  The row
    # is stored on the boss so save/load (or any future replay
    # system) can recreate the exact visual.
    from sprites.nebula_boss import NEBULA_BOSS_ROW_COUNT
    sprite_row = random.randrange(NEBULA_BOSS_ROW_COUNT)
    tex = load_nebula_boss_texture(sprite_row)
    gv._nebula_boss = NebulaBossShip(
        tex, gv._boss_laser_tex,
        best[0], best[1],
        home.center_x, home.center_y,
        sprite_row=sprite_row,
    )
    if not hasattr(gv, "_nebula_boss_list"):
        gv._nebula_boss_list = arcade.SpriteList()
    gv._nebula_boss_list.clear()
    gv._nebula_boss_list.append(gv._nebula_boss)
    if not hasattr(gv, "_nebula_gas_clouds"):
        gv._nebula_gas_clouds = []
    gv._nebula_gas_clouds.clear()
    # Reuse the existing boss-announce banner text.
    gv._boss_announce_timer = 5.0
    gv._t_boss_announce.text = "WARNING: NEBULA BOSS"
    gv._t_boss_subtitle.text = "A gaseous horror stirs in the nebula!"
    return True


def _furthest_corner_from(x: float, y: float) -> tuple[float, float]:
    """Return the world corner (100 px inset) furthest from (x, y).

    Both ``spawn_boss`` and ``spawn_nebula_boss`` place their boss at
    the corner of Zone 1 / Zone 2 that's furthest from the Home
    Station so the player gets an approach warning before combat
    starts.  Factored out to eliminate the 6-line corner-picking
    duplication between them.
    """
    corners = (
        (100.0, 100.0),
        (WORLD_WIDTH - 100.0, 100.0),
        (100.0, WORLD_HEIGHT - 100.0),
        (WORLD_WIDTH - 100.0, WORLD_HEIGHT - 100.0),
    )
    return max(corners, key=lambda c: math.hypot(c[0] - x, c[1] - y))


def spawn_boss(gv: GameView, station_x: float, station_y: float) -> None:
    """Spawn the boss as far as possible from the station."""
    best_corner = _furthest_corner_from(station_x, station_y)
    gv._boss = BossAlienShip(
        gv._boss_tex, gv._boss_laser_tex,
        best_corner[0], best_corner[1],
        station_x, station_y,
    )
    gv._boss_list.clear()
    gv._boss_list.append(gv._boss)
    gv._boss_spawned = True
    gv._boss_announce_timer = 5.0
    gv._t_boss_announce.text = "WARNING: BOSS INCOMING"
    gv._t_boss_subtitle.text = "A massive enemy approaches your station!"
