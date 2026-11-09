"""Checks that an email found by the LLM looks authentic."""
import re
from functools import lru_cache
from urllib.parse import urlparse

import dns.resolver

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
FREE_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"}


@lru_cache(maxsize=512)
def has_mx(domain: str) -> bool:
    try:
        return len(dns.resolver.resolve(domain, "MX", lifetime=5)) > 0
    except Exception:
        return False


def _root(domain: str) -> str:
    parts = domain.lower().split(".")
    # handles example.co.in / example.com
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "ac"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def verify(email: str, website: str | None, company: str) -> tuple[bool, str]:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        return False, "invalid format"
    domain = email.split("@", 1)[1]
    if not has_mx(domain):
        return False, "domain has no mail server (MX)"
    if domain in FREE_DOMAINS:
        return False, "free mail provider, not a company domain"
    site_domain = urlparse(website).netloc if website else ""
    if site_domain and _root(site_domain) == _root(domain):
        return True, "domain matches company website, MX ok"
    slug = re.sub(r"[^a-z0-9]", "", company.lower())
    if slug and slug[:5] in domain.replace("-", ""):
        return True, "domain resembles company name, MX ok"
    return False, "MX ok but domain does not match company website"
