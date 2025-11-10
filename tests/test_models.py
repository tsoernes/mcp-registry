"""Tests for Pydantic models and validation."""

from datetime import datetime

import pytest
from mcp_registry_server.models import (
    ActiveMount,
    ConfigSetRequest,
    LaunchMethod,
    RegistryEntry,
    RegistryStatus,
    SearchQuery,
    SourceRefreshStatus,
    SourceType,
)
from pydantic import ValidationError


class TestRegistryEntry:
    """Tests for RegistryEntry model."""

    def test_create_valid_entry(self):
        """Test creating a valid registry entry."""
        entry = RegistryEntry(
            id="docker/postgres",
            name="PostgreSQL Server",
            description="Database server",
            source=SourceType.DOCKER,
            container_image="docker.io/mcp/postgres",
        )

        assert entry.id == "docker/postgres"
        assert entry.name == "PostgreSQL Server"
        assert entry.source == SourceType.DOCKER
        assert entry.official is False  # Default
        assert entry.featured is False  # Default
        assert entry.requires_api_key is False  # Default

    def test_id_normalization(self):
        """Test that IDs are normalized to lowercase."""
        entry = RegistryEntry(
            id="Docker/PostgreSQL",
            name="Test",
            description="Test",
            source=SourceType.DOCKER,
        )

        assert entry.id == "docker/postgresql"

    def test_invalid_id_characters(self):
        """Test that invalid ID characters are rejected."""
        with pytest.raises(ValidationError):
            RegistryEntry(
                id="docker@postgres!",  # Invalid characters
                name="Test",
                description="Test",
                source=SourceType.DOCKER,
            )

    def test_empty_id_rejected(self):
        """Test that empty IDs are rejected."""
        with pytest.raises(ValidationError):
            RegistryEntry(
                id="",
                name="Test",
                description="Test",
                source=SourceType.DOCKER,
            )

    def test_invalid_container_image(self):
        """Test that invalid container images are rejected."""
        with pytest.raises(ValidationError):
            RegistryEntry(
                id="test/entry",
                name="Test",
                description="Test",
                source=SourceType.DOCKER,
                container_image="invalid",  # No slash or colon
            )

    def test_default_values(self):
        """Test default values for optional fields."""
        entry = RegistryEntry(
            id="test/entry",
            name="Test",
            description="Test",
            source=SourceType.DOCKER,
        )

        assert entry.categories == []
        assert entry.tags == []
        assert entry.official is False
        assert entry.featured is False
        assert entry.requires_api_key is False
        assert entry.tools == []
        assert entry.launch_method == LaunchMethod.UNKNOWN
        assert entry.raw_metadata == {}
        assert isinstance(entry.last_refreshed, datetime)
        assert isinstance(entry.added_at, datetime)

    def test_all_fields_populated(self):
        """Test creating an entry with all fields."""
        entry = RegistryEntry(
            id="docker/postgres",
            name="PostgreSQL",
            description="Database server",
            source=SourceType.DOCKER,
            repo_url="https://github.com/docker/postgres",
            container_image="docker.io/mcp/postgres:latest",
            categories=["Database", "SQL"],
            tags=["postgres", "sql", "db"],
            official=True,
            featured=True,
            requires_api_key=True,
            tools=["query", "insert", "update"],
            launch_method=LaunchMethod.PODMAN,
            raw_metadata={"custom": "data"},
        )

        assert len(entry.categories) == 2
        assert len(entry.tags) == 3
        assert entry.official is True
        assert entry.featured is True
        assert entry.requires_api_key is True
        assert len(entry.tools) == 3
        assert entry.launch_method == LaunchMethod.PODMAN


class TestActiveMount:
    """Tests for ActiveMount model."""

    def test_create_active_mount(self):
        """Test creating an active mount."""
        mount = ActiveMount(
            entry_id="docker/postgres",
            name="PostgreSQL",
            prefix="postgres",
            container_id="abc123",
            environment={"DATABASE_URL": "postgres://localhost"},
        )

        assert mount.entry_id == "docker/postgres"
        assert mount.name == "PostgreSQL"
        assert mount.prefix == "postgres"
        assert mount.container_id == "abc123"
        assert "DATABASE_URL" in mount.environment
        assert isinstance(mount.mounted_at, datetime)

    def test_default_values(self):
        """Test default values for optional fields."""
        mount = ActiveMount(
            entry_id="test/entry",
            name="Test",
            prefix="test",
        )

        assert mount.container_id is None
        assert mount.pid is None
        assert mount.environment == {}
        assert mount.tools == []
        assert isinstance(mount.mounted_at, datetime)


class TestSearchQuery:
    """Tests for SearchQuery model."""

    def test_create_search_query(self):
        """Test creating a search query."""
        query = SearchQuery(
            query="postgres",
            categories=["Database"],
            tags=["sql"],
            sources=[SourceType.DOCKER],
            limit=50,
        )

        assert query.query == "postgres"
        assert "Database" in query.categories
        assert "sql" in query.tags
        assert SourceType.DOCKER in query.sources
        assert query.limit == 50

    def test_default_values(self):
        """Test default values."""
        query = SearchQuery(query="test")

        assert query.categories == []
        assert query.tags == []
        assert query.sources == []
        assert query.official_only is False
        assert query.featured_only is False
        assert query.requires_api_key is None
        assert query.limit == 20

    def test_limit_validation(self):
        """Test that limit is validated within range."""
        # Valid limits
        SearchQuery(query="test", limit=1)
        SearchQuery(query="test", limit=100)

        # Invalid limits
        with pytest.raises(ValidationError):
            SearchQuery(query="test", limit=0)

        with pytest.raises(ValidationError):
            SearchQuery(query="test", limit=101)


class TestConfigSetRequest:
    """Tests for ConfigSetRequest model."""

    def test_create_config_request(self):
        """Test creating a valid config request."""
        config = ConfigSetRequest(
            entry_id="docker/postgres",
            environment={
                "API_KEY": "secret",
                "DATABASE_URL": "postgres://localhost",
            },
        )

        assert config.entry_id == "docker/postgres"
        assert "API_KEY" in config.environment
        assert "DATABASE_URL" in config.environment

    def test_allowed_env_var_prefixes(self):
        """Test that allowed prefixes are accepted."""
        allowed_vars = {
            "API_KEY": "key1",
            "API_TOKEN": "token1",
            "AUTH_TOKEN": "auth1",
            "DATABASE_URL": "db1",
            "DB_HOST": "host1",
            "GITHUB_TOKEN": "gh1",
            "OPENAI_API_KEY": "oai1",
            "ANTHROPIC_API_KEY": "ant1",
            "AWS_ACCESS_KEY": "aws1",
            "AZURE_KEY": "az1",
            "GCP_KEY": "gcp1",
            "SLACK_TOKEN": "slack1",
            "DISCORD_TOKEN": "discord1",
            "NOTION_TOKEN": "notion1",
            "MCP_CONFIG": "mcp1",
        }

        config = ConfigSetRequest(
            entry_id="test/entry",
            environment=allowed_vars,
        )

        assert len(config.environment) == len(allowed_vars)

    def test_disallowed_env_var_rejected(self):
        """Test that disallowed environment variables are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ConfigSetRequest(
                entry_id="test/entry",
                environment={"CUSTOM_VAR": "value"},  # Not in allowlist
            )

        assert "not in allowlist" in str(exc_info.value).lower()

    def test_case_insensitive_validation(self):
        """Test that env var validation is case-insensitive."""
        # Lowercase should work
        config = ConfigSetRequest(
            entry_id="test/entry",
            environment={"api_key": "secret"},
        )

        assert "api_key" in config.environment

    def test_empty_environment(self):
        """Test creating config with empty environment."""
        config = ConfigSetRequest(
            entry_id="test/entry",
            environment={},
        )

        assert config.environment == {}


class TestSourceRefreshStatus:
    """Tests for SourceRefreshStatus model."""

    def test_create_refresh_status(self):
        """Test creating a refresh status."""
        now = datetime.utcnow()
        status = SourceRefreshStatus(
            source_type=SourceType.DOCKER,
            last_refresh=now,
            last_attempt=now,
            entry_count=100,
            status="ok",
        )

        assert status.source_type == SourceType.DOCKER
        assert status.last_refresh == now
        assert status.entry_count == 100
        assert status.status == "ok"
        assert status.error_message is None

    def test_default_values(self):
        """Test default values."""
        status = SourceRefreshStatus(source_type=SourceType.MCPSERVERS)

        assert status.last_refresh is None
        assert status.last_attempt is None
        assert status.entry_count == 0
        assert status.status == "unknown"
        assert status.error_message is None

    def test_with_error(self):
        """Test status with error message."""
        status = SourceRefreshStatus(
            source_type=SourceType.DOCKER,
            status="error",
            error_message="Connection timeout",
        )

        assert status.status == "error"
        assert status.error_message == "Connection timeout"


class TestRegistryStatus:
    """Tests for RegistryStatus model."""

    def test_create_registry_status(self):
        """Test creating registry status."""
        status = RegistryStatus(
            total_entries=100,
            active_mounts=5,
            sources={
                "docker": {
                    "entry_count": 50,
                    "status": "ok",
                    "last_refresh": "2025-01-01T00:00:00",
                }
            },
            cache_dir="/tmp/cache",
            sources_dir="/tmp/sources",
        )

        assert status.total_entries == 100
        assert status.active_mounts == 5
        assert "docker" in status.sources
        assert status.cache_dir == "/tmp/cache"


class TestEnums:
    """Tests for enum types."""

    def test_source_type_values(self):
        """Test SourceType enum values."""
        assert SourceType.DOCKER.value == "docker"
        assert SourceType.MCPSERVERS.value == "mcpservers"
        assert SourceType.AWESOME.value == "awesome"
        assert SourceType.CUSTOM.value == "custom"

    def test_launch_method_values(self):
        """Test LaunchMethod enum values."""
        assert LaunchMethod.PODMAN.value == "podman"
        assert LaunchMethod.STDIO_PROXY.value == "stdio-proxy"
        assert LaunchMethod.REMOTE_HTTP.value == "remote-http"
        assert LaunchMethod.UNKNOWN.value == "unknown"

    def test_enum_from_string(self):
        """Test creating enums from string values."""
        assert SourceType("docker") == SourceType.DOCKER
        assert LaunchMethod("podman") == LaunchMethod.PODMAN

    def test_invalid_enum_value(self):
        """Test that invalid enum values raise errors."""
        with pytest.raises(ValueError):
            SourceType("invalid")

        with pytest.raises(ValueError):
            LaunchMethod("invalid")
