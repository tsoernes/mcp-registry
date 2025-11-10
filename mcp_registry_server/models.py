"""Pydantic models for MCP registry entries and configuration."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    """Registry source types."""

    DOCKER = "docker"
    MCPSERVERS = "mcpservers"
    AWESOME = "awesome"
    CUSTOM = "custom"


class LaunchMethod(str, Enum):
    """How to launch/run an MCP server."""

    PODMAN = "podman"
    STDIO_PROXY = "stdio-proxy"
    REMOTE_HTTP = "remote-http"
    UNKNOWN = "unknown"


class RegistryEntry(BaseModel):
    """Normalized MCP server registry entry."""

    id: str = Field(..., description="Stable deterministic slug/identifier")
    name: str = Field(..., description="Display name of the MCP server")
    description: str = Field(..., description="Human-readable description")
    source: SourceType = Field(..., description="Origin registry/source")
    repo_url: str | None = Field(None, description="Source code repository URL")
    container_image: str | None = Field(
        None, description="Docker/Podman image reference (e.g., docker.io/mcp/postgres)"
    )
    categories: list[str] = Field(
        default_factory=list,
        description="Functional categories (e.g., Database, Development)",
    )
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    official: bool = Field(False, description="Official status (from mcpservers.org)")
    featured: bool = Field(False, description="Featured status (from mcpservers.org)")
    requires_api_key: bool = Field(
        False, description="Whether API credentials are needed"
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Available tool names (discovered on activation)",
    )
    launch_method: LaunchMethod = Field(
        LaunchMethod.UNKNOWN, description="Preferred launch method"
    )
    last_refreshed: datetime = Field(
        default_factory=datetime.utcnow, description="Last metadata update timestamp"
    )
    added_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When entry was first added to registry",
    )
    raw_metadata: dict[str, Any] = Field(
        default_factory=dict, description="Original metadata for debugging"
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure ID is a valid slug (lowercase alphanumeric with hyphens)."""
        if not v:
            raise ValueError("ID cannot be empty")
        # Allow alphanumeric, hyphens, underscores, and slashes (for namespaced IDs)
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_/")
        if not all(c in allowed for c in v.lower()):
            raise ValueError(
                f"ID must contain only lowercase alphanumeric, hyphens, underscores, and slashes: {v}"
            )
        return v.lower()

    @field_validator("container_image")
    @classmethod
    def validate_image(cls, v: str | None) -> str | None:
        """Basic validation for container image references."""
        if v is None:
            return None
        # Basic sanity check - should contain at least one slash or colon
        if "/" not in v and ":" not in v:
            raise ValueError(f"Invalid container image format: {v}")
        return v

    model_config = {"frozen": False, "extra": "ignore"}


class ActiveMount(BaseModel):
    """Represents an actively mounted/running MCP server."""

    entry_id: str = Field(..., description="Registry entry ID")
    name: str = Field(..., description="Display name")
    prefix: str = Field(..., description="Tool prefix for namespacing")
    container_id: str | None = Field(
        None, description="Podman container ID if applicable"
    )
    pid: int | None = Field(None, description="Process ID if applicable")
    environment: dict[str, str] = Field(
        default_factory=dict, description="Environment variables set for this mount"
    )
    mounted_at: datetime = Field(
        default_factory=datetime.utcnow, description="When server was activated"
    )
    tools: list[str] = Field(
        default_factory=list, description="Discovered tools from this server"
    )

    model_config = {"frozen": False}


class RegistryStatus(BaseModel):
    """Overall registry status and statistics."""

    total_entries: int = Field(..., description="Total number of registry entries")
    active_mounts: int = Field(..., description="Number of currently active servers")
    sources: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-source statistics (entry count, last refresh, status)",
    )
    last_refresh_attempt: datetime | None = Field(
        None, description="Last time any source was refreshed"
    )
    cache_dir: str = Field(..., description="Cache directory path")
    sources_dir: str = Field(..., description="Sources directory path")

    model_config = {"frozen": False}


class SourceRefreshStatus(BaseModel):
    """Status of a specific registry source."""

    source_type: SourceType = Field(..., description="Source identifier")
    last_refresh: datetime | None = Field(
        None, description="Last successful refresh timestamp"
    )
    last_attempt: datetime | None = Field(
        None, description="Last refresh attempt timestamp"
    )
    entry_count: int = Field(0, description="Number of entries from this source")
    status: str = Field("unknown", description="Current status (ok, error, pending)")
    error_message: str | None = Field(None, description="Last error if any")

    model_config = {"frozen": False}


class SearchQuery(BaseModel):
    """Search query parameters."""

    query: str = Field(
        ..., description="Search text (fuzzy matched against name/description)"
    )
    categories: list[str] = Field(
        default_factory=list, description="Filter by categories (OR logic)"
    )
    tags: list[str] = Field(
        default_factory=list, description="Filter by tags (OR logic)"
    )
    sources: list[SourceType] = Field(
        default_factory=list, description="Filter by sources (OR logic)"
    )
    official_only: bool = Field(False, description="Only show official servers")
    featured_only: bool = Field(False, description="Only show featured servers")
    requires_api_key: bool | None = Field(
        None, description="Filter by API key requirement (None = no filter)"
    )
    limit: int = Field(20, ge=1, le=100, description="Max results to return")

    model_config = {"frozen": False}


class ConfigSetRequest(BaseModel):
    """Request to configure an active server."""

    entry_id: str = Field(..., description="Registry entry ID of active server")
    environment: dict[str, str] = Field(
        default_factory=dict, description="Environment variables to set/update"
    )

    @field_validator("environment")
    @classmethod
    def validate_env_keys(cls, v: dict[str, str]) -> dict[str, str]:
        """Validate environment variable names."""
        # Allowlist common patterns (can be expanded)
        allowed_prefixes = [
            "API_KEY",
            "API_TOKEN",
            "AUTH_",
            "DATABASE_",
            "DB_",
            "GITHUB_",
            "OPENAI_",
            "ANTHROPIC_",
            "AWS_",
            "AZURE_",
            "GCP_",
            "SLACK_",
            "DISCORD_",
            "NOTION_",
            "MCP_",
        ]

        for key in v.keys():
            if not any(key.upper().startswith(prefix) for prefix in allowed_prefixes):
                raise ValueError(
                    f"Environment variable '{key}' not in allowlist. "
                    f"Allowed prefixes: {', '.join(allowed_prefixes)}"
                )
        return v

    model_config = {"frozen": False}
