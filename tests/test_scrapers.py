"""Tests for registry scrapers."""

from dataclasses import dataclass, field

import pytest
from mcp_registry_server.models import LaunchMethod, SourceType
from mcp_registry_server.scrapers.mcpservers_scraper import _normalize_server_info
from mcp_registry_server.scrapers.awesome_mcp_scraper import (
    _extract_github_url,
    _parse_server_entry,
)


@dataclass
class MockServerInfo:
    """Mock ServerInfo for testing."""

    name: str
    url: str
    github_url: str | None = None
    description: str | None = None
    categories: list[str] = field(default_factory=list)
    official: bool | None = None
    featured: bool | None = None
    requires_api_key: bool | None = None
    api_key_evidence: list[str] = field(default_factory=list)
    api_env_vars: list[str] = field(default_factory=list)
    install_instructions: list[str] = field(default_factory=list)
    clients: list[str] = field(default_factory=list)
    related_servers: list[dict] = field(default_factory=list)


class TestMCPServersScraper:
    """Tests for MCPServers.org scraper."""

    def test_normalize_server_info(self):
        """Test normalization of ServerInfo to RegistryEntry."""
        server = MockServerInfo(
            name="Test Server",
            url="https://mcpservers.org/servers/test/server",
            github_url="https://github.com/test/server",
            description="A test server",
            categories=["Development", "Productivity"],
            official=False,
            featured=False,
            requires_api_key=True,
        )

        entry = _normalize_server_info(server)

        assert entry.name == "Test Server"
        assert "mcpservers" in entry.id
        assert entry.source == SourceType.MCPSERVERS
        assert entry.repo_url == "https://github.com/test/server"
        assert entry.categories == ["Development", "Productivity"]
        assert entry.tags == ["Development", "Productivity"]
        assert entry.official is False
        assert entry.featured is False
        assert entry.requires_api_key is True
        assert entry.launch_method == LaunchMethod.STDIO_PROXY

    def test_normalize_without_github_url(self):
        """Test normalization when GitHub URL is missing."""
        server = MockServerInfo(
            name="Another Server",
            url="https://mcpservers.org/servers/another/server",
            github_url=None,
            description="Another server",
            categories=["Database"],
        )

        entry = _normalize_server_info(server)

        assert entry.name == "Another Server"
        assert entry.repo_url is None
        assert entry.launch_method == LaunchMethod.STDIO_PROXY

    def test_normalize_id_generation(self):
        """Test ID generation from URL."""
        server = MockServerInfo(
            name="Server One",
            url="https://mcpservers.org/servers/org/name",
        )
        entry = _normalize_server_info(server)
        assert "mcpservers" in entry.id
        assert "name" in entry.id or "org" in entry.id

    def test_normalize_handles_missing_attributes(self):
        """Test normalization gracefully handles missing optional attributes."""
        server = MockServerInfo(
            name="Minimal Server",
            url="https://mcpservers.org/servers/minimal",
        )

        # Should not raise AttributeError
        entry = _normalize_server_info(server)

        assert entry.name == "Minimal Server"
        assert entry.launch_method == LaunchMethod.STDIO_PROXY

    def test_normalize_categories_and_tags(self):
        """Test categories and tags are properly copied."""
        server = MockServerInfo(
            name="Tagged Server",
            url="https://mcpservers.org/servers/tagged",
            categories=["Cat1", "Cat2", "Cat3"],
        )

        entry = _normalize_server_info(server)

        assert len(entry.categories) == 3
        assert "Cat1" in entry.categories
        assert len(entry.tags) == 3  # Tags should match categories

    def test_normalize_api_key_detection(self):
        """Test API key requirement detection."""
        server_with_key = MockServerInfo(
            name="API Server",
            url="https://mcpservers.org/servers/api",
            requires_api_key=True,
            api_env_vars=["API_KEY", "SECRET"],
        )

        entry = _normalize_server_info(server_with_key)
        assert entry.requires_api_key is True

        server_without_key = MockServerInfo(
            name="No API Server",
            url="https://mcpservers.org/servers/noapi",
            requires_api_key=False,
        )

        entry2 = _normalize_server_info(server_without_key)
        assert entry2.requires_api_key is False


class TestAwesomeMCPScraper:
    """Tests for awesome-mcp-servers scraper."""

    def test_extract_github_url_markdown(self):
        """Test extracting GitHub URL from markdown link."""
        text = "[owner/repo](https://github.com/owner/repo)"
        url = _extract_github_url(text)
        assert url == "https://github.com/owner/repo"

    def test_extract_github_url_plain(self):
        """Test extracting GitHub URL from plain text."""
        text = "Check out https://github.com/owner/repo for more"
        url = _extract_github_url(text)
        assert url == "https://github.com/owner/repo"

    def test_extract_github_url_none(self):
        """Test extracting GitHub URL returns None when not found."""
        text = "No GitHub URL here"
        url = _extract_github_url(text)
        assert url is None

    def test_parse_server_entry_basic(self):
        """Test parsing a basic server entry."""
        line = "- [owner/repo](https://github.com/owner/repo): A simple description"
        entry = _parse_server_entry(line, "Test Category")
        
        assert entry is not None
        assert entry.name == "owner/repo"
        assert entry.source == SourceType.AWESOME
        assert entry.repo_url == "https://github.com/owner/repo"
        assert "Test Category" in entry.categories
        assert "simple description" in entry.description.lower()

    def test_parse_server_entry_with_dash_separator(self):
        """Test parsing server entry with dash separator."""
        line = "- [user/project](https://github.com/user/project) - Facilitates something"
        entry = _parse_server_entry(line, "Development")
        
        assert entry is not None
        assert entry.name == "user/project"
        assert "facilitates" in entry.description.lower()

    def test_parse_server_entry_docker_detection(self):
        """Test launch method detection for Docker."""
        line = "- [org/proj](https://github.com/org/proj): Uses Docker containers"
        entry = _parse_server_entry(line, "Infrastructure")
        
        assert entry is not None
        assert entry.launch_method == LaunchMethod.PODMAN

    def test_parse_server_entry_npm_detection(self):
        """Test launch method detection for npm/Node."""
        line = "- [dev/tool](https://github.com/dev/tool): A Node.js based server"
        entry = _parse_server_entry(line, "Utilities")
        
        assert entry is not None
        assert entry.launch_method == LaunchMethod.STDIO_PROXY

    def test_parse_server_entry_api_key_detection(self):
        """Test API key requirement detection."""
        line = "- [api/server](https://github.com/api/server): Requires API key authentication"
        entry = _parse_server_entry(line, "Cloud")
        
        assert entry is not None
        assert entry.requires_api_key is True

    def test_parse_server_entry_invalid_line(self):
        """Test parsing invalid line returns None."""
        line = "Not a valid server entry"
        entry = _parse_server_entry(line, "Category")
        
        assert entry is None

    def test_parse_server_entry_no_github_url(self):
        """Test parsing line without GitHub URL returns None."""
        line = "- [something](https://example.com): Description"
        entry = _parse_server_entry(line, "Category")
        
        assert entry is None
