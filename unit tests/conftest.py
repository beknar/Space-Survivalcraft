"""Shared fixtures for Space Survivalcraft unit tests."""
from __future__ import annotations

import sys
import os
from types import SimpleNamespace

# Add project root to sys.path so game modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from PIL import Image as PILImage
import arcade


@pytest.fixture
def dummy_texture() -> arcade.Texture:
    """A 32x32 red RGBA PIL image wrapped as an arcade.Texture."""
    img = PILImage.new("RGBA", (32, 32), (255, 0, 0, 255))
    return arcade.Texture(img)


@pytest.fixture
def dummy_texture_list() -> list[arcade.Texture]:
    """A list of 6 dummy textures (for shield / explosion frame lists)."""
    textures = []
    for i in range(6):
        shade = 40 * i
        img = PILImage.new("RGBA", (32, 32), (shade, shade, shade, 255))
        textures.append(arcade.Texture(img))
    return textures


# ── Stub GameView fixtures ────────────────────────────────────────────────
#
# These let zone update loops, collision handlers, and other GameView-coupled
# code be unit-tested without spinning up a real Arcade window. Each stub
# attribute records what was called or how state changed so tests can assert
# against it.

class StubPlayer(arcade.Sprite):
    """Real ``arcade.Sprite`` masquerading as the player ship.

    ``arcade.check_for_collision_with_list`` requires its first argument to
    be a Sprite subclass, so we can't just use ``SimpleNamespace`` here.
    The class still has all the player attributes that zone update loops
    read so it slots into a ``StubGameView`` cleanly.

    Use ``cd > 0`` to simulate a recent collision (cooldown still ticking),
    which is the branch that triggered the Zone 2 ``UnboundLocalError``
    regression — handlers below the collision-cooldown gate must still work.
    """

    def __init__(self, x: float = 3200.0, y: float = 3200.0,
                 vx: float = 0.0, vy: float = 0.0,
                 hp: int = 100, max_hp: int = 100,
                 shields: int = 0, max_shields: int = 0,
                 cd: float = 0.0):
        # 32x32 dummy texture so the sprite has a hitbox for collision checks
        img = PILImage.new("RGBA", (32, 32), (0, 200, 255, 255))
        super().__init__(path_or_texture=arcade.Texture(img))
        self.center_x = x
        self.center_y = y
        self.vel_x = vx
        self.vel_y = vy
        self.hp = hp
        self.max_hp = max_hp
        self.shields = shields
        self.max_shields = max_shields
        self._collision_cd = cd
        self._shield_acc = 0.0
        self.heading = 0.0
        self.guns = 1


class StubGameView(SimpleNamespace):
    """Duck-typed GameView for unit tests of zone/collision/update logic.

    Records side effects on the ``calls`` dict so tests can assert that the
    code under test invoked the right callbacks (damage, shake, transition,
    etc.) without exercising real Arcade rendering or audio.
    """

    def __init__(self, player: StubPlayer | None = None) -> None:
        self.calls: dict[str, list] = {
            "damage": [], "shake": 0, "explosion": [],
            "iron_pickup": [], "blueprint_pickup": [], "xp": [],
            "transition": [], "flash": [], "play_sound": [],
        }

        super().__init__(
            player=player or StubPlayer(),

            # Sprite lists touched by zone update / collisions
            building_list=arcade.SpriteList(),
            alien_list=arcade.SpriteList(),
            alien_projectile_list=arcade.SpriteList(),
            iron_pickup_list=arcade.SpriteList(),
            blueprint_pickup_list=arcade.SpriteList(),
            asteroid_list=arcade.SpriteList(),
            projectile_list=arcade.SpriteList(),
            turret_projectile_list=arcade.SpriteList(),
            hit_sparks=[],

            # Wormhole / zone state
            _wormholes=[],
            _wormhole_list=arcade.SpriteList(),

            # Visual effect state
            _use_glow=(0, 0, 0, 0),
            _use_glow_timer=0.0,

            # Sounds (None — collision handlers play through arcade.play_sound
            # which we monkey-patch out in tests, or just accept the no-op)
            _victory_snd=None,
            _bump_snd=None,
            _explosion_snd=None,

            # Fog of war
            _fog_grid=None,
            _fog_revealed=0,

            # Misc state
            _trade_station=None,
            _char_level=1,
            _char_xp=0,
            _boss=None,
            _module_slots=[None] * 4,
            calls=self.calls,
        )

        # Bind tracked callback methods. Each appends its args to
        # self.calls[key] so tests can assert what was called.
        def _recorder(key):
            """Return a callable that records all calls under ``key``."""
            def record(*a, **kw):
                self.calls[key].append((a, kw) if kw else a)
            return record

        self._apply_damage_to_player = lambda d: self.calls["damage"].append(d)
        self._trigger_shake = lambda: self.calls.__setitem__(
            "shake", self.calls["shake"] + 1)
        self._spawn_explosion = _recorder("explosion")
        self._spawn_iron_pickup = _recorder("iron_pickup")
        self._spawn_blueprint_pickup = _recorder("blueprint_pickup")
        self._add_xp = lambda v: self.calls["xp"].append(v)
        self._transition_zone = _recorder("transition")
        self._flash_game_msg = _recorder("flash")


@pytest.fixture
def stub_player() -> StubPlayer:
    """Player at the centre of Zone 2, no cooldown."""
    return StubPlayer()


@pytest.fixture
def stub_gv(stub_player) -> StubGameView:
    """A StubGameView with a default StubPlayer attached."""
    return StubGameView(stub_player)
