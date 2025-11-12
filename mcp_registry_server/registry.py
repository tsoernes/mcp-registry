"""Core registry logic with search, indexing, and entry management."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from rapidfuzz import fuzz, process

from .models import (
    ActiveMount,
    LaunchMethod,
    RegistryEntry,
    RegistryStatus,
    SearchQuery,
    SourceRefreshStatus,
    SourceType,
)

logger = logging.getLogger(__name__)


class Registry:
    """Central registry for MCP servers with search and management."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        sources_dir: Path | None = None,
        refresh_interval_hours: int = 24,
    ):
        """Initialize the registry.

        Args:
            cache_dir: Directory for cached metadata
            sources_dir: Directory for cloned source repositories
            refresh_interval_hours: Hours between automatic refreshes
        """
        self.cache_dir = cache_dir or Path(__file__).parent / "cache"
        self.sources_dir = sources_dir or Path(__file__).parent / "sources"
        self.refresh_interval = timedelta(hours=refresh_interval_hours)

        # Ensure directories exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.sources_dir.mkdir(parents=True, exist_ok=True)

        # In-memory storage
        self._entries: dict[str, RegistryEntry] = {}
        self._active_mounts: dict[str, ActiveMount] = {}
        self._source_status: dict[SourceType, SourceRefreshStatus] = {}

        # Search index (for fuzzy matching)
        self._search_index: list[tuple[str, str, RegistryEntry]] = []

        # Locks for thread safety
        self._entries_lock = asyncio.Lock()
        self._mounts_lock = asyncio.Lock()
        self._refresh_locks: dict[SourceType, asyncio.Lock] = {
            source: asyncio.Lock() for source in SourceType
        }

        # Load persisted data
        self._load_entries_from_cache()
        self._load_active_mounts()

    def _load_entries_from_cache(self) -> None:
        """Load cached registry entries from disk."""
        cache_file = self.cache_dir / "registry_entries.json"
        if not cache_file.exists():
            logger.info("No cached registry entries found")
            return

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for entry_data in data.get("entries", []):
                try:
                    entry = RegistryEntry(**entry_data)
                    self._entries[entry.id] = entry
                except ValidationError as e:
                    logger.warning(f"Failed to load entry {entry_data.get('id')}: {e}")

            logger.info(f"Loaded {len(self._entries)} entries from cache")
            self._rebuild_search_index()
        except Exception as e:
            logger.error(f"Failed to load cached entries: {e}")

    def _save_entries_to_cache(self) -> None:
        """Persist registry entries to disk."""
        cache_file = self.cache_dir / "registry_entries.json"
        try:
            data = {
                "entries": [entry.model_dump(mode="json") for entry in self._entries.values()],
                "updated_at": datetime.utcnow().isoformat(),
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self._entries)} entries to cache")
        except Exception as e:
            logger.error(f"Failed to save entries to cache: {e}")

    def _load_active_mounts(self) -> None:
        """Load persisted active mounts from disk."""
        mounts_file = self.cache_dir / "active_mounts.json"
        if not mounts_file.exists():
            logger.info("No persisted active mounts found")
            return

        try:
            with open(mounts_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for mount_data in data.get("mounts", []):
                try:
                    mount = ActiveMount(**mount_data)
                    self._active_mounts[mount.entry_id] = mount
                except ValidationError as e:
                    logger.warning(f"Failed to load active mount {mount_data.get('entry_id')}: {e}")

            logger.info(f"Loaded {len(self._active_mounts)} active mounts from cache")
        except Exception as e:
            logger.error(f"Failed to load active mounts: {e}")

    def _save_active_mounts(self) -> None:
        """Persist active mounts to disk."""
        mounts_file = self.cache_dir / "active_mounts.json"
        try:
            data = {
                "mounts": [mount.model_dump(mode="json") for mount in self._active_mounts.values()],
                "updated_at": datetime.utcnow().isoformat(),
            }
            with open(mounts_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self._active_mounts)} active mounts")
        except Exception as e:
            logger.error(f"Failed to save active mounts: {e}")

    def _rebuild_search_index(self) -> None:
        """Rebuild the fuzzy search index."""
        self._search_index = []
        for entry in self._entries.values():
            # Index by name and description
            self._search_index.append((entry.name, "name", entry))
            self._search_index.append((entry.description, "description", entry))
            # Index by categories and tags
            for category in entry.categories:
                self._search_index.append((category, "category", entry))
            for tag in entry.tags:
                self._search_index.append((tag, "tag", entry))

    async def add_entry(self, entry: RegistryEntry) -> None:
        """Add or update a registry entry.

        Args:
            entry: Registry entry to add/update
        """
        async with self._entries_lock:
            self._entries[entry.id] = entry
            self._rebuild_search_index()
            self._save_entries_to_cache()
            logger.info(f"Added/updated entry: {entry.id} ({entry.name})")

    async def bulk_add_entries(self, entries: list[RegistryEntry]) -> int:
        """Add multiple entries efficiently.

        Args:
            entries: List of entries to add

        Returns:
            Number of entries added/updated
        """
        async with self._entries_lock:
            for entry in entries:
                self._entries[entry.id] = entry
            self._rebuild_search_index()
            self._save_entries_to_cache()
            logger.info(f"Bulk added {len(entries)} entries")
            return len(entries)

    async def get_entry(self, entry_id: str) -> RegistryEntry | None:
        """Get a registry entry by ID.

        Args:
            entry_id: Entry identifier

        Returns:
            Registry entry or None if not found
        """
        return self._entries.get(entry_id)

    def _calculate_popularity_score(self, entry: RegistryEntry) -> float:
        """Calculate a popularity score for ranking search results.

        Args:
            entry: Registry entry to score

        Returns:
            Popularity score (higher is better)
        """
        score = 0.0

        # Official servers get a significant boost
        if entry.official:
            score += 20.0

        # Featured servers get a moderate boost
        if entry.featured:
            score += 10.0

        # More categories suggests a well-maintained server
        score += min(len(entry.categories), 3) * 2.0

        # Source-based scoring (official sources rank higher)
        if entry.source == SourceType.MCP_OFFICIAL:
            score += 15.0  # Highest priority - official MCP registry
        elif entry.source == SourceType.DOCKER:
            score += 5.0

        # Servers with container images are typically more production-ready
        if entry.container_image:
            score += 3.0

        return score

    async def search(self, query: SearchQuery) -> list[RegistryEntry]:
        """Search registry entries with fuzzy matching and filters.

        Results are sorted by a combination of:
        - Fuzzy match score (primary factor)
        - Popularity metrics (official, featured, categories)

        Args:
            query: Search parameters

        Returns:
            List of matching entries sorted by relevance and popularity
        """
        candidates = list(self._entries.values())

        # Apply filters
        if query.sources:
            candidates = [e for e in candidates if e.source in query.sources]

        if query.categories:
            candidates = [
                e for e in candidates if any(cat in e.categories for cat in query.categories)
            ]

        if query.tags:
            candidates = [e for e in candidates if any(tag in e.tags for tag in query.tags)]

        if query.official_only:
            candidates = [e for e in candidates if e.official]

        if query.featured_only:
            candidates = [e for e in candidates if e.featured]

        if query.requires_api_key is not None:
            candidates = [e for e in candidates if e.requires_api_key == query.requires_api_key]

        # Fuzzy text search with popularity ranking
        if query.query.strip():
            scored_results: list[tuple[RegistryEntry, float]] = []
            seen_ids = set()

            # Search in indexed fields
            search_texts = [item[0] for item in self._search_index]
            matches = process.extract(
                query.query,
                search_texts,
                scorer=fuzz.WRatio,
                limit=query.limit * 3,  # Get more candidates for filtering
            )

            for text, score, idx in matches:
                if score < 60:  # Threshold for fuzzy match
                    continue
                _, field_type, entry = self._search_index[idx]
                if entry.id in seen_ids:
                    continue
                if entry in candidates:  # Must pass filters
                    # Combine fuzzy match score with popularity score
                    # Fuzzy score is 0-100, popularity is 0-40+
                    # Weight fuzzy match more heavily (60%) vs popularity (40%)
                    fuzzy_weight = 0.6
                    popularity_score = self._calculate_popularity_score(entry)
                    combined_score = (score * fuzzy_weight) + (
                        popularity_score * (1 - fuzzy_weight)
                    )

                    scored_results.append((entry, combined_score))
                    seen_ids.add(entry.id)

            # Sort by combined score descending
            scored_results.sort(key=lambda x: x[1], reverse=True)
            results = [entry for entry, _ in scored_results[: query.limit]]
        else:
            # No text query, sort by popularity only
            candidates.sort(key=lambda e: self._calculate_popularity_score(e), reverse=True)
            results = candidates[: query.limit]

        return results

    async def list_all(self, limit: int = 100) -> list[RegistryEntry]:
        """List all registry entries.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of registry entries
        """
        return list(self._entries.values())[:limit]

    async def add_active_mount(self, mount: ActiveMount) -> None:
        """Add an active mount.

        Args:
            mount: Active mount information
        """
        async with self._mounts_lock:
            self._active_mounts[mount.entry_id] = mount
            self._save_active_mounts()
            logger.info(f"Mounted server: {mount.name} (prefix: {mount.prefix})")

    async def remove_active_mount(self, entry_id: str) -> ActiveMount | None:
        """Remove an active mount.

        Args:
            entry_id: Entry ID of the mount to remove

        Returns:
            Removed mount or None if not found
        """
        async with self._mounts_lock:
            mount = self._active_mounts.pop(entry_id, None)
            if mount:
                self._save_active_mounts()
                logger.info(f"Unmounted server: {mount.name}")
            return mount

    async def get_active_mount(self, entry_id: str) -> ActiveMount | None:
        """Get an active mount by entry ID.

        Args:
            entry_id: Entry identifier

        Returns:
            Active mount or None if not found
        """
        return self._active_mounts.get(entry_id)

    async def list_active_mounts(self) -> list[ActiveMount]:
        """List all active mounts.

        Returns:
            List of active mounts
        """
        return list(self._active_mounts.values())

    async def update_mount_environment(
        self, entry_id: str, environment: dict[str, str]
    ) -> ActiveMount | None:
        """Update environment variables for an active mount.

        Args:
            entry_id: Entry ID
            environment: Environment variables to set/update

        Returns:
            Updated mount or None if not found
        """
        async with self._mounts_lock:
            mount = self._active_mounts.get(entry_id)
            if mount:
                mount.environment.update(environment)
                self._save_active_mounts()
                logger.info(f"Updated environment for {mount.name}: {list(environment.keys())}")
            return mount

    async def get_status(self) -> RegistryStatus:
        """Get overall registry status and statistics.

        Returns:
            Registry status information
        """
        sources_info = {}
        for source_type, status in self._source_status.items():
            sources_info[source_type.value] = {
                "entry_count": status.entry_count,
                "last_refresh": (status.last_refresh.isoformat() if status.last_refresh else None),
                "last_attempt": (status.last_attempt.isoformat() if status.last_attempt else None),
                "status": status.status,
                "error_message": status.error_message,
            }

        last_refresh = None
        for status in self._source_status.values():
            if status.last_attempt:
                if last_refresh is None or status.last_attempt > last_refresh:
                    last_refresh = status.last_attempt

        return RegistryStatus(
            total_entries=len(self._entries),
            active_mounts=len(self._active_mounts),
            sources=sources_info,
            last_refresh_attempt=last_refresh,
            cache_dir=str(self.cache_dir),
            sources_dir=str(self.sources_dir),
        )

    async def update_source_status(self, status: SourceRefreshStatus) -> None:
        """Update status for a specific source.

        Args:
            status: Source refresh status
        """
        self._source_status[status.source_type] = status

    async def should_refresh_source(self, source_type: SourceType) -> bool:
        """Check if a source should be refreshed based on interval.

        Args:
            source_type: Source to check

        Returns:
            True if source should be refreshed
        """
        status = self._source_status.get(source_type)
        if not status or not status.last_refresh:
            return True

        elapsed = datetime.utcnow() - status.last_refresh
        return elapsed >= self.refresh_interval

    def get_entries_by_source(self, source_type: SourceType) -> list[RegistryEntry]:
        """Get all entries from a specific source.

        Args:
            source_type: Source to filter by

        Returns:
            List of entries from the source
        """
        return [e for e in self._entries.values() if e.source == source_type]
