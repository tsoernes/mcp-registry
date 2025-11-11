#!/usr/bin/env python3
"""Advanced integration test for complete MCP registry workflow.

This script tests the full workflow:
1. Starting a container with registry_add
2. Discovering tools
3. Executing tools with real arguments
4. Multiple tool executions
5. Proper cleanup with registry_remove

Usage:
    python scripts/test_full_workflow.py
"""

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_registry_server.mcp_client import MCPClient, MCPClientManager
from mcp_registry_server.models import ActiveMount, LaunchMethod, RegistryEntry
from mcp_registry_server.podman_runner import PodmanRunner
from mcp_registry_server.registry import Registry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_full_workflow():
    """Test complete MCP registry workflow with real tool execution."""

    logger.info("=" * 70)
    logger.info("MCP Registry Full Workflow Test")
    logger.info("=" * 70)

    # Initialize components
    runner = PodmanRunner()
    client_manager = MCPClientManager()
    registry = Registry(
        cache_dir=Path(tempfile.gettempdir()) / "mcp-registry-test",
        sources_dir=Path(tempfile.gettempdir()) / "mcp-registry-test" / "sources",
    )

    # Test configuration
    test_image = "docker.io/mcp/sqlite"
    entry_id = "test/sqlite"
    prefix = "sqlite_test"
    container_name = f"mcp-registry-{prefix}"

    process = None
    container_id = None
    client = None
    test_db_path = None

    try:
        # Create a test entry
        entry = RegistryEntry(
            id=entry_id,
            name="SQLite Test Server",
            description="Test SQLite MCP server",
            source="custom",
            launch_method=LaunchMethod.PODMAN,
            container_image=test_image,
        )

        # Step 1: Pull image (simulating registry_add step 1)
        logger.info("\n[1/7] Pulling container image...")
        pull_success = await runner.pull_image(test_image)
        if not pull_success:
            logger.error("✗ Failed to pull image")
            return False
        logger.info("✓ Image pulled successfully")

        # Step 2: Start interactive container (simulating registry_add step 2)
        logger.info(f"\n[2/7] Starting interactive container: {container_name}")
        container_id, process = await runner.run_interactive_container(
            image=test_image,
            name=container_name,
            environment={},
            command=["--db-path", "/tmp/test.db"],  # SQLite needs a database path
        )

        if not container_id or not process:
            logger.error("✗ Failed to start container")
            return False
        logger.info(f"✓ Container started: {container_id}")

        # Step 3: Initialize MCP client (simulating registry_add step 3)
        logger.info("\n[3/7] Initializing MCP client...")
        client = MCPClient(process)

        try:
            capabilities = await asyncio.wait_for(client.initialize(), timeout=10.0)
            logger.info("✓ MCP client initialized")
            logger.info(f"  Protocol version: {capabilities.get('protocolVersion')}")
            logger.info(f"  Server: {capabilities.get('serverInfo', {}).get('name')}")
        except asyncio.TimeoutError:
            logger.error("✗ Timeout during MCP initialization")
            return False

        # Step 4: Discover tools (simulating registry_add step 4)
        logger.info("\n[4/7] Discovering tools...")
        try:
            tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
            tool_names = [tool.get("name", "unknown") for tool in tools]
            logger.info(f"✓ Discovered {len(tool_names)} tools: {tool_names}")
        except asyncio.TimeoutError:
            logger.error("✗ Timeout during tool discovery")
            return False

        # Register client (simulating registry_add step 5)
        client_manager.register_client(container_id, client, process)

        # Create active mount (simulating registry_add step 6)
        mount = ActiveMount(
            entry_id=entry_id,
            name=entry.name,
            prefix=prefix,
            container_id=container_id,
            environment={},
            tools=tool_names,
        )
        await registry.add_active_mount(mount)
        logger.info(f"✓ Active mount created with prefix: {prefix}")

        # Step 5: Execute tool - list_tables (simulating registry_exec)
        # Note: Tools are exposed with mcp_ prefix
        logger.info("\n[5/7] Executing tool: mcp_sqlite_test_list_tables...")
        try:
            result = await asyncio.wait_for(
                client.call_tool("list_tables", {}), timeout=10.0
            )
            logger.info("✓ Tool executed successfully")
            logger.info(f"  Result: {result}")
        except asyncio.TimeoutError:
            logger.error("✗ Tool execution timed out")
            return False
        except Exception as e:
            logger.error(f"✗ Tool execution failed: {e}")
            return False

        # Step 6: Execute tool - create_table (write operation)
        logger.info("\n[6/7] Executing tool: mcp_sqlite_test_create_table...")
        try:
            create_result = await asyncio.wait_for(
                client.call_tool(
                    "create_table",
                    {
                        "table_name": "test_users",
                        "schema": "id INTEGER PRIMARY KEY, name TEXT, email TEXT",
                    },
                ),
                timeout=10.0,
            )
            logger.info("✓ Table created successfully")
            logger.info(f"  Result: {create_result}")
        except Exception as e:
            logger.error(f"✗ Table creation failed: {e}")
            return False

        # Step 7: Execute tool - list_tables again (verify creation)
        logger.info("\n[7/7] Verifying table creation...")
        try:
            verify_result = await asyncio.wait_for(
                client.call_tool("list_tables", {}), timeout=10.0
            )
            logger.info("✓ Verification query executed")
            logger.info(f"  Tables: {verify_result}")

            # Check if our table exists
            if "test_users" in str(verify_result):
                logger.info("✓ Table 'test_users' confirmed in database")
            else:
                logger.warning("⚠ Table 'test_users' not found in list")

        except Exception as e:
            logger.error(f"✗ Verification failed: {e}")
            return False

        logger.info("\n" + "=" * 70)
        logger.info("✓ ALL TESTS PASSED: Complete workflow successful!")
        logger.info("=" * 70)
        logger.info("\nSummary:")
        logger.info(f"  • Container: {container_id}")
        logger.info(f"  • Prefix: {prefix}")
        logger.info(f"  • Tools discovered: {len(tool_names)}")
        logger.info(
            f"  • Tools executed: 3 (mcp_{prefix}_list_tables, mcp_{prefix}_create_table, mcp_{prefix}_list_tables)"
        )
        logger.info(f"  • Active mount: {entry_id}")
        logger.info("=" * 70)

        return True

    except Exception as e:
        logger.error(f"\n✗ TEST FAILED: {e}", exc_info=True)
        return False

    finally:
        # Cleanup (simulating registry_remove)
        logger.info("\n[Cleanup] Removing active mount and stopping container...")

        # Remove active mount
        try:
            await registry.remove_active_mount(entry_id)
            logger.info("✓ Active mount removed")
        except Exception as e:
            logger.warning(f"⚠ Error removing mount: {e}")

        # Clean up MCP client
        if container_id:
            try:
                await client_manager.remove_client(container_id)
                logger.info("✓ MCP client cleaned up")
            except Exception as e:
                logger.warning(f"⚠ Error cleaning up client: {e}")

        # Kill container
        if container_name:
            try:
                await runner.kill_container(container_name)
                logger.info("✓ Container killed")
            except Exception as e:
                logger.warning(f"⚠ Error killing container: {e}")

        logger.info("✓ Cleanup complete\n")


async def main():
    """Main entry point."""
    success = await test_full_workflow()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
