"""Player-facing names and icons of the currencies and the 5-pull item.

The save keeps its field names (fragments, super_fragments, item id 2); only what
players read changes, so a rename is a one-line edit here plus the text that uses it.
"""
from markupsafe import Markup

DUST = "Meteor Dust"            # was "fragments"
HEAD, HEADS = "Arrowhead", "Arrowheads"    # was "super fragment(s)"
PALM, PALMS = "Devil's Palm", "Devil's Palms"  # was "Stand Arrow(s)", item id 2

_SVG = {
    # a cluster of falling meteor sparks
    "dust": '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
            '<path d="M6.5 1.2l1.1 3.2 3.2 1.1-3.2 1.1-1.1 3.2-1.1-3.2L2.2 5.5l3.2-1.1z" fill="currentColor"/>'
            '<circle cx="12" cy="10.5" r="1.9" fill="currentColor" opacity=".85"/>'
            '<circle cx="7.6" cy="13.4" r="1.3" fill="currentColor" opacity=".7"/>'
            '<path d="M13.6 1.8l-2.4 2.4M15 4.6l-1.6 1.6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" opacity=".6"/></svg>',
    # the Stand Arrow's head: a gold blade with a beetle-red core
    "head": '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
            '<path d="M8 .8l4.6 7.4L8 15.2 3.4 8.2z" fill="currentColor"/>'
            '<path d="M8 3.4l2.6 4.8L8 12.6 5.4 8.2z" fill="#1C0F2E" opacity=".35"/>'
            '<circle cx="8" cy="8.2" r="1.7" fill="#D6246E"/></svg>',
    # Devil's Palm: a desert palm
    "palm": '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
            '<path d="M8.3 6.5c-.4 3-.2 5.8.6 8.7H7.3c-.6-2.8-.6-5.7-.2-8.7z" fill="currentColor" opacity=".8"/>'
            '<path d="M7.8 6.4C6.2 3.8 3.4 3.3 1.2 4.6c2.3-.1 4.1.6 5.5 2.2-2.4-.5-4.4.3-5.6 2 1.9-.9 4-1.1 6.2-.6zM8 6.3c1.3-2.8 4-3.8 6.5-2.9-2.2.2-3.9 1.1-5 2.8 2.3-.8 4.5-.3 5.9 1.3-2-.6-4-.5-6.3.4z" fill="currentColor"/>'
            '<path d="M1 15.2c2.2-1.3 4.6-1.6 7-1.2 2.3-.4 4.6-.1 7 1.2z" fill="currentColor" opacity=".45"/></svg>',
}
_LABEL = {"dust": DUST, "head": HEADS, "palm": PALMS}


def icon(kind: str, label: bool = True) -> Markup:
    """An inline currency icon; label=True adds hidden text for screen readers."""
    sr = f'<span class="sr">{_LABEL[kind]}</span>' if label else ""
    return Markup(f'<span class="cur cur-{kind}" title="{_LABEL[kind]}">{_SVG[kind]}{sr}</span>')


def amount(n, kind: str) -> Markup:
    """“1,500 [dust icon]” for prices, wallets and rewards."""
    return Markup(f'<span class="cur-amount">{int(n or 0):,}{icon(kind)}</span>')


def heads(n: int) -> str:
    return f"{n} {HEAD if n == 1 else HEADS}"


def palms(n: int) -> str:
    return f"{n} {PALM if n == 1 else PALMS}"
