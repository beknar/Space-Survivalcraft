"""Regression tests for the load-after-load character bleed fix.

Bug history (2026-05-04): loading save B after save A left the in-memory
``audio.character_name`` pointing at save A's character.  The visible /
audible character (HUD name, music, build/craft cost multipliers,
refugee dialogue tree) was wrong, and weapon damage/cooldown bonuses
from BOTH characters were stacked additively.

Three failure modes pinned here:

  * **Constructor reads stale global** — ``GameView.__init__`` calls
    ``_apply_character_weapon_bonuses`` BEFORE ``restore_state``
    updates ``audio.character_name``.  Fix: thread ``character_name``
    through the constructor so the global is set first.

  * **Truthiness guard skipped empty assignment** — ``restore_state``
    used ``if saved_char: audio.character_name = saved_char`` which
    let an empty/missing field silently inherit the previous value.
    Fix: unconditional assignment.

  * **Additive weapon bonuses** — each
    ``_apply_character_weapon_bonuses`` call did ``wpn.damage += dmg``
    instead of ``wpn.damage = baseline + dmg``.  Fix:
    ``Weapon.__init__`` now stores ``_base_*`` attrs and the bonus
    helper recomputes from baseline.
"""
from __future__ import annotations

import pytest

from settings import audio


@pytest.fixture
def _restore_global_character():
    """Save and restore the global ``audio.character_name`` so tests
    don't leak state into each other."""
    prev = audio.character_name
    yield
    audio.character_name = prev


# ── Fix A: constructor accepts character_name + sets global ───────────

class TestConstructorSetsCharacterGlobal:
    def test_character_name_kw_sets_global(self, _restore_global_character):
        from game_view import GameView
        audio.character_name = "Tara"
        GameView(faction="Earth", ship_type="Cruiser",
                 character_name="Vex", skip_music=True)
        assert audio.character_name == "Vex"

    def test_no_character_name_kw_leaves_global_alone(
            self, _restore_global_character):
        from game_view import GameView
        audio.character_name = "Tara"
        GameView(faction="Earth", ship_type="Cruiser", skip_music=True)
        # Backwards-compat: the existing call sites that DON'T pass
        # character_name keep the historical behaviour (don't touch
        # the global), so the new-game / selection-view flow that
        # sets character_name BEFORE constructing GameView still
        # works unchanged.
        assert audio.character_name == "Tara"

    def test_empty_character_name_kw_clears_global(
            self, _restore_global_character):
        """Explicit empty string means 'default character', not
        'preserve previous'."""
        from game_view import GameView
        audio.character_name = "Tara"
        GameView(faction="Earth", ship_type="Cruiser",
                 character_name="", skip_music=True)
        assert audio.character_name == ""


# ── Fix B: restore_state unconditional assignment ─────────────────────

class TestRestoreStateAlwaysAssignsCharacter:
    def test_missing_character_name_clears_global(
            self, _restore_global_character):
        """Save dict without a character_name field → global resets
        to '' instead of inheriting the previous in-memory value."""
        from game_view import GameView
        from game_save import save_to_dict, restore_state
        audio.character_name = "Vex"
        gv = GameView(faction="Earth", ship_type="Cruiser",
                      character_name="Vex", skip_music=True)
        # Build a save dict, strip the character_name field, then
        # restore.  Mirrors a corrupt or older-format save.
        data = save_to_dict(gv, "test")
        data.pop("character_name", None)
        # Pretend a fresh GV was just constructed for a different
        # character.
        audio.character_name = "Tara"
        restore_state(gv, data)
        assert audio.character_name == ""

    def test_explicit_character_name_overrides_previous(
            self, _restore_global_character):
        from game_view import GameView
        from game_save import save_to_dict, restore_state
        audio.character_name = "Vex"
        gv = GameView(faction="Earth", ship_type="Cruiser",
                      character_name="Vex", skip_music=True)
        data = save_to_dict(gv, "test")
        # Hand-edit so the save says character "Tara".
        data["character_name"] = "Tara"
        restore_state(gv, data)
        assert audio.character_name == "Tara"


# ── Fix C: weapon-bonus application is idempotent ─────────────────────

class TestWeaponBonusIdempotent:
    def test_weapon_baselines_captured_at_construction(
            self, _restore_global_character):
        from game_view import GameView
        audio.character_name = ""  # clean slate, no character bonus
        gv = GameView(faction="Earth", ship_type="Cruiser",
                      character_name="", skip_music=True)
        for w in gv._weapons:
            assert hasattr(w, "_base_damage")
            assert hasattr(w, "_base_cooldown")
            assert hasattr(w, "_base_proj_speed")
            assert hasattr(w, "_base_max_range")

    def test_repeated_application_does_not_stack(
            self, _restore_global_character):
        """Three back-to-back calls should leave weapons in the
        same state as one call.  Pre-fix, each call ADDED to the
        running totals."""
        from game_view import GameView
        audio.character_name = "Vex"
        gv = GameView(faction="Earth", ship_type="Cruiser",
                      character_name="Vex", skip_music=True)
        # Capture the post-one-application stats for each Basic Laser.
        snapshots = []
        for w in gv._weapons:
            if w.name == "Basic Laser":
                snapshots.append((w, w.damage, w.cooldown,
                                  w._proj_speed, w._max_range))
        # Re-apply twice more.
        gv._apply_character_weapon_bonuses()
        gv._apply_character_weapon_bonuses()
        for (w, dmg, cd, spd, rng) in snapshots:
            assert w.damage == dmg
            assert w.cooldown == cd
            assert w._proj_speed == spd
            assert w._max_range == rng


# ── End-to-end: load-after-load doesn't bleed character ───────────────

class TestLoadAfterLoadNoBleed:
    """The headline regression: load save A, then load save B —
    audio.character_name and weapon stats must reflect save B, not
    save A.  Simulates the file-on-disk path without writing files
    by going through ``save_to_dict`` + ``restore_state``."""

    def test_loading_second_save_overwrites_first_character(
            self, _restore_global_character):
        from game_view import GameView
        from game_save import save_to_dict, restore_state
        # Simulate save A: character "Vex".
        audio.character_name = "Vex"
        gv_a = GameView(faction="Earth", ship_type="Cruiser",
                        character_name="Vex", skip_music=True)
        save_a = save_to_dict(gv_a, "save_a")

        # Simulate save B: character "Tara".
        audio.character_name = "Tara"
        gv_b = GameView(faction="Earth", ship_type="Cruiser",
                        character_name="Tara", skip_music=True)
        save_b = save_to_dict(gv_b, "save_b")

        # User loads save A first.  In production load_game()
        # builds a fresh GameView and calls restore_state — emulate
        # that here with two fresh instances so the test mirrors
        # the real flow.
        gv_load_a = GameView(
            faction=save_a.get("faction"),
            ship_type=save_a.get("ship_type"),
            character_name=save_a.get("character_name"),
            skip_music=True)
        restore_state(gv_load_a, save_a)
        assert audio.character_name == "Vex"

        # NOW the user loads save B.  Pre-fix: audio.character_name
        # stays "Vex" because the constructor read the stale global
        # before restore_state could update it.
        gv_load_b = GameView(
            faction=save_b.get("faction"),
            ship_type=save_b.get("ship_type"),
            character_name=save_b.get("character_name"),
            skip_music=True)
        restore_state(gv_load_b, save_b)
        assert audio.character_name == "Tara", (
            "Loading save B left audio.character_name pointing at "
            "save A's character — load-after-load bleed regression")

    def test_weapon_damage_does_not_stack_across_loads(
            self, _restore_global_character):
        """After load A then load B, the loaded GV's weapons must
        have ONLY save B's character bonus on top of baseline — not
        A's bonus + B's bonus stacked."""
        from game_view import GameView
        from game_save import save_to_dict, restore_state
        # Build a fresh "no character" GV to grab the baselines.
        audio.character_name = ""
        gv_baseline = GameView(faction="Earth", ship_type="Cruiser",
                               character_name="", skip_music=True)
        baseline_dmg = next(w._base_damage for w in gv_baseline._weapons
                            if w.name == "Basic Laser")

        # Save A under character "Vex".
        audio.character_name = "Vex"
        gv_a = GameView(faction="Earth", ship_type="Cruiser",
                        character_name="Vex", skip_music=True)
        save_a = save_to_dict(gv_a, "save_a")

        # Save B under character "Tara".
        audio.character_name = "Tara"
        gv_b = GameView(faction="Earth", ship_type="Cruiser",
                        character_name="Tara", skip_music=True)
        save_b = save_to_dict(gv_b, "save_b")

        # Load A then B (mirroring load_game's fresh-GV flow).
        gv_load_a = GameView(
            faction=save_a.get("faction"),
            ship_type=save_a.get("ship_type"),
            character_name=save_a.get("character_name"),
            skip_music=True)
        restore_state(gv_load_a, save_a)
        gv_load_b = GameView(
            faction=save_b.get("faction"),
            ship_type=save_b.get("ship_type"),
            character_name=save_b.get("character_name"),
            skip_music=True)
        restore_state(gv_load_b, save_b)

        # Compute what gv_load_b's Basic Laser damage SHOULD be:
        # baseline + Tara's bonus at gv_load_b's level.
        from character_data import laser_damage_bonus
        expected_bonus = laser_damage_bonus("Tara", gv_load_b._char_level)
        loaded_dmg = next(w.damage for w in gv_load_b._weapons
                          if w.name == "Basic Laser")
        assert loaded_dmg == baseline_dmg + expected_bonus, (
            f"Expected {baseline_dmg} + {expected_bonus} = "
            f"{baseline_dmg + expected_bonus}, got {loaded_dmg} — "
            "save A's character bonus stacked onto save B's load")
