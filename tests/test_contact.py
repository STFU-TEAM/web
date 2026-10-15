"""Contact us and bug reports (app/contact.py): anyone can write, admins read them in the Contact tab."""
from app import contact
from test_app import client, login  # noqa: F401  (client is a fixture)
from test_features import player


def _csrf(client):
    with client.session_transaction() as s:
        s["csrf"] = "tok"
    return {"X-CSRF-Token": "tok"}


def test_a_visitor_sends_a_bug_report_and_an_admin_handles_it(client):
    page = client.get("/contact?kind=bug").data.decode()
    assert "Contact us" in page and 'value="bug" data-hint' in page and 'name="website"' in page
    assert "Report a bug" in client.get("/").data.decode()  # the footer links it everywhere
    h = _csrf(client)
    r = client.post("/contact", data={"kind": "bug", "message": "The ranked queue spins forever on Firefox.",
                                      "page": "/battles?mode=ranked", "email": "me@example.com"},
                    headers={**h, "User-Agent": "Firefox/140"})
    assert r.status_code == 302 and "sent=1" in r.headers["Location"]
    assert "Message sent" in client.get("/contact?sent=1").data.decode()
    rows = contact.listing(client.fake)
    assert len(rows) == 1 and rows[0]["kind"] == "bug" and rows[0]["ua"] == "Firefox/140" and rows[0]["email"] == "me@example.com"

    client.application.config["DISCORD_ADMIN_IDS"] = {"111"}
    player(client, "111")
    h = login(client, "111")
    inbox = client.get("/admin/contact").data.decode()
    assert "The ranked queue spins forever" in inbox and "me@example.com" in inbox and "/battles?mode=ranked" in inbox
    client.post(f"/admin/contact/{rows[0]['id']}/done", headers=h)
    assert contact.listing(client.fake, "open") == [] and contact.listing(client.fake, "done")[0]["closed_by"] == "111"
    client.post(f"/admin/contact/{rows[0]['id']}/delete", headers=h)
    assert contact.listing(client.fake, "all") == []


def test_messages_are_checked_rate_limited_and_bots_are_ignored(client):
    h = _csrf(client)
    r = client.post("/contact", data={"kind": "idea", "message": "short"}, headers=h)
    assert r.status_code == 400 and "at least" in r.data.decode() and 'value="idea" data-hint' in r.data.decode()
    r = client.post("/contact", data={"kind": "other", "message": "A long enough message here.", "email": "not an email"}, headers=h)
    assert r.status_code == 400 and "look right" in r.data.decode()
    client.post("/contact", data={"kind": "bug", "message": "Buy cheap stuff at spam.example", "website": "spam.example"}, headers=h)
    assert contact.listing(client.fake, "all") == []  # the honeypot: nothing stored
    for i in range(contact.PER_HOUR):
        assert client.post("/contact", data={"kind": "bug", "message": f"Bug number {i} happened again."}, headers=h).status_code == 302
    r = client.post("/contact", data={"kind": "bug", "message": "One more bug for the road."}, headers=h)
    assert r.status_code == 400 and "this hour" in r.data.decode()
    assert len(contact.listing(client.fake, "all")) == contact.PER_HOUR


def test_the_contact_inbox_is_for_admins_only(client):
    player(client, "222")
    login(client, "222")
    assert client.get("/admin/contact").status_code == 403
