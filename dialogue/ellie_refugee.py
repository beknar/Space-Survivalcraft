"""Ellie Kobayashi's Double Star Refugee conversation tree.

Same node format as ``debra_refugee.py``: each node carries a speaker
and text (plus an optional scene-header ``stage``), and flows either
to ``choices`` / a single ``next`` / an ``end`` with an ``aftermath``
dict of quest flags.  See ``debra-conversation-tree1.txt`` for the
source spec.
"""
from __future__ import annotations


ELLIE_REFUGEE_TREE: dict = {
    "start": "intro",

    # ── Scene 1 ────────────────────────────────────────────────────────
    "intro": {
        "stage": ("Dimly lit safe house. Kael Vox enters cautiously. "
                  "Ellie Kobayashi turns from the window, hand near a "
                  "concealed weapon."),
        "speaker": "KAEL",
        "text": ("Ellie Kobayashi? I'm Scout Kael Vox, sent from Double "
                 "Star Command. I need to talk to you about the Falling "
                 "Star incident."),
        "choices": [
            {"text": "[tense, guarded] How did you find me?",
             "next": "b1a"},
            {"text": "[hand on weapon] Command sent you? Prove it.",
             "next": "b1b"},
            {"text": "[coldly] I don't need protection. I need answers. "
                     "And someone to answer for what happened.",
             "next": "b1c"},
        ],
    },
    "b1a": {
        "speaker": "KAEL",
        "text": ("Command flagged your survival status. You went dark "
                 "after the incident. Took us months to locate you. "
                 "[Ellie relaxes slightly, but remains suspicious]"),
        "next": "s2_1",
    },
    "b1b": {
        "speaker": "KAEL",
        "text": ("[carefully shows credentials] \"I'm here to gather "
                 "information about what happened. And to offer you "
                 "protection.\" [Ellie's expression hardens]"),
        "next": "s2_1",
    },
    "b1c": {
        "speaker": "KAEL",
        "text": ("That's why I'm here. Tell me your side. "
                 "[Ellie studies him, deciding whether to trust him]"),
        "next": "s2_1",
    },

    # ── Scene 2 ────────────────────────────────────────────────────────
    "s2_1": {
        "speaker": "ELLIE",
        "text": ("[sits, still watchful] \"The Falling Star wasn't just "
                 "a hijacking. It was an operation. Kratos Corporation "
                 "orchestrated it.\""),
        "next": "s2_2",
    },
    "s2_2": {
        "speaker": "KAEL",
        "text": "Kratos? The defense contractor? What would they want?",
        "next": "s2_3",
    },
    "s2_3": {
        "speaker": "ELLIE",
        "text": ("A scientist. Dr. Marcus Chen. He was carrying data — "
                 "experimental results that belonged to Kratos. They "
                 "wanted him back. And they wanted that data erased."),
        "next": "s2_4",
    },
    "s2_4": {
        "speaker": "KAEL",
        "text": "And Chen was aboard the Falling Star?",
        "choices": [
            {"text": "Yes. He was in hiding. Someone at Command tipped "
                     "Kratos off. The dissidents weren't really "
                     "dissidents — they were Kratos operatives wearing "
                     "a political mask.", "next": "s2_a_1"},
            {"text": "Chen was terrified. He knew what Kratos would do "
                     "to silence him. But I promised to protect him. "
                     "I promised I'd get him to safety.", "next": "s2_b_1"},
        ],
    },
    "s2_a_1": {
        "speaker": "KAEL",
        "text": "[concerned] \"Are you saying Command was compromised?\"",
        "next": "s2_a_2",
    },
    "s2_a_2": {
        "speaker": "ELLIE",
        "text": ("[bitter laugh] \"Not was. Is. Kratos has reach "
                 "everywhere. Military, government, private sector. "
                 "They ARE the system.\""),
        "next": "s2_a_3",
    },
    "s2_a_3": {
        "speaker": "KAEL",
        "text": "Do you have proof?",
        "next": "s2_a_4",
    },
    "s2_a_4": {
        "speaker": "ELLIE",
        "text": ("I have survival. I have what I've learned. That's "
                 "proof enough for me."),
        "next": "kael_what_happened",
    },
    "s2_b_1": {
        "speaker": "ELLIE",
        "text": "[voice hardens] \"I failed.\"",
        "next": "kael_what_happened",
    },
    "kael_what_happened": {
        "speaker": "KAEL",
        "text": "What happened?",
        "next": "s3_1",
    },

    # ── Scene 3 ────────────────────────────────────────────────────────
    "s3_1": {
        "speaker": "ELLIE",
        "text": ("[standing, pacing with controlled anger] \"When the "
                 "dissidents — the Kratos operatives — breached the "
                 "bridge, chaos erupted. I fought back. I tried to "
                 "reach Chen. But there were too many of them.\""),
        "next": "s3_2",
    },
    "s3_2": {
        "speaker": "KAEL",
        "text": "And Chen?",
        "next": "s3_3",
    },
    "s3_3": {
        "speaker": "ELLIE",
        "text": ("[voice tight] \"They shot him. Right in front of me. "
                 "Then they turned on me. I was thrown toward the "
                 "airlock. I went out... into the void.\""),
        "next": "s3_4",
    },
    "s3_4": {
        "speaker": "KAEL",
        "text": "Your emergency suit saved you.",
        "next": "s3_5",
    },
    "s3_5": {
        "speaker": "ELLIE",
        "text": ("[touches her suit reflexively] \"Barely. I drifted "
                 "for hours before a salvage vessel picked me up. But "
                 "by then, it didn't matter. My life was already "
                 "over.\""),
        "next": "s3_6",
    },
    "s3_6": {
        "speaker": "KAEL",
        "text": "Over? You survived—",
        "choices": [
            {"text": "My assets were frozen within days. Kratos used "
                     "their influence. Every account, every credit, "
                     "every resource — locked. They painted me as a "
                     "security risk. A liability.", "next": "s3_a_1"},
            {"text": "People I knew disappeared. Friends stopped "
                     "answering calls. My career was destroyed. My "
                     "reputation, erased. I became a ghost.",
             "next": "s3_b_1"},
            {"text": "So I went dark. I ran. I hid. And I planned. "
                     "Because Kratos made one critical mistake.",
             "next": "s3_c_1"},
        ],
    },
    "s3_a_1": {
        "speaker": "KAEL",
        "text": "Why? If you were just defending yourself—",
        "next": "s3_a_2",
    },
    "s3_a_2": {
        "speaker": "ELLIE",
        "text": ("Because I was a witness. And I was asking questions. "
                 "Kratos doesn't allow loose ends. [Kael realises the "
                 "scope of what she's describing]"),
        "next": "s4_intro",
    },
    "s3_b_1": {
        "speaker": "KAEL",
        "text": "That's corporate assassination.",
        "next": "s3_b_2",
    },
    "s3_b_2": {
        "speaker": "ELLIE",
        "text": ("[nods] \"Exactly. Just without the bodies. They "
                 "killed Ellie Kobayashi without firing a shot.\""),
        "next": "s4_intro",
    },
    "s3_c_1": {
        "speaker": "KAEL",
        "text": "What's that?",
        "next": "s3_c_2",
    },
    "s3_c_2": {
        "speaker": "ELLIE",
        "text": "[eyes cold and focused] \"They left me alive.\"",
        "next": "s4_intro",
    },

    # ── Scene 4 ────────────────────────────────────────────────────────
    "s4_intro": {
        "speaker": "KAEL",
        "text": ("What do you want, Ellie? If you're not asking for "
                 "protection—"),
        "next": "s4_1",
    },
    "s4_1": {
        "speaker": "ELLIE",
        "text": ("[turns to face him directly] \"I want Kratos "
                 "dismantled. I want every operative who was on that "
                 "ship identified and prosecuted. I want the scientists "
                 "they're exploiting freed. And I want the people in "
                 "Command who are on their payroll exposed.\""),
        "next": "s4_2",
    },
    "s4_2": {
        "speaker": "KAEL",
        "text": "That's... a significant list of objectives.",
        "next": "s4_3",
    },
    "s4_3": {
        "speaker": "ELLIE",
        "text": ("I know. That's why I'm telling you, Scout. Because "
                 "Command needs to know what I know. And because I "
                 "need resources."),
        "next": "s4_4",
    },
    "s4_4": {
        "speaker": "KAEL",
        "text": ("Command can't openly move against a corporation as "
                 "large as Kratos without evidence. We'd need—"),
        "choices": [
            {"text": "Proof. I have it. [She pulls out a data chip]",
             "next": "s4_a_1"},
            {"text": "[leans against wall, exhausted and determined] "
                     "I've spent months gathering additional "
                     "intelligence. Kratos's operations extend further "
                     "than Command knows.", "next": "s4_b_1"},
            {"text": "But here's the thing, Scout. If you take that to "
                     "Command, and Command is as compromised as I "
                     "believe... I'm a dead woman within the week.",
             "next": "s4_c_1"},
        ],
    },
    "s4_a_1": {
        "speaker": "ELLIE",
        "text": ("Chen gave me this before they killed him. It contains "
                 "evidence of Kratos's illegal experiments, black site "
                 "locations, and names. Military names. Government "
                 "names. Corporate names."),
        "choices": [
            {"text": "[Kael, eyes widening] You've had this the whole "
                     "time?", "next": "s4_a_2_i"},
            {"text": "[Kael] If this is real, it changes everything.",
             "next": "s4_a_2_ii"},
        ],
    },
    "s4_a_2_i": {
        "speaker": "ELLIE",
        "text": ("I've been careful with it. Encrypted. Hidden. Waiting "
                 "for the right moment to use it."),
        "next": "s4_a_2_i_b",
    },
    "s4_a_2_i_b": {
        "speaker": "KAEL",
        "text": "Why tell me now?",
        "next": "s4_a_2_i_c",
    },
    "s4_a_2_i_c": {
        "speaker": "ELLIE",
        "text": ("Because I realised I can't do this alone. And "
                 "because... I need to know if Command is worth "
                 "saving. If you are. [Kael takes the chip carefully]"),
        "next": "s5_intro",
    },
    "s4_a_2_ii": {
        "speaker": "ELLIE",
        "text": ("It is real. And it does. The question is: what are "
                 "you going to do about it?"),
        "next": "s5_intro",
    },
    "s4_b_1": {
        "speaker": "KAEL",
        "text": "How much of this do you have documented?",
        "next": "s4_b_2",
    },
    "s4_b_2": {
        "speaker": "ELLIE",
        "text": ("Enough. Names, dates, transactions, facility "
                 "locations. All encrypted on that chip. All "
                 "verifiable."),
        "next": "s5_intro",
    },
    "s4_c_1": {
        "speaker": "KAEL",
        "text": "[hesitates] \"Then what do you propose?\"",
        "next": "s4_c_2",
    },
    "s4_c_2": {
        "speaker": "ELLIE",
        "text": ("We don't go to Command. Not directly. We go to "
                 "people we trust. People we can verify. Build a case "
                 "quietly. Then strike."),
        "next": "s5_intro",
    },

    # ── Scene 5 ────────────────────────────────────────────────────────
    "s5_intro": {
        "speaker": "ELLIE",
        "text": ("[walking closer, intensity in every movement] \"I "
                 "know Kratos's next major operation. They're "
                 "extracting a weapons scientist from a research "
                 "station in the outer sectors. In three weeks. I "
                 "have the coordinates. I have the timeline.\""),
        "next": "s5_1",
    },
    "s5_1": {
        "speaker": "KAEL",
        "text": "You want to intercept them.",
        "next": "s5_2",
    },
    "s5_2": {
        "speaker": "ELLIE",
        "text": ("I want to shut them down. I want to expose them. "
                 "And I want to make sure no one else dies like Chen "
                 "did."),
        "next": "s5_3",
    },
    "s5_3": {
        "speaker": "KAEL",
        "text": "That's a military operation, Ellie. You'd need—",
        "choices": [
            {"text": "[interrupts] I need people who aren't corrupted. "
                     "People who still believe in justice instead of "
                     "profit. Can you find those people, Scout?",
             "next": "s5_a_1"},
            {"text": "[dangerous smile] Or I can do this alone. I've "
                     "been alone before. I can handle it. But with "
                     "Command's resources, with your help... Kratos "
                     "doesn't stand a chance.", "next": "s5_b_1"},
            {"text": "[offers the data chip] Take this. Examine it. "
                     "Verify it. And then decide if you're the kind "
                     "of scout who just reports what he finds, or the "
                     "kind who acts on it.", "next": "s5_c_1"},
        ],
    },
    "s5_a_1": {
        "speaker": "KAEL",
        "text": ("[long pause] \"I can try. But I'm going to need "
                 "more than a data chip. I need you to brief me "
                 "fully. Names, dates, everything.\""),
        "next": "s5_a_2",
    },
    "s5_a_2": {
        "speaker": "ELLIE",
        "text": "Then we're doing this together?",
        "next": "s5_a_3",
    },
    "s5_a_3": {
        "speaker": "KAEL",
        "text": ("Against my better judgment... yes. But if you're "
                 "wrong about any of this—"),
        "next": "s5_a_4",
    },
    "s5_a_4": {
        "speaker": "ELLIE",
        "text": ("[coldly] \"I'm not wrong. And if I am, we both die "
                 "anyway.\""),
        "next": "s6_intro",
    },
    "s5_b_1": {
        "speaker": "KAEL",
        "text": "You're asking me to betray Command.",
        "next": "s5_b_2",
    },
    "s5_b_2": {
        "speaker": "ELLIE",
        "text": "I'm asking you to save it. There's a difference.",
        "next": "s6_intro",
    },
    "s5_c_1": {
        "speaker": "KAEL",
        "text": ("[takes the chip, its weight feeling significant]"),
        "next": "s6_intro",
    },

    # ── Scene 6 (closing) ──────────────────────────────────────────────
    "s6_intro": {
        "speaker": "KAEL",
        "text": ("If I do this, if I help you... what happens to you "
                 "after?"),
        "next": "s6_1",
    },
    "s6_1": {
        "speaker": "ELLIE",
        "text": ("[returns to the window, looking out] \"After we "
                 "dismantle Kratos? After we expose them? I don't "
                 "know. Maybe I get my life back. Maybe I just get "
                 "the satisfaction of knowing they're gone.\""),
        "next": "s6_2",
    },
    "s6_2": {
        "speaker": "KAEL",
        "text": "And if we fail?",
        "next": "s6_3",
    },
    "s6_3": {
        "speaker": "ELLIE",
        "text": ("[expression resolute] \"Then at least I'll have "
                 "tried. At least I'll have fought. That's more than "
                 "I've had since they threw me out of that airlock.\""),
        "next": "s6_4",
    },
    "s6_4": {
        "speaker": "KAEL",
        "text": ("[stands] \"Alright, Ellie Kobayashi. I'm in. But we "
                 "do this smart. We verify every piece of intel. We "
                 "build an airtight case. And we don't move until "
                 "we're certain.\""),
        "choices": [
            {"text": "How long will verification take?",
             "next": "s6_a_1"},
            {"text": "Where do we start?",
             "next": "s6_b_1"},
            {"text": "[extends her hand] Welcome to the fight, Scout. "
                     "I hope you're ready for what's coming.",
             "next": "s6_c_1"},
        ],
    },
    "s6_a_1": {
        "speaker": "KAEL",
        "text": ("A week. Maybe two. Depends on how thorough we need "
                 "to be. And how deep the corruption goes."),
        "next": "s6_a_2",
    },
    "s6_a_2": {
        "speaker": "ELLIE",
        "text": ("[nods] \"We have time. The operation isn't for "
                 "three weeks. Use it wisely.\""),
        "next": "ending",
    },
    "s6_b_1": {
        "speaker": "KAEL",
        "text": ("We start by finding out who in Command we can "
                 "trust. That's the hardest part. Everything else "
                 "flows from there."),
        "next": "s6_b_2",
    },
    "s6_b_2": {
        "speaker": "ELLIE",
        "text": ("I have a list. People I've been watching. People "
                 "who've acted against Kratos interests."),
        "next": "s6_b_3",
    },
    "s6_b_3": {
        "speaker": "KAEL",
        "text": "Good. We'll cross-reference it with my intelligence.",
        "next": "ending",
    },
    "s6_c_1": {
        "speaker": "KAEL",
        "text": ("[shakes her hand — firm, determined] \"I've survived "
                 "worse. I think.\""),
        "next": "s6_c_2",
    },
    "s6_c_2": {
        "speaker": "ELLIE",
        "text": "[slight smile] \"No. You haven't. But you will.\"",
        "next": "ending",
    },

    # ── Ending (shared across all Scene 6 branches) ────────────────────
    "ending": {
        "speaker": "NARRATOR",
        "text": ("They stand in the dim light, an unlikely alliance "
                 "formed."),
        "end": True,
        "aftermath": {
            "ellie_quest_dismantle_kratos": True,
            "status": "active_operative",
            "relationship_kael": "allied",
            "evidence": "chen_data_chip",
            "kratos_infiltration_revealed": True,
            "objective": ("Verify intelligence; intercept Kratos "
                          "extraction in 3 weeks"),
        },
    },
}
