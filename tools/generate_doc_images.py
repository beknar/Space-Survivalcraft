"""Regenerate every image referenced from ``docs/features.md`` +
``docs/statistics.md`` into ``docs/images/``.

The game ships most art as sprite sheets (faction ships, monsters,
Zone 2 alien variants) — this script crops the single-frame previews
the selection UI + HUD actually render, plus copies the per-file
assets (module icons, building PNGs, character portraits, trade
station art) so the docs can embed them without pulling the whole
``assets/`` tree into git.

Safe to rerun any time the assets change; output is idempotent.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PIL import Image as PILImage

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "docs" / "images"


# ── Faction + ship sheet layout ────────────────────────────────────────────
# 8×8 grids of 128×128 frames.  Column 0 of each row holds the faction-
# coloured preview used by ``selection_view.SelectionView``.
_FRAME = 128
_FACTIONS: dict[str, str] = {
    "earth": "faction_1_ships_128x128.png",
    "colonial": "faction_2_ships_128x128.png",
    "heavy_world": "faction_5_ships_128x128.png",
    "ascended": "faction_7_ships_128x128.png",
}
_SHIP_ROWS: dict[str, int] = {
    "cruiser": 7,
    "bastion": 6,
    "aegis": 5,
    "striker": 4,
    "thunderbolt": 3,
}
_FACTION_SHIPS_DIR = _ROOT / "assets" / "256Spaceships"
_MONSTER_SHEET = (_ROOT / "assets" / "256Spacemonsters"
                  / "faction_6_monsters_128x128.png")

# ── Zone 1 small alien + Zone 2 variants ──────────────────────────────────
# Cropped from the raw ``Ship.png`` sheet (2880×920) in
# ``alien spaceship creation kit``; the top row hosts each alien variant.
_ALIEN_KIT = (_ROOT / "assets" / "gamedevmarket assets"
              / "alien spaceship creation kit" / "png" / "Ship.png")
# First col (0) is the Zone-1 small alien; remaining columns match
# ``sprites/zone2_aliens.ALIEN_CROPS`` (which the game itself uses).
_ALIEN_CROPS: dict[str, tuple[int, int, int, int]] = {
    "small_alien": (330, 354, 862, 888),
    "shielded":    (883, 356, 1460, 815),
    "fast":        (1498, 306, 1883, 793),
    "gunner":      (1911, 336, 2427, 900),
    "rammer":      (2463, 332, 2838, 900),
}

# ── Module icons ──────────────────────────────────────────────────────────
# ``MODULE_TYPES[key]["icon"]`` is what we want — load via the real import
# so any future icon swaps propagate automatically.
def _module_icon_paths() -> dict[str, str]:
    import sys
    sys.path.insert(0, str(_ROOT))
    from constants import MODULE_TYPES
    return {key: info["icon"] for key, info in MODULE_TYPES.items()}


# ── Buildings ─────────────────────────────────────────────────────────────
def _building_paths() -> dict[str, str]:
    import sys
    sys.path.insert(0, str(_ROOT))
    from constants import BUILDING_TYPES, BUILDING_DIR
    out: dict[str, str] = {}
    for name, info in BUILDING_TYPES.items():
        # ``png_path`` override takes precedence (QWI, Basic Ship,
        # Advanced Ship all use custom asset paths).
        path = info.get("png_path") or os.path.join(
            BUILDING_DIR, info["png"])
        key = (name.lower().replace(" ", "_").replace("-", "_"))
        out[key] = path
    return out


# ── Characters ────────────────────────────────────────────────────────────
_CHARACTER_PORTRAITS = {
    "debra": _ROOT / "characters" / "portraits" / "Debra1.png",
    "ellie": _ROOT / "characters" / "portraits" / "Ellie1.png",
    "tara":  _ROOT / "characters" / "portraits" / "Tara1.png",
}

_TRADE_STATION = _ROOT / "assets" / "ai generated" / "space station.png"


# ── Extraction helpers ────────────────────────────────────────────────────

def _crop_sheet_frame(sheet: Path, row: int, col: int,
                      out: Path, scale: float = 1.5) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.open(sheet).convert("RGBA")
    box = (col * _FRAME, row * _FRAME,
           (col + 1) * _FRAME, (row + 1) * _FRAME)
    frame = img.crop(box)
    w = int(_FRAME * scale)
    frame = frame.resize((w, w), PILImage.NEAREST)
    frame.save(out)
    img.close()


def _crop_box(sheet: Path, box: tuple[int, int, int, int],
              out: Path, max_dim: int = 256) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.open(sheet).convert("RGBA")
    frame = img.crop(box)
    # Downscale to ``max_dim`` on the larger side so the docs render
    # consistently-sized thumbnails.
    w, h = frame.size
    if max(w, h) > max_dim:
        if w >= h:
            new = (max_dim, int(h * max_dim / w))
        else:
            new = (int(w * max_dim / h), max_dim)
        frame = frame.resize(new, PILImage.LANCZOS)
    frame.save(out)
    img.close()


def _copy_image(src: Path, out: Path, max_dim: int | None = None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if max_dim is None:
        shutil.copyfile(src, out)
        return
    img = PILImage.open(src).convert("RGBA")
    w, h = img.size
    if max(w, h) > max_dim:
        if w >= h:
            new = (max_dim, int(h * max_dim / w))
        else:
            new = (int(w * max_dim / h), max_dim)
        img = img.resize(new, PILImage.LANCZOS)
    img.save(out)


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)

    # Factions — one Cruiser-row preview per faction (col 0, row 7)
    for key, fname in _FACTIONS.items():
        sheet = _FACTION_SHIPS_DIR / fname
        _crop_sheet_frame(sheet, row=_SHIP_ROWS["cruiser"], col=0,
                          out=_OUT / "factions" / f"{key}.png")

    # Ship type × faction — 4 × 5 = 20 images
    for fkey, fname in _FACTIONS.items():
        sheet = _FACTION_SHIPS_DIR / fname
        for ship_key, row in _SHIP_ROWS.items():
            _crop_sheet_frame(sheet, row=row, col=0,
                              out=_OUT / "ships" / fkey / f"{ship_key}.png")

    # Characters
    for key, src in _CHARACTER_PORTRAITS.items():
        _copy_image(src, _OUT / "characters" / f"{key}.png", max_dim=200)

    # Module icons
    for key, path in _module_icon_paths().items():
        _copy_image(Path(path), _OUT / "modules" / f"{key}.png",
                    max_dim=96)

    # Enemies
    for key, box in _ALIEN_CROPS.items():
        _crop_box(_ALIEN_KIT, box, _OUT / "enemies" / f"{key}.png",
                  max_dim=220)
    # Double Star boss — col 0 row 0 of the faction_6 monster sheet is
    # the "base" boss appearance.  (The nebula-boss variant uses
    # ``NEBULA_BOSS_COL_INDEX = 1`` of the same sheet.)
    _crop_sheet_frame(_MONSTER_SHEET, row=0, col=0,
                      out=_OUT / "enemies" / "double_star_boss.png",
                      scale=2.0)

    # Buildings
    for key, path in _building_paths().items():
        _copy_image(Path(path), _OUT / "buildings" / f"{key}.png",
                    max_dim=200)

    # Trade station
    _copy_image(_TRADE_STATION, _OUT / "trade_station.png", max_dim=220)

    # Summary.
    total = sum(1 for _ in _OUT.rglob("*.png"))
    print(f"wrote {total} png files to {_OUT.relative_to(_ROOT)}/")


if __name__ == "__main__":
    main()
