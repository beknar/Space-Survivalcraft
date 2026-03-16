"""Faction and ship type selection screen."""
from __future__ import annotations

import os

import arcade
from PIL import Image as PILImage

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    FACTION_SHIPS_DIR, FACTIONS, SHIP_TYPES,
    SHIP_FRAME_SIZE, SHIP_SHEET_COLS,
)


class SelectionView(arcade.View):
    """Two-phase selection screen: choose faction, then ship type."""

    _PHASE_FACTION = 0
    _PHASE_SHIP = 1

    def __init__(self) -> None:
        super().__init__()

        self._phase: int = self._PHASE_FACTION
        self._faction_names: list[str] = list(FACTIONS.keys())
        self._ship_names: list[str] = list(SHIP_TYPES.keys())
        self._selected_faction: int = 0     # index into _faction_names
        self._selected_ship: int = 0        # index into _ship_names
        self._chosen_faction: str = ""      # set after faction is confirmed

        # Pre-load one preview frame per faction (first ship, first col)
        # We'll use the Cruiser row (row 7) col 0 as the faction preview
        self._faction_previews: list[arcade.Texture] = []
        for faction_name, filename in FACTIONS.items():
            path = os.path.join(FACTION_SHIPS_DIR, filename)
            pil_img = PILImage.open(path).convert("RGBA")
            # Use Cruiser row (7) col 0 as the faction representative
            row = SHIP_TYPES["Cruiser"]["row"]
            x0 = 0
            y0 = row * SHIP_FRAME_SIZE
            frame = pil_img.crop((x0, y0, x0 + SHIP_FRAME_SIZE, y0 + SHIP_FRAME_SIZE))
            self._faction_previews.append(arcade.Texture(frame))

        # Ship previews will be loaded once a faction is chosen
        self._ship_previews: list[arcade.Texture] = []

        # Pre-built text objects
        self._t_title = arcade.Text(
            "CHOOSE YOUR FACTION",
            SCREEN_WIDTH // 2, SCREEN_HEIGHT - 60,
            arcade.color.LIGHT_BLUE, 28, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_hint = arcade.Text(
            "UP / DOWN to select    ENTER to confirm    ESC to go back",
            SCREEN_WIDTH // 2, 40,
            (160, 160, 160), 12,
            anchor_x="center", anchor_y="center",
        )
        self._t_label = arcade.Text(
            "", SCREEN_WIDTH // 2, 0,
            arcade.color.WHITE, 16, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_stats = arcade.Text(
            "", 0, 0,
            arcade.color.LIGHT_GRAY, 11,
            anchor_x="left", anchor_y="top",
            multiline=True, width=400,
        )

    def _load_ship_previews(self, faction: str) -> None:
        """Load the first-column sprite for each ship type from the chosen faction."""
        filename = FACTIONS[faction]
        path = os.path.join(FACTION_SHIPS_DIR, filename)
        pil_img = PILImage.open(path).convert("RGBA")
        self._ship_previews = []
        for ship_name in self._ship_names:
            row = SHIP_TYPES[ship_name]["row"]
            x0 = 0
            y0 = row * SHIP_FRAME_SIZE
            frame = pil_img.crop((x0, y0, x0 + SHIP_FRAME_SIZE, y0 + SHIP_FRAME_SIZE))
            self._ship_previews.append(arcade.Texture(frame))

    # ── Drawing ─────────────────────────────────────────────────────────────
    def on_draw(self) -> None:
        self.clear()

        # Dark space background
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT),
            (8, 8, 24),
        )

        if self._phase == self._PHASE_FACTION:
            self._draw_faction_phase()
        else:
            self._draw_ship_phase()

        self._t_hint.draw()

    def _draw_faction_phase(self) -> None:
        self._t_title.text = "CHOOSE YOUR FACTION"
        self._t_title.draw()

        count = len(self._faction_names)
        spacing = 220
        total_w = (count - 1) * spacing
        start_x = SCREEN_WIDTH // 2 - total_w // 2

        for i, name in enumerate(self._faction_names):
            cx = start_x + i * spacing
            cy = SCREEN_HEIGHT // 2 + 30
            selected = (i == self._selected_faction)

            # Selection highlight
            if selected:
                arcade.draw_rect_filled(
                    arcade.LBWH(cx - 60, cy - 70, 120, 140),
                    (40, 60, 100, 180),
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(cx - 60, cy - 70, 120, 140),
                    arcade.color.CYAN, border_width=2,
                )

            # Ship preview (scaled up for visibility)
            scale = 2.5
            tex = self._faction_previews[i]
            w = tex.width * scale
            h = tex.height * scale
            arcade.draw_texture_rect(
                tex,
                arcade.LBWH(cx - w / 2, cy - h / 2 + 10, w, h),
            )

            # Faction name
            self._t_label.text = name
            self._t_label.x = cx
            self._t_label.y = cy - 60
            color = arcade.color.CYAN if selected else arcade.color.WHITE
            self._t_label.color = color
            self._t_label.draw()

    def _draw_ship_phase(self) -> None:
        self._t_title.text = f"{self._chosen_faction.upper()} — CHOOSE YOUR SHIP"
        self._t_title.draw()

        count = len(self._ship_names)
        spacing = 200
        total_w = (count - 1) * spacing
        start_x = SCREEN_WIDTH // 2 - total_w // 2

        for i, name in enumerate(self._ship_names):
            cx = start_x + i * spacing
            cy = SCREEN_HEIGHT // 2 + 60
            selected = (i == self._selected_ship)

            if selected:
                arcade.draw_rect_filled(
                    arcade.LBWH(cx - 60, cy - 70, 120, 140),
                    (40, 60, 100, 180),
                )
                arcade.draw_rect_outline(
                    arcade.LBWH(cx - 60, cy - 70, 120, 140),
                    arcade.color.CYAN, border_width=2,
                )

            # Ship preview
            if i < len(self._ship_previews):
                scale = 2.5
                tex = self._ship_previews[i]
                w = tex.width * scale
                h = tex.height * scale
                arcade.draw_texture_rect(
                    tex,
                    arcade.LBWH(cx - w / 2, cy - h / 2 + 10, w, h),
                )

            # Ship name
            self._t_label.text = name
            self._t_label.x = cx
            self._t_label.y = cy - 60
            color = arcade.color.CYAN if selected else arcade.color.WHITE
            self._t_label.color = color
            self._t_label.draw()

        # Stats panel for the selected ship
        stats = SHIP_TYPES[self._ship_names[self._selected_ship]]
        lines = [
            f"HP: {stats['hp']}",
            f"Shields: {stats['shields']}",
            f"Shield Regen: {stats['shield_regen']} pt/s",
            f"Rotation: {stats['rot_speed']} deg/s",
            f"Thrust: {stats['thrust']} px/s\u00b2",
            f"Brake: {stats['brake']} px/s\u00b2",
            f"Max Speed: {stats['max_speed']} px/s",
            f"Damping: {stats['damping']}x/frame",
            f"Guns: {stats['guns']}",
        ]
        self._t_stats.text = "\n".join(lines)
        self._t_stats.x = SCREEN_WIDTH // 2 - 200
        self._t_stats.y = SCREEN_HEIGHT // 2 - 80
        self._t_stats.draw()

    # ── Input ───────────────────────────────────────────────────────────────
    def on_key_press(self, key: int, modifiers: int) -> None:
        if self._phase == self._PHASE_FACTION:
            if key in (arcade.key.LEFT, arcade.key.A):
                self._selected_faction = (self._selected_faction - 1) % len(self._faction_names)
            elif key in (arcade.key.RIGHT, arcade.key.D):
                self._selected_faction = (self._selected_faction + 1) % len(self._faction_names)
            elif key in (arcade.key.RETURN, arcade.key.ENTER, arcade.key.SPACE):
                self._chosen_faction = self._faction_names[self._selected_faction]
                self._load_ship_previews(self._chosen_faction)
                self._selected_ship = 0
                self._phase = self._PHASE_SHIP
            elif key == arcade.key.ESCAPE:
                arcade.exit()

        elif self._phase == self._PHASE_SHIP:
            if key in (arcade.key.LEFT, arcade.key.A):
                self._selected_ship = (self._selected_ship - 1) % len(self._ship_names)
            elif key in (arcade.key.RIGHT, arcade.key.D):
                self._selected_ship = (self._selected_ship + 1) % len(self._ship_names)
            elif key in (arcade.key.RETURN, arcade.key.ENTER, arcade.key.SPACE):
                self._confirm_selection()
            elif key == arcade.key.ESCAPE:
                self._phase = self._PHASE_FACTION

    def _confirm_selection(self) -> None:
        """Transition to GameView with the chosen faction and ship type."""
        from game_view import GameView

        faction = self._chosen_faction
        ship_type = self._ship_names[self._selected_ship]
        view = GameView(faction=faction, ship_type=ship_type)
        self.window.show_view(view)
