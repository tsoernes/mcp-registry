"""Tests for core registry functionality."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from mcp_registry_server.models import (
    LaunchMethod,
    RegistryEntry,
    SearchQuery,
    SourceType,
)
from mcp_registry_server.registry import Registry


@pytest.fixture
async def registry(tmp_path):
    """Create a temporary registry instance for testing."""
    cache_dir = tmp_path / "cache"
    sources_dir = tmp_path / "sources"

    reg = Registry(
        cache_dir=cache_dir,
        sources_dir=sources_dir,
        refresh_interval_hours=1,
    )

    yield reg

    # Cleanup is handled automatically by tmp_path


@pytest.fixture
def sample_entries():
    """Create sample registry entries for testing."""
    return [
        RegistryEntry(
            id="docker/postgres",
            name="PostgreSQL MCP Server",
            description="Connect to PostgreSQL databases and run queries",
            source=SourceType.DOCKER,
            repo_url="https://github.com/docker/mcp-postgres",
            container_image="docker.io/mcp/postgres",
            categories=["Database"],
            tags=["sql", "postgres", "database"],
            official=True,
            featured=True,
            requires_api_key=False,
            launch_method=LaunchMethod.PODMAN,
        ),
        RegistryEntry(
            id="mcpservers/filesystem",
            name="Filesystem Operations",
            description="Read and write files on the local filesystem",
            source=SourceType.MCPSERVERS,
            repo_url="https://github.com/example/filesystem-mcp",
            categories=["File System", "Development"],
            tags=["files", "filesystem", "io"],
            official=False,
            featured=False,
            requires_api_key=False,
            launch_method=LaunchMethod.STDIO_PROXY,
        ),
        RegistryEntry(
            id="mcpservers/slack",
            name="Slack MCP Server",
            description="Send messages and interact with Slack workspaces",
            source=SourceType.MCPSERVERS,
            repo_url="https://github.com/example/slack-mcp",
            categories=["Communication"],
            tags=["slack", "chat", "messaging"],
            official=False,
            featured=True,
            requires_api_key=True,
            launch_method=LaunchMethod.PODMAN,
        ),
    ]


@pytest.mark.asyncio
async def test_add_entry(registry, sample_entries):
    """Test adding a single entry to the registry."""
    entry = sample_entries[0]
    await registry.add_entry(entry)

    retrieved = await registry.get_entry(entry.id)
    assert retrieved is not None
    assert retrieved.id == entry.id
    assert retrieved.name == entry.name
    assert retrieved.description == entry.description


@pytest.mark.asyncio
async def test_bulk_add_entries(registry, sample_entries):
    """Test bulk adding multiple entries."""
    count = await registry.bulk_add_entries(sample_entries)

    assert count == len(sample_entries)

    # Verify all entries are present
    for entry in sample_entries:
        retrieved = await registry.get_entry(entry.id)
        assert retrieved is not None
        assert retrieved.name == entry.name


@pytest.mark.asyncio
async def test_search_by_text(registry, sample_entries):
    """Test fuzzy text search."""
    await registry.bulk_add_entries(sample_entries)

    # Search for "postgres"
    query = SearchQuery(query="postgres", limit=10)
    results = await registry.search(query)

    assert len(results) > 0
    assert any("postgres" in r.name.lower() for r in results)


@pytest.mark.asyncio
async def test_search_by_category(registry, sample_entries):
    """Test filtering by category."""
    await registry.bulk_add_entries(sample_entries)

    # Search for database category
    query = SearchQuery(query="", categories=["Database"], limit=10)
    results = await registry.search(query)

    assert len(results) > 0
    assert all("Database" in r.categories for r in results)


@pytest.mark.asyncio
async def test_search_by_source(registry, sample_entries):
    """Test filtering by source."""
    await registry.bulk_add_entries(sample_entries)

    # Search for docker source only
    query = SearchQuery(query="", sources=[SourceType.DOCKER], limit=10)
    results = await registry.search(query)

    assert len(results) > 0
    assert all(r.source == SourceType.DOCKER for r in results)


@pytest.mark.asyncio
async def test_search_official_only(registry, sample_entries):
    """Test filtering by official flag."""
    await registry.bulk_add_entries(sample_entries)

    query = SearchQuery(query="", official_only=True, limit=10)
    results = await registry.search(query)

    assert len(results) > 0
    assert all(r.official for r in results)


@pytest.mark.asyncio
async def test_search_featured_only(registry, sample_entries):
    """Test filtering by featured flag."""
    await registry.bulk_add_entries(sample_entries)

    query = SearchQuery(query="", featured_only=True, limit=10)
    results = await registry.search(query)

    assert len(results) > 0
    assert all(r.featured for r in results)


@pytest.mark.asyncio
async def test_search_requires_api_key(registry, sample_entries):
    """Test filtering by requires_api_key."""
    await registry.bulk_add_entries(sample_entries)

    # Find servers requiring API keys
    query = SearchQuery(query="", requires_api_key=True, limit=10)
    results = await registry.search(query)

    assert len(results) > 0
    assert all(r.requires_api_key for r in results)

    # Find servers NOT requiring API keys
    query_no_key = SearchQuery(query="", requires_api_key=False, limit=10)
    results_no_key = await registry.search(query_no_key)

    assert len(results_no_key) > 0
    assert all(not r.requires_api_key for r in results_no_key)


@pytest.mark.asyncio
async def test_search_combined_filters(registry, sample_entries):
    """Test combining multiple filters."""
    await registry.bulk_add_entries(sample_entries)

    # Search for featured servers in Communication category
    query = SearchQuery(
        query="",
        categories=["Communication"],
        featured_only=True,
        limit=10,
    )
    results = await registry.search(query)

    assert len(results) > 0
    assert all(r.featured for r in results)
    assert all("Communication" in r.categories for r in results)


@pytest.mark.asyncio
async def test_list_all(registry, sample_entries):
    """Test listing all entries."""
    await registry.bulk_add_entries(sample_entries)

    all_entries = await registry.list_all(limit=100)

    assert len(all_entries) == len(sample_entries)


@pytest.mark.asyncio
async def test_persistence(tmp_path, sample_entries):
    """Test that entries persist across registry instances."""
    cache_dir = tmp_path / "cache"
    sources_dir = tmp_path / "sources"

    # Create registry and add entries
    registry1 = Registry(cache_dir=cache_dir, sources_dir=sources_dir)
    await registry1.bulk_add_entries(sample_entries)

    # Create new registry instance (should load from cache)
    registry2 = Registry(cache_dir=cache_dir, sources_dir=sources_dir)

    # Verify entries are loaded
    for entry in sample_entries:
        retrieved = await registry2.get_entry(entry.id)
        assert retrieved is not None
        assert retrieved.name == entry.name


@pytest.mark.asyncio
async def test_active_mount_persistence(tmp_path, sample_entries):
    """Test that active mounts persist across registry instances."""
    from mcp_registry_server.models import ActiveMount

    cache_dir = tmp_path / "cache"
    sources_dir = tmp_path / "sources"

    # Create registry and add mount
    registry1 = Registry(cache_dir=cache_dir, sources_dir=sources_dir)
    await registry1.bulk_add_entries(sample_entries)

    mount = ActiveMount(
        entry_id=sample_entries[0].id,
        name=sample_entries[0].name,
        prefix="postgres",
        container_id="abc123def456",
        environment={"DATABASE_URL": "postgres://localhost"},
    )
    await registry1.add_active_mount(mount)

    # Create new registry instance
    registry2 = Registry(cache_dir=cache_dir, sources_dir=sources_dir)

    # Verify mount is restored
    restored = await registry2.get_active_mount(sample_entries[0].id)
    assert restored is not None
    assert restored.name == mount.name
    assert restored.prefix == mount.prefix
    assert restored.container_id == mount.container_id


@pytest.mark.asyncio
async def test_update_mount_environment(registry, sample_entries):
    """Test updating environment variables for a mount."""
    from mcp_registry_server.models import ActiveMount

    await registry.bulk_add_entries(sample_entries)

    mount = ActiveMount(
        entry_id=sample_entries[0].id,
        name=sample_entries[0].name,
        prefix="postgres",
    )
    await registry.add_active_mount(mount)

    # Update environment
    new_env = {"API_KEY": "secret123", "DATABASE_URL": "postgres://db"}
    updated = await registry.update_mount_environment(sample_entries[0].id, new_env)

    assert updated is not None
    assert "API_KEY" in updated.environment
    assert updated.environment["API_KEY"] == "secret123"
    assert "DATABASE_URL" in updated.environment


@pytest.mark.asyncio
async def test_remove_active_mount(registry, sample_entries):
    """Test removing an active mount."""
    from mcp_registry_server.models import ActiveMount

    await registry.bulk_add_entries(sample_entries)

    mount = ActiveMount(
        entry_id=sample_entries[0].id,
        name=sample_entries[0].name,
        prefix="postgres",
    )
    await registry.add_active_mount(mount)

    # Verify it's active
    active_mounts = await registry.list_active_mounts()
    assert len(active_mounts) == 1

    # Remove it
    removed = await registry.remove_active_mount(sample_entries[0].id)
    assert removed is not None
    assert removed.name == mount.name

    # Verify it's gone
    active_mounts = await registry.list_active_mounts()
    assert len(active_mounts) == 0


@pytest.mark.asyncio
async def test_should_refresh_source(registry):
    """Test refresh interval logic."""
    from mcp_registry_server.models import SourceRefreshStatus

    # No refresh yet - should refresh
    should_refresh = await registry.should_refresh_source(SourceType.DOCKER)
    assert should_refresh is True

    # Set recent refresh
    status = SourceRefreshStatus(
        source_type=SourceType.DOCKER,
        last_refresh=datetime.utcnow(),
        entry_count=10,
        status="ok",
    )
    await registry.update_source_status(status)

    # Should not refresh (too recent)
    should_refresh = await registry.should_refresh_source(SourceType.DOCKER)
    assert should_refresh is False

    # Set old refresh
    status.last_refresh = datetime.utcnow() - timedelta(hours=25)
    await registry.update_source_status(status)

    # Should refresh (stale)
    should_refresh = await registry.should_refresh_source(SourceType.DOCKER)
    assert should_refresh is True


@pytest.mark.asyncio
async def test_get_status(registry, sample_entries):
    """Test getting registry status."""
    await registry.bulk_add_entries(sample_entries)

    status = await registry.get_status()

    assert status.total_entries == len(sample_entries)
    assert status.active_mounts == 0
    assert status.cache_dir is not None
    assert status.sources_dir is not None


@pytest.mark.asyncio
async def test_get_entries_by_source(registry, sample_entries):
    """Test filtering entries by source."""
    await registry.bulk_add_entries(sample_entries)

    docker_entries = registry.get_entries_by_source(SourceType.DOCKER)
    mcpservers_entries = registry.get_entries_by_source(SourceType.MCPSERVERS)

    assert len(docker_entries) > 0
    assert len(mcpservers_entries) > 0
    assert all(e.source == SourceType.DOCKER for e in docker_entries)
    assert all(e.source == SourceType.MCPSERVERS for e in mcpservers_entries)


@pytest.mark.asyncio
async def test_search_popularity_sorting(registry, sample_entries):
    """Test that search results are sorted by popularity."""
    await registry.bulk_add_entries(sample_entries)

    # Search without text query should sort by popularity
    query = SearchQuery(query="", limit=10)
    results = await registry.search(query)

    # Official and featured servers should appear first
    # postgres is official=True, featured=True
    # slack is official=False, featured=True
    # filesystem is official=False, featured=False
    assert results[0].name == "PostgreSQL MCP Server"  # official + featured
    assert results[1].name == "Slack MCP Server"  # featured only


@pytest.mark.asyncio
async def test_search_fuzzy_with_popularity(registry, sample_entries):
    """Test that search combines fuzzy matching with popularity."""
    await registry.bulk_add_entries(sample_entries)

    # Search for "server" - all match, but should be sorted by popularity
    query = SearchQuery(query="server", limit=10)
    results = await registry.search(query)

    # With fuzzy match, all should match but official/featured rank higher
    assert len(results) > 0
    # Official servers should rank higher in results
    official_indices = [i for i, r in enumerate(results) if r.official]
    if official_indices:
        # At least one official server should be in top half of results
        assert min(official_indices) < len(results) / 2


@pytest.mark.asyncio
async def test_popularity_score_calculation(registry, sample_entries):
    """Test the popularity score calculation."""
    await registry.bulk_add_entries(sample_entries)

    # Get the entries
    postgres = await registry.get_entry("docker/postgres")
    filesystem = await registry.get_entry("mcpservers/filesystem")
    slack = await registry.get_entry("mcpservers/slack")

    # Calculate popularity scores
    postgres_score = registry._calculate_popularity_score(postgres)
    filesystem_score = registry._calculate_popularity_score(filesystem)
    slack_score = registry._calculate_popularity_score(slack)

    # PostgreSQL (official + featured + docker source + container image) should rank highest
    assert postgres_score > filesystem_score
    assert postgres_score > slack_score

    # Slack (featured but not official) should rank higher than filesystem
    assert slack_score > filesystem_score
