# STFU Requiem — web

The stfu-reborn Discord bot (singularitybot) as a website at https://stfurequiem.com.
Players log in with Discord and find their bot save: the site reads and writes
the bot's Redis directly.

## Stack
Flask + HTMX + Jinja, gunicorn, Redis (shared with the bot). No other database.

## Data (same as the bot)
- `HSET users <discord_id> pickle(user_doc)`; very old players live under `b'<discord_id>'`
  and are written back to that same field, like the bot does.
- `HSET gangs <gang_id> pickle(gang_doc)` (read for profiles).
- Pickle protocol 4 (bot image is Python 3.11).
- Website-only keys start with `web:` (OAuth state, action locks, fights in progress,
  cached Discord names, cached leaderboards).

## Features
- Discord OAuth2 login; account creation = `/adventure begin` (1 super fragment)
- Banners: 10-pull with super fragments and pity, 5-pull with a Stand Arrow
- Team and 4 + 4 premium storages: add, swap, store, release, fuse, ascend, reforge,
  equip, unequip, team presets
- Items: use (arrows, chips, requiem arrow, bag of coins), crafting, default shop
- Daily reward, energy refill, wormhole fights (turn by turn, taunt, terrain)
- Quests (view, claim, claim all) and achievements tracked like the bot
- Public stand encyclopedia, leaderboards, player profiles

Not ported yet: ranked, tower, dungeon, story, gangs, player shops, trades.

## Game code
`app/game/` is vendored from stfu-reborn with Discord imports removed:
`character.py`, `items.py`, `effects.py`, `characterabilities.py`, `itemabilities.py`,
`quests.py`, `achievements.py`, `user.py`, and the JSON templates.
`logic.py` ports the slash commands, `fight.py` ports `fighthandler.fight_loop`
as a resumable state machine. When the bot's data or abilities change, copy the
files again.

## Deploy on Coolify
1. Docker Compose resource on this repo, domain `https://stfurequiem.com` on `web`, port 8000.
2. Environment from `.env.example`; `REDIS_URL` = the bot's Redis (put both in the same
   Coolify network, or use the bot Redis' public URL with a password).
3. Discord developer portal, OAuth2, Redirects: `https://stfurequiem.com/auth/callback`.

## Tests
`pip install -r requirements.txt pytest fakeredis && pytest -q`
