"""Tests for the ParkedShip sprite and multi-ship system."""
from __future__ import annotations

import pytest
from PIL import Image as PILImage

import arcade

from constants import (
    SHIP_TYPES, SHIP_LEVEL_HP_BONUS, SHIP_LEVEL_SHIELD_BONUS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def dummy_texture():
    img = PILImage.new("RGBA", (32, 32), (200, 0, 0, 255))
    return arcade.Texture(img)


@pytest.fixture
def parked_ship_l1(monkeypatch, dummy_texture):
    """A level 1 Cruiser ParkedShip with a monkeypatched texture."""
    from sprites.parked_ship import ParkedShip
    from sprites.player import PlayerShip
    monkeypatch.setattr(PlayerShip, "_extract_ship_texture",
                        staticmethod(lambda *a, **kw: dummy_texture))
    return ParkedShip("Earth", "Cruiser", 1, 100.0, 200.0, heading=45.0)


@pytest.fixture
def parked_ship_l2(monkeypatch, dummy_texture):
    """A level 2 Cruiser ParkedShip."""
    from sprites.parked_ship import ParkedShip
    from sprites.player import PlayerShip
    monkeypatch.setattr(PlayerShip, "_extract_ship_texture",
                        staticmethod(lambda *a, **kw: dummy_texture))
    return ParkedShip("Earth", "Cruiser", 2, 500.0, 600.0, heading=90.0)


# ═══════════════════════════════════════════════════════════════════════════
#  Construction
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipInit:
    def test_position_and_heading(self, parked_ship_l1):
        ps = parked_ship_l1
        assert ps.center_x == 100.0
        assert ps.center_y == 200.0
        assert ps.heading == 45.0
        assert ps.angle == 45.0

    def test_faction_and_type(self, parked_ship_l1):
        ps = parked_ship_l1
        assert ps.faction == "Earth"
        assert ps.ship_type == "Cruiser"
        assert ps.ship_level == 1

    def test_hp_level_1(self, parked_ship_l1):
        ps = parked_ship_l1
        expected_hp = SHIP_TYPES["Cruiser"]["hp"]
        assert ps.hp == expected_hp
        assert ps.max_hp == expected_hp

    def test_hp_level_2_includes_bonus(self, parked_ship_l2):
        ps = parked_ship_l2
        base_hp = SHIP_TYPES["Cruiser"]["hp"]
        expected_hp = base_hp + SHIP_LEVEL_HP_BONUS
        assert ps.hp == expected_hp
        assert ps.max_hp == expected_hp

    def test_shields_level_1(self, parked_ship_l1):
        ps = parked_ship_l1
        expected = SHIP_TYPES["Cruiser"]["shields"]
        assert ps.shields == expected
        assert ps.max_shields == expected

    def test_shields_level_2_includes_bonus(self, parked_ship_l2):
        ps = parked_ship_l2
        base = SHIP_TYPES["Cruiser"]["shields"]
        expected = base + SHIP_LEVEL_SHIELD_BONUS
        assert ps.shields == expected

    def test_empty_cargo_and_modules(self, parked_ship_l1):
        ps = parked_ship_l1
        assert ps.cargo_items == {}
        assert ps.module_slots == []

    def test_no_hit_flash_initially(self, parked_ship_l1):
        assert parked_ship_l1._hit_timer == 0.0


# ═══════════════════════════════════════════════════════════════════════════
#  Damage routing (shields → HP)
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipDamage:
    def test_damage_absorbed_by_shields(self, parked_ship_l1):
        ps = parked_ship_l1
        original_hp = ps.hp
        ps.take_damage(5)
        assert ps.hp == original_hp  # HP untouched
        assert ps.shields == ps.max_shields - 5

    def test_damage_overflows_to_hp(self, parked_ship_l1):
        ps = parked_ship_l1
        shields = ps.shields
        ps.take_damage(shields + 10)
        assert ps.shields == 0
        assert ps.hp == ps.max_hp - 10

    def test_damage_clamps_hp_at_zero(self, parked_ship_l1):
        ps = parked_ship_l1
        ps.take_damage(99999)
        assert ps.hp == 0
        assert ps.shields == 0

    def test_hit_flash_on_damage(self, parked_ship_l1):
        ps = parked_ship_l1
        ps.take_damage(1)
        assert ps._hit_timer > 0.0
        assert ps.color == (255, 100, 100, 255)

    def test_hit_flash_clears_after_update(self, parked_ship_l1):
        ps = parked_ship_l1
        ps.take_damage(1)
        ps.update_parked(1.0)  # large dt to clear timer
        assert ps._hit_timer == 0.0
        assert ps.color == (255, 255, 255, 255)


# ═══════════════════════════════════════════════════════════════════════════
#  Cargo and module storage
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipCargo:
    def test_store_and_retrieve_cargo(self, parked_ship_l1):
        ps = parked_ship_l1
        ps.cargo_items[(0, 0)] = ("iron", 50)
        ps.cargo_items[(0, 1)] = ("copper", 20)
        assert ps.cargo_items[(0, 0)] == ("iron", 50)
        assert ps.cargo_items[(0, 1)] == ("copper", 20)

    def test_store_module_slots(self, parked_ship_l1):
        ps = parked_ship_l1
        ps.module_slots = ["armor_plate", None, "engine_booster", None]
        assert ps.module_slots[0] == "armor_plate"
        assert ps.module_slots[1] is None
        assert ps.module_slots[2] == "engine_booster"


# ═══════════════════════════════════════════════════════════════════════════
#  Collision handler — parked ship damage from projectiles
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipCollisions:
    def test_alien_laser_damages_parked_ship(self, stub_gv, monkeypatch,
                                              dummy_texture):
        """Alien projectile hitting a parked ship deals damage."""
        from sprites.parked_ship import ParkedShip
        from sprites.player import PlayerShip
        from sprites.projectile import Projectile
        from collisions import handle_parked_ship_damage

        monkeypatch.setattr(PlayerShip, "_extract_ship_texture",
                            staticmethod(lambda *a, **kw: dummy_texture))
        ps = ParkedShip("Earth", "Cruiser", 1, 100.0, 100.0)
        original_hp = ps.hp
        original_shields = ps.shields
        stub_gv._parked_ships.append(ps)

        # Create alien projectile at same position
        proj = Projectile(dummy_texture, 100.0, 100.0, 0, 500, 800,
                          damage=10)
        stub_gv.alien_projectile_list.append(proj)

        handle_parked_ship_damage(stub_gv)

        assert ps.shields < original_shields or ps.hp < original_hp
        assert len(stub_gv.alien_projectile_list) == 0  # consumed

    def test_player_laser_damages_parked_ship(self, stub_gv, monkeypatch,
                                               dummy_texture):
        """Player projectile hitting a parked ship deals damage (friendly fire)."""
        from sprites.parked_ship import ParkedShip
        from sprites.player import PlayerShip
        from sprites.projectile import Projectile
        from collisions import handle_parked_ship_damage

        monkeypatch.setattr(PlayerShip, "_extract_ship_texture",
                            staticmethod(lambda *a, **kw: dummy_texture))
        ps = ParkedShip("Earth", "Cruiser", 1, 100.0, 100.0)
        original_shields = ps.shields
        stub_gv._parked_ships.append(ps)

        proj = Projectile(dummy_texture, 100.0, 100.0, 0, 500, 800,
                          damage=25)
        stub_gv.projectile_list.append(proj)

        handle_parked_ship_damage(stub_gv)

        assert ps.shields < original_shields
        assert len(stub_gv.projectile_list) == 0

    def test_destroyed_ship_drops_cargo(self, stub_gv, monkeypatch,
                                         dummy_texture):
        """Destroying a parked ship spawns explosion and drops cargo."""
        from sprites.parked_ship import ParkedShip
        from sprites.player import PlayerShip
        from sprites.projectile import Projectile
        from collisions import handle_parked_ship_damage

        monkeypatch.setattr(PlayerShip, "_extract_ship_texture",
                            staticmethod(lambda *a, **kw: dummy_texture))
        # Stub _blueprint_tex for blueprint pickup creation
        stub_gv._blueprint_tex = dummy_texture

        ps = ParkedShip("Earth", "Cruiser", 1, 100.0, 100.0)
        ps.hp = 1  # nearly dead
        ps.shields = 0
        ps.cargo_items[(0, 0)] = ("iron", 30)
        ps.module_slots = ["armor_plate"]
        stub_gv._parked_ships.append(ps)

        proj = Projectile(dummy_texture, 100.0, 100.0, 0, 500, 800,
                          damage=50)
        stub_gv.alien_projectile_list.append(proj)

        handle_parked_ship_damage(stub_gv)

        assert len(stub_gv._parked_ships) == 0  # removed
        assert len(stub_gv.calls["explosion"]) > 0  # explosion spawned
        assert len(stub_gv.calls["iron_pickup"]) > 0  # iron dropped
        assert len(stub_gv.blueprint_pickup_list) > 0  # module dropped

    def test_no_crash_with_empty_parked_ships(self, stub_gv):
        """Handler doesn't crash when _parked_ships is empty."""
        from collisions import handle_parked_ship_damage
        handle_parked_ship_damage(stub_gv)  # should be a no-op


# ═══════════════════════════════════════════════════════════════════════════
#  Serialization round trip
# ═══════════════════════════════════════════════════════════════════════════

class TestParkedShipSerialization:
    def test_serialize_and_restore(self, monkeypatch, dummy_texture):
        """ParkedShip survives a JSON-like serialize → restore round trip."""
        from sprites.parked_ship import ParkedShip
        from sprites.player import PlayerShip

        monkeypatch.setattr(PlayerShip, "_extract_ship_texture",
                            staticmethod(lambda *a, **kw: dummy_texture))

        ps = ParkedShip("Colonial", "Cruiser", 3, 1000.0, 2000.0, heading=180.0)
        ps.hp = 50
        ps.shields = 10
        ps.cargo_items[(0, 0)] = ("iron", 99)
        ps.cargo_items[(1, 2)] = ("copper", 15)
        ps.module_slots = ["armor_plate", None, "shield_booster"]

        # Serialize
        data = {
            "faction": ps.faction, "ship_type": ps.ship_type,
            "ship_level": ps.ship_level,
            "x": ps.center_x, "y": ps.center_y, "heading": ps.heading,
            "hp": ps.hp, "max_hp": ps.max_hp,
            "shields": ps.shields, "max_shields": ps.max_shields,
            "cargo_items": [
                {"r": r, "c": c, "type": it, "count": ct}
                for (r, c), (it, ct) in ps.cargo_items.items()
            ],
            "module_slots": ps.module_slots,
        }

        # Restore
        ps2 = ParkedShip(
            faction=data["faction"], ship_type=data["ship_type"],
            ship_level=data["ship_level"],
            x=data["x"], y=data["y"], heading=data["heading"],
        )
        ps2.hp = data["hp"]
        ps2.max_hp = data["max_hp"]
        ps2.shields = data["shields"]
        ps2.max_shields = data["max_shields"]
        for entry in data["cargo_items"]:
            ps2.cargo_items[(entry["r"], entry["c"])] = (entry["type"], entry["count"])
        ps2.module_slots = data["module_slots"]

        assert ps2.faction == "Colonial"
        assert ps2.ship_type == "Cruiser"
        assert ps2.ship_level == 3
        assert ps2.center_x == 1000.0
        assert ps2.center_y == 2000.0
        assert ps2.heading == 180.0
        assert ps2.hp == 50
        assert ps2.shields == 10
        assert ps2.cargo_items[(0, 0)] == ("iron", 99)
        assert ps2.cargo_items[(1, 2)] == ("copper", 15)
        assert ps2.module_slots == ["armor_plate", None, "shield_booster"]


# ═══════════════════════════════════════════════════════════════════════════
#  AI Pilot module
# ═══════════════════════════════════════════════════════════════════════════

class TestAIPilot:
    def test_has_ai_pilot_flag_reflects_module_slots(self, parked_ship_l1):
        ps = parked_ship_l1
        assert ps.has_ai_pilot is False
        ps.module_slots = ["armor_plate", None]
        assert ps.has_ai_pilot is False
        ps.module_slots.append("ai_pilot")
        assert ps.has_ai_pilot is True

    def test_update_ai_without_module_is_noop(self, parked_ship_l1, dummy_texture):
        ps = parked_ship_l1
        plist = arcade.SpriteList()
        x0, y0 = ps.center_x, ps.center_y
        ps.update_ai(1.0, (0.0, 0.0), [], plist, dummy_texture)
        assert (ps.center_x, ps.center_y) == (x0, y0)
        assert len(plist) == 0

    def test_update_ai_returns_to_patrol_leash(self, parked_ship_l1, dummy_texture):
        from constants import AI_PILOT_PATROL_RADIUS
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot"]
        ps.center_x = 2000.0
        ps.center_y = 0.0
        plist = arcade.SpriteList()
        ps.update_ai(1.0, (0.0, 0.0), [], plist, dummy_texture)
        # Clamp pins the ship to the leash edge when it strays far outside.
        import math
        dist = math.hypot(ps.center_x, ps.center_y)
        assert dist <= AI_PILOT_PATROL_RADIUS + 0.5

    def test_update_ai_fires_at_target_in_range(self, parked_ship_l1, dummy_texture):
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot"]
        ps.center_x = 0.0
        ps.center_y = 0.0
        # A target sitting close to home AND the ship.
        target = type("T", (), {"center_x": 120.0, "center_y": 0.0, "hp": 50})()
        plist = arcade.SpriteList()
        ps.update_ai(1.0, (0.0, 0.0), [target], plist, dummy_texture)
        assert len(plist) == 1

    def test_update_ai_nearest_target_selected(self, parked_ship_l1, dummy_texture):
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot"]
        ps.center_x = 0.0; ps.center_y = 0.0
        far = type("T", (), {"center_x": 300.0, "center_y": 0.0, "hp": 50})()
        near = type("T", (), {"center_x": 80.0, "center_y": 0.0, "hp": 50})()
        plist = arcade.SpriteList()
        ps.update_ai(0.01, (0.0, 0.0), [far, near], plist, dummy_texture)
        # After firing, heading should point at the near target (+x = 90 deg).
        assert 85.0 <= ps.heading <= 95.0

    def test_update_ai_ignores_targets_outside_leash_plus_detect(
            self, parked_ship_l1, dummy_texture):
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot"]
        ps.center_x = 0.0; ps.center_y = 0.0
        # Target is near the ship but extremely far from home.
        stray = type("T", (), {"center_x": 50.0, "center_y": 0.0,
                                 "hp": 50})()
        plist = arcade.SpriteList()
        ps.update_ai(1.0, (5000.0, 5000.0), [stray], plist, dummy_texture)
        assert len(plist) == 0  # target rejected as outside leash

    def test_update_ai_no_home_holds_position(self, parked_ship_l1, dummy_texture):
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot"]
        start = (ps.center_x, ps.center_y)
        plist = arcade.SpriteList()
        target = type("T", (), {"center_x": 0.0, "center_y": 0.0, "hp": 50})()
        ps.update_ai(1.0, None, [target], plist, dummy_texture)
        assert (ps.center_x, ps.center_y) == start  # no home → no-op
        assert len(plist) == 0

    def test_update_ai_fire_cooldown_prevents_rapid_shots(
            self, parked_ship_l1, dummy_texture):
        from constants import AI_PILOT_FIRE_COOLDOWN
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot"]
        ps.center_x = 0.0; ps.center_y = 0.0
        target = type("T", (), {"center_x": 120.0, "center_y": 0.0, "hp": 50})()
        plist = arcade.SpriteList()
        ps.update_ai(0.01, (0.0, 0.0), [target], plist, dummy_texture)
        ps.update_ai(0.01, (0.0, 0.0), [target], plist, dummy_texture)
        assert len(plist) == 1  # second tick still on cooldown
        # Tick past the cooldown.
        ps.update_ai(AI_PILOT_FIRE_COOLDOWN + 0.1,
                     (0.0, 0.0), [target], plist, dummy_texture)
        assert len(plist) == 2

    def test_update_ai_approaches_distant_target(
            self, parked_ship_l1, dummy_texture):
        from constants import AI_PILOT_SPEED
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot"]
        ps.center_x = 0.0; ps.center_y = 0.0
        # Target is far enough that the ship should advance.
        target = type("T", (), {"center_x": 500.0, "center_y": 0.0,
                                 "hp": 50})()
        plist = arcade.SpriteList()
        ps.update_ai(0.1, (0.0, 0.0), [target], plist, dummy_texture)
        # Moved roughly AI_PILOT_SPEED * dt along +x.
        assert ps.center_x > 0.0
        assert ps.center_x <= AI_PILOT_SPEED * 0.1 + 0.5

    def test_update_ai_skips_dead_targets(self, parked_ship_l1, dummy_texture):
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot"]
        ps.center_x = 0.0; ps.center_y = 0.0
        dead = type("T", (), {"center_x": 80.0, "center_y": 0.0, "hp": 0})()
        plist = arcade.SpriteList()
        ps.update_ai(0.1, (0.0, 0.0), [dead], plist, dummy_texture)
        assert len(plist) == 0

    def test_update_ai_no_crash_without_laser_tex(
            self, parked_ship_l1):
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot"]
        ps.center_x = 0.0; ps.center_y = 0.0
        target = type("T", (), {"center_x": 120.0, "center_y": 0.0, "hp": 50})()
        plist = arcade.SpriteList()
        ps.update_ai(1.0, (0.0, 0.0), [target], plist, None)
        assert len(plist) == 0  # no texture → no projectile

    def test_ai_pilot_serialises_with_module_slots(self, parked_ship_l1):
        ps = parked_ship_l1
        ps.module_slots = ["ai_pilot", "armor_plate"]
        assert ps.has_ai_pilot is True
        # module_slots is the persisted field, which save/load already covers
        assert "ai_pilot" in ps.module_slots
