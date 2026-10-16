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


def test_news_posts_render_markdown_safely():
    from app.news import render_body, summary
    text = ("# Patch notes\n\n## New stands\n- **Tenore Sax** (R): a *maze*, [wiki](https://jojowiki.com/Tenore_Sax)\n"
            "  - nested: `code`\n1. one\n2. two\n\n> a quote\n---\nline one\nline two <script>x</script> snake_case")
    html = str(render_body(text))
    for tag in ("<h2>Patch notes</h2>", "<h3>New stands</h3>", "<ul><li><strong>Tenore Sax</strong>", "<em>maze</em>",
                '<a href="https://jojowiki.com/Tenore_Sax"', "<ul><li>nested: <code>code</code></li></ul>",
                "<ol><li>one</li><li>two</li></ol>", "<blockquote>a quote</blockquote>", "<hr>", "line one<br>line two"):
        assert tag in html, tag
    assert "<script>" not in html and "&lt;script&gt;" in html and "snake_case" in html  # escaped; no stray italics
    assert summary("## Hi\n- **one** item\n---\n> two", 100) == "Hi one item two"


def test_news_posts_render_tables():
    from app.news import render_body, summary
    text = "Intro\n| Pact | You pay |\n|---|:---:|\n| **Mask** | no healing <b> |\n| Arrow |\n\nafter\n\n| just | pipes |"
    html = str(render_body(text))
    assert '<p>Intro</p><div class="md-table"><table><thead><tr><th>Pact</th>' in html
    assert '<th style="text-align: center">You pay</th>' in html
    assert "<td><strong>Mask</strong></td>" in html and "&lt;b&gt;" in html and "<b>" not in html
    assert '<tr><td>Arrow</td><td style="text-align: center"></td></tr>' in html  # short rows are padded
    assert "<p>after</p><p>| just | pipes |</p>" in html  # no separator row: not a table
    assert summary("| a | b |\n|---|---|\n| c | d |", 100) == "a · b c · d"


def test_news_posts_link_to_site_pages_with_buttons():
    from app.news import render_body, site_links, summary
    text = ("Try [the den](/den) or [Rohan's](/stand/some_id?x=1&y=2#top).\n\n"
            "[[Open the **Gauntlet**]](/gauntlet) [[Read more]](https://example.com/a_b)\n\n"
            "[bad](//evil.com) [bad2](/\\evil.com) [bad3](javascript:alert(1))")
    html = str(render_body(text))
    assert '<a href="/den">the den</a>' in html  # a site page opens in the same tab
    assert '<a href="/stand/some_id?x=1&amp;y=2#top">Rohan&#39;s</a>' in html  # the _ stays, no stray italics
    assert ('<p class="md-buttons"><a href="/gauntlet" class="btn gold md-btn">Open the <strong>Gauntlet</strong></a> '
            '<a href="https://example.com/a_b" class="btn gold md-btn" target="_blank" rel="noopener">Read more</a></p>') in html
    assert html.count("<a ") == 4 and "<p>[bad](//evil.com) [bad2](/\\evil.com) [bad3](javascript:alert(1))</p>" in html
    assert site_links(text) == ["/gauntlet", "/den", "/stand/some_id"]
    assert summary("[[Play now]](/gauntlet) and [the den](/den)", 100) == "Play now and the den"
