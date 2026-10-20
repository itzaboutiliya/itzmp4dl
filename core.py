"""Persistent authorization and link parsing; independent of Telegram."""
import ipaddress
import re
import socket
import sqlite3
from urllib.parse import urlsplit

TELEGRAM_DOMAINS = {"t.me", "telegram.me", "telegram.dog", "telegram.org", "telegra.ph"}


def links(text):
    result = []
    for url in re.findall(r"https?://[^\s<>]+", text or "", re.I):
        url = url.rstrip('.,!;:)\'"')
        try:
            host = (urlsplit(url).hostname or "").lower().rstrip(".")
            if host and not any(host == d or host.endswith("." + d) for d in TELEGRAM_DOMAINS):
                result.append(url)
        except ValueError:
            pass
    return result


def validate_public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a public HTTP or HTTPS link.")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Only standard website ports are supported.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private and local network links are not allowed.")


class Access:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS grants (id INTEGER PRIMARY KEY)")
        self.db.commit()

    def allowed(self, identity):
        return self.db.execute("SELECT 1 FROM grants WHERE id=?", (identity,)).fetchone() is not None

    def grant(self, identity):
        self.db.execute("INSERT OR IGNORE INTO grants VALUES (?)", (identity,))
        self.db.commit()

    def revoke(self, identity):
        self.db.execute("DELETE FROM grants WHERE id=?", (identity,))
        self.db.commit()

    def all(self):
        return [r[0] for r in self.db.execute("SELECT id FROM grants ORDER BY id")]
