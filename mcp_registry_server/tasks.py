"""Background task scheduler for automatic registry refresh."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from .models import SourceRefreshStatus, SourceType
from .registry import Registry
from .scrapers import scrape_docker_registry, scrape_mcpservers_org

logger = logging.getLogger(__name__)


class RefreshScheduler:
    """Manages background refresh tasks for registry sources."""

    def __init__(self, registry: Registry):
        """Initialize the refresh scheduler.

        Args:
            registry: Registry instance to update
        """
        self.registry = registry
        self._tasks: dict[SourceType, asyncio.Task] = {}
        self._running = False
        self._refresh_interval_seconds = registry.refresh_interval.total_seconds()

    async def _refresh_mcpservers(self) -> None:
        """Refresh mcpservers.org source."""
        source_type = SourceType.MCPSERVERS

        async with self.registry._refresh_locks[source_type]:
            logger.info("Starting mcpservers.org refresh")
            status = SourceRefreshStatus(
                source_type=source_type,
                last_attempt=datetime.utcnow(),
                status="refreshing",
            )
            await self.registry.update_source_status(status)

            try:
                # Scrape mcpservers.org
                entries = await scrape_mcpservers_org(
                    concurrency=20,
                    limit=None,
                    use_cache=True,
                    cache_dir=str(self.registry.cache_dir / "mcpservers_html"),
                )

                # Bulk add to registry
                count = await self.registry.bulk_add_entries(entries)

                # Update status
                status.last_refresh = datetime.utcnow()
                status.entry_count = count
                status.status = "ok"
                status.error_message = None
                await self.registry.update_source_status(status)

                logger.info(f"Successfully refreshed mcpservers.org: {count} entries")
            except Exception as e:
                logger.error(f"Failed to refresh mcpservers.org: {e}", exc_info=True)
                status.status = "error"
                status.error_message = str(e)
                await self.registry.update_source_status(status)

    async def _refresh_docker_registry(self) -> None:
        """Refresh Docker MCP registry source."""
        source_type = SourceType.DOCKER

        async with self.registry._refresh_locks[source_type]:
            logger.info("Starting Docker registry refresh")
            status = SourceRefreshStatus(
                source_type=source_type,
                last_attempt=datetime.utcnow(),
                status="refreshing",
            )
            await self.registry.update_source_status(status)

            try:
                # Scrape Docker registry (clones/pulls git repo)
                entries = await scrape_docker_registry(self.registry.sources_dir)

                # Bulk add to registry
                count = await self.registry.bulk_add_entries(entries)

                # Update status
                status.last_refresh = datetime.utcnow()
                status.entry_count = count
                status.status = "ok"
                status.error_message = None
                await self.registry.update_source_status(status)

                logger.info(f"Successfully refreshed Docker registry: {count} entries")
            except Exception as e:
                logger.error(f"Failed to refresh Docker registry: {e}", exc_info=True)
                status.status = "error"
                status.error_message = str(e)
                await self.registry.update_source_status(status)

    async def _refresh_source(self, source_type: SourceType) -> None:
        """Refresh a specific source.

        Args:
            source_type: Source to refresh
        """
        if source_type == SourceType.MCPSERVERS:
            await self._refresh_mcpservers()
        elif source_type == SourceType.DOCKER:
            await self._refresh_docker_registry()
        else:
            logger.warning(f"No refresh handler for source: {source_type}")

    async def _periodic_refresh_loop(self, source_type: SourceType) -> None:
        """Periodic refresh loop for a source.

        Args:
            source_type: Source to refresh periodically
        """
        logger.info(
            f"Starting periodic refresh loop for {source_type.value} "
            f"(interval: {self._refresh_interval_seconds}s)"
        )

        while self._running:
            try:
                # Check if refresh is needed
                if await self.registry.should_refresh_source(source_type):
                    logger.info(f"Triggering refresh for {source_type.value}")
                    await self._refresh_source(source_type)
                else:
                    logger.debug(
                        f"Skipping refresh for {source_type.value} (too recent)"
                    )

                # Wait for next check (check more frequently than interval)
                check_interval = min(self._refresh_interval_seconds / 4, 3600)
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                logger.info(f"Refresh loop cancelled for {source_type.value}")
                break
            except Exception as e:
                logger.error(
                    f"Error in refresh loop for {source_type.value}: {e}",
                    exc_info=True,
                )
                # Wait before retrying after error
                await asyncio.sleep(60)

    async def start(self) -> None:
        """Start background refresh tasks for all sources."""
        if self._running:
            logger.warning("Refresh scheduler already running")
            return

        self._running = True
        logger.info("Starting refresh scheduler")

        # Start periodic refresh tasks for each source
        sources_to_refresh = [SourceType.MCPSERVERS, SourceType.DOCKER]

        for source_type in sources_to_refresh:
            task = asyncio.create_task(self._periodic_refresh_loop(source_type))
            self._tasks[source_type] = task
            logger.info(f"Started refresh task for {source_type.value}")

        # Trigger initial refresh for sources that need it
        for source_type in sources_to_refresh:
            if await self.registry.should_refresh_source(source_type):
                asyncio.create_task(self._refresh_source(source_type))

    async def stop(self) -> None:
        """Stop all background refresh tasks."""
        if not self._running:
            logger.warning("Refresh scheduler not running")
            return

        self._running = False
        logger.info("Stopping refresh scheduler")

        # Cancel all tasks
        for source_type, task in self._tasks.items():
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled refresh task for {source_type.value}")

        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        self._tasks.clear()
        logger.info("Refresh scheduler stopped")

    async def force_refresh(self, source_type: SourceType) -> bool:
        """Force immediate refresh of a specific source.

        Args:
            source_type: Source to refresh

        Returns:
            True if refresh succeeded
        """
        logger.info(f"Force refreshing {source_type.value}")
        try:
            await self._refresh_source(source_type)
            return True
        except Exception as e:
            logger.error(f"Force refresh failed for {source_type.value}: {e}")
            return False
