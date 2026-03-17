"""Shared fixtures for Space Survivalcraft unit tests."""
from __future__ import annotations

import sys
import os

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
