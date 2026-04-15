"""Dialogue tree registry for NPC conversations."""
from __future__ import annotations

from .debra_refugee import DEBRA_REFUGEE_TREE
from .ellie_refugee import ELLIE_REFUGEE_TREE
from .tara_refugee import TARA_REFUGEE_TREE


def get_refugee_tree(character_name: str) -> dict:
    """Return the refugee dialogue tree for the active character."""
    if character_name == "Debra":
        return DEBRA_REFUGEE_TREE
    if character_name == "Ellie":
        return ELLIE_REFUGEE_TREE
    if character_name == "Tara":
        return TARA_REFUGEE_TREE
    return ELLIE_REFUGEE_TREE  # safe default
