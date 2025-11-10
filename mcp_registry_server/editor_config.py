"""Editor configuration management for MCP server integration."""

import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EditorConfigManager:
    """Manages MCP server configuration for various editors."""

    @staticmethod
    def get_zed_config_path() -> Path:
        """Get the Zed editor config file path.

        Returns:
            Path to Zed's settings.json
        """
        # Linux/macOS: ~/.config/zed/settings.json
        # Windows: %APPDATA%\Zed\settings.json
        if Path.home().joinpath("AppData").exists():
            # Windows
            return Path.home() / "AppData" / "Roaming" / "Zed" / "settings.json"
        else:
            # Linux/macOS
            return Path.home() / ".config" / "zed" / "settings.json"

    @staticmethod
    def get_claude_config_path() -> Path:
        """Get the Claude Desktop config file path.

        Returns:
            Path to claude_desktop_config.json
        """
        # macOS/Linux: ~/Library/Application Support/Claude/claude_desktop_config.json
        # Windows: %APPDATA%\Claude\claude_desktop_config.json
        if Path.home().joinpath("AppData").exists():
            # Windows
            return (
                Path.home()
                / "AppData"
                / "Roaming"
                / "Claude"
                / "claude_desktop_config.json"
            )
        elif Path.home().joinpath("Library").exists():
            # macOS
            return (
                Path.home()
                / "Library"
                / "Application Support"
                / "Claude"
                / "claude_desktop_config.json"
            )
        else:
            # Linux (XDG config)
            config_home = Path.home() / ".config"
            return config_home / "Claude" / "claude_desktop_config.json"

    @staticmethod
    def _backup_config(config_path: Path) -> Path | None:
        """Create a backup of the config file.

        Args:
            config_path: Path to config file

        Returns:
            Path to backup file or None if backup failed
        """
        if not config_path.exists():
            return None

        backup_path = config_path.with_suffix(config_path.suffix + ".backup")
        try:
            shutil.copy2(config_path, backup_path)
            logger.info(f"Created config backup: {backup_path}")
            return backup_path
        except Exception as e:
            logger.warning(f"Failed to create backup: {e}")
            return None

    @staticmethod
    def _load_json_config(config_path: Path) -> dict[str, Any]:
        """Load JSON config file, creating if it doesn't exist.

        Args:
            config_path: Path to config file

        Returns:
            Loaded config dictionary
        """
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            return {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {config_path}: {e}")
            raise ValueError(f"Config file contains invalid JSON: {e}")
        except Exception as e:
            logger.error(f"Failed to load config from {config_path}: {e}")
            raise

    @staticmethod
    def _save_json_config(config_path: Path, config: dict[str, Any]) -> None:
        """Save JSON config file with pretty formatting.

        Args:
            config_path: Path to config file
            config: Config dictionary to save
        """
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.write("\n")  # Add trailing newline
            logger.info(f"Saved config to {config_path}")
        except Exception as e:
            logger.error(f"Failed to save config to {config_path}: {e}")
            raise

    def add_zed_server(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Add an MCP server to Zed's configuration.

        Args:
            server_name: Name of the MCP server
            command: Command to run the server
            args: Optional command arguments
            env: Optional environment variables

        Returns:
            Success message with config file location
        """
        config_path = self.get_zed_config_path()
        self._backup_config(config_path)

        config = self._load_json_config(config_path)

        # Zed uses a different structure than Claude Desktop
        # Format: { "context_servers": { "server-name": { "command": "...", "args": [...], "env": {...} } } }
        if "context_servers" not in config:
            config["context_servers"] = {}

        server_config: dict[str, Any] = {"command": command}
        if args:
            server_config["args"] = args
        if env:
            server_config["env"] = env

        config["context_servers"][server_name] = server_config
        self._save_json_config(config_path, config)

        return f"""Successfully added '{server_name}' to Zed configuration.

**Config file:** {config_path}
**Command:** {command}
**Args:** {args or []}

Restart Zed for changes to take effect.
"""

    def add_claude_server(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Add an MCP server to Claude Desktop's configuration.

        Args:
            server_name: Name of the MCP server
            command: Command to run the server
            args: Optional command arguments
            env: Optional environment variables

        Returns:
            Success message with config file location
        """
        config_path = self.get_claude_config_path()
        self._backup_config(config_path)

        config = self._load_json_config(config_path)

        # Claude Desktop format: { "mcpServers": { "server-name": { "command": "...", "args": [...], "env": {...} } } }
        if "mcpServers" not in config:
            config["mcpServers"] = {}

        server_config: dict[str, Any] = {"command": command}
        if args:
            server_config["args"] = args
        if env:
            server_config["env"] = env

        config["mcpServers"][server_name] = server_config
        self._save_json_config(config_path, config)

        return f"""Successfully added '{server_name}' to Claude Desktop configuration.

**Config file:** {config_path}
**Command:** {command}
**Args:** {args or []}

Restart Claude Desktop for changes to take effect.
"""

    def remove_zed_server(self, server_name: str) -> str:
        """Remove an MCP server from Zed's configuration.

        Args:
            server_name: Name of the server to remove

        Returns:
            Success message
        """
        config_path = self.get_zed_config_path()

        if not config_path.exists():
            return f"Zed config file not found: {config_path}"

        self._backup_config(config_path)
        config = self._load_json_config(config_path)

        if (
            "context_servers" not in config
            or server_name not in config["context_servers"]
        ):
            return f"Server '{server_name}' not found in Zed configuration"

        del config["context_servers"][server_name]
        self._save_json_config(config_path, config)

        return f"Successfully removed '{server_name}' from Zed configuration"

    def remove_claude_server(self, server_name: str) -> str:
        """Remove an MCP server from Claude Desktop's configuration.

        Args:
            server_name: Name of the server to remove

        Returns:
            Success message
        """
        config_path = self.get_claude_config_path()

        if not config_path.exists():
            return f"Claude Desktop config file not found: {config_path}"

        self._backup_config(config_path)
        config = self._load_json_config(config_path)

        if "mcpServers" not in config or server_name not in config["mcpServers"]:
            return f"Server '{server_name}' not found in Claude Desktop configuration"

        del config["mcpServers"][server_name]
        self._save_json_config(config_path, config)

        return f"Successfully removed '{server_name}' from Claude Desktop configuration"

    def list_configured_servers(self, editor: str) -> dict[str, Any]:
        """List all configured MCP servers for an editor.

        Args:
            editor: Editor name ("zed" or "claude")

        Returns:
            Dictionary of configured servers
        """
        if editor.lower() == "zed":
            config_path = self.get_zed_config_path()
            key = "context_servers"
        elif editor.lower() == "claude":
            config_path = self.get_claude_config_path()
            key = "mcpServers"
        else:
            raise ValueError(f"Unsupported editor: {editor}")

        if not config_path.exists():
            return {}

        config = self._load_json_config(config_path)
        return config.get(key, {})
