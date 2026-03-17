"""
utils/adblocker.py
~~~~~~~~~~~~~~~~~~
Network-level ad/tracker blocker for NovaPlay's embedded QWebEngineView.

Architecture
------------
AdBlocker               Public API.  Wire to a QWebEngineProfile then call
                        load_lists() to start the async filter-list download.
_RequestInterceptor     QWebEngineUrlRequestInterceptor – blocks requests at
                        the Chromium network layer (before any bytes are sent).
_RuleSet                Thread-safe aggregated rule store + matching logic.
_ParsedRules            Transient dataclass produced by the parser per list.
_parse_filter_list()    Parses EasyList / Adblock-Plus / uBlock filter syntax.
_fetch_cached()         Downloads a URL with a 24-hour local disk cache.

Usage
-----
    from utils.adblocker import AdBlocker

    blocker = AdBlocker()
    blocker.attach(QWebEngineProfile.defaultProfile())
    blocker.load_lists()          # async – downloads / loads from cache

    # toggle at runtime
    blocker.enabled = False
    blocker.enabled = True

    # statistics
    stats = blocker.stats()
    print(stats["blocked_domains"], stats["requests_blocked"])
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit
from urllib.error import URLError
from urllib.request import Request, urlopen

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Filter-list URLs  (same "default" set as uBlock Origin)
# ---------------------------------------------------------------------------

DEFAULT_LISTS: list[tuple[str, str]] = [
    (
        "EasyList",
        "https://easylist.to/easylist/easylist.txt",
    ),
    (
        "EasyPrivacy",
        "https://easylist.to/easylist/easyprivacy.txt",
    ),
    (
        "Peter Lowe's Ad/Tracking",
        "https://pgl.yoyo.org/adservers/serverlist.php"
        "?hostformat=adblockplus&showintro=1&mimetype=plaintext",
    ),
    (
        "uBlock Origin Filters",
        "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters.txt",
    ),
]

CACHE_DIR = Path.home() / ".cache" / "novaplay" / "adblocker"
CACHE_TTL = 86_400  # seconds – re-download after 24 h

# Cap on cosmetic selectors injected into pages (prevents enormous <style> tags)
_COSMETIC_CAP = 8_000

# Script name used in the profile's script collection
_COSMETIC_SCRIPT_NAME = "novaplay-adblocker-cosmetic"

# ---------------------------------------------------------------------------
# Parsed rules (one per filter-list file)
# ---------------------------------------------------------------------------


@dataclass
class _ParsedRules:
    blocked_domains: set[str] = field(default_factory=set)
    exception_domains: set[str] = field(default_factory=set)
    blocked_patterns: list[re.Pattern] = field(default_factory=list)
    exception_patterns: list[re.Pattern] = field(default_factory=list)
    blocked_option_rules: list[_NetworkRule] = field(default_factory=list)
    exception_option_rules: list[_NetworkRule] = field(default_factory=list)
    cosmetic_selectors: list[str] = field(default_factory=list)


@dataclass
class _RuleOptions:
    include_types: set[str] = field(default_factory=set)
    exclude_types: set[str] = field(default_factory=set)
    include_domains: set[str] = field(default_factory=set)
    exclude_domains: set[str] = field(default_factory=set)
    third_party: Optional[bool] = None
    popup: Optional[bool] = None
    badfilter: bool = False
    unsupported: bool = False


@dataclass
class _NetworkRule:
    pattern: Optional[re.Pattern] = None
    domain: Optional[str] = None
    include_types: set[str] = field(default_factory=set)
    exclude_types: set[str] = field(default_factory=set)
    include_domains: set[str] = field(default_factory=set)
    exclude_domains: set[str] = field(default_factory=set)
    third_party: Optional[bool] = None
    popup: Optional[bool] = None

    def matches(
        self,
        url_str: str,
        host: str,
        request_type: str,
        first_party_host: str,
        is_third_party: bool,
        is_popup: bool = False,
    ) -> bool:
        if self.domain and not _host_in_set(host, {self.domain}):
            return False
        if self.pattern and not self.pattern.search(url_str):
            return False

        if self.include_types and request_type not in self.include_types:
            return False
        if self.exclude_types and request_type in self.exclude_types:
            return False

        if self.third_party is not None and self.third_party != is_third_party:
            return False
        if self.popup is not None and self.popup != is_popup:
            return False

        if self.include_domains:
            if not first_party_host or not _host_matches_any(
                first_party_host, self.include_domains
            ):
                return False
        if self.exclude_domains and first_party_host and _host_matches_any(
            first_party_host, self.exclude_domains
        ):
            return False

        return True


# ---------------------------------------------------------------------------
# Thread-safe rule store
# ---------------------------------------------------------------------------


class _RuleSet:
    """
    Aggregates rules from multiple filter lists.
    ``should_block`` is called from Qt's network thread; all state is
    protected by a re-entrant lock.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.blocked_domains: set[str] = set()
        self.exception_domains: set[str] = set()
        self.blocked_patterns: list[re.Pattern] = []
        self.exception_patterns: list[re.Pattern] = []
        self.blocked_option_rules: list[_NetworkRule] = []
        self.exception_option_rules: list[_NetworkRule] = []
        self.cosmetic_selectors: list[str] = []
        self._ready = False
        self._requests_blocked = 0

    # ------------------------------------------------------------------

    def add(self, rules: _ParsedRules) -> None:
        with self._lock:
            self.blocked_domains |= rules.blocked_domains
            self.exception_domains |= rules.exception_domains
            self.blocked_patterns.extend(rules.blocked_patterns)
            self.exception_patterns.extend(rules.exception_patterns)
            self.blocked_option_rules.extend(rules.blocked_option_rules)
            self.exception_option_rules.extend(rules.exception_option_rules)
            self.cosmetic_selectors.extend(rules.cosmetic_selectors)
            self._ready = True

    # ------------------------------------------------------------------

    def should_block(
        self,
        url_str: str,
        host: str,
        request_type: str,
        first_party_host: str,
        is_third_party: bool,
        is_popup: bool = False,
    ) -> bool:
        with self._lock:
            if not self._ready:
                return False

            host = host.lower()

            # ── exceptions take priority ────────────────────────────
            if _host_in_set(host, self.exception_domains):
                return False
            for pat in self.exception_patterns:
                if pat.search(url_str):
                    return False
            for rule in self.exception_option_rules:
                if rule.matches(
                    url_str,
                    host,
                    request_type,
                    first_party_host,
                    is_third_party,
                    is_popup,
                ):
                    return False

            # ── network blocks ──────────────────────────────────────
            if _host_in_set(host, self.blocked_domains):
                self._requests_blocked += 1
                return True
            for pat in self.blocked_patterns:
                if pat.search(url_str):
                    self._requests_blocked += 1
                    return True
            for rule in self.blocked_option_rules:
                if rule.matches(
                    url_str,
                    host,
                    request_type,
                    first_party_host,
                    is_third_party,
                    is_popup,
                ):
                    self._requests_blocked += 1
                    return True

        return False

    # ------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        return self._ready

    def stats(self) -> dict:
        with self._lock:
            return {
                "blocked_domains": len(self.blocked_domains),
                "exception_domains": len(self.exception_domains),
                "blocked_patterns": len(self.blocked_patterns),
                "exception_patterns": len(self.exception_patterns),
                "blocked_option_rules": len(self.blocked_option_rules),
                "exception_option_rules": len(self.exception_option_rules),
                "cosmetic_selectors": len(self.cosmetic_selectors),
                "requests_blocked": self._requests_blocked,
            }

    def cosmetic_css(self) -> str:
        """Return a CSS string that hides matched ad elements."""
        with self._lock:
            if not self.cosmetic_selectors:
                return ""
            selectors = ",\n".join(self.cosmetic_selectors[:_COSMETIC_CAP])
            return f"{selectors} {{ display: none !important; }}"


# ---------------------------------------------------------------------------
# Helper: domain ancestry matching
# ---------------------------------------------------------------------------


def _host_in_set(host: str, domain_set: set[str]) -> bool:
    """True if *host* or any of its parent domains appears in *domain_set*."""
    if host in domain_set:
        return True
    parts = host.split(".")
    # check parent domains, e.g. "a.b.example.com" → "b.example.com", "example.com"
    for i in range(1, len(parts) - 1):
        if ".".join(parts[i:]) in domain_set:
            return True
    return False


def _host_matches_any(host: str, domain_set: set[str]) -> bool:
    for domain in domain_set:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _is_same_party(host_a: str, host_b: str) -> bool:
    if not host_a or not host_b:
        return False
    if host_a == host_b:
        return True
    return host_a.endswith("." + host_b) or host_b.endswith("." + host_a)


def _host_from_url(url_str: str) -> str:
    try:
        return urlsplit(url_str).hostname.lower()
    except (AttributeError, ValueError):
        return ""


def _resource_type_name(resource_type: object) -> str:
    name = getattr(resource_type, "name", "")
    # Map Chromium request types to ABP/uBO-style resource names.
    mapping = {
        "ResourceTypeMainFrame": "document",
        "ResourceTypeSubFrame": "subdocument",
        "ResourceTypeStylesheet": "stylesheet",
        "ResourceTypeScript": "script",
        "ResourceTypeImage": "image",
        "ResourceTypeFontResource": "font",
        "ResourceTypeMedia": "media",
        "ResourceTypeObject": "object",
        "ResourceTypeXhr": "xmlhttprequest",
        "ResourceTypePing": "ping",
        "ResourceTypeWorker": "script",
        "ResourceTypeSharedWorker": "script",
        "ResourceTypeServiceWorker": "script",
        "ResourceTypePluginResource": "object",
    }
    return mapping.get(name, "other")


def _iter_found_scripts(found: object):
    """Yield QWebEngineScript objects from PyQt's varying find() results."""
    if isinstance(found, QWebEngineScript):
        yield found
        return
    if isinstance(found, (list, tuple)):
        for item in found:
            yield from _iter_found_scripts(item)


# ---------------------------------------------------------------------------
# Request interceptor (runs on Qt's network thread)
# ---------------------------------------------------------------------------


class _RequestInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, ruleset: _RuleSet) -> None:
        super().__init__()
        self._ruleset = ruleset
        self.enabled = True
        self.block_embedded_ads = False

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:  # noqa: N802
        if not self.enabled:
            return
        url = info.requestUrl()
        host = url.host().lower()
        if not host:
            return
        first_party_host = info.firstPartyUrl().host().lower()
        request_type = _resource_type_name(info.resourceType())
        if not self.block_embedded_ads and request_type != "ping":
            return
        is_third_party = bool(first_party_host) and not _is_same_party(
            host, first_party_host
        )
        if self._ruleset.should_block(
            url.toString(),
            host,
            request_type,
            first_party_host,
            is_third_party,
            False,
        ):
            info.block(True)


# ---------------------------------------------------------------------------
# Filter-list parser  (EasyList / ABP / uBlock Origin format)
# ---------------------------------------------------------------------------

# Regex metacharacters that need to be escaped when converting ABP patterns
_META_ESCAPE = re.compile(r"([.+?{}()\[\]|\\])")

# \^ in an ABP rule is the "separator" character: / ? # = & or end-of-string
_SEPARATOR = r"(?:[/?#=&]|$)"

# Pure domain-anchor rule:  ||domain.tld^  (with optional $options)
_PURE_DOMAIN_RE = re.compile(
    r"^\|\|"
    r"([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*)"
    r"\^(?:\$[^/]*)?$"
)

# Options that fundamentally change interpretation and which we skip
_SKIP_OPTIONS = ("csp=", "rewrite=", "redirect=", "redirect-rule=")

_RESOURCE_ALIASES: dict[str, str] = {
    "xhr": "xmlhttprequest",
    "xmlhttprequest": "xmlhttprequest",
    "script": "script",
    "image": "image",
    "stylesheet": "stylesheet",
    "font": "font",
    "media": "media",
    "object": "object",
    "subdocument": "subdocument",
    "document": "document",
    "ping": "ping",
    "other": "other",
    "popup": "document",
    "popunder": "document",
}

_IGNORED_OPTIONS = {
    "important",
    "match-case",
    "~match-case",
    "generichide",
    "~generichide",
    "specifichide",
    "~specifichide",
    "elemhide",
    "~elemhide",
}

_HARD_UNSUPPORTED_OPTIONS = (
    "removeparam",
    "urltransform",
    "replace=",
    "header=",
    "permissions=",
)


def _parse_rule_options(options_str: str) -> _RuleOptions:
    options = _RuleOptions()
    if not options_str:
        return options

    for raw in options_str.split(","):
        token = raw.strip().lower()
        if not token:
            continue

        if token == "badfilter":
            options.badfilter = True
            continue

        if token in _IGNORED_OPTIONS:
            continue

        if any(
            token.startswith(prefix)
            for prefix in _SKIP_OPTIONS + _HARD_UNSUPPORTED_OPTIONS
        ):
            options.unsupported = True
            continue

        if token == "third-party":
            options.third_party = True
            continue
        if token == "~third-party":
            options.third_party = False
            continue
        if token in {"popup", "popunder"}:
            options.popup = True
            continue
        if token in {"~popup", "~popunder"}:
            options.popup = False
            continue

        if token.startswith("domain="):
            _, _, domain_values = token.partition("=")
            for part in domain_values.split("|"):
                entry = part.strip().lower()
                if not entry:
                    continue
                if entry.startswith("~"):
                    options.exclude_domains.add(entry[1:])
                else:
                    options.include_domains.add(entry)
            continue

        negated = token.startswith("~")
        candidate = token[1:] if negated else token
        mapped = _RESOURCE_ALIASES.get(candidate)
        if mapped:
            if negated:
                options.exclude_types.add(mapped)
            else:
                options.include_types.add(mapped)

    return options


def _abp_to_regex(rule: str) -> Optional[re.Pattern]:
    """
    Convert an Adblock-Plus / uBlock network filter rule to a compiled regex.
    Returns None when the rule is unsupported or malformed.
    """
    # Anchors
    domain_anchor = rule.startswith("||")
    if domain_anchor:
        rule = rule[2:]

    left_anchor = (not domain_anchor) and rule.startswith("|")
    if left_anchor:
        rule = rule[1:]

    right_anchor = rule.endswith("|")
    if right_anchor:
        rule = rule[:-1]

    # Escape regex metacharacters (preserving * and ^)
    rule = _META_ESCAPE.sub(r"\\\1", rule)

    # Wildcards → .*
    rule = rule.replace("*", ".*")

    # ABP separator ^ → regex separator group
    rule = rule.replace("^", _SEPARATOR)

    # Assemble final pattern
    if domain_anchor:
        pattern = r"^https?://(?:[^/]*\.)?" + rule
    elif left_anchor:
        pattern = "^" + rule
    else:
        pattern = rule

    if right_anchor:
        pattern += "$"

    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def _parse_filter_list(text: str) -> _ParsedRules:
    """
    Parse a complete EasyList / ABP / uBlock-origin filter list.

    Supported syntax:
        !  ...               comment / metadata  → ignored
        @@rule               exception (allow) rule
        ||domain.com^        fast domain-anchor block  → domain set (O(1) lookup)
        ||rule^$options      option-aware network rule (domain/type/party)
        /pattern/            general network rule      → compiled regex
        ##selector           global cosmetic (element-hiding) rule
    """
    rules = _ParsedRules()

    for raw in text.splitlines():
        line = raw.strip()

        # ── skip blank lines, comments, header ─────────────────────────────
        if not line or line.startswith("!") or line.startswith("["):
            continue

        # ── cosmetic rules  ##  #@#  #?# ───────────────────────────────────
        for marker in ("##", "#@#", "#?#"):
            if marker in line:
                if marker == "##":
                    domain_part, _, selector = line.partition("##")
                    selector = selector.strip()
                    # Only global selectors (no domain restriction)
                    if not domain_part and selector and not selector.startswith("+js("):
                        rules.cosmetic_selectors.append(selector)
                break
        else:
            # ── exception rules  @@ ────────────────────────────────────────
            is_exception = line.startswith("@@")
            if is_exception:
                line = line[2:]

            # hosts-style entries occasionally appear in ancillary lists.
            host_match = re.match(
                r"^(?:0\.0\.0\.0|127\.0\.0\.1)\s+([a-z0-9.-]+)$",
                line,
                flags=re.IGNORECASE,
            )
            if host_match and not is_exception:
                rules.blocked_domains.add(host_match.group(1).lower())
                continue

            target_domains = (
                rules.exception_domains if is_exception else rules.blocked_domains
            )
            target_patterns = (
                rules.exception_patterns if is_exception else rules.blocked_patterns
            )
            target_option_rules = (
                rules.exception_option_rules
                if is_exception
                else rules.blocked_option_rules
            )

            rule_body = line
            options = _RuleOptions()
            if "$" in line:
                base, sep, opts = line.rpartition("$")
                if sep and base:
                    rule_body = base
                    options = _parse_rule_options(opts)

            if options.badfilter or options.unsupported:
                continue

            has_constraints = bool(
                options.include_types
                or options.exclude_types
                or options.include_domains
                or options.exclude_domains
                or options.third_party is not None
                or options.popup is not None
            )

            # ── fast path: pure domain anchor  ||domain.com^ ───────────────
            m = _PURE_DOMAIN_RE.match(rule_body)
            if m:
                domain = m.group(1).lower()
                if has_constraints:
                    target_option_rules.append(
                        _NetworkRule(
                            domain=domain,
                            include_types=options.include_types,
                            exclude_types=options.exclude_types,
                            include_domains=options.include_domains,
                            exclude_domains=options.exclude_domains,
                            third_party=options.third_party,
                            popup=options.popup,
                        )
                    )
                else:
                    target_domains.add(domain)
                continue

            # ── general network rule → compiled regex ───────────────────────
            pat = _abp_to_regex(rule_body)
            if pat is not None:
                if has_constraints:
                    target_option_rules.append(
                        _NetworkRule(
                            pattern=pat,
                            include_types=options.include_types,
                            exclude_types=options.exclude_types,
                            include_domains=options.include_domains,
                            exclude_domains=options.exclude_domains,
                            third_party=options.third_party,
                            popup=options.popup,
                        )
                    )
                else:
                    target_patterns.append(pat)

    log.debug(
        "AdBlocker: parsed list → %d domains | %d patterns | %d optioned | %d cosmetic",
        len(rules.blocked_domains),
        len(rules.blocked_patterns),
        len(rules.blocked_option_rules),
        len(rules.cosmetic_selectors),
    )
    return rules


# ---------------------------------------------------------------------------
# Disk-cached HTTP fetch
# ---------------------------------------------------------------------------


def _fetch_cached(url: str, cache_dir: Path) -> str:
    """
    Fetch *url* and return its text content, using a disk cache under
    *cache_dir*.  Re-downloads only when the cached copy is older than
    CACHE_TTL seconds.
    """
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", url)[:200]
    cache_path = cache_dir / (safe_name + ".txt")

    if cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < CACHE_TTL:
            log.debug("AdBlocker: cache hit  %s (%.0f s old)", cache_path.name, age)
            return cache_path.read_text(encoding="utf-8", errors="replace")

    log.info("AdBlocker: downloading  %s", url)
    req = Request(url, headers={"User-Agent": "NovaPlay/1.0 (adblocker)"})
    try:
        with urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (URLError, OSError) as exc:
        if cache_path.exists():
            log.warning("AdBlocker: download failed (%s) – using stale cache", exc)
            return cache_path.read_text(encoding="utf-8", errors="replace")
        raise

    cache_path.write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------------------
# Cosmetic CSS  QWebEngineScript
# ---------------------------------------------------------------------------


def _make_cosmetic_script(css: str) -> QWebEngineScript:
    """Build a QWebEngineScript that injects *css* into every page at DocumentReady."""
    script = QWebEngineScript()
    script.setName(_COSMETIC_SCRIPT_NAME)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
    script.setRunsOnSubFrames(False)
    js = (
        "(function(){"
        "var s=document.getElementById('novaplay-cosmetic-block');"
        "if(!s){"
        "s=document.createElement('style');"
        "s.id='novaplay-cosmetic-block';"
        "(document.head||document.documentElement).appendChild(s);}"
        f"s.textContent={repr(css)};"
        "})();"
    )
    script.setSourceCode(js)
    return script


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class AdBlocker(QObject):
    """
    Ad / tracker blocker for a ``QWebEngineView``.

    Wire to a profile, then start the async list loader::

        blocker = AdBlocker()
        blocker.attach(QWebEngineProfile.defaultProfile())
        blocker.load_lists()

    The filter lists are downloaded in a background daemon thread and cached
    locally for 24 hours.  The interceptor starts working as soon as the
    first list finishes parsing — no restart needed.

    Toggle at runtime::

        blocker.enabled = False   # all requests pass through instantly
        blocker.enabled = True

    Inspect statistics::

        s = blocker.stats()
        # {'blocked_domains': 120000, 'requests_blocked': 42, ...}
    """

    # Emitted from the background loader thread; connected to _inject_cosmetic
    # so the Qt profile/script objects are always touched on the main thread.
    _cosmetic_ready = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._ruleset = _RuleSet()
        self._interceptor = _RequestInterceptor(self._ruleset)
        self._profiles: list[QWebEngineProfile] = []
        self._lock = threading.Lock()
        self._loading = False  # prevents duplicate concurrent loads
        self._block_embedded_ads = False

        # Signal is always delivered on the main thread regardless of where
        # it was emitted from, so _inject_cosmetic is always called safely.
        self._cosmetic_ready.connect(self._inject_cosmetic)

    # ------------------------------------------------------------------
    # enable / disable
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._interceptor.enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._interceptor.enabled = value
        log.info("AdBlocker: %s", "enabled" if value else "disabled")

    @property
    def block_embedded_ads(self) -> bool:
        return self._block_embedded_ads

    @block_embedded_ads.setter
    def block_embedded_ads(self, value: bool) -> None:
        self._block_embedded_ads = value
        self._interceptor.block_embedded_ads = value
        log.info(
            "AdBlocker: embedded resource blocking %s",
            "enabled" if value else "disabled",
        )

    # ------------------------------------------------------------------
    # attach to a profile
    # ------------------------------------------------------------------

    def attach(self, profile: QWebEngineProfile) -> None:
        """
        Wire this blocker to *profile*.  Call before navigating.
        You can attach to multiple profiles if needed.
        """
        profile.setUrlRequestInterceptor(self._interceptor)
        with self._lock:
            self._profiles.append(profile)
        log.info(
            "AdBlocker: attached to profile %r",
            profile.storageName() or "(off-the-record)",
        )

    # ------------------------------------------------------------------
    # load filter lists
    # ------------------------------------------------------------------

    def load_lists(
        self,
        lists: list[tuple[str, str]] = DEFAULT_LISTS,
        cache_dir: Path = CACHE_DIR,
    ) -> None:
        """
        Download (or load from disk cache) the given filter lists.
        Runs entirely in a daemon thread so the UI is never blocked.

        *lists* is a sequence of ``(name, url)`` pairs.  Defaults to the
        same set used by uBlock Origin out of the box.

        Calling this while a load is already in progress is a no-op.
        """
        with self._lock:
            if self._loading:
                log.debug("AdBlocker: load_lists() called while already loading — skipped")
                return
            self._loading = True

        cache_dir.mkdir(parents=True, exist_ok=True)
        t = threading.Thread(
            target=self._load_worker,
            args=(lists, cache_dir),
            daemon=True,
            name="adblocker-loader",
        )
        t.start()

    # ------------------------------------------------------------------
    # statistics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return a snapshot of current rule counts and block statistics."""
        stats = self._ruleset.stats()
        stats["block_embedded_ads"] = self._block_embedded_ads
        return stats

    def should_block_navigation(
        self,
        url_str: str,
        first_party_url_str: str = "",
        *,
        popup: bool = False,
    ) -> bool:
        if not self.enabled or not self._ruleset.ready:
            return False

        host = _host_from_url(url_str)
        if not host:
            return False

        first_party_host = _host_from_url(first_party_url_str)
        is_third_party = bool(first_party_host) and not _is_same_party(
            host, first_party_host
        )
        return self._ruleset.should_block(
            url_str,
            host,
            "document",
            first_party_host,
            is_third_party,
            popup,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _load_worker(
        self, lists: list[tuple[str, str]], cache_dir: Path
    ) -> None:
        try:
            for name, url in lists:
                try:
                    text = _fetch_cached(url, cache_dir)
                    rules = _parse_filter_list(text)
                    self._ruleset.add(rules)
                    log.info(
                        "AdBlocker: %-35s  %6d domains | %5d patterns | %5d optioned | %5d cosmetic",
                        name,
                        len(rules.blocked_domains),
                        len(rules.blocked_patterns),
                        len(rules.blocked_option_rules),
                        len(rules.cosmetic_selectors),
                    )
                except Exception:
                    log.exception("AdBlocker: failed to load %r", name)

            # Emit signal so _inject_cosmetic runs on the main thread —
            # Qt profile/script objects must never be touched from a worker thread.
            css = self._ruleset.cosmetic_css()
            if css and self._block_embedded_ads:
                self._cosmetic_ready.emit(css)
        finally:
            with self._lock:
                self._loading = False

    def _inject_cosmetic(self, css: str) -> None:
        """
        Insert (or replace) the cosmetic-blocking script in every attached
        profile so that new page loads automatically hide ad elements.
        """
        script = _make_cosmetic_script(css)
        with self._lock:
            for profile in self._profiles:
                collection = profile.scripts()
                for existing in _iter_found_scripts(
                    collection.find(_COSMETIC_SCRIPT_NAME)
                ):
                    collection.remove(existing)
                collection.insert(script)
        log.info("AdBlocker: cosmetic CSS injected (%d chars)", len(css))
