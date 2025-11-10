#!/usr/bin/env python3
# /// script
# dependencies = ["requests", "beautifulsoup4", "lxml"]
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
import csv
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Iterable

from urllib.parse import urljoin, urlparse

import asyncio
import httpx
import hashlib
from pathlib import Path
import requests
from bs4 import BeautifulSoup, Tag

# Constants
BASE_URL = "https://mcpservers.org"
ALL_PAGE = urljoin(BASE_URL, "/all")

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
    category: str | None = None
    official: bool | None = None
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
    resp = requests.get(
        url, timeout=timeout, headers={"User-Agent": "mcpservers-scraper/1.0"}
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
        clients = classify_clients(text)
        if clients:
            for c in clients:
                by_client.setdefault(c, []).append(
                    f"{text}: {urljoin(BASE_URL, a['href'])}"
                )
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


def parse_server_html(url: str, html: str) -> ServerInfo:
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

    # Category: try to find category link on page (e.g., /category/...)
    category: str | None = None
    for a in soup.find_all("a", href=True):
        if "/category/" in a["href"]:
            cat = textify(a).strip()
            if cat:
                category = cat
                break

    # Badge flags
    official = (
        True
        if re.search(r"\bofficial\b", page_text, flags=re.I)
        else False
        if re.search(r"\b(community|unofficial)\b", page_text, flags=re.I)
        else None
    )
    sponsor = True if re.search(r"\bsponsor\b", page_text, flags=re.I) else None

    info = ServerInfo(
        name=name,
        url=url,
        github_url=github_url,
        description=description,
        category=category,
        official=official,
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
) -> list[ServerInfo]:
    sem = asyncio.Semaphore(concurrency)

    def _cache_path(url: str) -> str | None:
        if not cache_dir:
            return None
        import hashlib
        from pathlib import Path

        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(url.encode()).hexdigest()[:24]
        return str(Path(cache_dir) / f"{h}.html")

    async with httpx.AsyncClient(timeout=20) as client:

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
                                    info = parse_server_html(url, html)
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
                    info = parse_server_html(url, html)
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
    concurrency: int = 10,
    cache_dir: str | None = None,
    resume: bool = False,
    force_refresh: bool = False,
) -> list[ServerInfo]:
    # Cache listing page
    listing_html: str
    if cache_dir and resume and not force_refresh:
        # Attempt to read cached listing
        import hashlib
        from pathlib import Path

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
            from pathlib import Path

            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            lh = hashlib.sha256(ALL_PAGE.encode()).hexdigest()[:24]
            lpath = Path(cache_dir) / f"{lh}.html"
            try:
                lpath.write_text(listing_html, encoding="utf-8")
            except Exception:
                logger.debug("Failed to write listing cache")

    links = parse_all_server_links(listing_html)
    if limit is not None:
        links = links[:limit]
    servers = asyncio.run(
        _scrape_detail_pages_async(links, concurrency, cache_dir, resume, force_refresh)
    )
    servers = merge_duplicates_by_repo(servers)
    return servers


def output_json(servers: list[ServerInfo]) -> None:
    print(json.dumps([asdict(s) for s in servers], ensure_ascii=False, indent=2))


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
        if s.official is not None:
            lines.append(f"- Official: {'Yes' if s.official else 'No'}")
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
            "official",
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
                "" if s.official is None else ("yes" if s.official else "no"),
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
        default=10,
        help="Number of concurrent HTTP requests for detail pages (default: 10)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=".cache/html",
        help="Directory to store/read cached HTML (default: .cache/html)",
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
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    servers = scrape_all_servers(
        limit=args.limit,
        concurrency=args.concurrency,
        cache_dir=args.cache_dir,
        resume=args.resume,
        force_refresh=args.force_refresh,
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
