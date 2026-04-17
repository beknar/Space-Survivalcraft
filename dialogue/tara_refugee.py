"""Dr. Tara O'Connor's Double Star Refugee conversation tree.

Same node format as ``debra_refugee.py`` / ``ellie_refugee.py``: each
node carries a speaker and text (plus an optional scene-header
``stage``), and flows either to ``choices`` / a single ``next`` / an
``end`` with an ``aftermath`` dict of quest flags.  See
``tara-conversation-tree1.txt`` for the source spec.
"""
from __future__ import annotations


TARA_REFUGEE_TREE: dict = {
    "start": "intro",

    # ── Scene 1 ────────────────────────────────────────────────────────
    "intro": {
        "stage": ("Archaeological research station in the outer sectors. "
                  "Kael Vox enters a cluttered laboratory filled with "
                  "star charts, alien artifacts, and excavation "
                  "equipment. Tara O'Connor looks up from analysing an "
                  "ancient crystalline structure."),
        "speaker": "KAEL",
        "text": ("Dr. O'Connor? I'm Scout Kael Vox, Double Star "
                 "Command. I'm investigating the Falling Star incident "
                 "and attacks on civilian vessels in this sector."),
        "next": "s1_1",
    },
    "s1_1": {
        "speaker": "TARA",
        "text": ("[studying him, not looking up from her work] \"The "
                 "Falling Star. Yes. That was... unfortunate timing.\""),
        "next": "s1_2",
    },
    "s1_2": {
        "speaker": "KAEL",
        "text": ("Your ship was attacked around the same time. Can you "
                 "describe what happened?"),
        "next": "s1_3",
    },
    "s1_3": {
        "speaker": "TARA",
        "text": ("[removes protective gloves, faces him] \"Not "
                 "'attacked,' exactly. Intercepted. The raiders knew "
                 "exactly what they were looking for. Which means "
                 "someone knew what I had.\""),
        "next": "s1_4",
    },
    "s1_4": {
        "speaker": "KAEL",
        "text": "What did you have?",
        "choices": [
            {"text": "[gestures to the star charts on the walls] "
                     "Artifacts. Archaeological data. Star maps from an "
                     "expedition in the deep outer sectors. Maps that "
                     "lead to something... significant.",
             "next": "b1a"},
            {"text": "[opens a secured case carefully] Evidence of a "
                     "civilisation that predates all known spacefaring "
                     "species. A civilisation that may have... ruled "
                     "this region of space.", "next": "b1b"},
            {"text": "[turns away, troubled] The locals in the outer "
                     "sectors call them 'The Killers.' That's all "
                     "anyone knows. A name. A myth. A warning.",
             "next": "b1c"},
        ],
    },
    "b1a": {
        "speaker": "KAEL",
        "text": "What kind of significance?",
        "next": "s2_1",
    },
    "b1b": {
        "speaker": "KAEL",
        "text": "[steps closer, intrigued] \"How far back are we talking?\"",
        "next": "b1b_reply",
    },
    "b1b_reply": {
        "speaker": "TARA",
        "text": ("Tens of thousands of years. Maybe more. The dating "
                 "is difficult with artifacts this old."),
        "next": "s2_1",
    },
    "b1c": {
        "speaker": "KAEL",
        "text": ("[alert] \"The Killers?\" [He pulls out a data pad, "
                 "begins taking notes]"),
        "next": "s2_1",
    },

    # ── Scene 2 ────────────────────────────────────────────────────────
    "s2_1": {
        "speaker": "TARA",
        "text": ("[activates a holographic display] \"During our "
                 "excavation, we found structures. Technology. Things "
                 "that shouldn't exist given the age of the sites. "
                 "Things that suggest an intelligence far beyond our "
                 "current understanding.\""),
        "next": "s2_2",
    },
    "s2_2": {
        "speaker": "KAEL",
        "text": "And the raiders took your research?",
        "next": "s2_3",
    },
    "s2_3": {
        "speaker": "TARA",
        "text": ("[bitter laugh] \"They took the physical artifacts. "
                 "The data cores. Equipment. Everything portable. But "
                 "they missed something crucial.\" [She points to the "
                 "star charts]"),
        "next": "s2_4",
    },
    "s2_4": {
        "speaker": "TARA",
        "text": ("These maps. The ones showing the excavation sites. "
                 "The coordinates of where we found the artifacts. "
                 "Where we believe more remains."),
        "next": "s2_5",
    },
    "s2_5": {
        "speaker": "KAEL",
        "text": "[understanding] \"They left empty-handed?\"",
        "next": "s2_6",
    },
    "s2_6": {
        "speaker": "TARA",
        "text": ("Not quite. They left something behind. Devices. "
                 "Advanced tech that doesn't match the raiders' "
                 "profile. And the markings... they're corporate. "
                 "[She retrieves a metallic device, heavily damaged]"),
        "next": "s2_7",
    },
    "s2_7": {
        "speaker": "KAEL",
        "text": "[recognises it immediately] \"That's... Kratos Corporation engineering.\"",
        "next": "s2_8",
    },
    "s2_8": {
        "speaker": "TARA",
        "text": ("[nods grimly] \"Exactly. Which raised several "
                 "questions: Why were corporate operatives masquerading "
                 "as political dissidents? What does Kratos want with "
                 "ancient alien archaeology? And why would they abandon "
                 "their own equipment?\""),
        "next": "s2_9",
    },
    "s2_9": {
        "speaker": "KAEL",
        "text": "You're suggesting Kratos is searching for The Killers.",
        "choices": [
            {"text": "[sits, exhausted] I'm suggesting Kratos is afraid "
                     "of them. They didn't come for knowledge. They "
                     "came for containment. Or destruction. And they "
                     "failed.", "next": "s2_a_1"},
            {"text": "What if The Killers aren't extinct? What if "
                     "they're dormant? What if Kratos knows something "
                     "about them that terrifies them?",
             "next": "s2_b_1"},
            {"text": "The artifacts we found tell a story. A story of "
                     "expansion. Control. And then... silence. "
                     "Complete, absolute silence. As if an entire "
                     "civilisation simply... ceased.",
             "next": "s2_c_1"},
        ],
    },
    "s2_a_1": {
        "speaker": "KAEL",
        "text": "[sits across from her] \"Failed how?\"",
        "next": "s2_a_2",
    },
    "s2_a_2": {
        "speaker": "TARA",
        "text": ("They didn't find what they were looking for. Because "
                 "they didn't have the star maps. I kept those hidden. "
                 "[Kael leans back, processing]"),
        "next": "s3_intro",
    },
    "s2_b_1": {
        "speaker": "KAEL",
        "text": "That's speculation.",
        "next": "s2_b_2",
    },
    "s2_b_2": {
        "speaker": "TARA",
        "text": ("[intense] \"Is it? Then explain why a corporation "
                 "would risk military operations to suppress "
                 "archaeology.\""),
        "next": "s3_intro",
    },
    "s2_c_1": {
        "speaker": "KAEL",
        "text": "Ceased? You mean—",
        "next": "s2_c_2",
    },
    "s2_c_2": {
        "speaker": "TARA",
        "text": ("I mean we don't know. That's the terrifying part. "
                 "We don't know what happened to them. And if Kratos "
                 "is this desperate to prevent that knowledge from "
                 "spreading... maybe we should be terrified too."),
        "next": "s3_intro",
    },

    # ── Scene 3 ────────────────────────────────────────────────────────
    "s3_intro": {
        "speaker": "KAEL",
        "text": "Do you know what Kratos wants? Specifically?",
        "next": "s3_1",
    },
    "s3_1": {
        "speaker": "TARA",
        "text": ("[retrieves multiple data pads, spreads them out] "
                 "\"Based on the sites they targeted, the artifacts "
                 "they took, and the device they left behind, I've "
                 "reconstructed their search pattern.\""),
        "next": "s3_2",
    },
    "s3_2": {
        "speaker": "KAEL",
        "text": "And?",
        "next": "s3_3",
    },
    "s3_3": {
        "speaker": "TARA",
        "text": ("[pulls up a 3D star map, highlights several sectors] "
                 "\"They're looking for a central location. A hub. "
                 "What I believe was the capital world of The Killers' "
                 "civilisation. Or what's left of it.\""),
        "next": "s3_4",
    },
    "s3_4": {
        "speaker": "KAEL",
        "text": "How do you know that?",
        "next": "s3_5",
    },
    "s3_5": {
        "speaker": "TARA",
        "text": ("[points to ancient symbols on the device] \"These "
                 "markings. I've seen them before. On artifacts we "
                 "recovered from three separate sites spanning hundreds "
                 "of light-years. They appear to be directional "
                 "markers. Navigation aids. All pointing inward. All "
                 "converging.\""),
        "next": "s3_6",
    },
    "s3_6": {
        "speaker": "KAEL",
        "text": "[stands, paces] \"On what?\"",
        "next": "s3_7",
    },
    "s3_7": {
        "speaker": "TARA",
        "text": ("[focuses on a particular region of the star map] \"A "
                 "sector the locals call the 'Dead Zone.' Nothing "
                 "survives there, they say. Ships disappear. Signals "
                 "die. Space itself seems hostile.\""),
        "next": "s3_8",
    },
    "s3_8": {
        "speaker": "KAEL",
        "text": "Hostile how?",
        "choices": [
            {"text": "Gravitational anomalies. Radiation bursts. Energy "
                     "patterns that don't match any natural phenomenon "
                     "we know. Like something is actively... resisting "
                     "intrusion.", "next": "s3_a_1"},
            {"text": "If The Killers built technology that can persist "
                     "for tens of thousands of years, what kind of "
                     "defensive systems might they have constructed?",
             "next": "s3_b_1"},
            {"text": "Kratos wants to reach that hub. I believe they "
                     "want to either activate something, deactivate "
                     "something, or steal something. And they're "
                     "willing to commit corporate military resources "
                     "to do it.", "next": "s3_c_1"},
        ],
    },
    "s3_a_1": {
        "speaker": "KAEL",
        "text": "[darkly] \"Or defending itself.\"",
        "next": "s3_a_2",
    },
    "s3_a_2": {
        "speaker": "TARA",
        "text": "[nods slowly] \"Yes. That's what I've been thinking too.\"",
        "next": "s4_intro",
    },
    "s3_b_1": {
        "speaker": "KAEL",
        "text": "[sits back down, heavily] \"Systems that could still be active.\"",
        "next": "s3_b_2",
    },
    "s3_b_2": {
        "speaker": "TARA",
        "text": "Potentially. We won't know until someone goes there.",
        "next": "s4_intro",
    },
    "s3_c_1": {
        "speaker": "KAEL",
        "text": "Then why haven't they succeeded?",
        "next": "s3_c_2",
    },
    "s3_c_2": {
        "speaker": "TARA",
        "text": ("[slight smile] \"Because the Dead Zone is exactly as "
                 "dangerous as the locals claim. I've tracked three "
                 "Kratos expeditions that entered the region. None "
                 "returned. None even sent back a final signal.\""),
        "next": "s4_intro",
    },

    # ── Scene 4 ────────────────────────────────────────────────────────
    "s4_intro": {
        "speaker": "KAEL",
        "text": ("[approaches the star maps] \"If this is true, if The "
                 "Killers are real, if they're... protected or dormant "
                 "or whatever they are... this changes everything. "
                 "Everything.\""),
        "next": "s4_1",
    },
    "s4_1": {
        "speaker": "TARA",
        "text": ("It does. Which is why Kratos is desperate. They know "
                 "something we don't. And they're trying to control "
                 "the narrative by eliminating evidence and silencing "
                 "researchers."),
        "next": "s4_2",
    },
    "s4_2": {
        "speaker": "KAEL",
        "text": "Like you.",
        "next": "s4_3",
    },
    "s4_3": {
        "speaker": "TARA",
        "text": ("[nods] \"I was supposed to die in that raid. My "
                 "entire crew was. The fact that we survived was... "
                 "unexpected. For them.\""),
        "next": "s4_4",
    },
    "s4_4": {
        "speaker": "KAEL",
        "text": "Do you think they'll try again?",
        "next": "s4_5",
    },
    "s4_5": {
        "speaker": "TARA",
        "text": ("[walks to a window overlooking the outer sector "
                 "darkness] \"They already have. Three times. Twice "
                 "directly — raids on the station. Once indirectly — "
                 "cutting off our supply lines, isolating us. Each "
                 "time we've managed to survive. But it's only a "
                 "matter of time before they succeed.\""),
        "next": "s4_6",
    },
    "s4_6": {
        "speaker": "KAEL",
        "text": ("[joins her at the window] \"Then we need to move. "
                 "We need to get you somewhere safe, and we need to "
                 "get this information to Command.\""),
        "next": "s4_7",
    },
    "s4_7": {
        "speaker": "TARA",
        "text": ("[turns to face him, serious] \"I'm not leaving. And "
                 "I'm not hiding. I'm going back out there. To the "
                 "Dead Zone. To find answers.\""),
        "next": "s4_8",
    },
    "s4_8": {
        "speaker": "KAEL",
        "text": ("[shocked] \"That's suicide. You just said Kratos "
                 "expeditions don't return.\""),
        "choices": [
            {"text": "Kratos uses brute force. Military ships. Armed "
                     "teams. They go in looking for resources to take "
                     "or secrets to steal. That's a different approach "
                     "than mine.", "next": "s4_a_1"},
            {"text": "[returns to her work, organising data] The star "
                     "maps show the path. The archaeological sites "
                     "show the pattern. And the Kratos device proves "
                     "corporate interest. Everything points outward. "
                     "Everything points to answers.",
             "next": "s4_b_1"},
            {"text": "[pulls up the encrypted data files] I have "
                     "everything. Star maps. Artifact analysis. Kratos "
                     "device specifications. Expedition logs. "
                     "Navigation coordinates. Everything needed to "
                     "reach the Dead Zone safely.",
             "next": "s4_c_1"},
        ],
    },
    "s4_a_1": {
        "speaker": "KAEL",
        "text": "Which is?",
        "next": "s4_a_2",
    },
    "s4_a_2": {
        "speaker": "TARA",
        "text": ("[intense determination] \"Understanding. Respect. "
                 "I'm going as a scientist, not a soldier. I'm going "
                 "to listen, not conquer. That changes everything.\""),
        "next": "s4_a_3",
    },
    "s4_a_3": {
        "speaker": "KAEL",
        "text": ("[skeptical] \"You think an alien civilisation tens "
                 "of thousands of years old will negotiate with a "
                 "single human archaeologist?\""),
        "next": "s4_a_4",
    },
    "s4_a_4": {
        "speaker": "TARA",
        "text": ("I think if The Killers are dormant, they might "
                 "respond to peaceful intent. I think if they're "
                 "active, they might recognise curiosity as less "
                 "threatening than conquest. And if they're "
                 "hostile... well, I want to know why."),
        "next": "s5_intro",
    },
    "s4_b_1": {
        "speaker": "KAEL",
        "text": "You're serious. You're actually planning to go alone.",
        "next": "s4_b_2",
    },
    "s4_b_2": {
        "speaker": "TARA",
        "text": ("Not alone. I need a crew. A real crew. Not soldiers. "
                 "Scientists, engineers, specialists who understand "
                 "what we're looking for."),
        "next": "s4_b_3",
    },
    "s4_b_3": {
        "speaker": "KAEL",
        "text": "And Command? What about your obligations?",
        "next": "s4_b_4",
    },
    "s4_b_4": {
        "speaker": "TARA",
        "text": ("[challenging] \"Command sent you to investigate. I'm "
                 "telling you what happened. I'm also telling you what "
                 "needs to happen next. The question is: are you going "
                 "to report me, arrest me, or help me?\""),
        "next": "s5_intro",
    },
    "s4_c_1": {
        "speaker": "TARA",
        "text": ("[offers Kael a data chip] \"Take this to Command. "
                 "Tell them what you found. But tell them also that "
                 "I'm going. With or without authorisation. The "
                 "mystery of The Killers won't stay buried forever. "
                 "Kratos is proof of that.\""),
        "next": "s5_intro",
    },

    # ── Scene 5 (closing) ──────────────────────────────────────────────
    "s5_intro": {
        "speaker": "KAEL",
        "text": ("[studies the data chip] \"If you go out there, into "
                 "the Dead Zone, you might find answers. Or you might "
                 "find something worse.\""),
        "next": "s5_1",
    },
    "s5_1": {
        "speaker": "TARA",
        "text": ("I know. But I'd rather face something and know the "
                 "truth than hide here waiting for Kratos to decide "
                 "I'm finally expendable."),
        "next": "s5_2",
    },
    "s5_2": {
        "speaker": "KAEL",
        "text": ("[turns away, conflicted] \"Command won't authorise "
                 "a civilian expedition into hostile space. They'll "
                 "quarantine this data. Lock down the research.\""),
        "next": "s5_3",
    },
    "s5_3": {
        "speaker": "TARA",
        "text": ("[smiles slightly] \"Then it's fortunate that I'm "
                 "not asking for authorisation. I'm going to need a "
                 "week. Maybe two. To gather my team, prepare "
                 "supplies, and chart the safest possible course "
                 "through the Dead Zone.\""),
        "next": "s5_4",
    },
    "s5_4": {
        "speaker": "KAEL",
        "text": "And after? Assuming you somehow survive and discover something?",
        "choices": [
            {"text": "Then we document it. We broadcast it. We make "
                     "sure the entire galaxy knows what we've found. "
                     "Because once knowledge is public, Kratos can't "
                     "suppress it anymore.", "next": "s5_a_1"},
            {"text": "[returns to organising her research] Tell Command "
                     "I'm the most valuable asset they have right now. "
                     "Because I have what Kratos wants. And I know "
                     "how to survive what they can't. That makes me "
                     "useful.", "next": "s5_b_1"},
            {"text": "[extends her hand] Help me, Scout. Not as "
                     "Command's representative. As someone who wants "
                     "the truth more than they want orders.",
             "next": "s5_c_1"},
        ],
    },
    "s5_a_1": {
        "speaker": "KAEL",
        "text": "[realises the implications] \"You're going to blow this wide open.\"",
        "next": "s5_a_2",
    },
    "s5_a_2": {
        "speaker": "TARA",
        "text": ("[nods firmly] \"Yes. Whether Command wants me to or "
                 "not. The truth about The Killers belongs to "
                 "everyone, not to Kratos and their secrets.\""),
        "next": "ending",
    },
    "s5_b_1": {
        "speaker": "KAEL",
        "text": "And what do you want from me?",
        "next": "s5_b_2",
    },
    "s5_b_2": {
        "speaker": "TARA",
        "text": ("Don't arrest me. Don't report my location until "
                 "I've left the station. And if you find evidence of "
                 "who tipped Kratos off about my expedition... find "
                 "them. Because there's a traitor in Command, and "
                 "they're going to try again."),
        "next": "ending",
    },
    "s5_c_1": {
        "speaker": "KAEL",
        "text": ("[shakes her hand] \"I'll document everything. I'll "
                 "report to Command. But I won't stop you. And I'll "
                 "make sure you have every piece of intelligence I "
                 "can gather about the Dead Zone.\""),
        "next": "s5_c_2",
    },
    "s5_c_2": {
        "speaker": "TARA",
        "text": ("[genuine relief] \"Thank you. The fate of humanity "
                 "might depend on what we find in that zone. The fate "
                 "of everything else... well, that might depend on "
                 "what we wake up.\""),
        "next": "ending",
    },

    # ── Ending (shared across all Scene 5 branches) ────────────────────
    "ending": {
        "speaker": "NARRATOR",
        "text": ("They stand together, looking at the star maps "
                 "pointing toward the Dead Zone."),
        "end": True,
        "aftermath": {
            "tara_quest_dead_zone": True,
            "status": "unauthorised_expedition_leader",
            "relationship_kael": "cautious_ally",
            "evidence": "archaeology_database_and_kratos_device_specs",
            "the_killers_revealed": True,
            "kratos_conspiracy_revealed": True,
            "objective": ("Assemble expedition team; prepare for Dead "
                          "Zone entry in 1-2 weeks"),
        },
    },
}
