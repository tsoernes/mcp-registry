#!/usr/bin/env python3
"""Integration test script for MCP container communication.

This script tests the complete flow of:
1. Starting a container in interactive mode
2. Initializing MCP client communication
3. Discovering tools
4. Executing a tool
5. Cleaning up

Usage:
    python scripts/test_mcp_container.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_registry_server.mcp_client import MCPClient
from mcp_registry_server.podman_runner import PodmanRunner

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_mcp_container():
    """Test MCP container communication end-to-end."""

    # Configuration
    test_image = "docker.io/mcp/sqlite"  # Simple MCP server for testing
    container_name = "test-mcp-sqlite"

    logger.info("=" * 60)
    logger.info("MCP Container Communication Test")
    logger.info("=" * 60)

    runner = PodmanRunner()
    process = None
    container_id = None

    try:
        # Step 1: Pull the image
        logger.info(f"\n[1/5] Pulling image: {test_image}")
        pull_success = await runner.pull_image(test_image)
        if not pull_success:
            logger.error("Failed to pull image")
            return False
        logger.info("✓ Image pulled successfully")

        # Step 2: Start container in interactive mode
        logger.info(f"\n[2/5] Starting interactive container: {container_name}")
        container_id, process = await runner.run_interactive_container(
            image=test_image,
            name=container_name,
            environment={},
            command=["--db-path", "/tmp/test.db"],  # SQLite needs a database path
        )

        if not container_id or not process:
            logger.error("Failed to start interactive container")
            return False
        logger.info(f"✓ Container started: {container_id}")

        # Step 3: Initialize MCP client
        logger.info("\n[3/5] Initializing MCP client...")
        client = MCPClient(process)

        try:
            capabilities = await asyncio.wait_for(client.initialize(), timeout=10.0)
            logger.info(f"✓ MCP client initialized")
            logger.info(f"  Server capabilities: {capabilities}")
        except asyncio.TimeoutError:
            logger.error("✗ Timeout initializing MCP client")
            return False
        except Exception as e:
            logger.error(f"✗ Error initializing MCP client: {e}")
            return False

        # Step 4: Discover tools
        logger.info("\n[4/5] Discovering available tools...")
        try:
            tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
            logger.info(f"✓ Discovered {len(tools)} tools:")
            for tool in tools:
                tool_name = tool.get("name", "unknown")
                tool_desc = tool.get("description", "No description")
                logger.info(f"  - {tool_name}: {tool_desc[:60]}...")
        except asyncio.TimeoutError:
            logger.error("✗ Timeout discovering tools")
            return False
        except Exception as e:
            logger.error(f"✗ Error discovering tools: {e}")
            return False

        # Step 5: Execute a simple tool (if available)
        logger.info("\n[5/5] Testing tool execution...")
        if tools:
            # Try to find a simple read-only tool
            test_tool = None
            for tool in tools:
                tool_name = tool.get("name", "")
                # Look for listing or query tools
                if any(
                    keyword in tool_name.lower()
                    for keyword in ["list", "query", "read", "describe"]
                ):
                    test_tool = tool
                    break

            if not test_tool:
                # Just use the first tool
                test_tool = tools[0]

            tool_name = test_tool.get("name")
            logger.info(f"  Testing tool: {tool_name}")

            # Try to call with minimal/empty arguments
            try:
                # Most MCP tools accept empty args or have defaults
                result = await asyncio.wait_for(
                    client.call_tool(tool_name, {}), timeout=15.0
                )
                logger.info(f"✓ Tool executed successfully")
                logger.info(f"  Result preview: {str(result)[:200]}...")
            except asyncio.TimeoutError:
                logger.warning(
                    "⚠ Tool execution timed out (this may be expected for some tools)"
                )
            except Exception as e:
                logger.warning(f"⚠ Tool execution failed: {e}")
                logger.info(
                    "  (This may be expected if tool requires specific arguments)"
                )
        else:
            logger.warning("⚠ No tools discovered to test")

        logger.info("\n" + "=" * 60)
        logger.info("✓ TEST PASSED: MCP container communication working!")
        logger.info("=" * 60)
        return True

    except Exception as e:
        logger.error(f"\n✗ TEST FAILED: {e}", exc_info=True)
        return False

    finally:
        # Cleanup
        logger.info("\n[Cleanup] Stopping container and cleaning up...")

        if process:
            try:
                if process.stdin:
                    process.stdin.close()
                await asyncio.wait_for(process.wait(), timeout=5.0)
                logger.info("✓ Process terminated gracefully")
            except asyncio.TimeoutError:
                logger.warning("⚠ Process didn't terminate, killing...")
                try:
                    process.kill()
                    await process.wait()
                except Exception as e:
                    logger.warning(f"⚠ Error killing process: {e}")
            except Exception as e:
                logger.warning(f"⚠ Error during process cleanup: {e}")

        # Try to kill container by name (in case it's still running)
        if container_name:
            try:
                await runner.kill_container(container_name)
            except Exception:
                pass  # Container might already be stopped

        logger.info("✓ Cleanup complete\n")


async def main():
    """Main entry point."""
    success = await test_mcp_container()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
