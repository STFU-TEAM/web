"""The chat automod: every message to the global chat, a private conversation or a raid chat passes here first
(chat.post). It cleans what it can and refuses or flags the rest:

- Blocked words: slurs and anything an admin adds (ADMIN_WORDS, from the admin Reports tab). Matched through spacing,
  l33t and repeated letters. The message is refused and counts as a strike.
- Spam: the same message twice in a row, or a flood (FLOOD messages in FLOOD_WINDOW seconds) is refused; a flood also
  mutes for FLOOD_MUTE minutes. Shouting is turned down to lower case and long runs of one letter are cut short.
- Links: the global chat takes links to this site, its Discord and GIF sites only.
- Scams: asking for passwords or logins, fake free-Nitro / gift links, "send first and I'll double it", posing as
  staff. A scam message is refused in the global chat; in a private one it is delivered with a warning shown to the
  receiver, and an admin report is filed either way.
- Private messages: a player starts at most NEW_DM_HOUR new conversations an hour and NEW_DM_DAY a day (fewer for
  brand-new saves), and the same text sent to COPY_PASTE different players in COPY_WINDOW is refused (mass DMs).
STRIKES strikes in a day mute the player for STRIKE_MUTE hours. Admins are never filtered.

Redis:
    web:automod:words               set of extra blocked words (admins)
    web:automod:strikes:<uid>       strike count, for a day
    web:automod:flood:<uid>         message count in the flood window
    web:automod:last:<uid>:<chan>   the player's last message there (for repeats)
    web:automod:newdm:<uid>:h|d     new conversations started this hour / today
    web:automod:copy:<uid>:<hash>   set of players who got that text recently
"""
import hashlib
import re
import time
from typing import Optional, Tuple

from app.db import r
from app.game.logic import GameError

WORDS_KEY = "web:automod:words"
STRIKES, STRIKE_MUTE = 3, 1          # strikes a day, then muted this many hours
FLOOD, FLOOD_WINDOW, FLOOD_MUTE = 6, 15, 5
REPEAT_WINDOW = 120
NEW_DM_HOUR, NEW_DM_DAY = 6, 20
NEW_DM_DAY_FRESH = 4                 # a save under a day old, or under player level 3
COPY_PASTE, COPY_WINDOW = 3, 600
SHOUT_MIN = 12

# The slurs every chat refuses (matched as whole words after the text is normalised: see _norm). Admins add the rest.
BASE_WORDS = {"nigger", "nigga", "niggers", "niggas", "faggot", "faggots", "fag", "fags", "retard", "retards", "retarded",
              "tranny", "trannies", "chink", "chinks", "spic", "spics", "kike", "kikes", "wetback", "coon", "coons"}
LEET = str.maketrans({"0": "o", "1": "i", "!": "i", "3": "e", "4": "a", "@": "a", "5": "s", "$": "s", "7": "t", "+": "t",
                      "8": "b", "|": "i"})
ALLOWED_HOSTS = ("stfurequiem.com", "discord.gg/stfurequiem", "discord.com/invite/stfurequiem", "tenor.com", "giphy.com",
                 "media.tenor.com", "media.giphy.com")
LINK = re.compile(r"(?i)\b((?:https?://|www\.)\S+|[a-z0-9-]+\.(?:com|net|org|gg|gift|ru|xyz|io|me|ly|co|link|click|top|shop|app)"
                  r"(?:/\S*)?)")
SCAM = [
    (re.compile(r"(?i)\b(send|give|tell|dm|share)\b.{0,25}\b(your|ur|me your)\b.{0,15}\b(password|pass|pw|login|token|"
                r"code|2fa|email and password)\b"), "asks for a password or login"),
    (re.compile(r"(?i)\b(password|login|token)\b.{0,20}\b(send|give|share|dm)\b.{0,10}\bme\b"), "asks for a password or login"),
    (re.compile(r"(?i)free\s*(discord\s*)?nitro|discord\.?gift|dlscord|disc0rd|discorcl|steamcommunlty|stearn"),
     "a fake gift link"),
    (re.compile(r"(?i)\b(send|give)\b.{0,30}\b(and|&)\b.{0,15}\b(i'?ll|i will|ill)\b.{0,15}\b(double|triple|x2|x3|give back)"),
     "the send-first scam"),
    (re.compile(r"(?i)\b(i'?m|i am|this is)\b.{0,10}\b(an? )?(admin|staff|moderator|mod|developer|dev)\b.{0,40}"
                r"\b(verify|password|login|account|ban|banned)\b"), "poses as staff"),
    (re.compile(r"(?i)\b(verify|confirm|unlock)\b.{0,20}\b(your|ur)\b.{0,10}\baccount\b.{0,40}(https?://|www\.|\.com|\.gg)"),
     "a fake verification link"),
]
SCAM_WARNING = ("⚠ Careful: this message looks like a scam. Nobody from STFU Requiem will ever ask for your password, "
                "and trades go through the trade and auction pages only.")


def _norm(text: str) -> str:
    """Lower case, l33t undone, accents and spacing tricks gone, letter runs cut to two: "N i G G 3 r" -> "niger"."""
    t = text.lower().translate(LEET)
    t = re.sub(r"[^a-z\s]", "", t)
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)
    return t


def _words(text: str) -> set:
    t = _norm(text)
    words = set(t.split())
    # letters spaced out one by one ("n i g g e r"): joined back up
    joined = re.sub(r"\b(\w) (?=\w\b)", r"\1", t)
    words |= set(joined.split())
    # runs cut to one letter too ("niiiigger" was cut to "niigger" above)
    words |= {re.sub(r"(.)\1+", r"\1", w) for w in list(words)}
    return words


def blocked_words() -> set:
    return BASE_WORDS | {w.decode() if isinstance(w, bytes) else w for w in r().smembers(WORDS_KEY)}


def add_word(word: str) -> str:
    w = _norm(word).replace(" ", "")
    if not 2 <= len(w) <= 40:
        raise GameError("Give a word of 2 to 40 letters.")
    r().sadd(WORDS_KEY, w)
    return w


def remove_word(word: str):
    r().srem(WORDS_KEY, word)


def admin_words() -> list:
    return sorted(w.decode() if isinstance(w, bytes) else w for w in r().smembers(WORDS_KEY))


def _strike(uid: str, why: str):
    key = f"web:automod:strikes:{uid}"
    n = r().incr(key)
    if n == 1:
        r().expire(key, 86400)
    if n >= STRIKES:
        from app.game import chat
        chat.mute(uid, "automod", STRIKE_MUTE, f"automod: {why}")
        r().delete(key)
        return True
    return False


def _report(uid: str, text: str, kind: str, why: str):
    """File an admin report from the automod (no daily cap, one per player and reason an hour)."""
    if not r().set(f"web:automod:reported:{uid}:{why[:20]}", 1, nx=True, ex=3600):
        return
    try:
        import json
        import secrets
        from app.db import identity
        from app.game import profile as P
        r().set("web:identity:automod", json.dumps({"name": "🤖 Automod", "avatar": None}))
        rid = secrets.token_hex(5)
        entry = {"id": rid, "target": str(uid), "reporter": "automod", "reason": "chat", "note": f"Automod: {why}",
                 "at": int(time.time()), "status": "open",
                 "seen": {"name": identity(uid)["name"], "avatar": identity(uid).get("avatar"),
                          "message": {"text": text[:400], "chat": kind, "at": int(time.time())}}}
        r().hset(P.REPORTS_KEY, rid, json.dumps(entry))
        r().zadd(P.OPEN_KEY, {rid: entry["at"]})
    except Exception:
        pass


def scam_reason(text: str) -> Optional[str]:
    for pattern, why in SCAM:
        if pattern.search(text):
            return why
    return None


def _links_ok(text: str) -> bool:
    for m in LINK.finditer(text):
        link = m.group(0).lower()
        if not any(h in link for h in ALLOWED_HOSTS):
            return False
    return True


def _calm(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= SHOUT_MIN and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        text = text.lower()
    return re.sub(r"(\S)\1{5,}", lambda m: m.group(1) * 4, text)  # "noooooooooo" -> "noooo"


def _fresh(uid: str) -> bool:
    """A brand-new player (stricter private-message limits)."""
    try:
        from app.db import get_db
        u = get_db().get_user(uid)
        if u is None:
            return True
        start = (u.data.get("web_welcome") or {}).get("start")
        young = start and start >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
        return bool(young) or u.level < 3
    except Exception:
        return False


def _dm_limits(uid: str, ch, text: str):
    new = not r().exists(ch.store)
    if new:
        hour, day = f"web:automod:newdm:{uid}:h", f"web:automod:newdm:{uid}:d"
        h, d = int(r().get(hour) or 0), int(r().get(day) or 0)
        cap = NEW_DM_DAY_FRESH if _fresh(uid) else NEW_DM_DAY
        if h >= NEW_DM_HOUR or d >= cap:
            raise GameError("You've started a lot of new conversations: wait a while before messaging someone new.")
        pipe = r().pipeline()
        pipe.incr(hour)
        pipe.expire(hour, 3600)
        pipe.incr(day)
        pipe.expire(day, 86400)
        pipe.execute()
    if len(text) >= 15:  # the same message to many players: mass DMs
        sig = hashlib.sha1(_norm(text).encode()).hexdigest()[:12]
        key = f"web:automod:copy:{uid}:{sig}"
        r().sadd(key, ch.other)
        r().expire(key, COPY_WINDOW)
        if r().scard(key) > COPY_PASTE:
            _strike(uid, "the same message to many players")
            raise GameError("You sent that same message to several players already. Write to people one by one.")


def check(ch, uid: str, text: str) -> Tuple[str, Optional[str]]:
    """The text to post (cleaned) and a flag for it ("scam" or None), or GameError with why it was refused."""
    from app.auth import is_admin
    if is_admin(uid):
        return text, None
    words = _words(text)
    hit = words & blocked_words()
    if hit:
        muted = _strike(uid, "blocked words")
        _report(uid, text, ch.kind, "blocked words")
        raise GameError("Automod: that message has a word that isn't allowed here."
                        + (" You're muted for a while." if muted else ""))
    flood = f"web:automod:flood:{uid}"
    n = r().incr(flood)
    if n == 1:
        r().expire(flood, FLOOD_WINDOW)
    if n > FLOOD:
        from app.game import chat
        chat.mute(uid, "automod", FLOOD_MUTE / 60, "automod: flooding the chat")
        raise GameError(f"Automod: too many messages at once. You're muted for {FLOOD_MUTE} minutes.")
    last_key = f"web:automod:last:{uid}:{ch.key}"
    norm = _norm(text)
    last = r().get(last_key)
    if last is not None and (last.decode() if isinstance(last, bytes) else last) == norm and norm:
        raise GameError("You just said that.")
    r().set(last_key, norm, ex=REPEAT_WINDOW)
    scam = scam_reason(text)
    if ch.kind == "dm":
        _dm_limits(uid, ch, text)
    if scam:
        _report(uid, text, ch.kind, f"possible scam: {scam}")
        if ch.kind != "dm":
            _strike(uid, "possible scam")
            raise GameError("Automod: that looks like a scam, so it wasn't posted. An admin will check it.")
    if ch.kind == "global" and not _links_ok(text):
        raise GameError("Links to other sites aren't allowed in the global chat.")
    return _calm(text), ("scam" if scam else None)
