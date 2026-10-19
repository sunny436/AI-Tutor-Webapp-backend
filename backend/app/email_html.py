"""The HTML part of PadhAI's emails: one branded layout and a few blocks, everything escaped.

Every email is plain text first; this module builds its second part from the same values
(app/auth/emails.py, app/notifications/emails.py). What keeps it safe:

- Untrusted values (names, addresses, device labels, numbers) are text: every block escapes
  what it is given. Only `SafeHtml`, which only the blocks here make, passes through as markup.
- A link is only ever PUBLIC_APP_URL plus a fixed page (`app_link`), or the signed unsubscribe
  link on that same address (`checked_url`). If PUBLIC_APP_URL is not a plain https origin, the
  email has no links and no logo; the instructions are in the text either way.
- A failure here never stops an email: `render_html` logs it and the email goes out as text.

Email-client rules: tables and inline styles, a solid colour behind every gradient, no web
fonts, and nothing that needs images (the wordmark is text; the logo is decoration).
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable
from typing import NamedTuple

from app.logging import get_logger
from app.settings import Settings

log = get_logger("app.email")


class Email(NamedTuple):
    """One email: the subject and the plain text, and the HTML part when there is one."""

    subject: str
    body: str
    html: str | None = None


class SafeHtml(str):
    """Markup made by this module. Anything else given to a block is text, and is escaped."""


def _esc(value: object) -> str:
    return value if isinstance(value, SafeHtml) else html.escape(str(value), quote=True)


def join(*parts: object) -> SafeHtml:
    """Text and markup run together: a sentence with a bold word or a link in it."""
    return SafeHtml("".join(_esc(part) for part in parts))


# The brand (frontend/packages/ui/src/globals.css and frontend/apps/app/src/lib/brand.ts).
FONT = "'Noto Sans', 'Segoe UI', Roboto, -apple-system, Arial, sans-serif"
MONO = "'Courier New', Courier, monospace"
BRAND = "#4F6F8F"
BRAND_TINT = "#EAF1F6"
PAGE = "#F7F8FA"
TEXT = "#20252B"
MUTED = "#5F6873"
BORDER = "#E4E7EB"
DARK = "#171B20"
SUCCESS = "#1B7F3A"
WARNING = "#7A5C00"
DANGER = "#B23A48"
SAGE = "#5A7360"
FLAME = "#F28C45"
GOLD = "#FFC46B"
TAGLINE = "Your Questions. Your Tutor. Your Way."

# The pages an email may link to; nothing else is ever a link.
PAGES = {
    "home": "/",
    "login": "/login",
    "privacy": "/settings/privacy",
    "notifications": "/settings/notifications",
    "progress": "/settings/progress",
}
LOGO = "/brand/padhai-mark-email.png"  # frontend/apps/app/public: 72x72, shown at 36x36
_BIDI_CONTROLS = {chr(code) for code in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))}


def clean_text(value: object) -> str:
    """Display text without Unicode direction controls that can visually reorder trusted copy."""
    return "".join(char for char in str(value) if char not in _BIDI_CONTROLS)


def public_base(settings: Settings | None) -> str | None:
    """The validated PUBLIC_APP_URL origin."""
    return settings.public_app_origin if settings else None


def app_link(settings: Settings | None, page: str) -> str | None:
    base = public_base(settings)
    return f"{base}{PAGES[page]}" if base else None


def checked_url(settings: Settings | None, url: str | None) -> str | None:
    """A full URL (the signed unsubscribe link), only when it is on the app's own address."""
    base = public_base(settings)
    if not url or not base or not url.startswith(f"{base}/"):
        return None
    return url


def first_name(display_name: str | None) -> str | None:
    """The first word of the name the student gave, if any ("Hi Aditi,")."""
    words = clean_text(display_name or "").split()
    return words[0][:40] if words else None


def bdi(value: object) -> SafeHtml:
    """User-supplied text with browser/email-client direction isolation."""
    return SafeHtml(f'<bdi dir="auto">{_esc(clean_text(value))}</bdi>')


def render_html(name: str, build: Callable[[], str]) -> str | None:
    """`build()`, or None (logged) when it fails: the email then goes out as text only."""
    try:
        return build()
    except Exception as error:  # noqa: BLE001 - a template bug must never stop an email
        log.error("email html render failed", extra={"template": name, "error_type": type(error).__name__})
        return None


# ---------------------------------------------------------------------- blocks
def _table(cells: str, style: str = "") -> str:
    attribute = f' style="{style}"' if style else ""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"{attribute}>{cells}</table>'
    )


def _row(inner: str, top: int) -> SafeHtml:
    return SafeHtml(f'<tr><td style="padding-top:{top}px;">{inner}</td></tr>')


def _spaced(inner: str, top: int) -> str:
    return _table(f'<tr><td style="padding-top:{top}px;">{inner}</td></tr>')


def _p(content: object, *, size: int = 16, color: str = MUTED, weight: int = 400, align: str = "left") -> str:
    return (
        f'<p style="margin:0;font-family:{FONT};font-size:{size}px;line-height:{size + 8}px;'
        f'font-weight:{weight};color:{color};text-align:{align};">{_esc(content)}</p>'
    )


def heading(text: object, *, top: int = 32) -> SafeHtml:
    return _row(
        f'<h1 style="margin:0;font-family:{FONT};font-size:20px;line-height:28px;font-weight:700;'
        f'color:{TEXT};">{_esc(text)}</h1>',
        top,
    )


def paragraph(content: object, *, top: int = 12, size: int = 16) -> SafeHtml:
    return _row(_p(content, size=size), top)


def strong(text: object) -> SafeHtml:
    return SafeHtml(f'<strong style="color:{TEXT};font-weight:700;">{_esc(text)}</strong>')


def link(label: str, url: str | None) -> SafeHtml:
    """An inline link, or the label as plain text when there is no address to link to."""
    if not url:
        return SafeHtml(_esc(label))
    return SafeHtml(
        f'<a href="{_esc(url)}" target="_blank" style="color:{BRAND};font-weight:600;'
        f'text-decoration:underline;">{_esc(label)}</a>'
    )


def code_box(code: str) -> SafeHtml:
    return _row(
        _table(
            f'<tr><td align="center" class="code-box" style="background-color:{BRAND_TINT};border-radius:8px;'
            f"padding:24px 16px 24px 24px;font-family:{MONO};font-size:36px;line-height:44px;font-weight:700;"
            f'letter-spacing:8px;color:{BRAND};">{_esc(code)}</td></tr>'
        ),
        32,
    )


def caution(text: object) -> SafeHtml:
    """One centred line in the security colour (don't share the code)."""
    return _row(_p(text, size=14, color=DANGER, weight=600, align="center"), 20)


def footnote(content: object) -> SafeHtml:
    """The quiet line under a rule at the end of the card (if you didn't ask for this...)."""
    return _row(
        _table(f'<tr><td style="border-top:1px solid {BORDER};padding-top:24px;">{_p(content, size=14)}</td></tr>'), 32
    )


def details(rows: Iterable[tuple[str, str | None]]) -> SafeHtml:
    """Label and value rows on a grey panel. A row without a value is left out, so is an empty panel."""
    cells = "".join(
        f'<tr><td class="meta-label" width="120" valign="top" style="padding:4px 12px 4px 0;font-family:{FONT};'
        f'font-size:14px;line-height:20px;font-weight:500;color:{MUTED};">{_esc(name)}</td>'
        f'<td valign="top" style="padding:4px 0;font-family:{FONT};font-size:14px;line-height:20px;'
        f'font-weight:600;color:{TEXT};word-break:break-word;">{bdi(value)}</td></tr>'
        for name, value in rows
        if value
    )
    if not cells:
        return SafeHtml("")
    panel = (
        f'<tr><td style="padding:16px 20px;"><table role="presentation" class="meta-table" width="100%" '
        f'cellpadding="0" cellspacing="0" border="0">{cells}</table></td></tr>'
    )
    return _row(_table(panel, f"background-color:{PAGE};border:1px solid {BORDER};border-radius:8px;"), 24)


def _button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" class="btn-wrap"><tr>'
        f'<td align="center" bgcolor="{DARK}" style="border-radius:8px;background-color:{DARK};padding:12px 24px;">'
        f'<a href="{_esc(url)}" target="_blank" style="font-family:{FONT};font-size:16px;line-height:20px;'
        f'font-weight:600;color:#FFFFFF;text-decoration:none;display:inline-block;">{_esc(label)}</a>'
        "</td></tr></table>"
    )


def button(label: str, url: str | None, *, top: int = 24, center: bool = False) -> SafeHtml:
    """A dark button, or nothing when there is no address to link to."""
    if not url:
        return SafeHtml("")
    align = "center" if center else "left"
    return _row(_table(f'<tr><td align="{align}">{_button(label, url)}</td></tr>'), top)


def alert(
    title: object,
    text: object,
    *,
    color: str = DANGER,
    title_color: str | None = None,
    title_size: int = 16,
    text_size: int = 14,
    action: tuple[str, str | None] | None = None,
    top: int = 32,
) -> SafeHtml:
    """A block marked by a coloured left border: the security warning, or a success or warning notice."""
    inner = _p(title, size=title_size, color=title_color or color, weight=700) + _spaced(_p(text, size=text_size), 8)
    if action and action[1]:
        inner += _spaced(_button(action[0], action[1]), 16)
    return _row(_table(f'<tr><td style="border-left:4px solid {color};padding:2px 0 2px 16px;">{inner}</td></tr>'), top)


def hero(title: object, text: object) -> SafeHtml:
    """The calm blue-to-sage block of the learning emails; plain brand blue where gradients don't show."""
    return _row(
        _table(
            f'<tr><td align="center" class="hero-wrap" bgcolor="{BRAND}" style="background-color:{BRAND};'
            f"background-image:linear-gradient(135deg,{BRAND} 0%,{SAGE} 100%);border-radius:12px;"
            f'padding:36px 28px;">{_p(title, size=24, color="#FFFFFF", weight=700, align="center")}'
            f"{_spaced(_p(text, color=BRAND_TINT, align='center'), 12)}</td></tr>"
        ),
        24,
    )


def streak_badge(days: int) -> SafeHtml:
    return _row(
        _table(
            f'<tr><td align="center" bgcolor="{FLAME}" style="background-color:{FLAME};'
            f'background-image:linear-gradient(135deg,{FLAME} 0%,{GOLD} 100%);border-radius:12px;padding:32px 20px;">'
            f'<p class="streak-number" style="margin:0;font-family:{FONT};font-size:64px;line-height:72px;'
            f'font-weight:900;color:{DARK};">{_esc(days)}</p>'
            f'<p style="margin:4px 0 0 0;font-family:{FONT};font-size:14px;line-height:20px;font-weight:700;'
            f'letter-spacing:2px;text-transform:uppercase;color:{DARK};">Day streak</p></td></tr>'
        ),
        28,
    )


def stats(rows: Iterable[tuple[str, str]]) -> SafeHtml:
    cell = f"padding:14px 0;border-bottom:1px solid {BORDER};font-family:{FONT};font-size:16px;line-height:22px;"
    cells = "".join(
        f'<tr><td style="{cell}color:{MUTED};">{_esc(name)}</td>'
        f'<td align="right" style="{cell}font-weight:600;color:{TEXT};">{_esc(value)}</td></tr>'
        for name, value in rows
    )
    return _row(_table(cells, f"border-top:1px solid {BORDER};"), 16)


def caption(text: object, *, top: int = 24) -> SafeHtml:
    """A small capitalised line above a section (the week a summary is about)."""
    return _row(
        f'<p style="margin:0;font-family:{FONT};font-size:12px;line-height:16px;font-weight:700;'
        f'letter-spacing:0.5px;text-transform:uppercase;color:{MUTED};">{_esc(text)}</p>',
        top,
    )


# --------------------------------------------------------------------- layout
_STYLE = (
    "body,table,td,a{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}"
    "table,td{mso-table-lspace:0pt;mso-table-rspace:0pt;}"
    "img{-ms-interpolation-mode:bicubic;border:0;height:auto;line-height:100%;outline:none;text-decoration:none;}"
    "@media screen and (max-width:640px){"
    ".email-container{width:100%!important;}"
    ".card{border-radius:0!important;border-left:none!important;border-right:none!important;}"
    ".pad-wrap{padding:32px 20px!important;}"
    ".code-box{font-size:30px!important;letter-spacing:5px!important;}"
    ".meta-table td{display:block!important;width:100%!important;}"
    ".hero-wrap{padding:28px 20px!important;}"
    ".streak-number{font-size:52px!important;line-height:60px!important;}"
    "}"
)
_MSO = (
    "<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch>"
    "</o:OfficeDocumentSettings></xml></noscript><![endif]-->"
)
# Keeps the inbox preview to the preheader instead of running on into the email's text.
_PREVIEW_FILL = "&zwnj;&nbsp;" * 40


def document(
    settings: Settings | None,
    *,
    title: str,
    preview: str,
    blocks: Iterable[SafeHtml],
    note: str,
    settings_url: str | None = None,
    unsubscribe_url: str | None = None,
) -> str:
    """The whole email: the wordmark, the card with `blocks`, and a footer saying why it was sent.

    `settings_url` and `unsubscribe_url` must come from `app_link` and `checked_url`."""
    base = public_base(settings)
    home = f"{base}/" if base else None
    wordmark = f'<span style="color:{TEXT};">Padh</span><span style="color:{BRAND};">AI</span>'
    if home and base:
        brand = (
            f'<img src="{_esc(base + LOGO)}" width="36" height="36" alt="" '
            'style="display:inline-block;vertical-align:middle;width:36px;height:36px;border:0;border-radius:8px;">'
            f'<span style="display:inline-block;vertical-align:middle;padding-left:12px;">{wordmark}</span>'
        )
        wordmark = (
            f'<a href="{_esc(home)}" target="_blank" aria-label="PadhAI home" style="text-decoration:none;">{brand}</a>'
        )
    header = (
        '<tr><td><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="middle" style="font-family:{FONT};font-size:24px;line-height:28px;font-weight:900;'
        f'letter-spacing:-0.5px;">{wordmark}</td></tr></table></td></tr>'
    )
    links = [
        part
        for part in (
            link("Choose which emails you get", settings_url) if settings_url else None,
            link("Stop emails like this one", unsubscribe_url) if unsubscribe_url else None,
        )
        if part
    ]
    footer_links = f'<p style="margin:12px 0 0 0;">{" &nbsp;·&nbsp; ".join(links)}</p>' if links else ""
    footer = (
        '<table role="presentation" class="email-container" width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="width:600px;max-width:600px;"><tr>'
        f'<td align="center" style="padding:24px 20px;font-family:{FONT};font-size:12px;line-height:18px;'
        f'color:{MUTED};">'
        f'<p style="margin:0;font-weight:700;color:{TEXT};">PadhAI</p>'
        f'<p style="margin:4px 0 0 0;">{_esc(TAGLINE)}</p>'
        f'<p style="margin:12px 0 0 0;">{_esc(note)}</p>{footer_links}</td></tr></table>'
    )
    card = (
        '<table role="presentation" class="email-container card" width="600" cellpadding="0" cellspacing="0" '
        f'border="0" bgcolor="#FFFFFF" style="width:600px;max-width:600px;background-color:#FFFFFF;'
        f'border:1px solid {BORDER};border-radius:16px;border-collapse:separate;">'
        f'<tr><td class="pad-wrap" style="padding:40px 48px;">{_table(header + "".join(blocks))}</td></tr></table>'
    )
    return (
        '<!DOCTYPE html><html lang="en" xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:o="urn:schemas-microsoft-com:office:office"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<meta name="x-apple-disable-message-reformatting">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        f'<title>{_esc(title)}</title>{_MSO}<style type="text/css">{_STYLE}</style></head>'
        f'<body style="margin:0;padding:0;background-color:{PAGE};">'
        '<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;'
        f'overflow:hidden;mso-hide:all;">{_esc(preview)}{_PREVIEW_FILL}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAGE}" '
        f'style="background-color:{PAGE};"><tr><td align="center" style="padding:32px 10px;">'
        f"{card}{footer}</td></tr></table></body></html>"
    )
