"""Podman container management for running MCP servers."""

import asyncio
import json
import logging
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ContainerInfo:
    """Information about a running container."""

    container_id: str
    name: str
    image: str
    status: str
    created_at: datetime
    environment: dict[str, str]


class PodmanRunner:
    """Manages Podman containers for MCP servers."""

    def __init__(self):
        """Initialize the Podman runner."""
        self._verify_podman_installed()
        self._running_containers: dict[str, ContainerInfo] = {}

    def _verify_podman_installed(self) -> None:
        """Verify that Podman is installed and accessible."""
        try:
            result = subprocess.run(
                ["podman", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            logger.info(f"Podman version: {result.stdout.strip()}")
        except FileNotFoundError:
            raise RuntimeError(
                "Podman not found. Please install Podman and ensure it's in PATH."
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Podman verification failed: {e}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Podman verification timed out")

    async def pull_image(self, image: str) -> bool:
        """Pull a container image if not present.

        Args:
            image: Image reference (e.g., docker.io/mcp/postgres)

        Returns:
            True if successful
        """
        logger.info(f"Pulling image: {image}")
        try:
            proc = await asyncio.create_subprocess_exec(
                "podman",
                "pull",
                image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                logger.info(f"Successfully pulled image: {image}")
                return True
            else:
                logger.error(f"Failed to pull image {image}: {stderr.decode()}")
                return False
        except Exception as e:
            logger.error(f"Exception pulling image {image}: {e}")
            return False

    async def run_container(
        self,
        image: str,
        name: str,
        environment: dict[str, str] | None = None,
        ports: dict[str, str] | None = None,
        volumes: dict[str, str] | None = None,
        command: list[str] | None = None,
    ) -> str | None:
        """Run a container with the specified configuration.

        Args:
            image: Container image to run
            name: Container name (used for identification)
            environment: Environment variables to set
            ports: Port mappings (host:container)
            volumes: Volume mappings (host:container)
            command: Command to run in container

        Returns:
            Container ID if successful, None otherwise
        """
        # Build podman run command
        cmd = [
            "podman",
            "run",
            "-d",  # Detached mode
            "--name",
            name,
            "--rm",  # Auto-remove on exit
        ]

        # Add environment variables
        if environment:
            for key, value in environment.items():
                cmd.extend(["-e", f"{key}={value}"])

        # Add port mappings
        if ports:
            for host_port, container_port in ports.items():
                cmd.extend(["-p", f"{host_port}:{container_port}"])

        # Add volume mounts (disabled by default for security)
        if volumes:
            logger.warning(
                f"Volume mounts requested for {name}, but currently disabled for security"
            )

        # Add image
        cmd.append(image)

        # Add command if specified
        if command:
            cmd.extend(command)

        logger.info(f"Starting container: {' '.join(shlex.quote(c) for c in cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                container_id = stdout.decode().strip()
                logger.info(f"Container started: {container_id[:12]} ({name})")

                # Store container info
                self._running_containers[container_id] = ContainerInfo(
                    container_id=container_id,
                    name=name,
                    image=image,
                    status="running",
                    created_at=datetime.utcnow(),
                    environment=environment or {},
                )

                return container_id
            else:
                logger.error(f"Failed to start container {name}: {stderr.decode()}")
                return None
        except Exception as e:
            logger.error(f"Exception starting container {name}: {e}")
            return None

    async def run_interactive_container(
        self,
        image: str,
        name: str,
        environment: dict[str, str] | None = None,
        command: list[str] | None = None,
    ) -> tuple[str | None, asyncio.subprocess.Process | None]:
        """Run a container in interactive mode with stdio communication.

        Args:
            image: Container image to run
            name: Container name (used for identification)
            environment: Environment variables to set
            command: Command to run in container

        Returns:
            Tuple of (container_id, process) if successful, (None, None) otherwise
        """
        # Build podman run command
        cmd = [
            "podman",
            "run",
            "-i",  # Interactive mode - keep stdin open
            "--name",
            name,
            "--rm",  # Auto-remove on exit
        ]

        # Add environment variables
        if environment:
            for key, value in environment.items():
                cmd.extend(["-e", f"{key}={value}"])

        # Add image
        cmd.append(image)

        # Add command if specified
        if command:
            cmd.extend(command)

        logger.info(
            f"Starting interactive container: {' '.join(shlex.quote(c) for c in cmd)}"
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Give container a moment to start
            await asyncio.sleep(0.5)

            # Generate a pseudo container ID (we can't get real ID easily in interactive mode)
            container_id = f"interactive-{name}"

            logger.info(f"Interactive container started: {name}")

            # Store container info with process reference
            self._running_containers[container_id] = ContainerInfo(
                container_id=container_id,
                name=name,
                image=image,
                status="running",
                created_at=datetime.utcnow(),
                environment=environment or {},
            )

            return container_id, proc

        except Exception as e:
            logger.error(f"Exception starting interactive container {name}: {e}")
            return None, None

    async def exec_in_container(
        self,
        container_id: str,
        command: list[str],
        stdin_data: str | None = None,
    ) -> tuple[str, str, int]:
        """Execute a command in a running container.

        Args:
            container_id: Container ID or name
            command: Command to execute
            stdin_data: Optional data to send to stdin

        Returns:
            Tuple of (stdout, stderr, returncode)
        """
        logger.info(f"Executing in container {container_id[:12]}: {' '.join(command)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                "podman",
                "exec",
                "-i",
                container_id,
                *command,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate(
                input=stdin_data.encode() if stdin_data else None
            )

            return (
                stdout.decode() if stdout else "",
                stderr.decode() if stderr else "",
                proc.returncode or 0,
            )

        except Exception as e:
            logger.error(f"Exception executing in container {container_id}: {e}")
            return "", str(e), -1

    async def stop_container(self, container_id: str, timeout: int = 10) -> bool:
        """Stop a running container gracefully.

        Args:
            container_id: Container ID or name
            timeout: Seconds to wait before killing

        Returns:
            True if successful
        """
        logger.info(f"Stopping container: {container_id[:12]}")
        try:
            proc = await asyncio.create_subprocess_exec(
                "podman",
                "stop",
                "-t",
                str(timeout),
                container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                logger.info(f"Container stopped: {container_id[:12]}")
                self._running_containers.pop(container_id, None)
                return True
            else:
                logger.error(
                    f"Failed to stop container {container_id[:12]}: {stderr.decode()}"
                )
                return False
        except Exception as e:
            logger.error(f"Exception stopping container {container_id[:12]}: {e}")
            return False

    async def kill_container(self, container_id: str) -> bool:
        """Forcefully kill a container.

        Args:
            container_id: Container ID or name

        Returns:
            True if successful
        """
        logger.warning(f"Killing container: {container_id[:12]}")
        try:
            proc = await asyncio.create_subprocess_exec(
                "podman",
                "kill",
                container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                logger.info(f"Container killed: {container_id[:12]}")
                self._running_containers.pop(container_id, None)
                return True
            else:
                logger.error(
                    f"Failed to kill container {container_id[:12]}: {stderr.decode()}"
                )
                return False
        except Exception as e:
            logger.error(f"Exception killing container {container_id[:12]}: {e}")
            return False

    async def inspect_container(self, container_id: str) -> dict[str, Any] | None:
        """Get detailed information about a container.

        Args:
            container_id: Container ID or name

        Returns:
            Container inspection data or None if not found
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "podman",
                "inspect",
                container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                data = json.loads(stdout.decode())
                return data[0] if data else None
            else:
                logger.error(
                    f"Failed to inspect container {container_id[:12]}: {stderr.decode()}"
                )
                return None
        except Exception as e:
            logger.error(f"Exception inspecting container {container_id[:12]}: {e}")
            return None

    async def list_containers(
        self, all_containers: bool = False
    ) -> list[dict[str, Any]]:
        """List running containers.

        Args:
            all_containers: Include stopped containers

        Returns:
            List of container information dictionaries
        """
        cmd = ["podman", "ps", "--format", "json"]
        if all_containers:
            cmd.append("-a")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                data = json.loads(stdout.decode())
                return data if isinstance(data, list) else []
            else:
                logger.error(f"Failed to list containers: {stderr.decode()}")
                return []
        except Exception as e:
            logger.error(f"Exception listing containers: {e}")
            return []

    async def get_container_logs(
        self, container_id: str, tail: int = 100
    ) -> str | None:
        """Get logs from a container.

        Args:
            container_id: Container ID or name
            tail: Number of lines to retrieve

        Returns:
            Container logs or None on error
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "podman",
                "logs",
                "--tail",
                str(tail),
                container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return stdout.decode()
            else:
                logger.error(
                    f"Failed to get logs for {container_id[:12]}: {stderr.decode()}"
                )
                return None
        except Exception as e:
            logger.error(f"Exception getting logs for {container_id[:12]}: {e}")
            return None

    async def exec_in_container(
        self, container_id: str, command: list[str]
    ) -> tuple[str, str, int] | None:
        """Execute a command in a running container.

        Args:
            container_id: Container ID or name
            command: Command and arguments to execute

        Returns:
            Tuple of (stdout, stderr, return_code) or None on error
        """
        cmd = ["podman", "exec", container_id] + command

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            return (stdout.decode(), stderr.decode(), proc.returncode)
        except Exception as e:
            logger.error(f"Exception executing command in {container_id[:12]}: {e}")
            return None

    async def cleanup_all(self) -> int:
        """Stop and remove all managed containers.

        Returns:
            Number of containers cleaned up
        """
        container_ids = list(self._running_containers.keys())
        cleaned = 0

        for container_id in container_ids:
            if await self.stop_container(container_id):
                cleaned += 1
            else:
                # Try force kill if graceful stop fails
                if await self.kill_container(container_id):
                    cleaned += 1

        logger.info(f"Cleaned up {cleaned} containers")
        return cleaned

    def get_running_containers(self) -> list[ContainerInfo]:
        """Get list of containers managed by this runner.

        Returns:
            List of container information
        """
        return list(self._running_containers.values())
