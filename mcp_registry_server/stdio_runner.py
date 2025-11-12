"""Stdio-based MCP server runner for direct process management.

This module provides functionality to spawn and manage MCP servers that
communicate via stdio (npm/npx packages, Python scripts, etc.) without
requiring containers.
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StdioServerRunner:
    """Manages stdio-based MCP servers as direct subprocesses.

    This runner spawns MCP servers that use stdin/stdout for communication,
    such as npm packages (npx @modelcontextprotocol/server-*) and Python
    packages. It manages the process lifecycle and provides the same interface
    as containerized servers.
    """

    def __init__(self):
        """Initialize the stdio server runner."""
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        logger.info("StdioServerRunner initialized")

    async def spawn_server(
        self,
        server_id: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> tuple[str, asyncio.subprocess.Process]:
        """Spawn a stdio-based MCP server.

        Args:
            server_id: Unique identifier for this server instance
            command: Command to execute (e.g., "npx", "python", "node")
            args: Command arguments (e.g., ["@modelcontextprotocol/server-filesystem", "/tmp"])
            env: Optional environment variables

        Returns:
            Tuple of (server_id, process)

        Raises:
            FileNotFoundError: If command is not found in PATH
            RuntimeError: If server fails to start
        """
        # Check if command exists
        if not shutil.which(command):
            raise FileNotFoundError(
                f"Command '{command}' not found in PATH. "
                f"Please install the required package or ensure it's in PATH."
            )

        # Check if server_id already exists
        if server_id in self._processes:
            raise RuntimeError(f"Server {server_id} is already running")

        # Prepare environment
        process_env = dict(env) if env else {}
        # Inherit PATH and other critical env vars
        import os

        for key in ["PATH", "HOME", "USER", "SHELL"]:
            if key in os.environ and key not in process_env:
                process_env[key] = os.environ[key]

        logger.info(f"Spawning stdio server: {command} {' '.join(args)}")

        try:
            # Spawn the process
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
            )

            # Wait a moment to check if process started successfully
            await asyncio.sleep(0.5)

            # Check if process is still running
            if process.returncode is not None:
                stderr = await process.stderr.read()
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise RuntimeError(
                    f"Server process exited immediately with code {process.returncode}: {error_msg}"
                )

            # Store process reference
            self._processes[server_id] = process
            logger.info(
                f"Stdio server {server_id} started successfully (PID: {process.pid})"
            )

            return (server_id, process)

        except Exception as e:
            logger.error(f"Failed to spawn stdio server {server_id}: {e}")
            raise

    async def stop_server(self, server_id: str, timeout: float = 5.0) -> bool:
        """Stop a running stdio server.

        Args:
            server_id: Server identifier
            timeout: Grace period before force kill (seconds)

        Returns:
            True if stopped successfully, False otherwise
        """
        if server_id not in self._processes:
            logger.warning(f"Server {server_id} not found in running processes")
            return False

        process = self._processes[server_id]

        try:
            # Try graceful shutdown first
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                    logger.info(f"Stdio server {server_id} terminated gracefully")
                except asyncio.TimeoutError:
                    # Force kill if graceful shutdown times out
                    logger.warning(
                        f"Stdio server {server_id} did not terminate, force killing"
                    )
                    process.kill()
                    await process.wait()

            # Remove from tracking
            del self._processes[server_id]
            return True

        except Exception as e:
            logger.error(f"Error stopping stdio server {server_id}: {e}")
            return False

    async def is_running(self, server_id: str) -> bool:
        """Check if a server is currently running.

        Args:
            server_id: Server identifier

        Returns:
            True if server is running, False otherwise
        """
        if server_id not in self._processes:
            return False

        process = self._processes[server_id]
        return process.returncode is None

    async def get_server_pid(self, server_id: str) -> int | None:
        """Get the PID of a running server.

        Args:
            server_id: Server identifier

        Returns:
            PID if server is running, None otherwise
        """
        if server_id not in self._processes:
            return None

        process = self._processes[server_id]
        return process.pid if process.returncode is None else None

    async def cleanup_all(self) -> None:
        """Stop all running stdio servers.

        This should be called during shutdown to ensure all processes are cleaned up.
        """
        logger.info(f"Cleaning up {len(self._processes)} stdio servers")

        server_ids = list(self._processes.keys())
        for server_id in server_ids:
            await self.stop_server(server_id)

        logger.info("All stdio servers cleaned up")

    def list_running(self) -> dict[str, int]:
        """List all currently running servers.

        Returns:
            Dictionary mapping server_id to PID
        """
        running = {}
        for server_id, process in self._processes.items():
            if process.returncode is None:
                running[server_id] = process.pid

        return running


async def validate_command_available(command: str) -> tuple[bool, str]:
    """Validate that a command is available in PATH.

    Args:
        command: Command to check (e.g., "npx", "python")

    Returns:
        Tuple of (is_available, message)
    """
    if shutil.which(command):
        try:
            # Try to get version for additional validation
            process = await asyncio.create_subprocess_exec(
                command,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            version = (stdout or stderr).decode().strip().split("\n")[0]
            return (True, f"{command} is available: {version}")
        except Exception:
            return (True, f"{command} is available in PATH")
    else:
        suggestions = []
        if command == "npx":
            suggestions.append("Install Node.js: https://nodejs.org/")
            suggestions.append("Or use your package manager: sudo dnf install nodejs")
        elif command == "python":
            suggestions.append("Python should be installed by default")
            suggestions.append("Try: python3 instead")
        elif command == "node":
            suggestions.append("Install Node.js: https://nodejs.org/")

        message = f"{command} not found in PATH.\n"
        if suggestions:
            message += "Installation suggestions:\n" + "\n".join(
                f"  - {s}" for s in suggestions
            )

        return (False, message)


def parse_server_command(command_str: str) -> tuple[str, list[str]]:
    """Parse a server command string into command and arguments.

    Handles common patterns like:
    - "npx @modelcontextprotocol/server-filesystem /tmp"
    - "python -m my_mcp_server"
    - "node server.js --port 3000"

    Args:
        command_str: Full command string

    Returns:
        Tuple of (command, args)

    Examples:
        >>> parse_server_command("npx @modelcontextprotocol/server-filesystem /tmp")
        ("npx", ["@modelcontextprotocol/server-filesystem", "/tmp"])

        >>> parse_server_command("python -m mcp_server --verbose")
        ("python", ["-m", "mcp_server", "--verbose"])
    """
    parts = command_str.split()
    if not parts:
        raise ValueError("Command string is empty")

    command = parts[0]
    args = parts[1:] if len(parts) > 1 else []

    return (command, args)


def build_server_command(command: str, args: list[str]) -> str:
    """Build a command string from command and arguments.

    Args:
        command: Base command
        args: List of arguments

    Returns:
        Full command string

    Examples:
        >>> build_server_command("npx", ["@modelcontextprotocol/server-filesystem", "/tmp"])
        "npx @modelcontextprotocol/server-filesystem /tmp"
    """
    if not command:
        raise ValueError("Command is required")

    parts = [command] + (args or [])
    return " ".join(parts)
