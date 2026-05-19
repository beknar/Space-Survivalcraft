"""Pin: ``_MiniAlien`` (enemy-spawner warp zone) implements the
``take_damage`` contract so the lightsabre AOE pass can hit it.

Pre-fix the sabre swing crashed with ``AttributeError`` because
the AOE pass calls ``t.take_damage(int(blade.damage))`` on every
sprite in ``gv.alien_list``, and ``_MiniAlien`` was the lone
enemy sprite without the method (projectile hits decrement
``alien.hp`` directly in ``_update_hazards``, so the gap went
unobserved until the player swung the sabre).

In-game traceback that motivated this test:

    File "update_blade.py", line 257, in _update_blade_aoe
        t.take_damage(int(blade.damage))
    AttributeError: '_MiniAlien' object has no attribute 'take_damage'
"""
from __future__ import annotations

import arcade
import pytest
from PIL import Image as PILImage


def _make_mini_alien(x: float, y: float):
    """Construct a ``_MiniAlien`` with throwaway textures so the
    test doesn't depend on the warp zone's asset loading."""
    from zones.zone_warp_enemy import _MiniAlien
    img = PILImage.new("RGBA", (32, 32), (255, 0, 0, 255))
    tex = arcade.Texture(img)
    return _MiniAlien(tex, tex, x, y)


class TestMiniAlienTakeDamageContract:
    def test_take_damage_exists_and_decrements_hp(self):
        """The fix: ``_MiniAlien`` defines ``take_damage`` matching
        the contract every other enemy sprite implements."""
        alien = _make_mini_alien(0.0, 0.0)
        start_hp = alien.hp
        alien.take_damage(10)
        assert alien.hp == start_hp - 10

    def test_take_damage_can_drive_hp_below_zero(self):
        """The AOE handler checks ``hp <= 0`` after the call and
        routes through the reward path — so a lethal hit must let
        hp drop past zero rather than being clamped above it."""
        alien = _make_mini_alien(0.0, 0.0)
        alien.take_damage(alien.hp + 50)
        assert alien.hp <= 0


class TestLightsabreSwingHitsMiniAlien:
    """End-to-end: drive a real lightsabre swing against a real
    ``_MiniAlien`` and confirm (a) no ``AttributeError`` and
    (b) the alien took ``MELEE_DAMAGE`` of damage."""

    def test_swing_damages_mini_alien_without_crashing(self):
        from update_logic import update_weapons
        from game_view import GameView
        from constants import MELEE_DAMAGE

        gv = GameView(faction="Earth", ship_type="Cruiser",
                      skip_music=True)
        # Cycle to Melee (Basic Laser -> Mining Beam -> Melee).
        gv._cycle_weapon(); gv._cycle_weapon()

        # Place a mini alien at the lightsabre's idle hit position
        # (50 px ahead is well inside the 80 px hit radius).
        alien = _make_mini_alien(
            gv.player.center_x,
            gv.player.center_y + 80.0)
        start_hp = alien.hp
        gv.alien_list = [alien]

        # Swing — pre-fix this raised AttributeError.
        update_weapons(gv, 1 / 60, fire=True)

        assert alien.hp == start_hp - MELEE_DAMAGE

    def test_lethal_swing_routes_through_reward_path(self):
        """When the swing drops hp to 0 or below, the AOE handler
        calls ``_reward_alien_kill`` which removes the sprite from
        its sprite list.  Using a real ``arcade.SpriteList`` here so
        ``remove_from_sprite_lists`` actually unlinks the sprite."""
        from update_logic import update_weapons
        from game_view import GameView

        gv = GameView(faction="Earth", ship_type="Cruiser",
                      skip_music=True)
        gv._cycle_weapon(); gv._cycle_weapon()

        alien = _make_mini_alien(
            gv.player.center_x,
            gv.player.center_y + 80.0)
        # Force lethal: drop hp to 1 so a single swing kills it.
        alien.hp = 1

        sl = arcade.SpriteList()
        sl.append(alien)
        gv.alien_list = sl

        update_weapons(gv, 1 / 60, fire=True)

        assert alien.hp <= 0
        # Reward path removed the sprite from its list.
        assert alien not in sl
