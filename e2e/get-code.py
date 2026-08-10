"""
Fetch the newest auth code that was emailed to a given address.

    python get-code.py <recipient> [timeout_seconds]

Prints the code to stdout, or exits 1 if none arrived.

WHY THIS EXISTS
`auth-local.js` reads codes out of `convex logs`, which worked only while no mail
provider was configured — the code is logged in `authEmail.ts` ONLY from the catch
block, i.e. when sending FAILED. Once SMTP started delivering, the codes stopped
appearing in the logs entirely and that suite could never find one.

Reading the real inbox is also a stronger test: it proves the code actually
travelled by email rather than merely being generated.

Uses plus-addressing (user+tag@domain) so every test run gets a unique recipient
while all the mail still lands in one readable inbox.

Credentials come from the environment, never hard-coded:
    E2E_IMAP_USER, E2E_IMAP_PASS
"""

from __future__ import annotations

import email
import imaplib
import os
import re
import sys
import time
from email.header import decode_header

USER = os.environ.get("E2E_IMAP_USER", "")
PASS = (os.environ.get("E2E_IMAP_PASS", "") or "").replace(" ", "")

if not USER or not PASS:
    print("E2E_IMAP_USER / E2E_IMAP_PASS not set", file=sys.stderr)
    sys.exit(2)

recipient = sys.argv[1] if len(sys.argv) > 1 else USER
deadline = time.time() + (float(sys.argv[2]) if len(sys.argv) > 2 else 60.0)

# A code to REJECT, so a second request for the same address cannot hand back the
# first email's code. Without this the reset step read the sign-up email — the
# new message simply had not arrived yet — and "verified" and "reset" both
# reported the same digits while looking perfectly healthy.
exclude = sys.argv[3] if len(sys.argv) > 3 else ""

# The codes are 6-8 digits. Anchor on the wording the template uses so a stray
# number in a footer or a date cannot be mistaken for the code.
CODE_NEAR_LABEL = re.compile(r"code is[:\s]*([0-9]{6,8})", re.IGNORECASE)
ANY_CODE = re.compile(r"\b([0-9]{6,8})\b")


def body_of(msg) -> str:
    if not msg.is_multipart():
        payload = msg.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="ignore")
    parts = []
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            payload = part.get_payload(decode=True) or b""
            parts.append(payload.decode("utf-8", errors="ignore"))
    return "\n".join(parts)


def header_value(msg, name: str) -> str:
    raw = msg.get(name, "")
    try:
        return "".join(
            piece.decode(enc or "utf-8", errors="ignore") if isinstance(piece, bytes) else piece
            for piece, enc in decode_header(raw)
        )
    except Exception:  # noqa: BLE001
        return str(raw)


while time.time() < deadline:
    try:
        box = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30)
        box.login(USER, PASS)
        box.select("INBOX")
        # Newest first. Search by recipient so parallel runs cannot steal each
        # other's codes.
        typ, data = box.search(None, f'(TO "{recipient}")')
        ids = data[0].split()
        for message_id in reversed(ids[-10:]):
            typ, raw = box.fetch(message_id, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1])
            if recipient.lower() not in header_value(msg, "To").lower():
                continue
            text = body_of(msg)
            found = CODE_NEAR_LABEL.search(text) or ANY_CODE.search(text)
            if found and found.group(1) != exclude:
                print(found.group(1))
                box.logout()
                sys.exit(0)
        box.logout()
    except Exception as error:  # noqa: BLE001
        print(f"imap retry: {error}", file=sys.stderr)
    time.sleep(3)

print(f"no code for {recipient} within the timeout", file=sys.stderr)
sys.exit(1)
