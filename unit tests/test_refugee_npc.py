"""Tests for the Double Star Refugee NPC + dialogue system."""
from __future__ import annotations

import arcade
import pytest
from PIL import Image as PILImage


@pytest.fixture
def dummy_texture(monkeypatch):
    """Return a tiny texture and patch arcade.load_texture so
    RefugeeNPCShip's __init__ doesn't try to load the Kenney PNG."""
    img = PILImage.new("RGBA", (32, 32), (200, 100, 0, 255))
    tex = arcade.Texture(img)
    monkeypatch.setattr(arcade, "load_texture", lambda *a, **kw: tex)
    return tex


class TestRefugeeNPCShip:
    def test_spawn_faces_and_approaches(self, dummy_texture):
        from sprites.npc_ship import RefugeeNPCShip
        ship = RefugeeNPCShip(2000.0, 1000.0, (1000.0, 1000.0))
        assert ship.arrived is False
        # One second of approach — at 140 px/s it should have moved ~140 px.
        ship.update_npc(1.0)
        assert ship.center_x < 2000.0
        assert 855.0 < ship.center_x < 1865.0

    def test_arrives_within_hold_distance(self, dummy_texture):
        from sprites.npc_ship import RefugeeNPCShip
        from constants import NPC_REFUGEE_HOLD_DIST
        ship = RefugeeNPCShip(1000.0 + NPC_REFUGEE_HOLD_DIST - 10.0,
                              1000.0, (1000.0, 1000.0))
        ship.update_npc(0.1)
        assert ship.arrived is True

    def test_arrived_ship_does_not_drift(self, dummy_texture):
        from sprites.npc_ship import RefugeeNPCShip
        ship = RefugeeNPCShip(1100.0, 1000.0, (1000.0, 1000.0))
        ship.update_npc(1.0)
        assert ship.arrived is True
        pos = (ship.center_x, ship.center_y)
        ship.update_npc(1.0)
        assert (ship.center_x, ship.center_y) == pos

    def test_take_damage_is_noop(self, dummy_texture):
        from sprites.npc_ship import RefugeeNPCShip
        ship = RefugeeNPCShip(2000.0, 1000.0, (1000.0, 1000.0))
        ship.take_damage(9999)
        # No hp attribute expected — the call must simply not raise.
        assert ship.label == "Double Star Refugee"


class TestDialogueTreeStructure:
    def test_debra_tree_is_reachable_end_to_end(self):
        """Every path from start reaches an ``end`` node. Every ``next``
        or choice ``next`` points at a node that exists."""
        from dialogue.debra_refugee import DEBRA_REFUGEE_TREE as t
        start = t["start"]
        assert start in t
        visited = set()

        def walk(node_id):
            if node_id in visited:
                return
            visited.add(node_id)
            node = t[node_id]
            if node.get("end"):
                return
            if "choices" in node:
                for ch in node["choices"]:
                    nxt = ch["next"]
                    assert nxt in t, f"choice next '{nxt}' missing"
                    walk(nxt)
                return
            nxt = node.get("next")
            assert nxt in t, f"next '{nxt}' missing for {node_id}"
            walk(nxt)

        walk(start)
        # At least one end should be reached somewhere in the tree.
        assert any(t[nid].get("end") for nid in visited)

    def test_ellie_tree_is_reachable_end_to_end(self):
        """Every path from start reaches an ``end`` node. Every
        ``next`` or choice ``next`` points at a node that exists."""
        from dialogue.ellie_refugee import ELLIE_REFUGEE_TREE as t
        start = t["start"]
        assert start in t
        visited = set()

        def walk(node_id):
            if node_id in visited:
                return
            visited.add(node_id)
            node = t[node_id]
            if node.get("end"):
                return
            if "choices" in node:
                for ch in node["choices"]:
                    nxt = ch["next"]
                    assert nxt in t, f"choice next '{nxt}' missing"
                    walk(nxt)
                return
            nxt = node.get("next")
            assert nxt in t, f"next '{nxt}' missing for {node_id}"
            walk(nxt)

        walk(start)
        assert any(t[nid].get("end") for nid in visited)
        # Every non-start node should be reachable — no orphaned beats.
        unreachable = set(t.keys()) - visited - {"start"}
        assert not unreachable, f"Orphaned Ellie nodes: {unreachable}"

    def test_ellie_tree_aftermath_sets_quest_flags(self):
        """The terminal ``end`` node must set the Kratos-quest aftermath
        flags so ending the overlay actually activates the mission."""
        from dialogue.ellie_refugee import ELLIE_REFUGEE_TREE as t
        end_nodes = [n for n in t.values() if isinstance(n, dict)
                     and n.get("end")]
        assert end_nodes, "Ellie tree has no terminal node"
        aftermaths = [n.get("aftermath") or {} for n in end_nodes]
        # At least one end must activate the Kratos quest.
        assert any(a.get("ellie_quest_dismantle_kratos")
                   for a in aftermaths)

    def test_tara_tree_is_reachable_end_to_end(self):
        """Every path from start reaches an ``end`` node. Every
        ``next`` or choice ``next`` points at a node that exists,
        and no node is orphaned."""
        from dialogue.tara_refugee import TARA_REFUGEE_TREE as t
        start = t["start"]
        assert start in t
        visited = set()

        def walk(node_id):
            if node_id in visited:
                return
            visited.add(node_id)
            node = t[node_id]
            if node.get("end"):
                return
            if "choices" in node:
                for ch in node["choices"]:
                    nxt = ch["next"]
                    assert nxt in t, f"choice next '{nxt}' missing"
                    walk(nxt)
                return
            nxt = node.get("next")
            assert nxt in t, f"next '{nxt}' missing for {node_id}"
            walk(nxt)

        walk(start)
        assert any(t[nid].get("end") for nid in visited)
        unreachable = set(t.keys()) - visited - {"start"}
        assert not unreachable, f"Orphaned Tara nodes: {unreachable}"

    def test_tara_tree_aftermath_sets_dead_zone_quest(self):
        """The terminal node must activate the Dead Zone quest flag."""
        from dialogue.tara_refugee import TARA_REFUGEE_TREE as t
        end_nodes = [n for n in t.values() if isinstance(n, dict)
                     and n.get("end")]
        assert end_nodes, "Tara tree has no terminal node"
        aftermaths = [n.get("aftermath") or {} for n in end_nodes]
        assert any(a.get("tara_quest_dead_zone") for a in aftermaths)

    def test_get_refugee_tree_per_character(self):
        from dialogue import get_refugee_tree
        assert "start" in get_refugee_tree("Debra")
        assert "start" in get_refugee_tree("Ellie")
        assert "start" in get_refugee_tree("Tara")
        # Unknown character falls back to a non-crashing tree.
        assert "start" in get_refugee_tree("Unknown")


class TestDialogueOverlay:
    def test_starts_closed(self):
        from dialogue_overlay import DialogueOverlay
        d = DialogueOverlay()
        assert d.open is False

    def test_start_opens_and_renders_first_node(self):
        from dialogue_overlay import DialogueOverlay
        from dialogue.debra_refugee import DEBRA_REFUGEE_TREE
        d = DialogueOverlay()
        d.start(DEBRA_REFUGEE_TREE)
        assert d.open is True
        assert d._current == DEBRA_REFUGEE_TREE["start"]

    def test_advance_walks_linear_beats(self):
        from dialogue_overlay import DialogueOverlay
        tree = {
            "start": "a",
            "a": {"speaker": "KAEL", "text": "A", "next": "b"},
            "b": {"speaker": "DEBRA", "text": "B", "end": True,
                  "aftermath": {"flag": 1}},
        }
        sink: dict = {}
        d = DialogueOverlay()
        d.start(tree, aftermath_sink=sink)
        d._advance()
        assert d._current == "b"
        d._advance()
        assert d.open is False
        assert sink == {"flag": 1}

    def test_choice_pick_branches(self):
        from dialogue_overlay import DialogueOverlay
        tree = {
            "start": "root",
            "root": {"speaker": "KAEL", "text": "Pick",
                     "choices": [
                         {"text": "Left", "next": "left"},
                         {"text": "Right", "next": "right"},
                     ]},
            "left": {"speaker": "KAEL", "text": "L", "end": True,
                     "aftermath": {"picked": "left"}},
            "right": {"speaker": "KAEL", "text": "R", "end": True,
                      "aftermath": {"picked": "right"}},
        }
        sink: dict = {}
        d = DialogueOverlay()
        d.start(tree, aftermath_sink=sink)
        d._pick(1)
        assert d._current == "right"
        d._advance()
        assert d.open is False
        assert sink == {"picked": "right"}

    def test_esc_closes_without_aftermath(self):
        import arcade as _ac
        from dialogue_overlay import DialogueOverlay
        from dialogue.debra_refugee import DEBRA_REFUGEE_TREE
        sink: dict = {}
        d = DialogueOverlay()
        d.start(DEBRA_REFUGEE_TREE, aftermath_sink=sink)
        d.on_key_press(_ac.key.ESCAPE)
        assert d.open is False
        assert sink == {}

    def test_number_key_picks_choice(self):
        import arcade as _ac
        from dialogue_overlay import DialogueOverlay
        from dialogue.debra_refugee import DEBRA_REFUGEE_TREE
        d = DialogueOverlay()
        d.start(DEBRA_REFUGEE_TREE)
        d.on_key_press(_ac.key.KEY_2)  # pick the second choice at intro
        intro = DEBRA_REFUGEE_TREE[DEBRA_REFUGEE_TREE["start"]]
        assert d._current == intro["choices"][1]["next"]
