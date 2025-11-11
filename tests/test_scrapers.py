"""Tests for registry scrapers."""

from dataclasses import dataclass, field

import pytest
from mcp_registry_server.models import LaunchMethod, SourceType
from mcp_registry_server.scrapers.mcpservers_scraper import _normalize_server_info


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
