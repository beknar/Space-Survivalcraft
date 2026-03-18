"""HUD status panel and mini-map drawing for Space Survivalcraft."""
from __future__ import annotations

import math

import arcade

from constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT, STATUS_WIDTH,
    WORLD_WIDTH, WORLD_HEIGHT,
    MINIMAP_PAD, MINIMAP_W, MINIMAP_H, MINIMAP_X, MINIMAP_Y,
)


class HUD:
    """Left-side status panel with stats, weapon display, controls, and mini-map."""

    def __init__(
        self,
        has_gamepad: bool = False,
        faction: str | None = None,
        ship_type: str | None = None,
    ) -> None:
        cx = STATUS_WIDTH // 2
        self._t_title = arcade.Text(
            "STATUS", cx, SCREEN_HEIGHT - 26,
            arcade.color.LIGHT_BLUE, 14, bold=True,
            anchor_x="center", anchor_y="center",
        )
        self._t_spd = arcade.Text("", 10, SCREEN_HEIGHT - 60,
                                  arcade.color.WHITE, 11)
        self._t_hdg = arcade.Text("", 10, SCREEN_HEIGHT - 80,
                                  arcade.color.WHITE, 11)
        self._t_iron_hud = arcade.Text("", 10, SCREEN_HEIGHT - 100,
                                       arcade.color.ORANGE, 11)
        self._t_hp = arcade.Text("HP", 10, SCREEN_HEIGHT - 140,
                                 arcade.color.LIME_GREEN, 10, bold=True)
        self._t_hp_val = arcade.Text("", 10, SCREEN_HEIGHT - 168,
                                     arcade.color.WHITE, 9)
        self._t_shield = arcade.Text("SHIELD", 10, SCREEN_HEIGHT - 184,
                                     arcade.color.CYAN, 10, bold=True)
        self._t_shield_val = arcade.Text("", 10, SCREEN_HEIGHT - 212,
                                         arcade.color.WHITE, 9)
        self._t_wpn_hdr = arcade.Text("WEAPON", cx, SCREEN_HEIGHT - 230,
                                      arcade.color.LIGHT_GRAY, 9,
                                      anchor_x="center")
        self._t_wpn_name = arcade.Text("", cx, SCREEN_HEIGHT - 246,
                                       arcade.color.YELLOW, 10, bold=True,
                                       anchor_x="center")
        self._t_ctrl_hdr = arcade.Text("CONTROLS", cx, SCREEN_HEIGHT - 268,
                                       arcade.color.LIGHT_GRAY, 9,
                                       anchor_x="center")
        self._t_ctrl_lines = [
            arcade.Text("L/R  A/D    Rotate",   10, SCREEN_HEIGHT - 286,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Up / W      Thrust",   10, SCREEN_HEIGHT - 302,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Dn / S      Brake",    10, SCREEN_HEIGHT - 318,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Space       Fire",     10, SCREEN_HEIGHT - 334,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("Tab         Weapon",   10, SCREEN_HEIGHT - 350,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("I           Inventory", 10, SCREEN_HEIGHT - 366,
                        arcade.color.LIGHT_GRAY, 9),
            arcade.Text("F           FPS",      10, SCREEN_HEIGHT - 382,
                        arcade.color.LIGHT_GRAY, 9),
        ]
        self._t_gamepad = (
            arcade.Text("Gamepad: connected", 10, SCREEN_HEIGHT - 402,
                        arcade.color.LIME_GREEN, 9)
            if has_gamepad else None
        )
        self._show_fps: bool = False
        self._fps: float = 60.0
        self._t_fps = arcade.Text("", 10, SCREEN_HEIGHT - 420,
                                  arcade.color.YELLOW, 10, bold=True)
        self._t_minimap = arcade.Text(
            "MINI-MAP", STATUS_WIDTH // 2,
            MINIMAP_Y + MINIMAP_H + 3,
            arcade.color.LIGHT_GRAY, 9, anchor_x="center",
        )

        faction_label = faction if faction else "Legacy"
        ship_label = ship_type if ship_type else "Classic"
        self._t_faction = arcade.Text(
            f"FACTION: {faction_label}",
            10, SCREEN_HEIGHT - 440,
            arcade.color.LIGHT_BLUE, 9, bold=True,
        )
        self._t_ship_type = arcade.Text(
            f"SHIP: {ship_label}",
            10, SCREEN_HEIGHT - 456,
            arcade.color.LIGHT_GREEN, 9, bold=True,
        )
        self._t_music_hdr = arcade.Text(
            "NOW PLAYING", STATUS_WIDTH // 2, SCREEN_HEIGHT - 476,
            arcade.color.LIGHT_GRAY, 9, anchor_x="center",
        )
        self._t_track_name = arcade.Text(
            "", STATUS_WIDTH // 2, SCREEN_HEIGHT - 492,
            arcade.color.KHAKI, 9, bold=True, anchor_x="center",
        )

    def toggle_fps(self) -> None:
        self._show_fps = not self._show_fps

    @property
    def show_fps(self) -> bool:
        return self._show_fps

    def update_fps(self, delta_time: float) -> None:
        if delta_time > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / delta_time)

    def draw(
        self,
        speed: float,
        heading: float,
        iron: int,
        weapon_name: str,
        hp: int,
        max_hp: int,
        shields: int,
        max_shields: int,
        asteroid_list: arcade.SpriteList,
        iron_pickup_list: arcade.SpriteList,
        alien_list: arcade.SpriteList,
        player_x: float,
        player_y: float,
        player_heading: float,
        track_name: str = "",
        building_list: arcade.SpriteList | None = None,
    ) -> None:
        """Draw the full HUD status panel."""
        # Panel background
        arcade.draw_rect_filled(
            arcade.LBWH(0, 0, STATUS_WIDTH, SCREEN_HEIGHT),
            (15, 15, 40, 235),
        )
        arcade.draw_rect_outline(
            arcade.LBWH(0, 0, STATUS_WIDTH, SCREEN_HEIGHT),
            arcade.color.STEEL_BLUE, border_width=2,
        )

        self._t_title.draw()
        self._t_hp.draw()
        self._t_shield.draw()
        self._t_wpn_hdr.draw()
        self._t_ctrl_hdr.draw()
        for t in self._t_ctrl_lines:
            t.draw()
        if self._t_gamepad:
            self._t_gamepad.draw()
        if self._show_fps:
            self._t_fps.text = f"FPS  {self._fps:>6.1f}"
            self._t_fps.draw()

        self._t_spd.text = f"SPD   {speed:>7.1f}"
        self._t_spd.draw()
        self._t_hdg.text = f"HDG   {heading:>6.1f}\u00b0"
        self._t_hdg.draw()
        self._t_iron_hud.text = f"IRON  {iron:>7}"
        self._t_iron_hud.draw()
        self._t_wpn_name.text = weapon_name
        self._t_wpn_name.draw()

        # HP bar
        hp_frac = max(0.0, hp / max_hp) if max_hp > 0 else 0.0
        hp_color = (
            (0, 180, 0) if hp_frac > 0.5
            else (220, 140, 0) if hp_frac > 0.25
            else (200, 30, 30)
        )
        arcade.draw_rect_filled(
            arcade.LBWH(10, SCREEN_HEIGHT - 156, int(190 * hp_frac), 10),
            hp_color,
        )
        # HP numerical value
        self._t_hp_val.text = f"{hp} / {max_hp}"
        self._t_hp_val.draw()

        # Shield bar
        shield_frac = max(0.0, shields / max_shields) if max_shields > 0 else 0.0
        arcade.draw_rect_filled(
            arcade.LBWH(10, SCREEN_HEIGHT - 200, int(190 * shield_frac), 10),
            (0, 140, 210),
        )
        # Shield numerical value
        self._t_shield_val.text = f"{shields} / {max_shields}"
        self._t_shield_val.draw()

        self._t_faction.draw()
        self._t_ship_type.draw()

        # Now-playing track name
        if track_name:
            self._t_music_hdr.draw()
            self._t_track_name.text = track_name
            self._t_track_name.draw()

        self._draw_minimap(
            asteroid_list, iron_pickup_list, alien_list,
            player_x, player_y, player_heading,
            building_list=building_list,
        )

    def _draw_minimap(
        self,
        asteroid_list: arcade.SpriteList,
        iron_pickup_list: arcade.SpriteList,
        alien_list: arcade.SpriteList,
        player_x: float,
        player_y: float,
        player_heading: float,
        building_list: arcade.SpriteList | None = None,
    ) -> None:
        """Draw a scaled overview of the world inside the status panel."""
        mx, my = MINIMAP_X, MINIMAP_Y
        mw, mh = MINIMAP_W, MINIMAP_H

        arcade.draw_rect_filled(arcade.LBWH(mx, my, mw, mh), (5, 5, 20, 245))
        arcade.draw_rect_outline(
            arcade.LBWH(mx, my, mw, mh), arcade.color.STEEL_BLUE, border_width=1,
        )
        self._t_minimap.draw()

        def to_map(wx: float, wy: float) -> tuple[float, float]:
            return (
                mx + (wx / WORLD_WIDTH) * mw,
                my + (wy / WORLD_HEIGHT) * mh,
            )

        for asteroid in asteroid_list:
            ax, ay = to_map(asteroid.center_x, asteroid.center_y)
            arcade.draw_circle_filled(ax, ay, 2.0, (150, 150, 150))

        for pickup in iron_pickup_list:
            px, py = to_map(pickup.center_x, pickup.center_y)
            arcade.draw_circle_filled(px, py, 2.0, (255, 165, 0))

        for alien in alien_list:
            amx, amy = to_map(alien.center_x, alien.center_y)
            arcade.draw_circle_filled(amx, amy, 2.0, (220, 50, 50))

        if building_list is not None:
            for building in building_list:
                bx, by = to_map(building.center_x, building.center_y)
                arcade.draw_circle_filled(bx, by, 2.5, (100, 220, 255))

        sx, sy = to_map(player_x, player_y)
        rad = math.radians(player_heading)
        lx = sx + math.sin(rad) * 5
        ly = sy + math.cos(rad) * 5
        arcade.draw_line(sx, sy, lx, ly, arcade.color.CYAN, 1)
        arcade.draw_circle_filled(sx, sy, 3.0, arcade.color.WHITE)
