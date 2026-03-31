"""Ship statistics overlay — shows faction, ship type, level, and stats with module mods."""
from __future__ import annotations

import arcade

from constants import SCREEN_WIDTH, SCREEN_HEIGHT, MODULE_TYPES

_PANEL_W = 320
_PANEL_H = 420


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
            for _ in range(22)
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

    def draw(self) -> None:
        if not self.open:
            return
        sw = self._window.width if self._window else SCREEN_WIDTH
        sh = self._window.height if self._window else SCREEN_HEIGHT
        px = (sw - _PANEL_W) // 2
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
