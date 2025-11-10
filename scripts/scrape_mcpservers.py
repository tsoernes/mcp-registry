#!/usr/bin/env python3
# /// script
# dependencies = ["httpx", "beautifulsoup4", "lxml"]
# requires-python = ">=3.12"
# ///

"""
Scrape MCP server details from mcpservers.org.

Features:
- Collect all MCP servers from the /all listing page.
- For each server page, extract:
  * Name and server page URL
  * GitHub URL (when present)
  * Short description
  * Install instructions (code blocks and key links)
  * Whether an API key is required (heuristic)
- Output formats: json (default), markdown, csv.

Dependencies:
- requests
- beautifulsoup4
- lxml (optional but recommended for faster parsing)

Usage with uv:
- uv run --script playwright-mcp-test/scripts/scrape_mcpservers.py --limit 5 --output markdown
- uv run --script playwright-mcp-test/scripts/scrape_mcpservers.py --output json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import logging
import pathlib
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path  # ensure global Path import for cache usage
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
import requests
from bs4 import BeautifulSoup, Tag

# Constants
BASE_URL = "https://mcpservers.org"
ALL_PAGE = urljoin(BASE_URL, "/all")

# Canonical category mapping by slug
CATEGORY_SLUG_MAP: dict[str, str] = {
    "search": "Search",
    "web-scraping": "Web Scraping",
    "communication": "Communication",
    "productivity": "Productivity",
    "development": "Development",
    "database": "Database",
    "cloud-service": "Cloud Service",
    "file-system": "File System",
    "cloud-storage": "Cloud Storage",
    "version-control": "Version Control",
    "other": "Other",
}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("scrape_mcpservers")

# Caching (HTML by URL)
CACHE_DEFAULT = Path(".cache/html")


def cache_key(url: str, cache_dir: Path) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return cache_dir / f"{h}.html"


def read_cache(url: str, cache_dir: Path) -> str | None:
    try:
        key = cache_key(url, cache_dir)
        if key.exists():
            return key.read_text(encoding="utf-8")
    except Exception:
        return None
    return None


def write_cache(url: str, html: str, cache_dir: Path) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = cache_key(url, cache_dir)
        key.write_text(html, encoding="utf-8")
    except Exception:
        # Non-fatal
        pass


@dataclass(slots=True)
class ServerInfo:
    name: str
    url: str
    github_url: str | None = None
    description: str | None = None
    category: str | None = None  # primary (first) category for backward compatibility
    categories: list[str] = field(
        default_factory=list
    )  # full set of functional categories (excludes Featured / Official flags)
    official: bool | None = None
    featured: bool | None = None
    sponsor: bool | None = None
    clients: list[str] = field(default_factory=list)
    install_instructions: list[str] = field(default_factory=list)
    installs_by_client: dict[str, list[str]] = field(default_factory=dict)
    requires_api_key: bool | None = None
    api_key_evidence: list[str] = field(default_factory=list)
    api_env_vars: list[str] = field(default_factory=list)
    related_servers: list[dict[str, str]] = field(default_factory=list)


def fetch_html(url: str, timeout: int = 20) -> str:
    logger.debug(f"Fetching URL: {url}")
    resp = httpx.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "mcpservers-scraper/1.0"},
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text


def parse_all_server_links(html: str) -> list[str]:
    """
    Extract all unique server detail page URLs from the /all listing.
    """
    soup = BeautifulSoup(html, "lxml")
    detail_links: set[str] = set()

    # Typical pattern: cards linking to /servers/<org>/<name> or /servers/<slug>
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Normalize href to absolute
        abs_url = urljoin(BASE_URL, href)

        parsed = urlparse(abs_url)
        if parsed.netloc != urlparse(BASE_URL).netloc:
            continue

        if parsed.path.startswith("/servers/"):
            detail_links.add(abs_url)

    links = sorted(detail_links)
    logger.info(f"Found {len(links)} server pages.")
    return links


def textify(el: Tag | None) -> str:
    if not el:
        return ""
    return " ".join(el.stripped_strings)


def collect_code_blocks(soup: BeautifulSoup) -> list[str]:
    blocks: list[str] = []
    # Common code containers
    for pre in soup.find_all("pre"):
        code_text = pre.get_text("\n", strip=True)
        if code_text:
            blocks.append(code_text)
    for code in soup.find_all("code"):
        # Skip inline tiny code if not useful; but include non-trivial
        code_text = code.get_text(" ", strip=True)
        if code_text and len(code_text) > 20:
            blocks.append(code_text)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_blocks: list[str] = []
    for b in blocks:
        if b not in seen:
            unique_blocks.append(b)
            seen.add(b)
    return unique_blocks


INSTALL_CODE_KEYWORDS = [
    "npx",
    "mcpServers",
    "amp mcp add",
    "claude mcp add",
    "codex mcp add",
    "/mcp",
    "cursor",
    "docker run",
    "code --add-mcp",
    "Add MCP Server",
    "Install in Goose",
    "lmstudio.ai/install-mcp",
    "opencode.ai/config.json",
    "Qodo Gen",
    "Windsurf",
    "LM Studio",
    "Warp",
    "Factory",
    "Qodo",
    "Cherry Studio",
    "Zed",
    "zed",
]

# Client detection keywords (map => list of phrases to search)
CLIENT_KEYWORDS: dict[str, list[str]] = {
    "VS Code": ["vscode:", "code --add-mcp", "VS Code", "vscode-insiders:mcp/install"],
    "Cursor": ["cursor.com/en/install-mcp", "Cursor"],
    "Claude": ["claude_desktop_config.json", "claude mcp add", "Claude"],
    "Windsurf": ["docs.windsurf.com", "Windsurf"],
    "LM Studio": ["lmstudio.ai/install-mcp", "LM Studio"],
    "Goose": ["block.github.io/goose", "Install in Goose"],
    "Warp": ["docs.warp.dev", "Warp"],
    "Factory": ["droid mcp add", "Factory"],
    "Codex": ["~/.codex/config.toml", "Codex MCP"],
    "Qodo": ["docs.qodo.ai", "Qodo Gen"],
    "Cherry Studio": ["Cherry Studio", "cherrystudio"],
    "Zed": ["Zed", "zed", "zed.dev"],
}

# Environment variable name extraction (matches JSON and shell-like forms)
ENV_VAR_RE = re.compile(
    r'"?([A-Z0-9_]{6,})"?\s*:\s*"(?:\\.|[^"])*"|(^|\b)([A-Z0-9_]{6,})\s*=\s*["\']?[^"\']+',
    re.I,
)


def extract_env_vars_from_text(text: str) -> list[str]:
    found: set[str] = set()
    blacklist = {
        "width",
        "height",
        "viewport",
        "device",
        "host",
        "port",
        "url",
        "name",
        "command",
        "args",
        "description",
        "transport",
        "workingdirectory",
        "format",
        "frequency",
        "start_date",
        "end_date",
        "storage_state",
        "user_data_dir",
        "timeout",
        "caps",
        "category",
    }
    hints = (
        "KEY",
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "PASS",
        "AUTH",
        "BEARER",
        "API",
        "ACCESS",
    )
    for m in ENV_VAR_RE.finditer(text):
        name = (m.group(1) or m.group(3) or "").strip()
        if not name or name.isdigit():
            continue
        lower = name.lower()
        upper = name.upper()
        # Ignore common configuration keys
        if lower in blacklist:
            continue
        # Prefer true secret-like names
        if any(h in upper for h in hints):
            found.add(name)
    return sorted(found)


def classify_clients(text: str) -> list[str]:
    hits: set[str] = set()
    low = text.lower()
    for client, keys in CLIENT_KEYWORDS.items():
        for k in keys:
            if k.lower() in low:
                hits.add(client)
                break
    return sorted(hits)


def group_install_instructions_by_client(
    code_blocks: list[str], soup: BeautifulSoup
) -> dict[str, list[str]]:
    by_client: dict[str, list[str]] = {}
    # Consider code blocks
    for block in code_blocks:
        # Require install keywords to avoid unrelated client mentions
        if not any(k.lower() in block.lower() for k in INSTALL_CODE_KEYWORDS):
            continue
        clients = classify_clients(block)
        if not clients:
            continue
        for c in clients:
            by_client.setdefault(c, []).append(block)
    # Consider install-related links/text
    for a in soup.find_all("a", href=True):
        text = textify(a)
        if not text:
            continue
        # Link must indicate install intent or contain install keywords
        href = a["href"]
        installish = (
            re.search(r"\binstall\b", text, flags=re.I)
            or any(k.lower() in text.lower() for k in INSTALL_CODE_KEYWORDS)
            or any(k.lower() in href.lower() for k in INSTALL_CODE_KEYWORDS)
        )
        if not installish:
            continue
        clients = classify_clients(text + " " + href)
        if clients:
            for c in clients:
                by_client.setdefault(c, []).append(f"{text}: {urljoin(BASE_URL, href)}")
    return by_client


def parse_related_servers(soup: BeautifulSoup) -> list[dict[str, str]]:
    rel: list[dict[str, str]] = []
    # Look for "Related Servers" section heading
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        if re.search(r"\bRelated Servers\b", textify(h), re.I):
            # Collect subsequent links until next heading
            sib = h.next_sibling
            while sib and not (
                isinstance(sib, Tag) and re.match(r"^h[1-6]$", sib.name or "")
            ):
                if isinstance(sib, Tag):
                    for a in sib.find_all("a", href=True):
                        name = textify(a)
                        href = urljoin(BASE_URL, a["href"])
                        if name and href and href.startswith(BASE_URL):
                            rel.append({"name": name, "url": href})
                sib = sib.next_sibling
            break
    # De-dupe by url
    seen: set[str] = set()
    uniq: list[dict[str, str]] = []
    for r in rel:
        if r["url"] not in seen:
            uniq.append(r)
            seen.add(r["url"])
    return uniq


def filter_install_instructions(
    code_blocks: Iterable[str], soup: BeautifulSoup
) -> list[str]:
    """
    Heuristic: prefer code blocks and prominent install links/snippets that contain
    known install keywords. Also include nearby text hints around 'Getting started'
    or 'install' headings.
    """
    instructions: list[str] = []

    # Code blocks filtered by keywords
    for block in code_blocks:
        if any(k.lower() in block.lower() for k in INSTALL_CODE_KEYWORDS):
            instructions.append(block)

    # Install-related links
    for a in soup.find_all("a", href=True):
        text = textify(a)
        href = a["href"]
        if not text:
            continue
        if re.search(r"\binstall\b", text, flags=re.I) or re.search(
            r"\bAdd MCP\b", text, flags=re.I
        ):
            instructions.append(f"{text}: {urljoin(BASE_URL, href)}")

    # Nearby text around 'Getting started' or 'install' headings
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        h_text = textify(h)
        if re.search(r"getting started|install", h_text, flags=re.I):
            # Collect subsequent sibling paragraphs until next heading
            sib = h.next_sibling
            collected_chunk: list[str] = [h_text]
            while sib and not (
                isinstance(sib, Tag) and re.match(r"^h[1-6]$", sib.name or "")
            ):
                if isinstance(sib, Tag):
                    para_txt = textify(sib)
                    if para_txt:
                        collected_chunk.append(para_txt)
                sib = sib.next_sibling
            chunk = "\n".join(collected_chunk)
            if chunk and len(chunk.strip()) > 0:
                instructions.append(chunk)

    # Deduplicate and trim
    dedup: list[str] = []
    seen: set[str] = set()
    for s in instructions:
        s_norm = s.strip()
        if s_norm and s_norm not in seen:
            dedup.append(s_norm)
            seen.add(s_norm)
    return dedup


API_KEY_POSITIVE_PATTERNS = [
    r"\bAPI key\b",
    r"\bAPI keys\b",
    r"\bAPI_TOKEN\b",
    r"\bAPI_KEY\b",
    r"\bX-API-Key\b",
    r"\bAuthorization\b",
    r"Bearer\s+[A-Za-z0-9\-_\.]+",
    r"\bset\s+environment\s+variable\b",
    r"\bdotenv\b",
    r"\bsecrets\b",
    r"\bprovide your.*key\b",
    r"\bsign up.*key\b",
    r"\brequires.*key\b",
    r"\bget your API key\b",
]

API_KEY_NEGATIVE_PATTERNS = [
    r"\bno[-\s]?auth\b",
    r"\bno authentication\b",
    r"\bno api key\b",
    r"\bwithout api key\b",
    r"\bno token required\b",
]


def detect_api_key_requirement(full_text: str) -> tuple[bool | None, list[str]]:
    """
    Return (requires_api_key, evidence)
    True if likely requires, False if likely not required, None if ambiguous.
    """
    evidence: list[str] = []

    for pat in API_KEY_NEGATIVE_PATTERNS:
        m = re.search(pat, full_text, flags=re.I)
        if m:
            evidence.append(f"NEGATIVE: {m.group(0)}")
            # If any strong negative pattern found, likely false
            return False, evidence

    positives = []
    for pat in API_KEY_POSITIVE_PATTERNS:
        m = re.search(pat, full_text, flags=re.I)
        if m:
            positives.append(m.group(0))

    if positives:
        evidence.extend([f"POSITIVE: {p}" for p in positives])
        return True, evidence

    # Ambiguous
    return None, evidence


def parse_server_html(
    url: str,
    html: str,
    category_map: dict[str, list[str]] | None = None,
    official_map: set[str] | None = None,
    featured_set: set[str] | None = None,
) -> ServerInfo:
    soup = BeautifulSoup(html, "lxml")

    # Name: first h1 in main content
    name = None
    main = soup.find("main")
    h1: Tag | None = None
    if main:
        h1 = main.find("h1")
        if h1:
            name = textify(h1)

    if not name:
        # Fallback: title tag
        title_tag = soup.find("title")
        name = textify(title_tag) if title_tag else url

    # Short description: first meaningful paragraph after the H1, or first paragraph in main
    description: str | None = None
    if main:
        desc_p: Tag | None = None
        if h1:
            # Walk siblings after h1 to find the first paragraph with text
            sib = h1.next_sibling
            while sib:
                if isinstance(sib, Tag) and sib.name == "p":
                    ptxt = textify(sib)
                    if ptxt:
                        desc_p = sib
                        break
                sib = sib.next_sibling
        if not desc_p:
            # Fallback to first paragraph anywhere in main content
            cand = main.find("p")
            if cand and textify(cand):
                desc_p = cand
        if desc_p:
            description = textify(desc_p)

    # GitHub link
    github_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "github.com" in href:
            github_url = href
            break

    # Install instructions and clients
    code_blocks = collect_code_blocks(soup)
    install_instructions = filter_install_instructions(code_blocks, soup)
    installs_by_client = group_install_instructions_by_client(code_blocks, soup)

    # API key requirement
    page_text = textify(main) if main else soup.get_text(" ", strip=True)
    requires_api_key, evidence = detect_api_key_requirement(page_text)

    # Clients supported (scan whole page text + code blocks)
    clients = classify_clients(page_text + "\n" + "\n\n".join(code_blocks))

    # API env vars from code and page text
    api_env_vars = extract_env_vars_from_text(
        "\n\n".join(code_blocks) + "\n" + page_text
    )

    # Related servers section
    related_servers = parse_related_servers(soup)

    # Categories: prefer listing-derived mapping (multi-category support)
    categories: list[str] = category_map.get(url, []) if category_map else []
    category: str | None = categories[0] if categories else None

    # Badge flags
    # Flags
    official = True if (official_map and url in official_map) else None
    featured = True if (featured_set and url in featured_set) else None
    sponsor = True if re.search(r"\bsponsor\b", page_text, flags=re.I) else None

    info = ServerInfo(
        name=name,
        url=url,
        github_url=github_url,
        description=description,
        category=category,
        categories=categories,
        official=official,
        featured=featured,
        sponsor=sponsor,
        clients=clients,
        install_instructions=install_instructions,
        installs_by_client=installs_by_client,
        requires_api_key=requires_api_key,
        api_key_evidence=evidence,
        api_env_vars=api_env_vars,
        related_servers=related_servers,
    )
    return info


def parse_server_page(url: str) -> ServerInfo:
    html = fetch_html(url)
    return parse_server_html(url, html)


def merge_duplicates_by_repo(servers: list[ServerInfo]) -> list[ServerInfo]:
    by_repo: dict[str, ServerInfo] = {}
    standalone: list[ServerInfo] = []
    for s in servers:
        if s.github_url:
            key = s.github_url.rstrip("/")
            if key in by_repo:
                base = by_repo[key]
                # Merge fields
                base.install_instructions = sorted(
                    set(base.install_instructions + s.install_instructions)
                )
                # installs_by_client
                for c, blocks in s.installs_by_client.items():
                    base.installs_by_client.setdefault(c, [])
                    for b in blocks:
                        if b not in base.installs_by_client[c]:
                            base.installs_by_client[c].append(b)
                # requires_api_key
                base.requires_api_key = (
                    True
                    if (base.requires_api_key is True or s.requires_api_key is True)
                    else False
                    if (base.requires_api_key is False or s.requires_api_key is False)
                    else None
                )
                base.api_key_evidence = sorted(
                    set(base.api_key_evidence + s.api_key_evidence)
                )
                base.clients = sorted(set(base.clients + s.clients))
                base.api_env_vars = sorted(set(base.api_env_vars + s.api_env_vars))
                base.related_servers = list(
                    {
                        r["url"]: r for r in (base.related_servers + s.related_servers)
                    }.values()
                )
                if not base.description and s.description:
                    base.description = s.description
                # Categories merge
                base.categories = sorted(set(base.categories + s.categories))
                # Incorporate single category fallback from s if not already in list
                if s.category and s.category not in base.categories:
                    base.categories.append(s.category)
                    base.categories = sorted(set(base.categories))
                # Primary category selection
                if not base.category:
                    if base.categories:
                        base.category = base.categories[0]
                else:
                    # Ensure primary category present in list
                    if base.category not in base.categories:
                        base.categories.append(base.category)
                        base.categories = sorted(set(base.categories))
                # Allow upgrading primary category from s if base lacks and s has
                if not base.category and s.category:
                    base.category = s.category
                base.official = (
                    True
                    if (base.official or s.official)
                    else (
                        False
                        if (base.official is False or s.official is False)
                        else None
                    )
                )
                base.sponsor = (
                    True
                    if (base.sponsor or s.sponsor)
                    else (
                        False if (base.sponsor is False or s.sponsor is False) else None
                    )
                )
            else:
                by_repo[key] = s
        else:
            standalone.append(s)
    return list(by_repo.values()) + standalone


async def _scrape_detail_pages_async(
    links: list[str],
    concurrency: int,
    cache_dir: str | None,
    resume: bool,
    force_refresh: bool,
    category_map: dict[str, str] | None,
    official_map: set[str] | None,
    featured_set: set[str] | None,
    http2: bool,
    max_connections: int,
    max_keepalive: int,
) -> list[ServerInfo]:
    sem = asyncio.Semaphore(concurrency)

    def _cache_path(url: str) -> str | None:
        if not cache_dir:
            return None
        import hashlib
        # from pathlib import Path  # removed to avoid shadowing global Path import

        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(url.encode()).hexdigest()[:24]
        return str(Path(cache_dir) / f"{h}.html")

    # Configure connection limits for httpx client
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive,
    )
    async with httpx.AsyncClient(timeout=20, limits=limits, http2=http2) as client:

        async def fetch_one(idx: int, url: str):
            async with sem:
                try:
                    # Try cache (resume or general caching)
                    cpath = _cache_path(url)
                    if cpath and not force_refresh:
                        try:
                            with open(cpath, "r", encoding="utf-8") as fh:
                                html = fh.read()
                                if html and resume:
                                    info = parse_server_html(
                                        url,
                                        html,
                                        category_map,
                                        official_map,
                                        featured_set,
                                    )
                                    logger.info(
                                        f"[{idx}/{len(links)}] Resumed {url} (cache)"
                                    )
                                    return idx, info
                        except FileNotFoundError:
                            pass
                    # Fetch from network
                    resp = await client.get(url)
                    resp.raise_for_status()
                    html = resp.text
                    # Write cache
                    if cpath:
                        try:
                            with open(cpath, "w", encoding="utf-8") as fh:
                                fh.write(html)
                        except Exception:
                            logger.debug(f"Failed to write cache for {url}")
                    info = parse_server_html(
                        url, html, category_map, official_map, featured_set
                    )
                    logger.info(f"[{idx}/{len(links)}] Scraped {url}")
                    return idx, info
                except Exception as e:
                    logger.error(f"Failed to scrape {url}: {e}", exc_info=True)
                    return idx, None

        tasks = [fetch_one(i, u) for i, u in enumerate(links, start=1)]
        results = await asyncio.gather(*tasks)
    # Preserve order and drop None
    ordered: list[ServerInfo] = []
    for _, info in sorted(results, key=lambda t: t[0]):
        if info:
            ordered.append(info)
    return ordered


def scrape_all_servers(
    limit: int | None = None,
    concurrency: int = 20,
    cache_dir: str | None = None,
    meta_cache_dir: str | None = None,
    resume: bool = False,
    force_refresh: bool = False,
    use_categories: bool = False,
    use_sitemap: bool = False,
    sitemap_url: str | None = None,
    http2: bool = False,
    max_connections: int = 128,
    max_keepalive: int = 32,
    strict_official: bool = False,
) -> list[ServerInfo]:
    links: list[str]
    # Pre-pass: build category and official maps from category listing pages
    category_map: dict[str, list[str]] = {}
    official_map: set[str] = set()
    featured_set: set[str] = set()
    category_links: set[str] = set()
    # Use separate meta cache dir for maps (category/official/featured flags)
    meta_dir_path: pathlib.Path | None = None
    if meta_cache_dir:
        meta_dir_path = Path(meta_cache_dir)
        try:
            meta_dir_path.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # Load persisted maps if present (category_map.json, official_map.json, featured_set.json)
        try:
            cat_file = meta_dir_path / "category_map.json"
            off_file = meta_dir_path / "official_map.json"
            feat_file = meta_dir_path / "featured_set.json"
            if cat_file.exists():
                raw_cat = json.loads(cat_file.read_text(encoding="utf-8"))
                if isinstance(raw_cat, dict):
                    for k, v in raw_cat.items():
                        if isinstance(v, list):
                            category_map.setdefault(k, [])
                            for c in v:
                                if c not in category_map[k]:
                                    category_map[k].append(c)
            if off_file.exists() and not strict_official:
                raw_off = json.loads(off_file.read_text(encoding="utf-8"))
                if isinstance(raw_off, list):
                    official_map.update([u for u in raw_off if isinstance(u, str)])
            if feat_file.exists():
                raw_feat = json.loads(feat_file.read_text(encoding="utf-8"))
                if isinstance(raw_feat, list):
                    featured_set.update([u for u in raw_feat if isinstance(u, str)])
            if strict_official:
                logger.info(
                    "Strict official mode: ignoring persisted official_map; will recompute from /category/official pages (max 10 pages)."
                )
                official_map.clear()
        except Exception:
            logger.debug("Failed to load meta cache maps")
        # Always rebuild official_map fresh (persisted values may be stale or overly broad)
        official_map.clear()
    if use_categories:
        # Discover category slugs dynamically from the /all page
        try:
            resp_all = httpx.get(
                f"{BASE_URL}/all",
                timeout=30,
                headers={"User-Agent": "mcpservers-scraper/1.0"},
                follow_redirects=True,
            )
            # Mark featured servers from first page listing
            try:
                soup_feat = BeautifulSoup(resp_all.text, "lxml")
                feat_count = 0
                for a in soup_feat.select('a[href^="/servers/"]'):
                    href = a.get("href", "")
                    if not href:
                        continue
                    u = urljoin(BASE_URL, href)
                    featured_set.add(u)
                    feat_count += 1
                logger.info(f"Identified {feat_count} featured servers (flags only)")
            except Exception:
                pass
            resp_all.raise_for_status()
            soup_all = BeautifulSoup(resp_all.text, "lxml")
            cat_slugs: set[str] = set()
            for a in soup_all.select('a[href^="/category/"]'):
                href = a.get("href", "")
                if not href:
                    continue
                slug = href.rstrip("/").split("/")[-1]
                if slug:
                    cat_slugs.add(slug)
            logger.info(
                f"Discovered category slugs: {sorted(cat_slugs)} (official present: {'official' in cat_slugs})"
            )
        except Exception:
            cat_slugs = set()
        # Scrape dedicated /official pages (site-specific) if 'official' slug not in discovered categories
        if "official" not in cat_slugs:
            try:
                max_official_pages = 1000  # remove artificial 10-page cap; paginate fully until no new links
                total_official_before = len(official_map)
                for page in range(1, max_official_pages + 1):
                    off_url = f"{BASE_URL}/official" + (
                        "" if page == 1 else f"?page={page}"
                    )
                    try:
                        resp_off = httpx.get(
                            off_url,
                            timeout=30,
                            headers={"User-Agent": "mcpservers-scraper/1.0"},
                            follow_redirects=True,
                        )
                        if resp_off.status_code >= 400:
                            break
                        soup_off = BeautifulSoup(resp_off.text, "lxml")
                        main_off = soup_off.find("main") or soup_off
                        new_links = 0
                        for a in main_off.select('a[href^="/servers/"]'):
                            href = a.get("href", "")
                            if not href:
                                continue
                            u = urljoin(BASE_URL, href)
                            if u not in official_map:
                                official_map.add(u)
                                new_links += 1
                            if u not in category_links:
                                category_links.add(u)
                        if new_links == 0:
                            # Stop early if no new official links discovered on this page
                            break
                    except Exception:
                        break
                logger.info(
                    f"Collected {len(official_map) - total_official_before} official servers from /official pages (total={len(official_map)})"
                )
            except Exception:
                logger.warning("Failed scraping /official pages for official flags")
        # For each category, paginate and collect server links + official badges
        for slug in sorted(cat_slugs):
            # Log discovered slugs for debugging
            logger.info(f"Discovered category slugs: {sorted(cat_slugs)}")
            # Determine max pagination page from first page, then iterate deterministically
            try:
                first_url = f"{BASE_URL}/category/{slug}"
                resp0 = httpx.get(
                    first_url,
                    timeout=30,
                    headers={"User-Agent": "mcpservers-scraper/1.0"},
                    follow_redirects=True,
                )
                resp0.raise_for_status()
                soup0 = BeautifulSoup(resp0.text, "lxml")
                main0 = soup0.find("main") or soup0
                # Derive canonical category name from slug (ignore heading text for normalization)
                canonical_name = CATEGORY_SLUG_MAP.get(slug, "Other")
                page_category_name0 = canonical_name
                # Find max page from pagination links (?page=N)
                max_page = 1
                for p in main0.select('a[href*="?page="]'):
                    hrefp = p.get("href", "")
                    m = re.search(r"[?&]page=(\d+)", hrefp)
                    if m:
                        try:
                            max_page = max(max_page, int(m.group(1)))
                        except ValueError:
                            pass
                # Restrict official category pagination to first 10 pages
                if slug == "official":
                    max_page = min(max_page, 10)
                if slug == "official" and strict_official:
                    # Limit official category pagination in strict mode
                    original_max = max_page
                    max_page = min(max_page, 10)
                    logger.info(
                        f"Strict official mode: limiting official pages from {original_max} to {max_page}"
                    )
                # Process page 1 now
                for a in main0.select('a[href^="/servers/"]'):
                    href = a.get("href", "")
                    if not href:
                        continue
                    u = urljoin(BASE_URL, href)
                    if u in category_links:
                        continue
                    category_links.add(u)
                    # Nearest container for badge detection
                    container = a.find_parent(["li", "article", "div"]) or a
                    if slug == "official":
                        official_map.add(u)
                    else:
                        category_map.setdefault(u, [])
                        if page_category_name0 not in category_map[u]:
                            category_map[u].append(page_category_name0)
                # Iterate remaining pages 2..max_page
                for page in range(2, max_page + 1):
                    cat_url = f"{BASE_URL}/category/{slug}?page={page}"
                    try:
                        resp = httpx.get(
                            cat_url,
                            timeout=30,
                            headers={"User-Agent": "mcpservers-scraper/1.0"},
                            follow_redirects=True,
                        )
                        resp.raise_for_status()
                        soup = BeautifulSoup(resp.text, "lxml")
                        main_el = soup.find("main") or soup
                        # Category name should match first page h1
                        for a in main_el.select('a[href^="/servers/"]'):
                            href = a.get("href", "")
                            if not href:
                                continue
                            u = urljoin(BASE_URL, href)
                            if u in category_links:
                                continue
                            category_links.add(u)
                            container = a.find_parent(["li", "article", "div"]) or a
                            if slug == "official":
                                official_map.add(u)
                            else:
                                category_map.setdefault(u, [])
                                if page_category_name0 not in category_map[u]:
                                    category_map[u].append(page_category_name0)
                    except Exception:
                        # Continue to next page on error
                        continue
            except Exception:
                # Skip this category if first page fails
                continue

    if use_categories:
        # Featured already flagged earlier; do not add to categories
        links = sorted(category_links)
    elif use_sitemap:
        # Discover server links via sitemap.xml
        sm_url = sitemap_url or f"{BASE_URL}/sitemap.xml"
        sitemap_text: str

        if cache_dir and resume and not force_refresh:
            # Attempt to read cached sitemap
            import hashlib
            # from pathlib import Path  # removed to avoid creating local Path

            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            sh = hashlib.sha256(sm_url.encode()).hexdigest()[:24]
            spath = Path(cache_dir) / f"{sh}.html"
            if spath.exists():
                sitemap_text = spath.read_text(encoding="utf-8")
            else:
                resp = httpx.get(
                    sm_url,
                    timeout=30,
                    headers={"User-Agent": "mcpservers-scraper/1.0"},
                    follow_redirects=True,
                )
                resp.raise_for_status()
                sitemap_text = resp.text
                spath.write_text(sitemap_text, encoding="utf-8")
        else:
            resp = httpx.get(
                sm_url,
                timeout=30,
                headers={"User-Agent": "mcpservers-scraper/1.0"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            sitemap_text = resp.text
            if cache_dir:
                import hashlib
                # from pathlib import Path  # removed to rely on module-level Path

                Path(cache_dir).mkdir(parents=True, exist_ok=True)
                sh = hashlib.sha256(sm_url.encode()).hexdigest()[:24]
                spath = Path(cache_dir) / f"{sh}.html"
                try:
                    spath.write_text(sitemap_text, encoding="utf-8")
                except Exception:
                    logger.debug("Failed to write sitemap cache")

        # Parse URLs from sitemap content and filter server detail pages
        candidates = re.findall(r"https?://[^\s<>]+", sitemap_text)
        links = sorted(
            {u for u in candidates if u.startswith(BASE_URL) and "/servers/" in u}
        )
        logger.info(f"Discovered {len(links)} server pages via sitemap")
    else:
        # Cache listing page
        listing_html: str
        if cache_dir and resume and not force_refresh:
            # Attempt to read cached listing
            import hashlib
            # from pathlib import Path  # removed to prevent local shadowing

            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            lh = hashlib.sha256(ALL_PAGE.encode()).hexdigest()[:24]
            lpath = Path(cache_dir) / f"{lh}.html"
            if lpath.exists():
                listing_html = lpath.read_text(encoding="utf-8")
            else:
                listing_html = fetch_html(ALL_PAGE)
                lpath.write_text(listing_html, encoding="utf-8")
        else:
            listing_html = fetch_html(ALL_PAGE)
            if cache_dir:
                import hashlib

                Path(cache_dir).mkdir(parents=True, exist_ok=True)
                lh = hashlib.sha256(ALL_PAGE.encode()).hexdigest()[:24]
                lpath = Path(cache_dir) / f"{lh}.html"
                try:
                    lpath.write_text(listing_html, encoding="utf-8")
                except Exception:
                    logger.debug("Failed to write listing cache")

        links = parse_all_server_links(listing_html)
        # Official detection is sourced from category pages only in this mode.
        pass

    if limit is not None:
        links = links[:limit]
    # Persist updated maps before scraping details (so a failed run still leaves maps)
    if meta_dir_path:
        try:
            (meta_dir_path / "category_map.json").write_text(
                json.dumps(
                    {k: v for k, v in category_map.items()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (meta_dir_path / "official_map.json").write_text(
                json.dumps(sorted(list(official_map)), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (meta_dir_path / "featured_set.json").write_text(
                json.dumps(sorted(list(featured_set)), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.debug("Failed to persist meta maps before detail scrape")
    servers = asyncio.run(
        _scrape_detail_pages_async(
            links,
            concurrency,
            cache_dir,
            resume,
            force_refresh,
            category_map,
            official_map,
            featured_set,
            http2,
            max_connections,
            max_keepalive,
        )
    )
    logger.info(
        f"Final official flag count: {sum(1 for s in servers if s.official)} (strict_official={strict_official})"
    )
    # Persist again after successful scrape (may include newly discovered servers)
    if meta_dir_path:
        try:
            (meta_dir_path / "category_map.json").write_text(
                json.dumps(
                    {k: v for k, v in category_map.items()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (meta_dir_path / "official_map.json").write_text(
                json.dumps(sorted(list(official_map)), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (meta_dir_path / "featured_set.json").write_text(
                json.dumps(sorted(list(featured_set)), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                f"Meta caches persisted: {len(category_map)} category entries, "
                f"{len(official_map)} official, {len(featured_set)} featured flags"
            )
        except Exception:
            logger.debug("Failed to persist meta maps after detail scrape")
    servers = merge_duplicates_by_repo(servers)
    return servers


def output_json(servers: list[ServerInfo]) -> None:
    enriched = []
    for s in servers:
        data = asdict(s)
        data["category"] = s.category
        data["categories"] = s.categories
        data["official"] = s.official
        data["featured"] = s.featured
        enriched.append(data)
    print(json.dumps(enriched, ensure_ascii=False, indent=2))


def output_markdown(servers: list[ServerInfo]) -> None:
    lines: list[str] = []
    lines.append("# MCP Servers from mcpservers.org")
    for s in servers:
        lines.append(f"## {s.name}")
        lines.append(f"- Page: {s.url}")
        if s.github_url:
            lines.append(f"- GitHub: {s.github_url}")
        if s.description:
            lines.append(f"- Description: {s.description}")
        if s.category:
            lines.append(f"- Category: {s.category}")
        if s.categories:
            lines.append(f"- Categories: {', '.join(s.categories)}")
        if s.official is not None:
            lines.append(f"- Official: {'Yes' if s.official else 'No'}")
        if s.featured is not None:
            lines.append(f"- Featured: {'Yes' if s.featured else 'No'}")
        if s.sponsor is not None:
            lines.append(f"- Sponsor: {'Yes' if s.sponsor else 'No'}")
        if s.clients:
            lines.append(f"- Clients: {', '.join(s.clients)}")
        if s.api_env_vars:
            lines.append(f"- API env vars: {', '.join(s.api_env_vars)}")
        if s.related_servers:
            lines.append("- Related servers:")
            for r in s.related_servers:
                lines.append(f"  - {r.get('name', '')} ({r.get('url', '')})")
        if s.installs_by_client:
            lines.append("- Install by client:")
            for client, blocks in s.installs_by_client.items():
                lines.append(f"  - {client}:")
                for b in blocks:
                    lines.append("```")
                    lines.append(b)
                    lines.append("```")
        ra = (
            "Unknown"
            if s.requires_api_key is None
            else ("Yes" if s.requires_api_key else "No")
        )
        lines.append(f"- Requires API key: {ra}")
        if s.api_key_evidence:
            lines.append("- Evidence:")
            for ev in s.api_key_evidence:
                lines.append(f"  - {ev}")
        if s.install_instructions:
            lines.append("- Install instructions:")
            for instr in s.install_instructions:
                # Wrap code-looking instructions in fenced blocks, otherwise bullet
                if any(
                    k in instr for k in ["\n", "{", "}", "mcp", "npx", "docker", '"']
                ):
                    lines.append("```")
                    lines.append(instr)
                    lines.append("```")
                else:
                    lines.append(f"  - {instr}")
        lines.append("")
    print("\n".join(lines))


def output_csv(servers: list[ServerInfo]) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(
        [
            "name",
            "url",
            "github_url",
            "description",
            "category",
            "categories",
            "official",
            "featured",
            "sponsor",
            "clients",
            "requires_api_key",
            "api_key_evidence",
            "api_env_vars",
            "install_instructions",
        ]
    )
    for s in servers:
        writer.writerow(
            [
                s.name,
                s.url,
                s.github_url or "",
                s.description or "",
                s.category or "",
                ", ".join(s.categories),
                "" if s.official is None else ("yes" if s.official else "no"),
                "" if s.featured is None else ("yes" if s.featured else "no"),
                "" if s.sponsor is None else ("yes" if s.sponsor else "no"),
                ", ".join(s.clients),
                ""
                if s.requires_api_key is None
                else ("yes" if s.requires_api_key else "no"),
                " | ".join(s.api_key_evidence),
                ", ".join(s.api_env_vars),
                " || ".join(s.install_instructions),
            ]
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape MCP servers from mcpservers.org"
    )
    parser.add_argument(
        "--output",
        choices=["json", "markdown", "csv"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of servers to scrape",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=50,
        help="Number of concurrent HTTP requests for detail pages (default: 50)",
    )
    parser.add_argument(
        "--http2",
        action="store_true",
        help="Enable HTTP/2 for the HTTP client (default: disabled)",
    )
    parser.add_argument(
        "--max-connections",
        type=int,
        default=128,
        help="httpx max concurrent connections (default: 128)",
    )
    parser.add_argument(
        "--max-keepalive",
        type=int,
        default=32,
        help="httpx max keep-alive connections (default: 32)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=".cache/html",
        help="Directory to store/read cached HTML (default: .cache/html)",
    )
    parser.add_argument(
        "--meta-cache-dir",
        type=str,
        default=".cache/meta",
        help="Directory to store/read cached metadata maps (default: .cache/meta)",
    )
    parser.add_argument(
        "--strict-official",
        action="store_true",
        help="Restrict official detection to first 10 pages of /category/official (ignore persisted official map)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume by using cached HTML for already-scraped pages when available",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore cache and re-fetch all pages",
    )
    parser.add_argument(
        "--use-categories",
        action="store_true",
        default=True,
        help="Discover categories dynamically and scrape per-category with pagination (default: enabled)",
    )
    parser.add_argument(
        "--use-sitemap",
        action="store_true",
        help="Discover server URLs via sitemap.xml instead of the /all listing",
    )
    parser.add_argument(
        "--sitemap-url",
        type=str,
        default=f"{BASE_URL}/sitemap.xml",
        help="Alternate sitemap URL (default: BASE_URL/sitemap.xml)",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    # Enforce default True for use_categories when flag not explicitly provided
    if "--use-categories" not in argv:
        args.use_categories = True

    servers = scrape_all_servers(
        limit=args.limit,
        concurrency=args.concurrency,
        cache_dir=args.cache_dir,
        meta_cache_dir=args.meta_cache_dir,
        resume=args.resume,
        force_refresh=args.force_refresh,
        use_categories=args.use_categories,
        use_sitemap=args.use_sitemap,
        sitemap_url=args.sitemap_url,
        http2=args.http2,
        max_connections=args.max_connections,
        max_keepalive=args.max_keepalive,
        strict_official=args.strict_official,
    )

    if args.output == "json":
        output_json(servers)
    elif args.output == "markdown":
        output_markdown(servers)
    elif args.output == "csv":
        output_csv(servers)
    else:
        logger.error(f"Unknown output format: {args.output}")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
