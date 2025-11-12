"""Scraper for awesome-mcp-servers repository with normalization to RegistryEntry format."""

import asyncio
import logging
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from ..models import LaunchMethod, RegistryEntry, SourceType

logger = logging.getLogger(__name__)

AWESOME_MCP_REPO_URL = "https://github.com/TensorBlock/awesome-mcp-servers"
AWESOME_MCP_RAW_README = "https://raw.githubusercontent.com/TensorBlock/awesome-mcp-servers/main/README.md"


def _extract_github_url(text: str) -> str | None:
    """Extract GitHub URL from markdown link or plain text.
    
    Args:
        text: Text that may contain a GitHub URL
        
    Returns:
        GitHub URL if found, None otherwise
    """
    # Try to match markdown link format: [text](url)
    md_link_pattern = r'\[([^\]]+)\]\((https://github\.com/[^\)]+)\)'
    md_match = re.search(md_link_pattern, text)
    if md_match:
        return md_match.group(2)
    
    # Try to match plain URL
    url_pattern = r'(https://github\.com/[\w\-\.]+/[\w\-\.]+)'
    url_match = re.search(url_pattern, text)
    if url_match:
        return url_match.group(1)
    
    return None


def _parse_server_entry(line: str, category: str) -> RegistryEntry | None:
    """Parse a single server entry line from the awesome list.
    
    Args:
        line: A markdown list item line
        category: The category this server belongs to
        
    Returns:
        Normalized RegistryEntry or None if parsing fails
    """
    try:
        # Expected format: - [owner/repo](url): description
        # or: - [owner/repo](url) - description
        
        # Extract GitHub URL
        github_url = _extract_github_url(line)
        if not github_url:
            logger.debug(f"No GitHub URL found in line: {line}")
            return None
        
        # Extract repo name from URL
        url_parts = github_url.rstrip('/').split('/')
        if len(url_parts) < 2:
            return None
        
        owner = url_parts[-2]
        repo_name = url_parts[-1]
        
        # Extract description (everything after the link)
        # Remove leading markdown list marker and clean up
        desc_match = re.search(r'\]\([^\)]+\)[:\-\s]+(.+)$', line)
        description = desc_match.group(1).strip() if desc_match else ""
        
        # Remove any trailing badges or extra markdown
        description = re.sub(r'\!\[.*?\]\(.*?\)', '', description).strip()
        
        # Generate stable ID
        entry_id = f"awesome/{owner}/{repo_name}".lower()
        
        # Infer launch method from description
        launch_method = LaunchMethod.UNKNOWN
        if any(keyword in description.lower() for keyword in ['docker', 'container', 'image']):
            launch_method = LaunchMethod.PODMAN
        elif any(keyword in description.lower() for keyword in ['npm', 'node', 'python', 'typescript']):
            launch_method = LaunchMethod.STDIO_PROXY
        elif any(keyword in description.lower() for keyword in ['api', 'http', 'rest', 'server']):
            launch_method = LaunchMethod.REMOTE_HTTP
        
        return RegistryEntry(
            id=entry_id,
            name=f"{owner}/{repo_name}",
            description=description,
            source=SourceType.AWESOME,
            repo_url=github_url,
            container_image=None,
            categories=[category],
            tags=[category],
            official=False,
            featured=False,
            requires_api_key=any(keyword in description.lower() for keyword in ['api key', 'authentication', 'token', 'credentials']),
            tools=[],
            launch_method=launch_method,
            server_command=None,
            raw_metadata={
                "category": category,
                "source_line": line,
                "github_url": github_url,
            },
        )
    except Exception as e:
        logger.warning(f"Failed to parse server entry: {line[:100]}... Error: {e}")
        return None


async def scrape_awesome_mcp_servers(
    limit: int | None = None,
    timeout: int = 30,
) -> list[RegistryEntry]:
    """Scrape awesome-mcp-servers repository and return normalized registry entries.
    
    Args:
        limit: Optional limit on number of servers to scrape
        timeout: HTTP request timeout in seconds
        
    Returns:
        List of normalized RegistryEntry objects
    """
    logger.info("Scraping awesome-mcp-servers repository")
    
    entries = []
    current_category = "Uncategorized"
    
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            # Fetch the main README
            logger.info(f"Fetching README from {AWESOME_MCP_RAW_README}")
            response = await client.get(AWESOME_MCP_RAW_README)
            response.raise_for_status()
            readme_content = response.text
            
            # Parse line by line
            lines = readme_content.split('\n')
            
            for line in lines:
                line = line.strip()
                
                # Detect category headers (## followed by emoji and text)
                if line.startswith('## ') and any(emoji in line for emoji in ['🤖', '🎨', '🌐', '🏗️', '☁️', '✨', '💻', '💬', '📝', '📊', '🗄️', '🛠️', '📁', '💰', '🧰', '🎮', '⚙️', '❤️', '🏗️', '🧠', '🗺️', '📈', '📡', '🖼️', '🖥️', '✅', '🔬', '🔎', '🔒', '📱', '⚽', '✈️', '🔧', '🔄']):
                    # Extract category name (remove ## and emoji)
                    category_text = re.sub(r'^##\s*[\w\s]+\s*-\s*', '', line)
                    category_text = re.sub(r'[^\w\s&,\-]', '', category_text).strip()
                    if category_text:
                        current_category = category_text
                        logger.debug(f"Found category: {current_category}")
                
                # Parse server entries (lines starting with -)
                elif line.startswith('- [') and 'github.com' in line.lower():
                    entry = _parse_server_entry(line, current_category)
                    if entry:
                        entries.append(entry)
                        logger.debug(f"Parsed entry: {entry.name}")
                        
                        # Check limit
                        if limit and len(entries) >= limit:
                            logger.info(f"Reached limit of {limit} entries")
                            break
            
            logger.info(f"Successfully scraped {len(entries)} entries from awesome-mcp-servers")
            
    except Exception as e:
        logger.error(f"Failed to scrape awesome-mcp-servers: {e}", exc_info=True)
        return []
    
    return entries
