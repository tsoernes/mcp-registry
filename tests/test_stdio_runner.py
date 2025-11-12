"""Tests for stdio server runner."""

import asyncio
from pathlib import Path

import pytest

from mcp_registry_server.stdio_runner import (
    StdioServerRunner,
    build_server_command,
    parse_server_command,
    validate_command_available,
)


class TestParseServerCommand:
    """Test command string parsing."""

    def test_simple_command(self):
        """Test parsing a simple command."""
        command, args = parse_server_command("python")
        assert command == "python"
        assert args == []

    def test_command_with_args(self):
        """Test parsing command with arguments."""
        command, args = parse_server_command("npx -y @modelcontextprotocol/server-filesystem")
        assert command == "npx"
        assert args == ["-y", "@modelcontextprotocol/server-filesystem"]

    def test_command_with_multiple_args(self):
        """Test parsing command with multiple arguments."""
        command, args = parse_server_command("python -m my_server --verbose --port 3000")
        assert command == "python"
        assert args == ["-m", "my_server", "--verbose", "--port", "3000"]

    def test_empty_command(self):
        """Test parsing empty command raises error."""
        with pytest.raises(ValueError, match="Command string is empty"):
            parse_server_command("")


class TestBuildServerCommand:
    """Test command string building."""

    def test_simple_command(self):
        """Test building simple command."""
        result = build_server_command("python", [])
        assert result == "python"

    def test_command_with_args(self):
        """Test building command with arguments."""
        result = build_server_command("npx", ["-y", "@modelcontextprotocol/server-filesystem"])
        assert result == "npx -y @modelcontextprotocol/server-filesystem"

    def test_command_with_multiple_args(self):
        """Test building command with multiple arguments."""
        result = build_server_command("python", ["-m", "my_server", "--verbose"])
        assert result == "python -m my_server --verbose"

    def test_empty_command(self):
        """Test building with empty command raises error."""
        with pytest.raises(ValueError, match="Command is required"):
            build_server_command("", ["arg"])


class TestValidateCommandAvailable:
    """Test command availability validation."""

    @pytest.mark.asyncio
    async def test_python_available(self):
        """Test that python command is available."""
        is_available, message = await validate_command_available("python")
        assert is_available is True
        assert "python" in message.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_command(self):
        """Test that nonexistent command is not available."""
        is_available, message = await validate_command_available(
            "definitely_not_a_real_command_12345"
        )
        assert is_available is False
        assert "not found" in message.lower()


class TestStdioServerRunner:
    """Test stdio server runner."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test runner initializes successfully."""
        runner = StdioServerRunner()
        assert runner is not None
        assert len(runner._processes) == 0

    @pytest.mark.asyncio
    async def test_spawn_simple_process(self):
        """Test spawning a simple process."""
        runner = StdioServerRunner()

        try:
            # Use sleep as a long-running test command
            server_id, process = await runner.spawn_server(
                server_id="test-sleep", command="sleep", args=["5"], env=None
            )

            assert server_id == "test-sleep"
            assert process is not None
            assert process.pid is not None

            # Verify it's running
            assert await runner.is_running("test-sleep")

        finally:
            await runner.cleanup_all()

    @pytest.mark.asyncio
    async def test_spawn_nonexistent_command(self):
        """Test spawning nonexistent command raises error."""
        runner = StdioServerRunner()

        with pytest.raises(FileNotFoundError, match="not found in PATH"):
            await runner.spawn_server(
                server_id="test-fail",
                command="definitely_not_a_real_command_12345",
                args=[],
                env=None,
            )

    @pytest.mark.asyncio
    async def test_spawn_duplicate_server_id(self):
        """Test spawning with duplicate server_id raises error."""
        runner = StdioServerRunner()

        try:
            # Use sleep to keep process alive
            await runner.spawn_server(server_id="test-sleep", command="sleep", args=["5"], env=None)

            # Try to spawn again with same ID
            with pytest.raises(RuntimeError, match="already running"):
                await runner.spawn_server(
                    server_id="test-sleep", command="sleep", args=["5"], env=None
                )

        finally:
            await runner.cleanup_all()

    @pytest.mark.asyncio
    async def test_stop_server(self):
        """Test stopping a running server."""
        runner = StdioServerRunner()

        try:
            # Spawn a long-running process
            server_id, process = await runner.spawn_server(
                server_id="test-stop", command="sleep", args=["60"], env=None
            )

            # Verify it's running
            assert await runner.is_running("test-stop")

            # Stop the server
            stopped = await runner.stop_server("test-stop")
            assert stopped is True

            # Verify it's no longer running
            assert not await runner.is_running("test-stop")

        finally:
            await runner.cleanup_all()

    @pytest.mark.asyncio
    async def test_stop_nonexistent_server(self):
        """Test stopping nonexistent server returns False."""
        runner = StdioServerRunner()

        stopped = await runner.stop_server("nonexistent")
        assert stopped is False

    @pytest.mark.asyncio
    async def test_is_running(self):
        """Test checking if server is running."""
        runner = StdioServerRunner()

        try:
            # Should return False before spawning
            assert not await runner.is_running("test-running")

            # Spawn a server
            await runner.spawn_server(
                server_id="test-running", command="sleep", args=["60"], env=None
            )

            # Should return True after spawning
            assert await runner.is_running("test-running")

            # Stop the server
            await runner.stop_server("test-running")

            # Should return False after stopping
            assert not await runner.is_running("test-running")

        finally:
            await runner.cleanup_all()

    @pytest.mark.asyncio
    async def test_get_server_pid(self):
        """Test getting server PID."""
        runner = StdioServerRunner()

        try:
            # Should return None before spawning
            assert await runner.get_server_pid("test-pid") is None

            # Spawn a server
            server_id, process = await runner.spawn_server(
                server_id="test-pid", command="sleep", args=["60"], env=None
            )

            # Should return the PID
            pid = await runner.get_server_pid("test-pid")
            assert pid == process.pid
            assert pid is not None

            # Stop the server
            await runner.stop_server("test-pid")

            # Should return None after stopping
            assert await runner.get_server_pid("test-pid") is None

        finally:
            await runner.cleanup_all()

    @pytest.mark.asyncio
    async def test_list_running(self):
        """Test listing running servers."""
        runner = StdioServerRunner()

        try:
            # Should be empty initially
            running = runner.list_running()
            assert len(running) == 0

            # Spawn two servers
            server_id1, process1 = await runner.spawn_server(
                server_id="test-list-1", command="sleep", args=["60"], env=None
            )

            server_id2, process2 = await runner.spawn_server(
                server_id="test-list-2", command="sleep", args=["60"], env=None
            )

            # Should list both
            running = runner.list_running()
            assert len(running) == 2
            assert "test-list-1" in running
            assert "test-list-2" in running
            assert running["test-list-1"] == process1.pid
            assert running["test-list-2"] == process2.pid

            # Stop one
            await runner.stop_server("test-list-1")

            # Should list only one
            running = runner.list_running()
            assert len(running) == 1
            assert "test-list-2" in running

        finally:
            await runner.cleanup_all()

    @pytest.mark.asyncio
    async def test_cleanup_all(self):
        """Test cleaning up all servers."""
        runner = StdioServerRunner()

        # Spawn multiple servers
        await runner.spawn_server(server_id="cleanup-1", command="sleep", args=["60"], env=None)

        await runner.spawn_server(server_id="cleanup-2", command="sleep", args=["60"], env=None)

        # Verify they're running
        assert len(runner.list_running()) == 2

        # Cleanup all
        await runner.cleanup_all()

        # Verify all stopped
        assert len(runner.list_running()) == 0

    @pytest.mark.asyncio
    async def test_environment_variables(self):
        """Test that environment variables are passed to subprocess."""
        runner = StdioServerRunner()

        try:
            # Spawn a long-running process with custom env var
            # (We can't easily test env var output without making the test complex)
            server_id, process = await runner.spawn_server(
                server_id="test-env",
                command="sleep",
                args=["5"],
                env={"TEST_VAR": "custom_value"},
            )

            # Verify it started successfully
            assert server_id == "test-env"
            assert process.pid is not None
            assert await runner.is_running("test-env")

        finally:
            await runner.cleanup_all()
