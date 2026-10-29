"""Which channel brought a sign-up, from the query its sign-up flow started with (ADR-0047)."""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

MAX_LEN = 64
CHANNELS = frozenset({"campaign", "search", "social", "referral", "skills_catalog", "direct"})

_SEARCH = ("google.", "yandex.", "bing.com", "duckduckgo.com")
_SOCIAL = frozenset(
    {
        "t.me",
        "telegram.org",
        "x.com",
        "twitter.com",
        "linkedin.com",
        "reddit.com",
        "news.ycombinator.com",
        "youtube.com",
        "vc.ru",
        "habr.com",
    }
)
_OWN = ("agentarea.ai", "agentarea.ru")
_SKILLS = ("/skills/", "/ru/skills/")
_PATTERNED = ("/ru/skills/", "/skills/", "/ru/blog/", "/blog/")


@dataclass(frozen=True)
class Attribution:
    channel: str
    referrer_host: str | None = None
    landing_host: str | None = None
    landing_path: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None


def _clean(value: str | None) -> str | None:
    return (value or "").strip()[:MAX_LEN] or None


def _bare(host: str) -> str:
    return host.lower().removeprefix("www.")


def _is_own(host: str) -> bool:
    return any(host == own or host.endswith("." + own) for own in _OWN)


def _is_search(host: str) -> bool:
    return any(host.startswith(s) or ("." + s) in host for s in _SEARCH)


def path_pattern(path: str | None) -> str | None:
    """``/skills/*``, ``/blog/*`` (and their ``/ru`` twins), otherwise the literal path."""
    if not path:
        return None
    for prefix in _PATTERNED:
        if path.startswith(prefix):
            return prefix + "*"
    return path[:MAX_LEN]


def classify_channel(
    *, referrer_host: str | None, landing_path: str | None, utm_source: str | None
) -> str:
    """The channel of a visit's first touch, by the first rule of ADR-0047's table that holds."""
    if utm_source:
        return "campaign"
    host = _bare(referrer_host) if referrer_host else None
    if host and not _is_own(host):
        if _is_search(host):
            return "search"
        if host in _SOCIAL:
            return "social"
        return "referral"
    if landing_path and landing_path.startswith(_SKILLS):
        return "skills_catalog"
    return "direct"


def attribution_from_request_url(request_url: str | None) -> Attribution:
    """The landing's ``aa_*``/``utm_*`` parameters; a declared channel is kept only if known."""
    try:
        query = parse_qs(urlsplit(request_url or "").query)
    except ValueError:
        query = {}

    def first(name: str) -> str | None:
        return _clean((query.get(name) or [None])[0])

    referrer, landing_path, utm_source = first("aa_ref"), first("aa_lp"), first("utm_source")
    declared = first("aa_ch")
    channel = (
        declared
        if declared and declared in CHANNELS
        else classify_channel(
            referrer_host=referrer, landing_path=landing_path, utm_source=utm_source
        )
    )
    return Attribution(
        channel=channel,
        referrer_host=referrer,
        landing_host=first("aa_lh"),
        landing_path=path_pattern(landing_path),
        utm_source=utm_source,
        utm_medium=first("utm_medium"),
        utm_campaign=first("utm_campaign"),
    )
