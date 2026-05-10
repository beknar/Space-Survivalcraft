"""Per-frame homing missile + Death Blossom tick.

Extracted from ``update_logic`` in the 2026-05-10 split.  Holds the
zone-aware homing-missile target list, the per-zone collision
branches (Zone 1 aliens, Zone 2 aliens, Star Maze maze aliens +
spawners + stalkers + Nebula population), boss missile damage, and
the Death Blossom missile-spam sequence.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_view import GameView


def update_missiles(gv: GameView, dt: float) -> None:
    """Update homing missiles and check hits."""
    from sprites.explosion import HitSpark

    from zones import ZoneID
    targets = []
    if gv._zone.zone_id == ZoneID.MAIN:
        for a in gv.alien_list:
            targets.append((a.center_x, a.center_y))
    elif hasattr(gv._zone, '_aliens'):
        for a in gv._zone._aliens:
            targets.append((a.center_x, a.center_y))
    if gv._zone.zone_id == ZoneID.STAR_MAZE:
        for a in getattr(gv._zone, "_maze_aliens", ()):
            targets.append((a.center_x, a.center_y))
        for sp in getattr(gv._zone, "spawners", ()):
            if not sp.killed:
                targets.append((sp.center_x, sp.center_y))
        for st in getattr(gv._zone, "_stalkers", ()):
            if getattr(st, "hp", 0) > 0:
                targets.append((st.center_x, st.center_y))
    if gv._boss is not None and gv._boss.hp > 0:
        targets.append((gv._boss.center_x, gv._boss.center_y))
    nb_target = getattr(gv, "_nebula_boss", None)
    if nb_target is not None and nb_target.hp > 0:
        targets.append((nb_target.center_x, nb_target.center_y))

    from collisions import _apply_kill_rewards
    from character_data import bonus_iron_enemy
    from constants import ALIEN_IRON_DROP, BLUEPRINT_DROP_CHANCE_ALIEN
    for m in list(gv._missile_list):
        m.update_missile(dt, targets)
        if gv._zone.zone_id == ZoneID.MAIN:
            for a in list(gv.alien_list):
                if math.hypot(m.center_x - a.center_x, m.center_y - a.center_y) < 25:
                    gv.hit_sparks.append(HitSpark(m.center_x, m.center_y))
                    gv._spawn_explosion(m.center_x, m.center_y)
                    a.take_damage(int(m.damage))
                    if a.hp <= 0:
                        _apply_kill_rewards(
                            gv, a.center_x, a.center_y,
                            ALIEN_IRON_DROP, bonus_iron_enemy,
                            BLUEPRINT_DROP_CHANCE_ALIEN,
                        )
                        a.remove_from_sprite_lists()
                    m.remove_from_sprite_lists()
                    break
        elif gv._zone.zone_id == ZoneID.STAR_MAZE:
            from zones.zone2_world import drop_zone2_alien_loot
            from constants import (
                MAZE_ALIEN_IRON_DROP, MAZE_ALIEN_XP,
                MAZE_SPAWNER_IRON_DROP, MAZE_SPAWNER_XP,
            )
            hit = False
            for a in list(gv._zone._maze_aliens):
                if math.hypot(m.center_x - a.center_x,
                              m.center_y - a.center_y) < 25:
                    gv.hit_sparks.append(HitSpark(m.center_x, m.center_y))
                    gv._spawn_explosion(m.center_x, m.center_y)
                    a.take_damage(int(m.damage))
                    if a.hp <= 0:
                        _apply_kill_rewards(
                            gv, a.center_x, a.center_y,
                            MAZE_ALIEN_IRON_DROP, bonus_iron_enemy,
                            BLUEPRINT_DROP_CHANCE_ALIEN,
                            xp=MAZE_ALIEN_XP,
                        )
                        gv._zone._on_maze_alien_killed(a)
                        a.remove_from_sprite_lists()
                    m.remove_from_sprite_lists()
                    hit = True
                    break
            if not hit:
                for sp in gv._zone.spawners:
                    if sp.killed:
                        continue
                    if math.hypot(m.center_x - sp.center_x,
                                  m.center_y - sp.center_y) <= (
                            sp.radius + 10):
                        gv.hit_sparks.append(HitSpark(
                            m.center_x, m.center_y))
                        gv._spawn_explosion(m.center_x, m.center_y)
                        sp.take_damage(int(m.damage))
                        if sp.killed:
                            _apply_kill_rewards(
                                gv, sp.center_x, sp.center_y,
                                MAZE_SPAWNER_IRON_DROP, bonus_iron_enemy,
                                0.0, xp=MAZE_SPAWNER_XP,
                            )
                        m.remove_from_sprite_lists()
                        hit = True
                        break
            if not hit:
                for st in list(getattr(gv._zone, "_stalkers", ())):
                    if math.hypot(m.center_x - st.center_x,
                                  m.center_y - st.center_y) < 25:
                        gv.hit_sparks.append(HitSpark(
                            m.center_x, m.center_y))
                        gv._spawn_explosion(m.center_x, m.center_y)
                        st.take_damage(int(m.damage))
                        if getattr(st, "hp", 1) <= 0:
                            drop_zone2_alien_loot(gv._zone, gv, st)
                        m.remove_from_sprite_lists()
                        hit = True
                        break
            if not hit:
                for a in list(gv._zone._aliens):
                    if math.hypot(m.center_x - a.center_x,
                                  m.center_y - a.center_y) < 25:
                        gv.hit_sparks.append(HitSpark(
                            m.center_x, m.center_y))
                        gv._spawn_explosion(m.center_x, m.center_y)
                        a.take_damage(int(m.damage))
                        if a.hp <= 0:
                            drop_zone2_alien_loot(gv._zone, gv, a)
                        m.remove_from_sprite_lists()
                        break
        elif hasattr(gv._zone, '_aliens'):
            from zones.zone2_world import drop_zone2_alien_loot
            for a in list(gv._zone._aliens):
                if math.hypot(m.center_x - a.center_x, m.center_y - a.center_y) < 25:
                    gv.hit_sparks.append(HitSpark(m.center_x, m.center_y))
                    gv._spawn_explosion(m.center_x, m.center_y)
                    a.take_damage(int(m.damage))
                    if a.hp <= 0:
                        drop_zone2_alien_loot(gv._zone, gv, a)
                    m.remove_from_sprite_lists()
                    break

        if not m.sprite_lists:
            continue
        for _boss in (gv._boss, getattr(gv, "_nebula_boss", None)):
            if _boss is None or _boss.hp <= 0:
                continue
            _boss_hit = _boss.radius + 10.0
            if math.hypot(m.center_x - _boss.center_x,
                          m.center_y - _boss.center_y) < _boss_hit:
                gv.hit_sparks.append(HitSpark(m.center_x, m.center_y))
                gv._spawn_explosion(m.center_x, m.center_y)
                _boss.take_damage(int(m.damage))
                m.remove_from_sprite_lists()
                if _boss.hp <= 0:
                    from collisions import _boss_death, _nebula_boss_death
                    if _boss is gv._boss:
                        _boss_death(gv)
                    else:
                        _nebula_boss_death(gv)
                break


def update_death_blossom(gv: GameView, dt: float) -> None:
    """Update death blossom sequence if active."""
    if not gv._death_blossom_active:
        return
    from constants import DEATH_BLOSSOM_FIRE_RATE, DEATH_BLOSSOM_MISSILES_PER_VOLLEY, DEATH_BLOSSOM_HP_AFTER
    from sprites.missile import HomingMissile

    gv.player.heading = (gv.player.heading + gv.player._rot_speed * dt) % 360
    gv.player.angle = gv.player.heading

    gv._death_blossom_timer -= dt
    if gv._death_blossom_timer <= 0 and gv._death_blossom_missiles_left > 0:
        gv._death_blossom_timer = DEATH_BLOSSOM_FIRE_RATE
        count = min(DEATH_BLOSSOM_MISSILES_PER_VOLLEY, gv._death_blossom_missiles_left)
        for i in range(count):
            angle = (360.0 / count) * i + gv.player.heading
            m = HomingMissile(gv._missile_tex,
                              gv.player.center_x, gv.player.center_y, angle)
            gv._missile_list.append(m)
        gv._death_blossom_missiles_left -= count

    if gv._death_blossom_missiles_left <= 0:
        gv._death_blossom_active = False
        gv.player.shields = 0
        gv.player.hp = DEATH_BLOSSOM_HP_AFTER
