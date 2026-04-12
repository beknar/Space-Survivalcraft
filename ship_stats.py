"""Ship statistics overlay — shows faction, ship type, level, and stats with module mods."""
from __future__ import annotations

import glob
import os
import random

import arcade

from constants import SCREEN_WIDTH, SCREEN_HEIGHT, MODULE_TYPES

_PANEL_W = 380
_PANEL_H = 520

_BIO_PANEL_W = 360
_BIO_PANEL_H = 520
_PORTRAIT_H = 220

_PORTRAITS_DIR = os.path.join("characters", "portraits")

_BACKSTORIES: dict[str, str] = {
    "Debra": (
        "Debra's smile hides a sadness that she barely overcomes.  "
        "She laughs, smiles, tells jokes, whatever she has to do to keep going.  "
        "The shadow of the Double-Star War looms over her, tainting everything she does.  "
        "She believes that her light can overcome her past, and she wants you to join her "
        "on her journey.  Will you help her escape?  Or will you help Debra overcome her "
        "personal darkness?"
    ),
    "Ellie": (
        "Tara isn't fleeing.  She's chasing vengeance.  Every corner, every doorway could "
        "reveal a clue to the whereabouts of the villains of the Double-Star War that "
        "betrayed her and others.  What could these people have done that would cause a "
        "young woman to give up her life to hunt criminals?"
    ),
    "Tara": (
        "Tara is a treasure hunter looking for the technology of the ancients.  After "
        "having her work destroyed during the Double-Star War, she now searches for "
        "vestiges of a past glory that she suspects is greater than the current status quo.  "
        "A few clues from distant dig sites have led her here.  Is she really looking for "
        "answers from the past or does she have a hidden motive?"
    ),
}


class ShipStats:
    """Non-pausing overlay showing the player's ship statistics."""

    def __init__(self) -> None:
        self.open: bool = False

        try:
            self._window = arcade.get_window()
        except Exception:
            self._window = None

        self._t_title = arcade.Text("SHIP STATS", 0, 0,
                                    arcade.color.LIGHT_BLUE, 14, bold=True,
                                    anchor_x="center", anchor_y="center")
        self._lines: list[arcade.Text] = [
            arcade.Text("", 0, 0, arcade.color.WHITE, 9)
            for _ in range(26)
        ]

        # Character bio panel state
        self._portrait_texture: arcade.Texture | None = None
        self._bio_title = arcade.Text("", 0, 0, arcade.color.KHAKI, 13,
                                      bold=True, anchor_x="center",
                                      anchor_y="center")
        self._bio_lines: list[arcade.Text] = [
            arcade.Text("", 0, 0, arcade.color.WHITE, 9,
                        multiline=True, width=_BIO_PANEL_W - 32)
            for _ in range(1)
        ]

    def toggle(self) -> None:
        self.open = not self.open

    def refresh(self, player, faction: str, ship_type: str, modules: list,
                char_name: str = "", char_xp: int = 0, char_level: int = 1) -> None:
        """Update cached stats from the player ship, showing module modifications."""
        # Build a map of which module affects which stat
        mod_effects: dict[str, tuple[str, int | float]] = {}
        for mod in modules:
            if mod is None:
                continue
            info = MODULE_TYPES.get(mod)
            if info:
                mod_effects[info["effect"]] = (info["label"], info["value"])

        def _fmt(label: str, base, current, effect_key: str, unit: str = "",
                 color=arcade.color.WHITE) -> tuple[str, tuple]:
            mod = mod_effects.get(effect_key)
            if mod:
                mod_label, mod_val = mod
                sign = "+" if mod_val >= 0 else ""
                return (f"{label}: {base}{unit} -> {current}{unit}  "
                        f"({sign}{mod_val} {mod_label})", (200, 180, 80))
            return f"{label}: {current}{unit}", color

        faction_str = faction or "Legacy"
        ship_str = ship_type or "Classic"
        base = player

        from character_data import CHARACTERS, xp_for_next_level
        char_class = ""
        if char_name and char_name in CHARACTERS:
            char_class = f" ({CHARACTERS[char_name]['class']})"
        next_xp = xp_for_next_level(char_xp)
        xp_str = f"{char_xp}/{next_xp}" if next_xp else f"{char_xp} (MAX)"

        data = [
            (f"Faction: {faction_str}", arcade.color.LIGHT_BLUE),
            (f"Ship: {ship_str}", arcade.color.LIGHT_GREEN),
            (f"Character: {char_name or 'None'}{char_class}", arcade.color.KHAKI),
            (f"Level: {char_level}  XP: {xp_str}", arcade.color.YELLOW),
        ]
        # Show active character benefits
        if char_name and char_name in CHARACTERS:
            benefits = CHARACTERS[char_name]["benefits"]
            for i in range(min(char_level, len(benefits))):
                data.append((f"  L{i+1}: {benefits[i]}", (160, 200, 160)))
        data.append(("", (0, 0, 0, 0)))
        data += [
            _fmt("HP", base._base_max_hp, base.max_hp, "max_hp",
                 color=arcade.color.LIME_GREEN),
            _fmt("Shields", base._base_max_shields, base.max_shields, "max_shields",
                 color=arcade.color.CYAN),
            _fmt("Shield Regen", f"{base._base_shield_regen:.1f}",
                 f"{base._shield_regen:.1f}", "shield_regen", "/s",
                 color=arcade.color.CYAN),
            _fmt("Max Speed", int(base._base_max_spd), int(base._max_spd), "max_speed"),
            (f"Thrust: {int(base._thrust)}", arcade.color.WHITE),
            (f"Brake: {int(base._brake)}", arcade.color.WHITE),
            (f"Guns: {base.guns}", arcade.color.YELLOW),
        ]

        # Damage absorber
        absorb_mod = mod_effects.get("shield_absorb")
        if absorb_mod:
            data.append((f"Absorb: -{absorb_mod[1]} shield dmg ({absorb_mod[0]})",
                        (200, 180, 80)))
        # Broadside
        broadside_mod = mod_effects.get("broadside")
        if broadside_mod:
            data.append((f"Broadside: active ({broadside_mod[0]})", (200, 180, 80)))

        for i, item in enumerate(data):
            if i >= len(self._lines):
                break
            if isinstance(item, tuple) and len(item) == 2:
                text, color = item
                self._lines[i].text = text
                self._lines[i].color = color
            else:
                self._lines[i].text = ""

        # Load a random portrait for the current character
        self._portrait_texture = None
        if char_name:
            pattern = os.path.join(_PORTRAITS_DIR, f"{char_name}*.png")
            matches = glob.glob(pattern)
            if matches:
                chosen = random.choice(matches)
                self._portrait_texture = arcade.load_texture(chosen)
            backstory = _BACKSTORIES.get(char_name, "")
            self._bio_title.text = f"{char_name}'s Backstory"
            self._bio_lines[0].text = backstory
        else:
            self._bio_title.text = ""
            self._bio_lines[0].text = ""

    def draw(self) -> None:
        if not self.open:
            return
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT

        # Total width of both panels + gap
        gap = 12
        total_w = _PANEL_W + gap + _BIO_PANEL_W
        start_x = (sw - total_w) // 2

        # --- Left panel: ship stats ---
        px = start_x
        py = (sh - _PANEL_H) // 2

        arcade.draw_rect_filled(
            arcade.LBWH(px, py, _PANEL_W, _PANEL_H), (15, 15, 40, 235))
        arcade.draw_rect_outline(
            arcade.LBWH(px, py, _PANEL_W, _PANEL_H),
            arcade.color.STEEL_BLUE, border_width=2)

        self._t_title.x = px + _PANEL_W // 2
        self._t_title.y = py + _PANEL_H - 20
        self._t_title.draw()

        line_y = py + _PANEL_H - 48
        for t in self._lines:
            if t.text:
                t.x = px + 16
                t.y = line_y
                t.draw()
            line_y -= 18

        # --- Right panel: character bio ---
        if self._bio_title.text:
            bx = start_x + _PANEL_W + gap
            by = py

            arcade.draw_rect_filled(
                arcade.LBWH(bx, by, _BIO_PANEL_W, _BIO_PANEL_H),
                (15, 15, 40, 235))
            arcade.draw_rect_outline(
                arcade.LBWH(bx, by, _BIO_PANEL_W, _BIO_PANEL_H),
                arcade.color.STEEL_BLUE, border_width=2)

            # Portrait
            if self._portrait_texture:
                tex = self._portrait_texture
                # Scale portrait to fit within the panel width and _PORTRAIT_H
                scale = min((_BIO_PANEL_W - 24) / tex.width,
                            _PORTRAIT_H / tex.height)
                draw_w = tex.width * scale
                draw_h = tex.height * scale
                img_cx = bx + _BIO_PANEL_W // 2
                img_cy = by + _BIO_PANEL_H - 10 - int(draw_h // 2)
                arcade.draw_texture_rect(
                    tex,
                    arcade.XYWH(img_cx, img_cy, draw_w, draw_h))
                title_y = by + _BIO_PANEL_H - 20 - int(draw_h) - 10
            else:
                title_y = by + _BIO_PANEL_H - 20

            # Title
            self._bio_title.x = bx + _BIO_PANEL_W // 2
            self._bio_title.y = title_y
            self._bio_title.draw()

            # Backstory text
            self._bio_lines[0].x = bx + 16
            self._bio_lines[0].y = title_y - 20
            self._bio_lines[0].draw()
