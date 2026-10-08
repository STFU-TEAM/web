"""The stand picker on every page that picks a stand: each renders its options and posts the field it replaced."""
import json
import re

from app.game.user import create_user
from test_app import char, client, doc, login, put  # noqa: F401  (client is a fixture)


def options(page, source):
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % re.escape(source), page, re.S)
    assert m, source
    return json.loads(m.group(1))


def player(c, uid="111", **fields):
    d = create_user(uid)
    d.update(fields)
    put(c, d)
    return login(c, uid)


def test_pickers_render_where_stands_are_picked(client):
    team = [char(1, xp=5000), char(2, xp=3000), char(3, xp=3000)]
    spare = char(1, xp=100)
    h = player(client, main_characters=team, storage_characters=[spare, char(5, xp=2000)],
               items=[{"id": 3}, {"id": 1}], fragments=10_000)
    panel = client.get(f"/team/stand/{team[0]['uuid']}").data.decode()
    assert [o["v"] for o in options(panel, "sp-fodder")] == [spare["uuid"]] and 'data-sp-name="fodder"' in panel
    items = client.get("/items").data.decode()
    assert len(options(items, "sp-requiem")) == 3 and len(options(items, "sp-equip")) == 3
    assert 'data-sp-source="#sp-equip"' in items
    for path, source in (("/auction", "sp-sell"), ("/journey", "sp-journey")):
        page = client.get(path).data.decode()
        assert options(page, source), path
    trade = client.get("/trades/new?with=111").data.decode()  # yourself: refused, but the page still renders
    assert "data-sp" in trade or "trade" in trade.lower()


def test_fusing_through_the_picker_still_works(client):
    keep, spare = char(1, xp=2500), char(1, xp=100)
    h = player(client, main_characters=[keep], storage_characters=[spare])
    client.post("/team/fuse", data={"uuid": keep["uuid"], "fodder": spare["uuid"]}, headers=h)
    d = doc(client, "111")
    assert len(d["storage_characters"]) == 0 and d["main_characters"][0]["xp"] > 2500


def test_banner_spark_picker_lists_the_pools_ssrs(client):
    from app.game import logic
    d = create_user("111")
    d["main_characters"] = [char(1)]
    d["web_sparks"] = logic.SPARK_COST
    put(client, d)
    login(client, "111")
    page = client.get("/banners").data.decode()
    sparks = re.findall(r'id="(sp-spark-\d+)"', page)
    assert sparks  # enough sparks: every open banner offers the exchange
    for source in sparks:
        assert all(o["r"] == "SSR" for o in options(page, source))


def test_item_options_group_count_and_skip_bound(client):
    from app.game import pickers
    from app.game.items import TORN_DIARY_PAGE, item_from_dict
    items = [item_from_dict({"id": i}) for i in (2, 2, 2, 47, 15, TORN_DIARY_PAGE)]
    with client.application.app_context():
        mine = {o["n"]: o for o in pickers.owned_items(items, tradable=True)}
        assert mine["Devil's Palm"]["q"] == 3 and mine["Devil's Palm"]["g"] == "usable"
        assert mine["Lottery ticket"]["g"] == "gear" and "+10 CRT" in mine["Lottery ticket"]["m"]
        assert not any(o["id"] == TORN_DIARY_PAGE for o in mine.values())  # bound: never traded or listed
        assert [o["id"] for o in pickers.owned_items(items, equipable=True)] == [15]
        from app.game.items import item_file
        assert len(pickers.catalog_items()) == len(item_file)


def test_a_trade_sent_through_the_item_picker(client):
    d = create_user("222")
    d["main_characters"] = [char(4)]
    put(client, d)
    h = player(client, main_characters=[char(1)], items=[{"id": 2}] * 4)
    page = client.get("/trades/new?with=222").data.decode()
    assert options(page, "sp-give-items")[0]["q"] == 4 and 'data-sp-qty' in page
    from app.game import trades  # the picker posts "id:count", the format the offer parser reads
    from werkzeug.datastructures import MultiDict
    assert trades.parse_side(MultiDict([("give_item", "2:3")]), "give")["items"] == {"2": 3}
