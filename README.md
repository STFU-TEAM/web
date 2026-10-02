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
- Website-only tower progress is stored in `web_tower_*` user fields; the bot's user model
  preserves unknown fields when it writes the shared document.

## Features
- Discord OAuth2 login; account creation = `/adventure begin` (1 super fragment)
- Banners: 10-pull with super fragments and pity, 5-pull with a Stand Arrow
- Team and one unified 200-stand collection: add, swap, store, release, fuse, ascend, reforge,
  equip, unequip, team presets
- Items: use (arrows, chips, requiem arrow, bag of coins), crafting, default shop
- Daily reward, energy refill, wormhole fights (turn by turn, taunt, terrain)
- Quests (view, claim, claim all) and achievements tracked like the bot
- Ranked Elo ladder, with global player profiles
- Battle modes: dummy practice, live ranked queue and accepted friend challenges
- Fight special animations loaded from `IMAGE_BASE_URL/special/<stand_id>.gif` when available
- Gangs: ranks (kick/promote/demote/hand over boss), guardians, vault + payments, stash and wars
  (matched by the bot's warmatchmaking worker). Weekly raids are web-only: one villain a week,
  one attack per member per day, four damage tiers every attacker claims (`app/game/gangs.py`)
- Story mode (`app/game/story.py`) and the weekly boss rush (`app/game/rush.py`): the six story
  bosses back to back with health carried over, one run a day, weekly leaderboard
- News feed (`app/news.py`): admins post from /admin/news with an uploaded or linked cover image
- Crafting: materials (Meteorite Shard, Rokakaka Fruit, Arrow Fragment) and craftable gear in
  `items.json` / `recipes.json`; gear specials live in `itemabilities.py`
- The adventure dungeon is closed for now: set `DUNGEON_ENABLED=1` to bring it back
- Logins: Discord OAuth or username + password (app/accounts.py). Password saves get an `acc…` id;
  linking Discord later moves the save to the Discord id so the bot sees it
- Story mode, achievements page, trades (async offers of stands/items/fragments), item selling
- Collection tools: stand panel, search/rarity/fusable filters, sorting, bulk release, locks
- Banners: kinder web odds (logic.BANNER_ODDS / PITY_LIMIT), SR floor per 10-pull, flip reveal, history
- Admin: dashboard, player editor (values, items, stands, cooldowns, story, supporter, web ban, raw
  save), gangs, shops, banner on/off, filterable audit log
- Player shops: list, buy and return items with locked buyer/seller transfers
- Tower: six sequential PvE floors, persisted progress and shared fight UI
- Adventure dungeon: map exploration with battles, weighted chests, bombs and energy wager
- Admin panel: bot-moderator Discord IDs can grant bounded resources; changes are audited
- Public stand encyclopedia, leaderboards, player profiles
- Wiki (`/wiki`): the bot's `/wiki` topics plus terrain and synergy explorers, built from
  `effects.py` / `characterabilities.py` by `app/wiki.py`. When a special starts checking a
  synergy, add its effect text to `SYNERGY_EFFECTS` (a test fails until you do)
- Installable web app: `/manifest.webmanifest`, bottom tab bar and menu sheet below 1024px

Not ported yet: multi-map dungeon progression, top.gg voting.

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

The site also links to Discord's standard bot-install authorization at `/auth/bot`.
It uses the existing `DISCORD_CLIENT_ID` and requests the `bot` and
`applications.commands` scopes; no extra secret or password flow is needed.
Admin access mirrors the bot's `give_character` permission IDs by default. Set
`DISCORD_ADMIN_IDS` to a comma-separated Discord ID list to override them.

## Local testing
`pip install -r requirements-dev.txt && python scripts/dev.py`, then log in at
http://127.0.0.1:5000/auth/login with `admin` / `admin`. That account is an admin (`/admin`)
and starts with a team, storage, fragments and items. Data lives in an in-memory Redis
that is wiped when the server stops; pass `--redis redis://localhost:6379/0` to keep it.
The script ignores `REDIS_URL`, so it never touches the bot's Redis by accident.

## Tests
`pip install -r requirements-dev.txt && pytest -q`

## Storage migration
Preview the old-box consolidation against the configured Redis database with
`python scripts/migrate_storage.py`. Apply it with `python scripts/migrate_storage.py --apply`;
the script backs up each original user pickle to `web:storage:migration:v1:backup`
before writing the unified collection. The migration is safe to rerun. Keep the
legacy bot offline during migration; do not restart a bot build that only reads
the old per-box fields until it has been updated to read and write
`storage_characters` as well.
