"""The public changelog (/changelog): what changed, newest first. Add an entry at the top for every release.

entry = {"version", "date" (ISO), "title", "sections": [(heading, [line, ...]), ...]}
"""
ENTRIES = [
    {"version": "1.0", "date": "2026-10-12", "title": "Requiem",
     "sections": [
         ("New", [
             "The Requiem Tower: a second weekly climb for maxed teams, level 100 ★5 from floor 1, with Requiem Arrows every 10th floor and its own ladder.",
             "The dungeon goes down to B9: the Over Heaven depths (B4–B6) and the Requiem depths (B7–B9), bosses on B3, B6 and B9, and up to ×4 loot.",
             "Requiem · Over Heaven: six fights that open once Requiem mode is cleared, Requiem's finales with heaven's rules on top.",
             "The Over Heaven toggle: climb either tower under heaven's rules for 30% more Meteor Dust.",
             "Chip combining: fuse spare chips into one of the synergy you want, with a chance to climb a tier.",
             "The Bites the Dust Switch, an event-only item that detonates every poison and burn at once.",
             "Share cards: show off a pull, a clear or a tower record with a link that previews in Discord and everywhere else.",
             "A welcome week for new Stand users: a reward every day for the first 7 days.",
         ]),
         ("Changes", [
             "Heavy Weather: Whitesnake and Weather Report now form a synergy.",
             "Poison stands hit harder, and poison also eats a share of the target's max health.",
             "Fights are paced to last about 5 turns between top teams.",
             "★4 and ★5 now take a Requiem Arrow and a spare copy of the stand.",
             "Refining costs more (2,500 to 10,000 Meteor Dust a level) and has a new forge page showing exactly what each level adds.",
         ]),
         ("Quality of life", [
             "The dungeon plays without reloading the page.",
             "Stunned, poisoned and burning stands show it on their portrait.",
             "A live ranked-queue counter in the menu.",
             "Summon results fit small phones properly.",
         ]),
     ]},
    {"version": "0.9", "date": "2026-10-11", "title": "Endgame",
     "sections": [
         ("New", [
             "Requiem mode: the story, every universe and Carry Me again, tuned for maxed teams.",
             "Carry Me, Part 10: Joyce Joestar's story, with an encore under Over Heaven rules.",
             "Over Heaven tracks for every mode.",
             "The daily puzzle, Who's that Stand?, the Gang Cup and the gang ladder.",
         ]),
     ]},
    {"version": "0.8", "date": "2026-10-08", "title": "Teams",
     "sections": [
         ("New", [
             "Synergies and resonances between stands that belong together.",
             "Team presets, the team planner and the simulator.",
             "The training ground, reforging, push notifications and progression unlocks.",
         ]),
     ]},
    {"version": "0.7", "date": "2026-10-04", "title": "Collection",
     "sections": [
         ("New", [
             "Full art and shiny stands, the auction house and the Crusaders' Journey.",
             "Pity on every banner and Devil's Palm pulls.",
         ]),
     ]},
]
