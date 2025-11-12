"""Simplified MCP client for communicating with MCP servers."""

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    """Simplified MCP protocol client for tool execution.

    This is a minimal implementation that supports:
    - JSON-RPC 2.0 message format
    - Tool discovery (tools/list)
    - Tool execution (tools/call)
    - Basic error handling

    Note: This is a simplified client. A production implementation would
    need to handle the full MCP protocol including capabilities negotiation,
    resource management, prompts, etc.
    """

    def __init__(self, process: asyncio.subprocess.Process):
        """Initialize MCP client with a process.

        Args:
            process: subprocess with stdin/stdout for MCP communication
        """
        self.process = process
        self._request_id = 0
        self._initialized = False

    def _next_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    async def _send_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response.

        Args:
            method: JSON-RPC method name
            params: Optional parameters dict

        Returns:
            Response result dict

        Raises:
            RuntimeError: If process is not available or communication fails
        """
        if not self.process or not self.process.stdin:
            raise RuntimeError("MCP client process not available")

        request_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        # Send request
        request_json = json.dumps(request) + "\n"
        logger.debug(f"Sending MCP request: {request_json.strip()}")

        try:
            self.process.stdin.write(request_json.encode())
            await self.process.stdin.drain()
        except Exception as e:
            logger.error(f"Failed to send MCP request: {e}")
            raise RuntimeError(f"Failed to send request: {e}")

        # Read response
        try:
            response_line = await asyncio.wait_for(
                self.process.stdout.readline(), timeout=30.0
            )
            if not response_line:
                raise RuntimeError("MCP server closed connection")

            response = json.loads(response_line.decode())
            logger.debug(f"Received MCP response: {response}")

            # Check for error
            if "error" in response:
                error = response["error"]
                raise RuntimeError(
                    f"MCP error: {error.get('message', 'Unknown error')}"
                )

            return response.get("result", {})

        except asyncio.TimeoutError:
            logger.error("MCP request timed out")
            raise RuntimeError("Request timed out")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse MCP response: {e}")
            raise RuntimeError(f"Invalid JSON response: {e}")

    async def initialize(self) -> dict[str, Any]:
        """Initialize the MCP connection.

        Returns:
            Server capabilities dict
        """
        if self._initialized:
            return {}

        result = await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "mcp-registry", "version": "0.1.0"},
            },
        )

        # Send initialized notification
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        notification_json = json.dumps(notification) + "\n"
        self.process.stdin.write(notification_json.encode())
        await self.process.stdin.drain()

        self._initialized = True
        logger.info("MCP client initialized")
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP server.

        Returns:
            List of tool definitions
        """
        if not self._initialized:
            await self.initialize()

        result = await self._send_request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments as a dict

        Returns:
            Tool execution result
        """
        if not self._initialized:
            await self.initialize()

        result = await self._send_request(
            "tools/call", {"name": tool_name, "arguments": arguments}
        )

        # Extract content from result
        content = result.get("content", [])
        if content and isinstance(content, list) and len(content) > 0:
            return content[0].get("text", result)

        return result

    async def close(self):
        """Close the MCP client connection."""
        if self.process and self.process.stdin:
            try:
                self.process.stdin.close()
                await self.process.wait()
            except Exception as e:
                logger.warning(f"Error closing MCP client: {e}")


class MCPClientManager:
    """Manages MCP client instances for active containers."""

    def __init__(self):
        """Initialize the MCP client manager."""
        self._clients: dict[str, tuple[MCPClient, asyncio.subprocess.Process]] = {}

    def register_client(
        self, container_id: str, client: MCPClient, process: asyncio.subprocess.Process
    ):
        """Register an MCP client for a container.

        Args:
            container_id: Container identifier
            client: MCP client instance
            process: Subprocess for the container
        """
        self._clients[container_id] = (client, process)
        logger.info(f"Registered MCP client for container {container_id}")

    def get_client(self, container_id: str) -> MCPClient | None:
        """Get MCP client for a container.

        Args:
            container_id: Container identifier

        Returns:
            MCP client if found, None otherwise
        """
        if container_id in self._clients:
            return self._clients[container_id][0]
        return None

    async def remove_client(self, container_id: str):
        """Remove and close MCP client for a container.

        Args:
            container_id: Container identifier
        """
        if container_id in self._clients:
            client, process = self._clients.pop(container_id)
            await client.close()
            logger.info(f"Removed MCP client for container {container_id}")

    async def close_all(self):
        """Close all MCP clients."""
        for container_id in list(self._clients.keys()):
            await self.remove_client(container_id)
