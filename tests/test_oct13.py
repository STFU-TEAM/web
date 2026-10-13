"""Guests, renaming, the storage-gear shelf, the "Looking for" board, webhook tests and the chat automod."""
import pickle

import pytest

from app import accounts
from app.game import automod, wanted as W
from app.game.chat import Channel
from app.game.logic import GameError
from app.game.user import User
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)
from test_features import player


def _hx(h):
    return {**h, "HX-Request": "true"}


# ── Items: gear held by stands in storage ───────────────────────────────

def test_stands_in_storage_give_their_gear_back(client):
    player(client, "111", main_characters=[char(1)], storage_characters=[char(2, items=[{"id": 1}]), char(3, items=[{"id": 4}, {"id": 1}])])
    h = login(client, "111")
    page = client.get("/items").data.decode()
    assert "Held by stands in storage" in page and "3 items on 2 stands" in page
    r = client.post("/items/unequip-storage", headers=_hx(h))
    assert "3 items back in your bag" in r.data.decode()
    d = doc(client, "111")
    assert all(not c["items"] for c in d["storage_characters"]) and len(d["items"]) == 3
    assert "Your stands in storage hold nothing" in client.post("/items/unequip-storage", headers=_hx(h)).data.decode()


# ── Guests ───────────────────────────────────────────────────────────────

def test_a_guest_plays_from_a_cookie_and_saves_it_with_a_username(client):
    page = client.get("/auth/register").data.decode()
    assert "Play as a guest" in page and 'name="agree"' in page
    r = client.post("/auth/guest", data={"csrf": _csrf(client)})
    assert "Tick the box" in _flashes(client)  # no consent, no cookie
    r = client.post("/auth/guest", data={"csrf": _csrf(client), "agree": "1"})
    assert r.headers["Location"].endswith("/auth/welcome")
    cookie = client.get_cookie(accounts.GUEST_COOKIE)
    assert cookie and cookie.max_age and cookie.max_age > 300 * 86400
    with client.session_transaction() as s:
        uid = s["uid"]
    assert accounts.is_guest(uid) and accounts.is_local(uid)
    client.post("/auth/welcome", data={"csrf": _csrf(client)})
    assert client.fake.hexists("users", uid)
    assert "playing as a guest" in client.get("/team").data.decode()

    # logged out, the cookie brings the same save back
    client.post("/auth/logout", data={"csrf": _csrf(client)})
    assert "Continue as Guest-" in client.get("/auth/login").data.decode()
    client.post("/auth/guest", data={"csrf": _csrf(client)})
    with client.session_transaction() as s:
        assert s["uid"] == uid

    # guests can't chat or trade
    h = {"X-CSRF-Token": _csrf(client)}
    r = client.post("/chat/c/global", data={"text": "hi"}, headers=_hx(h))
    assert r.status_code == 204 and "save your progress" in r.headers["HX-Trigger"]
    assert client.post("/auction/sell", data={"uuid": "x"}, headers=h).status_code == 302

    # saving it: a real account, the same save, and the cookie stops logging in
    page = client.get("/auth/account").data.decode()
    assert "Save your progress" in page and "Link my Discord" not in page
    client.post("/auth/account", data={"csrf": _csrf(client), "action": "add", "username": "Polnareff", "password": "silverchariot",
                                       "confirm": "silverchariot"})
    assert not accounts.is_guest(uid) and accounts.authenticate("Polnareff", "silverchariot", "1.1.1.1")["uid"] == uid
    assert accounts.guest_of(cookie.value) is None
    assert "playing as a guest" not in client.get("/team").data.decode()


def test_guest_saves_are_capped_per_address(client):
    for _ in range(5):
        client.post("/auth/guest", data={"csrf": _csrf(client), "agree": "1"})
        client.delete_cookie(accounts.GUEST_COOKIE)
    r = client.post("/auth/guest", data={"csrf": _csrf(client), "agree": "1"})
    assert r.headers["Location"].endswith("/auth/register") and "Too many guest saves" in _flashes(client)


def _csrf(c):
    with c.session_transaction() as s:
        s.setdefault("csrf", "tok")
        return s["csrf"]


def _flashes(c):
    with c.session_transaction() as s:
        return " ".join(m for _, m in s.get("_flashes", []))


# ── Renaming a web-only account ─────────────────────────────────────────

def test_web_only_players_rename_once_a_week(client):
    acc = accounts.create_account("Kakyoin", "hierophant1")
    uid = acc["uid"]
    player(client, uid)
    h = login(client, uid, "Kakyoin")
    assert "Change your name" in client.get("/auth/account").data.decode()
    client.post("/auth/account", data={"action": "rename", "username": "Noriaki"}, headers=h)
    assert accounts.username_of(uid) == "Noriaki" and accounts.get_account("kakyoin") is None
    assert accounts.authenticate("Noriaki", "hierophant1", "2.2.2.2")["uid"] == uid
    from app.db import identity
    assert identity(uid)["name"] == "Noriaki"
    with pytest.raises(accounts.AccountError, match="rename again"):
        accounts.rename(uid, "Kak")
    accounts.create_account("Avdol", "magiciansred")
    client.fake.delete(f"web:rename:{uid}")
    with pytest.raises(accounts.AccountError, match="taken"):
        accounts.rename(uid, "avdol")
    with pytest.raises(accounts.AccountError, match="Discord"):
        accounts.rename("123456789", "Someone")


# ── The "Looking for" board ─────────────────────────────────────────────

def test_a_request_holds_the_offer_and_pays_whoever_fills_it(client):
    player(client, "111", fragments=10_000, super_fragments=3)
    player(client, "222", main_characters=[char(1)], storage_characters=[char(5, xp=20_000, items=[{"id": 1}]), char(5)])
    h = login(client, "111")
    client.post("/auction/wanted", data={"stand": W.STANDS[5]["name"].upper(), "level": "10", "dust": "4000", "heads": "1"}, headers=h)
    d = doc(client, "111")
    assert d["fragments"] == 6000 and d["super_fragments"] == 2  # held
    post = W.all_posts(client.fake)[0]
    assert post["stand"] == 5 and post["level"] == 10

    h2 = login(client, "222", "Dio")
    page = client.get("/auction?tab=wanted").data.decode()
    assert "1 you can fill" in page and "Sell it" in page
    seller = User(doc(client, "222"))
    fits = W.candidates(seller, post)
    assert len(fits) == 1 and fits[0].level >= 10  # the level-0 copy doesn't fit
    client.post(f"/auction/wanted/{post['id']}/fill", data={"uuid": fits[0].uuid}, headers=h2)
    s, b = doc(client, "222"), doc(client, "111")
    assert s["fragments"] == 3800 and s["super_fragments"] == 1  # 5% fee on the Dust
    assert any(i["id"] == 1 for i in s["items"])  # the gear stayed with the seller
    assert any(c["id"] == 5 for c in b["storage_characters"]) and not W.all_posts(client.fake)


def test_a_request_is_refunded_when_cancelled_or_expired(client):
    player(client, "111", fragments=10_000)
    h = login(client, "111")
    client.post("/auction/wanted", data={"stand": "#7", "dust": "3000"}, headers=h)
    post = W.all_posts(client.fake)[0]
    client.post(f"/auction/wanted/{post['id']}/cancel", headers=h)
    assert doc(client, "111")["fragments"] == 10_000 and not W.all_posts(client.fake)
    client.post("/auction/wanted", data={"stand": "#7", "dust": "3000"}, headers=h)
    post = W.all_posts(client.fake)[0]
    post["ends"] = 0
    client.fake.hset(W.KEY, post["id"], __import__("json").dumps(post))
    client.get("/auction?tab=wanted", headers=h)
    assert doc(client, "111")["fragments"] == 10_000 and not W.all_posts(client.fake)
    with pytest.raises(GameError, match="afford"):
        W.create(client.fake, User(doc(client, "111")), 7, 0, 0, 999_999, 0)


# ── Webhook tests (admin) ───────────────────────────────────────────────

def test_admins_send_a_test_to_each_webhook(client, monkeypatch):
    import requests
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    h = login(client, "111")
    assert "BACKUP_WEBHOOK_URL" in client.get("/admin/safety").data.decode()
    sent = []

    class Resp:
        ok, status_code, text = True, 204, ""
    monkeypatch.setattr(requests, "post", lambda url, json=None, timeout=None: sent.append((url, json)) or Resp())
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.test/hook")
    client.post("/admin/safety/webhook", data={"which": "alert"}, headers=h)
    assert sent and sent[0][0] == "https://discord.test/hook" and "Test from the STFU Requiem admin panel" in sent[0][1]["content"]
    monkeypatch.delenv("BACKUP_WEBHOOK_URL", raising=False)
    client.post("/admin/safety/webhook", data={"which": "backup"}, headers=h)
    assert len(sent) == 1  # not set: nothing sent


# ── The chat automod ────────────────────────────────────────────────────

def _send(client, uid, text, token="global"):
    from app.game import chat
    client.fake.delete(f"web:chat:slow:{uid}", f"web:automod:flood:{uid}")
    try:
        return chat.post(chat.resolve(token, uid), uid, text)
    except GameError as e:
        return str(e)


def test_the_automod_refuses_slurs_spam_and_scams(client):
    player(client, "111")
    player(client, "222")
    login(client, "111")
    with client.application.test_request_context():
        assert isinstance(_send(client, "111", "Nice pull! Snigger all you want"), dict)  # whole words only
        assert _send(client, "111", "gg") and "just said that" in _send(client, "111", "GG")
        assert "Links to other sites" in _send(client, "111", "free stands at stfu-free.xyz")
        assert isinstance(_send(client, "111", "join https://discord.gg/stfurequiem"), dict)
        assert _send(client, "111", "WHY IS DIO SO STRONG IN PART THREE")["text"] == "why is dio so strong in part three"
        assert automod.admin_words() == []
        automod.add_word("Kars")
        assert "isn't allowed" in _send(client, "222", "k a r s is here")
        # three strikes in a day: muted
        assert "isn't allowed" in _send(client, "111", "you n i g g 3 r")
        assert "isn't allowed" in _send(client, "111", "F A G G O T")
        assert "looks like a scam" in _send(client, "111", "send me your password and I'll give you an LR")
        from app.game import chat, profile as P
        reports = [__import__("json").loads(v) for v in client.fake.hvals(P.REPORTS_KEY)]
        assert any(e["reporter"] == "automod" and "scam" in e["note"] for e in reports)
        assert chat.muted("111") and "muted" in _send(client, "111", "hello again")
        # a flood mutes for a few minutes
        for i in range(automod.FLOOD):
            client.fake.delete("web:chat:slow:222")
            assert isinstance(chat.post(chat.resolve("global", "222"), "222", f"message {i}"), dict)
        client.fake.delete("web:chat:slow:222")
        with pytest.raises(GameError, match="too many messages"):
            chat.post(chat.resolve("global", "222"), "222", "one more")


def test_private_scams_reach_the_reader_with_a_warning_and_mass_dms_stop(client):
    for uid in ("111", "222", "333", "444", "555", "666"):
        player(client, uid, xp=50_000)
    login(client, "111")
    with client.application.test_request_context():
        msg = _send(client, "111", "I'm an admin, verify your account here or you get banned", "dm-222")
        assert msg["flag"] == "scam"
        h = login(client, "222", "Polnareff")
        page = client.get("/chat/dm/111", headers=h).data.decode()
        assert "looks like a scam" in page
        text = "hey want to trade your best stand for my LR?"
        for other in ("333", "444", "555"):
            assert isinstance(_send(client, "111", text, f"dm-{other}"), dict)
            client.fake.delete("web:automod:last:111:" + __import__("app.game.chat", fromlist=["dm_key"]).dm_key("111", other))
        assert "same message to several players" in _send(client, "111", text, "dm-666")


def test_new_conversations_are_limited_for_brand_new_saves(client):
    player(client, "111", level=1)
    for i in range(10):
        player(client, f"9{i}")
    with client.application.test_request_context():
        results = [_send(client, "111", f"hello number {i}", f"dm-9{i}") for i in range(6)]
    assert all(isinstance(x, dict) for x in results[:automod.NEW_DM_DAY_FRESH])
    assert "new conversations" in results[automod.NEW_DM_DAY_FRESH]


def test_the_very_first_pull_has_at_least_an_ssr(monkeypatch):
    import random
    from app.game import logic
    from app.game.user import create_user
    banner = next(b for b in logic.BANNERS if logic.banner_enabled(b))
    monkeypatch.setattr(logic, "BANNER_ODDS", {"R": 1.0})  # the unluckiest pull there is
    for seed in range(5):
        random.seed(seed)
        u = User(create_user("1"))
        u.super_fragments = 2
        res = logic.banner_pull(u, banner["id"])
        assert any(c.rarity in ("SSR", "UR", "LR") for c, _ in res["drawn"])
        res = logic.banner_pull(u, banner["id"])  # the second pull: only the SR floor
        assert not any(c.rarity in ("SSR", "UR", "LR") for c, _ in res["drawn"])


# ── Filming and promo tools ─────────────────────────────────────────────

def test_admins_can_force_a_stand_and_a_shiny_on_their_own_pulls(client):
    from app.game import logic
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111", super_fragments=2)
    h = login(client, "111")
    client.post("/banners/force", data={"stand": "Gold Experience Requiem", "shiny": "1", "scope": "last"}, headers=h)
    banner = next(b for b in logic.BANNERS if logic.banner_enabled(b))
    client.post(f"/banners/{banner['id']}/pull", headers={**h, "HX-Request": "true"})
    pulled = [c for c in doc(client, "111")["main_characters"] + doc(client, "111")["storage_characters"] if c["id"] == 84]
    assert pulled and pulled[0]["shiny"]
    assert "No stand is called" in client.post("/banners/force", data={"stand": "Not A Stand"}, headers=h, follow_redirects=True).data.decode()
    player(client, "222", super_fragments=1)  # not an admin: no forcing
    assert client.post("/banners/force", data={"stand": "84"}, headers=login(client, "222")).status_code == 403


def test_film_mode_hides_the_overlays_for_that_admin_only(client):
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    h = login(client, "111")
    assert 'class="has-side film"' not in client.get("/team").data.decode()
    client.post("/admin/film", data={"on": "1"}, headers=h)
    assert 'class="has-side film"' in client.get("/team").data.decode()
    client.post("/admin/film", data={"on": "0"}, headers=h)
    assert 'class="has-side film"' not in client.get("/team").data.decode()


def test_src_links_count_visits_and_the_signups_they_bring(client):
    from app import campaign
    client.get("/?src=TikTok")
    client.get("/stands?src=tiktok")  # the same session: one visit
    client.get("/?src=<script>")  # not a source name: ignored
    login(client, "555")
    with client.session_transaction() as s:
        s["src"] = "tiktok"
    client.post("/auth/welcome", headers={"X-CSRF-Token": "tok"})
    rows = {r["src"]: r for r in campaign.report(client.fake)}
    assert rows["tiktok"]["visits"] == 1 and rows["tiktok"]["signups"] == 1 and len(rows) == 1
    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    assert "Where players come from" in client.get("/admin", headers=login(client, "111")).data.decode()


def test_the_demo_world_for_filming_seeds_players_a_gang_a_market_and_a_chat(client, monkeypatch):
    import importlib.util
    import json as _json
    from app.game import puzzle
    monkeypatch.setattr(puzzle, "generate_one", lambda: None)  # ~10 s in real life
    spec = importlib.util.spec_from_file_location("devscript", "scripts/dev.py")
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    with client.application.app_context():
        dev.seed_admin()
        dev.seed_demo()
    admin = doc(client, dev.ADMIN_UID)
    assert not any(c["id"] == 84 for c in admin["main_characters"] + admin["storage_characters"])  # GER pulls NEW
    assert [c["id"] for c in admin["main_characters"]] == dev.DEMO_TEAM and admin["gang_id"]
    assert client.fake.hlen("users") == 1 + len(dev.DEMO_PLAYERS)
    assert client.fake.hlen("web:auction:listings") == 6 and client.fake.hlen(W.KEY) == 4
    assert client.fake.llen("web:chat:global") == len(dev.DEMO_CHAT)
    assert _json.loads(client.fake.get(f"web:account:{dev.ADMIN_USERNAME}"))["name"] == dev.DEMO_NAME
