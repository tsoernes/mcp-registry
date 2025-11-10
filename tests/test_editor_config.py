"""Tests for editor configuration management."""

import json
from pathlib import Path

import pytest
from mcp_registry_server.editor_config import EditorConfigManager


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary config directories for testing."""
    zed_config = tmp_path / "zed"
    claude_config = tmp_path / "claude"
    zed_config.mkdir()
    claude_config.mkdir()
    return {
        "zed": zed_config / "settings.json",
        "claude": claude_config / "claude_desktop_config.json",
    }


@pytest.fixture
def editor_manager(temp_config_dir, monkeypatch):
    """Create EditorConfigManager with mocked config paths."""
    manager = EditorConfigManager()

    # Mock the config path methods to use temp directories
    monkeypatch.setattr(
        EditorConfigManager,
        "get_zed_config_path",
        lambda: temp_config_dir["zed"],
    )
    monkeypatch.setattr(
        EditorConfigManager,
        "get_claude_config_path",
        lambda: temp_config_dir["claude"],
    )

    return manager


class TestEditorConfigManager:
    """Tests for EditorConfigManager class."""

    def test_add_zed_server_new_config(self, editor_manager, temp_config_dir):
        """Test adding a server to a new Zed config."""
        result = editor_manager.add_zed_server(
            server_name="test-server",
            command="npx",
            args=["-y", "@test/server"],
            env={"API_KEY": "secret"},
        )

        assert "Successfully added" in result
        assert "test-server" in result

        # Verify config file was created
        config_path = temp_config_dir["zed"]
        assert config_path.exists()

        # Verify content
        with open(config_path, "r") as f:
            config = json.load(f)

        assert "context_servers" in config
        assert "test-server" in config["context_servers"]
        assert config["context_servers"]["test-server"]["command"] == "npx"
        assert config["context_servers"]["test-server"]["args"] == [
            "-y",
            "@test/server",
        ]
        assert config["context_servers"]["test-server"]["env"]["API_KEY"] == "secret"

    def test_add_zed_server_existing_config(self, editor_manager, temp_config_dir):
        """Test adding a server to an existing Zed config."""
        config_path = temp_config_dir["zed"]

        # Create existing config
        existing_config = {
            "context_servers": {
                "existing-server": {"command": "python", "args": ["-m", "existing"]}
            },
            "other_setting": "value",
        }
        with open(config_path, "w") as f:
            json.dump(existing_config, f)

        # Add new server
        editor_manager.add_zed_server(
            server_name="new-server",
            command="node",
            args=["server.js"],
        )

        # Verify both servers exist and other settings preserved
        with open(config_path, "r") as f:
            config = json.load(f)

        assert len(config["context_servers"]) == 2
        assert "existing-server" in config["context_servers"]
        assert "new-server" in config["context_servers"]
        assert config["other_setting"] == "value"

    def test_add_claude_server_new_config(self, editor_manager, temp_config_dir):
        """Test adding a server to a new Claude Desktop config."""
        result = editor_manager.add_claude_server(
            server_name="test-server",
            command="npx",
            args=["-y", "@test/server"],
            env={"DATABASE_URL": "postgres://localhost"},
        )

        assert "Successfully added" in result
        assert "test-server" in result

        # Verify config file was created
        config_path = temp_config_dir["claude"]
        assert config_path.exists()

        # Verify content
        with open(config_path, "r") as f:
            config = json.load(f)

        assert "mcpServers" in config
        assert "test-server" in config["mcpServers"]
        assert config["mcpServers"]["test-server"]["command"] == "npx"
        assert config["mcpServers"]["test-server"]["args"] == ["-y", "@test/server"]
        assert (
            config["mcpServers"]["test-server"]["env"]["DATABASE_URL"]
            == "postgres://localhost"
        )

    def test_add_server_without_args_or_env(self, editor_manager, temp_config_dir):
        """Test adding a server with only command."""
        editor_manager.add_zed_server(
            server_name="simple-server",
            command="python",
        )

        config_path = temp_config_dir["zed"]
        with open(config_path, "r") as f:
            config = json.load(f)

        server_config = config["context_servers"]["simple-server"]
        assert server_config["command"] == "python"
        assert "args" not in server_config
        assert "env" not in server_config

    def test_remove_zed_server(self, editor_manager, temp_config_dir):
        """Test removing a server from Zed config."""
        # Add a server first
        editor_manager.add_zed_server(
            server_name="test-server",
            command="npx",
        )

        # Remove it
        result = editor_manager.remove_zed_server("test-server")
        assert "Successfully removed" in result

        # Verify it's gone
        config_path = temp_config_dir["zed"]
        with open(config_path, "r") as f:
            config = json.load(f)

        assert "test-server" not in config.get("context_servers", {})

    def test_remove_nonexistent_server(self, editor_manager, temp_config_dir):
        """Test removing a server that doesn't exist."""
        # Create empty config
        config_path = temp_config_dir["zed"]
        with open(config_path, "w") as f:
            json.dump({"context_servers": {}}, f)

        result = editor_manager.remove_zed_server("nonexistent")
        assert "not found" in result

    def test_remove_server_no_config_file(self, editor_manager, temp_config_dir):
        """Test removing a server when config file doesn't exist."""
        result = editor_manager.remove_zed_server("test-server")
        assert "not found" in result.lower()

    def test_remove_claude_server(self, editor_manager, temp_config_dir):
        """Test removing a server from Claude Desktop config."""
        # Add a server first
        editor_manager.add_claude_server(
            server_name="test-server",
            command="python",
        )

        # Remove it
        result = editor_manager.remove_claude_server("test-server")
        assert "Successfully removed" in result

        # Verify it's gone
        config_path = temp_config_dir["claude"]
        with open(config_path, "r") as f:
            config = json.load(f)

        assert "test-server" not in config.get("mcpServers", {})

    def test_list_configured_servers_zed(self, editor_manager, temp_config_dir):
        """Test listing configured servers for Zed."""
        # Add multiple servers
        editor_manager.add_zed_server("server1", "npx")
        editor_manager.add_zed_server("server2", "python")

        servers = editor_manager.list_configured_servers("zed")

        assert len(servers) == 2
        assert "server1" in servers
        assert "server2" in servers
        assert servers["server1"]["command"] == "npx"
        assert servers["server2"]["command"] == "python"

    def test_list_configured_servers_claude(self, editor_manager, temp_config_dir):
        """Test listing configured servers for Claude Desktop."""
        # Add multiple servers
        editor_manager.add_claude_server("server1", "node")
        editor_manager.add_claude_server("server2", "uvx")

        servers = editor_manager.list_configured_servers("claude")

        assert len(servers) == 2
        assert "server1" in servers
        assert "server2" in servers

    def test_list_configured_servers_empty(self, editor_manager, temp_config_dir):
        """Test listing servers when none are configured."""
        servers = editor_manager.list_configured_servers("zed")
        assert servers == {}

    def test_list_configured_servers_no_file(self, editor_manager, temp_config_dir):
        """Test listing servers when config file doesn't exist."""
        servers = editor_manager.list_configured_servers("zed")
        assert servers == {}

    def test_list_configured_servers_invalid_editor(
        self, editor_manager, temp_config_dir
    ):
        """Test listing servers with invalid editor name."""
        with pytest.raises(ValueError, match="Unsupported editor"):
            editor_manager.list_configured_servers("invalid")

    def test_backup_created(self, editor_manager, temp_config_dir):
        """Test that backup file is created when modifying config."""
        config_path = temp_config_dir["zed"]

        # Create initial config
        initial_config = {"context_servers": {"old": {"command": "old"}}}
        with open(config_path, "w") as f:
            json.dump(initial_config, f)

        # Add new server (should create backup)
        editor_manager.add_zed_server("new", "new")

        # Check backup exists
        backup_path = config_path.with_suffix(config_path.suffix + ".backup")
        assert backup_path.exists()

        # Verify backup contains original content
        with open(backup_path, "r") as f:
            backup_config = json.load(f)

        assert backup_config == initial_config

    def test_invalid_json_handling(self, editor_manager, temp_config_dir):
        """Test handling of invalid JSON in config file."""
        config_path = temp_config_dir["zed"]

        # Write invalid JSON
        with open(config_path, "w") as f:
            f.write("{invalid json")

        # Should raise ValueError
        with pytest.raises(ValueError, match="invalid JSON"):
            editor_manager.add_zed_server("test", "test")

    def test_config_formatting(self, editor_manager, temp_config_dir):
        """Test that saved config is properly formatted."""
        editor_manager.add_zed_server("test", "npx")

        config_path = temp_config_dir["zed"]
        content = config_path.read_text()

        # Should be indented and have trailing newline
        assert "  " in content  # Has indentation
        assert content.endswith("\n")  # Has trailing newline

        # Should be valid JSON
        json.loads(content)

    def test_overwrite_existing_server(self, editor_manager, temp_config_dir):
        """Test overwriting an existing server configuration."""
        # Add server with initial config
        editor_manager.add_zed_server(
            server_name="test",
            command="python",
            args=["-m", "old"],
        )

        # Overwrite with new config
        editor_manager.add_zed_server(
            server_name="test",
            command="node",
            args=["new.js"],
        )

        config_path = temp_config_dir["zed"]
        with open(config_path, "r") as f:
            config = json.load(f)

        # Should have new configuration
        assert config["context_servers"]["test"]["command"] == "node"
        assert config["context_servers"]["test"]["args"] == ["new.js"]


class TestConfigPaths:
    """Tests for config path detection."""

    def test_zed_config_path_detection(self):
        """Test Zed config path is reasonable."""
        path = EditorConfigManager.get_zed_config_path()
        assert isinstance(path, Path)
        assert "zed" in str(path).lower()
        assert path.name == "settings.json"

    def test_claude_config_path_detection(self):
        """Test Claude Desktop config path is reasonable."""
        path = EditorConfigManager.get_claude_config_path()
        assert isinstance(path, Path)
        assert "claude" in str(path).lower()
        assert "config.json" in path.name
