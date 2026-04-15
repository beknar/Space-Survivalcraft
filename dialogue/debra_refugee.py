"""Debra's Double Star Refugee conversation tree.

Each node is keyed by id and contains:
- ``speaker`` + ``text`` (one beat shown per node)
- optional ``stage`` (scene description shown once as dialogue header)
- exactly one of ``choices`` (list of {text, next}), ``next`` (id), or
  ``end`` (True, optional ``aftermath`` dict of flags to set).

The overlay advances through ``next``/choices until it hits an ``end``.
"""
from __future__ import annotations


DEBRA_REFUGEE_TREE: dict = {
    "start": "intro",

    # ── Scene 1 ────────────────────────────────────────────────────────
    "intro": {
        "stage": "Outer sector outpost. Kael Vox, military scout, approaches Debra Wildstar.",
        "speaker": "KAEL",
        "text": ("Commander Wildstar? I'm Scout Kael Vox, sent from "
                 "Double Star Command. I have a report—"),
        "choices": [
            {"text": "Make it quick. I don't have time for bureaucracy.",
             "next": "b1a"},
            {"text": "What is it, Scout?", "next": "b1b"},
            {"text": "If this is about the Falling Sword incident, "
                     "I've already—", "next": "b1c"},
        ],
    },
    "b1a": {
        "speaker": "KAEL",
        "text": ("This concerns Ken Tamashii. Your... fiancé. "
                 "[Debra's expression hardens]"),
        "next": "s2_1",
    },
    "b1b": {
        "speaker": "KAEL",
        "text": ("I have information about Ken Tamashii from Command. "
                 "[Debra tenses visibly]"),
        "next": "s2_1",
    },
    "b1c": {
        "speaker": "KAEL",
        "text": "It's about what happened after. To Ken. [Debra goes silent]",
        "next": "s2_1",
    },

    # ── Scene 2 ────────────────────────────────────────────────────────
    "s2_1": {
        "speaker": "KAEL",
        "text": "His body... it's gone missing. From the Inner Core System.",
        "next": "s2_2",
    },
    "s2_2": {
        "speaker": "DEBRA",
        "text": "[voice cold] \"What do you mean, 'gone missing'?\"",
        "next": "s2_3",
    },
    "s2_3": {
        "speaker": "KAEL",
        "text": ("Three weeks ago, Command discovered the body was no "
                 "longer in secured storage. The guards reported no breach, "
                 "no unauthorized access. It simply... vanished."),
        "next": "s2_4",
    },
    "s2_4": {
        "speaker": "DEBRA",
        "text": ("[grips Kael's uniform] \"That's impossible. Ken was "
                 "guarded. The funeral—\""),
        "next": "s2_5",
    },
    "s2_5": {
        "speaker": "KAEL",
        "text": ("The funeral never happened. Command kept it classified. "
                 "They were still investigating when—"),
        "next": "s3_intro",
    },

    # ── Scene 3 ────────────────────────────────────────────────────────
    "s3_intro": {
        "speaker": "DEBRA",
        "text": ("[releasing him, voice shaking with rage] "
                 "\"Tell me EVERYTHING. I want every detail Command has.\""),
        "choices": [
            {"text": "How long has this been happening?", "next": "s3a"},
            {"text": "Who had access to the body?", "next": "s3b"},
            {"text": "Why wasn't I informed?", "next": "s3c"},
        ],
    },
    "s3a": {
        "speaker": "KAEL",
        "text": ("The disappearance occurred 21 days ago. Command sent me "
                 "because communications from the outer sectors have been... "
                 "unreliable. I was supposed to find survivors and "
                 "investigate the sector blackouts."),
        "choices": [
            {"text": "Blackouts? What blackouts?", "next": "s3a_i"},
            {"text": "And you're just now telling me about Ken?",
             "next": "s3a_ii"},
        ],
    },
    "s3a_i": {
        "speaker": "KAEL",
        "text": ("Entire regions of the Nebula Zone have gone dark. No "
                 "transmissions. No automated beacons. Command sent me to "
                 "find out why. [Debra's anger shifts toward concern]"),
        "next": "s4_intro",
    },
    "s3a_ii": {
        "speaker": "KAEL",
        "text": ("Command prioritized the sector investigation. I was "
                 "given your location as a secondary objective. "
                 "[Debra looks away, fists clenched]"),
        "next": "s4_intro",
    },
    "s3b": {
        "speaker": "KAEL",
        "text": ("Medical personnel, two guards, and Command officers. "
                 "All cleared. No suspects."),
        "choices": [
            {"text": "That's not 'no suspects.' That's everyone with access.",
             "next": "s3b_i"},
            {"text": "That's a 12-hour window.", "next": "s3b_iii"},
        ],
    },
    "s3b_i": {
        "speaker": "KAEL",
        "text": "Command doesn't believe any of them were involved.",
        "choices": [
            {"text": "Command was wrong about a lot of things.",
             "next": "s3b_i_a"},
            {"text": "What about the guards? Were they questioned?",
             "next": "s3b_i_b"},
        ],
    },
    "s3b_i_a": {
        "speaker": "DEBRA",
        "text": "[Debra turns away, pacing]",
        "next": "s4_intro",
    },
    "s3b_i_b": {
        "speaker": "KAEL",
        "text": ("Extensively. They maintain they saw nothing unusual. "
                 "The body was there during final checks. Gone at morning "
                 "inspection. [Debra slams her fist against the wall]"),
        "next": "s4_intro",
    },
    "s3b_iii": {
        "speaker": "KAEL",
        "text": "Yes. Command has no explanation.",
        "next": "s4_intro",
    },
    "s3c": {
        "speaker": "KAEL",
        "text": ("Command classified it. They didn't want to create panic "
                 "in the outer sectors. And... they weren't sure if you'd "
                 "already made contact with dissidents. "
                 "[Debra stares at him, stunned]"),
        "choices": [
            {"text": "You think I'm compromised?", "next": "s3c_i"},
            {"text": "After everything I did to save those people, "
                     "Command doubts me?", "next": "s3c_ii"},
        ],
    },
    "s3c_i": {
        "speaker": "KAEL",
        "text": ("I don't think that. But Command had to consider every "
                 "possibility."),
        "next": "s4_intro",
    },
    "s3c_ii": {
        "speaker": "KAEL",
        "text": ("They doubt everyone now. The Falling Sword incident "
                 "shook confidence in protocols. [Uncomfortable silence]"),
        "next": "s4_intro",
    },

    # ── Scene 4 ────────────────────────────────────────────────────────
    "s4_intro": {
        "speaker": "DEBRA",
        "text": ("[voice barely controlled] \"Is there anything else? "
                 "Anything Command found? Traces? DNA samples? Anything?\""),
        "next": "s4_1",
    },
    "s4_1": {
        "speaker": "KAEL",
        "text": ("The storage chamber was clean. No signs of forced entry, "
                 "no contamination. Whoever took him knew what they were "
                 "doing."),
        "next": "s4_2",
    },
    "s4_2": {
        "speaker": "DEBRA",
        "text": ("[long pause] \"Took him. You said 'took him,' not 'it' "
                 "or 'the body.'\""),
        "next": "s4_3",
    },
    "s4_3": {
        "speaker": "KAEL",
        "text": "[hesitates] \"Yes. I did.\"",
        "next": "s4_4",
    },
    "s4_4": {
        "speaker": "DEBRA",
        "text": ("\"Why would someone take Ken's body?\" "
                 "[She looks directly at Kael, eyes intense]"),
        "next": "s4_5",
    },
    "s4_5": {
        "speaker": "KAEL",
        "text": ("Command doesn't have a theory. But given the sector "
                 "blackouts and the disappearance... I don't think "
                 "they're unrelated."),
        "next": "s4_6",
    },
    "s4_6": {
        "speaker": "DEBRA",
        "text": "[voice drops to dangerous whisper] \"What are you saying, Scout?\"",
        "next": "s4_7",
    },
    "s4_7": {
        "speaker": "KAEL",
        "text": ("I'm saying Command is frightened. They sent me out here "
                 "to find answers, but no one's given me the full picture. "
                 "You're a survivor of the Falling Sword. You understand "
                 "crisis situations. This feels like something bigger."),
        "choices": [
            {"text": "The aliens.", "next": "s4a"},
            {"text": "[to herself] They wanted his body for a reason.",
             "next": "s4b"},
            {"text": "Send me everything Command has. All files. "
                     "All theories.", "next": "s4c"},
        ],
    },
    "s4a": {
        "speaker": "KAEL",
        "text": "[surprised] \"Aliens? What aliens?\"",
        "choices": [
            {"text": "You came to the Nebula Zone blind, didn't you?",
             "next": "s4a_i"},
            {"text": "There are things here, Scout. In the dark. "
                     "They're not human, and they're not friendly.",
             "next": "s4a_ii"},
        ],
    },
    "s4a_i": {
        "speaker": "KAEL",
        "text": ("What do you know about the Nebula Zone? "
                 "[Debra realizes Kael is a liability]"),
        "next": "s5_intro",
    },
    "s4a_ii": {
        "speaker": "KAEL",
        "text": "[hand moves to sidearm] \"How do you know this?\"",
        "next": "s4a_ii_b",
    },
    "s4a_ii_b": {
        "speaker": "DEBRA",
        "text": "Experience. Survival. The hard way.",
        "next": "s5_intro",
    },
    "s4b": {
        "speaker": "KAEL",
        "text": "Commander?",
        "next": "s4b_b",
    },
    "s4b_b": {
        "speaker": "DEBRA",
        "text": "Nothing. I need to think.",
        "next": "s5_intro",
    },
    "s4c": {
        "speaker": "KAEL",
        "text": "I can provide what I'm cleared to share—",
        "next": "s4c_b",
    },
    "s4c_b": {
        "speaker": "DEBRA",
        "text": ("[steps forward, dangerous] \"I don't care about "
                 "clearance levels, Scout. Ken Tamashii was my "
                 "responsibility. He died because I failed him. I will NOT "
                 "fail him again.\" [Kael nods slowly]"),
        "next": "s5_intro",
    },

    # ── Scene 5 ────────────────────────────────────────────────────────
    "s5_intro": {
        "speaker": "DEBRA",
        "text": ("[decision made] \"I'm going deeper. Beyond the Nebula "
                 "Zone. Whoever—whatever—took Ken, they came from further "
                 "out.\""),
        "next": "s5_1",
    },
    "s5_1": {
        "speaker": "KAEL",
        "text": ("[alarmed] \"Commander, that's beyond charted territory. "
                 "There's nothing out there but void and speculation.\""),
        "next": "s5_2",
    },
    "s5_2": {
        "speaker": "DEBRA",
        "text": ("Exactly. Which is why Command doesn't know what took "
                 "Ken. They're looking inward. I need to look outward."),
        "next": "s5_3",
    },
    "s5_3": {
        "speaker": "KAEL",
        "text": ("The sector blackouts don't extend that far. We have "
                 "no data—"),
        "choices": [
            {"text": "No data means no answers. And no witnesses.",
             "next": "s5a"},
            {"text": "Those blackouts are a barrier, Scout. Someone's "
                     "keeping something contained—or hidden.", "next": "s5b"},
            {"text": "Stay here. Keep Command updated on sector conditions. "
                     "If I don't report in within thirty days, tell them "
                     "I'm gone deeper than any of us have gone before.",
             "next": "s5c"},
        ],
    },
    "s5a": {
        "speaker": "KAEL",
        "text": "Or no survivors to give answers.",
        "next": "s5a_b",
    },
    "s5a_b": {
        "speaker": "DEBRA",
        "text": "Then I'll be the first to come back with them.",
        "next": "s5_closing",
    },
    "s5b": {
        "speaker": "KAEL",
        "text": "You think Ken's body is beyond the blackout zone?",
        "next": "s5b_b",
    },
    "s5b_b": {
        "speaker": "DEBRA",
        "text": ("I think the answers are. Ken might be too. "
                 "[She begins moving toward her ship]"),
        "next": "s5_closing",
    },
    "s5c": {
        "speaker": "KAEL",
        "text": "And if something happens to you out there?",
        "next": "s5c_b",
    },
    "s5c_b": {
        "speaker": "DEBRA",
        "text": ("Then at least I'll have answers. Which is more than "
                 "Ken got. [She pauses at the door]"),
        "next": "s5_closing",
    },

    # ── Closing ────────────────────────────────────────────────────────
    "s5_closing": {
        "speaker": "DEBRA",
        "text": ("Scout, one final thing. When—if—I come back, we talk "
                 "again. I'll bring evidence. I'll bring proof of what's "
                 "out there."),
        "next": "s5_closing_2",
    },
    "s5_closing_2": {
        "speaker": "KAEL",
        "text": "[uncertain] \"Understood, Commander. But what do I tell Command?\"",
        "next": "s5_closing_3",
    },
    "s5_closing_3": {
        "speaker": "DEBRA",
        "text": ("Tell them Debra Wildstar is following the trail. "
                 "Beyond the Nebula Zone. Into uncharted space. Tell them... "
                 "I'm not coming back until I find him. Or until I find "
                 "out why he was taken. [She exits, determined and alone]"),
        "end": True,
        "aftermath": {
            "debra_quest_find_ken": True,
            "path_uncharted_space": True,
            "emotional_state": "obsessed",
            "aliens_revealed": True,
            "objective": "Explore beyond the Nebula Zone",
        },
    },
}
