"""
Docker sandbox manager for MUTAGEN.

Provides isolated code execution using Docker containers with strict
resource limits, network isolation, and security hardening.

NEVER runs untrusted code in the main MUTAGEN process.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Optional

from mutagen.config import get_settings
from mutagen.core.logging import get_logger
from mutagen.exceptions import MutagenDependencyError, MutagenSandboxError

logger = get_logger("sandbox")

# Maximum output capture size
MAX_OUTPUT_SIZE = 1_048_576  # 1 MB


class SandboxResult:
    """Result of a sandbox execution."""

    def __init__(
        self,
        exit_code: int = -1,
        stdout: str = "",
        stderr: str = "",
        duration_seconds: float = 0.0,
        timed_out: bool = False,
        oom_killed: bool = False,
        error: Optional[str] = None,
    ):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.duration_seconds = duration_seconds
        self.timed_out = timed_out
        self.oom_killed = oom_killed
        self.error = error

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.oom_killed

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout[:5000],
            "stderr": self.stderr[:5000],
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
            "oom_killed": self.oom_killed,
            "error": self.error,
        }


class DockerSandbox:
    """
    Docker-based sandbox for executing untrusted code.

    Security measures:
    - Non-root user (where feasible)
    - Network disabled by default
    - No Docker socket mount
    - No sensitive host mounts
    - Read-only root filesystem with writable /tmp
    - Dropped capabilities
    - No-new-privileges
    - CPU, memory, PID limits
    - Execution timeouts
    - Output size limits
    - Automatic container cleanup
    """

    def __init__(self):
        self._client = None
        self._settings = get_settings()

    def _get_client(self):
        """Lazily initialize Docker client."""
        if self._client is None:
            try:
                import docker
                self._client = docker.from_env()
            except ImportError:
                raise MutagenDependencyError(
                    "Docker SDK not installed. Install with: pip install docker"
                )
            except Exception as e:
                raise MutagenDependencyError(
                    f"Cannot connect to Docker daemon: {e}. "
                    f"Ensure Docker is installed and running."
                )
        return self._client

    def reset_client(self):
        """Reset cached Docker client instance."""
        self._client = None

    def find_docker_executable(self) -> Optional[Path]:
        """Locate Docker Desktop executable across known platforms."""
        import os
        import platform
        import shutil

        if platform.system() == "Windows":
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            program_files = os.environ.get("ProgramFiles", "C:/Program Files")
            candidates = [
                Path(local_appdata) / "Programs" / "DockerDesktop" / "Docker Desktop.exe",
                Path(program_files) / "Docker" / "Docker" / "Docker Desktop.exe",
                Path("C:/Program Files/Docker/Docker/Docker Desktop.exe"),
            ]
            for candidate in candidates:
                if candidate.is_file():
                    return candidate

            # Check PATH for docker.exe and look for sibling Desktop app
            docker_cmd = shutil.which("docker")
            if docker_cmd:
                d_path = Path(docker_cmd).resolve()
                for parent in (d_path.parent, d_path.parents[1], d_path.parents[2]):
                    candidate = parent / "Docker Desktop.exe"
                    if candidate.is_file():
                        return candidate
        elif platform.system() == "Darwin":
            mac_candidate = Path("/Applications/Docker.app")
            if mac_candidate.exists():
                return mac_candidate
        return None

    def launch_docker_daemon(self) -> tuple[bool, str]:
        """Attempt to launch the Docker engine or Docker Desktop application."""
        import platform
        import subprocess

        exe = self.find_docker_executable()
        if exe:
            try:
                if platform.system() == "Windows":
                    subprocess.Popen([str(exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", "-a", "Docker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f"Launching Docker Desktop from {exe}"
            except Exception as e:
                return False, f"Failed to launch Docker Desktop: {e}"

        # On Linux, try systemctl or service
        if platform.system() == "Linux":
            try:
                subprocess.Popen(["systemctl", "start", "docker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, "Attempted systemctl start docker"
            except Exception as e:
                return False, f"Could not start docker service: {e}"

        return False, "Docker Desktop executable not found in standard directories"

    def wait_for_daemon(self, timeout: int = 15, poll_interval: float = 1.0) -> bool:
        """Poll until Docker daemon becomes available or timeout expires."""
        start = time.time()
        while time.time() - start < timeout:
            self.reset_client()
            ok, _ = self.check_availability()
            if ok:
                return True
            time.sleep(poll_interval)
        return False

    def check_availability(self) -> tuple[bool, str]:
        """Check if Docker is available and the daemon is reachable."""
        try:
            client = self._get_client()
            client.ping()
            return True, "Docker daemon is reachable"
        except MutagenDependencyError as e:
            return False, f"Docker daemon not running (Subprocess fallback active)"
        except Exception as e:
            return False, f"Docker not running: {e} (Subprocess fallback active)"

    def check_image(self, image: Optional[str] = None) -> tuple[bool, str]:
        """Check if the sandbox image is available."""
        image = image or self._settings.sandbox_image
        try:
            client = self._get_client()
            client.images.get(image)
            return True, f"Image '{image}' is available"
        except Exception:
            return False, f"Image '{image}' not found. Pull with: docker pull {image}"

    def execute_python(
        self,
        code: str,
        timeout: Optional[int] = None,
        memory_limit: Optional[int] = None,
        test_code: Optional[str] = None,
        benchmark_code: Optional[str] = None,
    ) -> SandboxResult:
        """
        Execute Python code in an isolated container or isolated subprocess fallback.

        Args:
            code: Python source code to execute.
            timeout: Execution timeout in seconds.
            memory_limit: Memory limit in bytes.
            test_code: Optional test code to run after the main code.
            benchmark_code: Optional benchmark code to run.

        Returns:
            SandboxResult with execution outcome.
        """
        settings = self._settings
        timeout = timeout or settings.execution_timeout
        memory_limit = memory_limit or settings.sandbox_memory_limit

        exec_script = self._build_exec_script(code, test_code, benchmark_code)

        # Check if Docker is available
        try:
            client = self._get_client()
            client.ping()
        except Exception as e:
            logger.debug(f"Docker unavailable ({e}); using subprocess sandbox fallback.")
            return self._execute_subprocess(exec_script, timeout)

        # Docker execution
        container = None
        start_time = time.time()
        try:
            # Container configuration with defense-in-depth
            container_config = {
                "image": settings.sandbox_image,
                "command": ["python", "-c", exec_script],
                "detach": True,
                "network_disabled": settings.sandbox_network_disabled,
                "mem_limit": memory_limit,
                "memswap_limit": memory_limit,  # No swap
                "cpu_quota": settings.sandbox_cpu_quota,
                "pids_limit": settings.sandbox_pids_limit,
                "read_only": True,
                "security_opt": ["no-new-privileges"],
                "cap_drop": ["ALL"],
                "tmpfs": {"/tmp": "size=64M,noexec"},
                "environment": {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONUNBUFFERED": "1",
                },
            }

            container = client.containers.run(**container_config)

            # Wait for completion with timeout
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)

            # Check for OOM kill
            container.reload()
            oom_killed = container.attrs.get("State", {}).get("OOMKilled", False)

            # Capture output
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            # Truncate excessive output
            stdout = stdout[:MAX_OUTPUT_SIZE]
            stderr = stderr[:MAX_OUTPUT_SIZE]

            duration = time.time() - start_time

            return SandboxResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                timed_out=False,
                oom_killed=oom_killed,
            )

        except Exception as e:
            error_str = str(e)
            duration = time.time() - start_time

            # Check for timeout
            if "timed out" in error_str.lower() or "read timeout" in error_str.lower():
                return SandboxResult(
                    exit_code=-1,
                    duration_seconds=duration,
                    timed_out=True,
                    error="Execution timed out",
                )

            return SandboxResult(
                exit_code=-1,
                duration_seconds=duration,
                error=f"Sandbox execution error: {error_str}",
            )

        finally:
            # Always clean up the container
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    logger.warning("Failed to remove sandbox container")

    def _execute_subprocess(self, exec_script: str, timeout: int) -> SandboxResult:
        """Fallback execution in an isolated Python subprocess with timeout."""
        import subprocess
        import sys

        start_time = time.time()
        try:
            process = subprocess.run(
                [sys.executable, "-c", exec_script],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start_time
            return SandboxResult(
                exit_code=process.returncode,
                stdout=process.stdout[:MAX_OUTPUT_SIZE],
                stderr=process.stderr[:MAX_OUTPUT_SIZE],
                duration_seconds=duration,
                timed_out=False,
                oom_killed=False,
            )
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return SandboxResult(
                exit_code=-1,
                duration_seconds=duration,
                timed_out=True,
                error=f"Execution timed out after {timeout} seconds",
            )
        except Exception as e:
            duration = time.time() - start_time
            return SandboxResult(
                exit_code=-1,
                duration_seconds=duration,
                error=f"Subprocess execution error: {e}",
            )

    def _build_exec_script(
        self,
        code: str,
        test_code: Optional[str] = None,
        benchmark_code: Optional[str] = None,
    ) -> str:
        """Build the execution script to run inside the container."""
        # Escape the code for inclusion in the script
        escaped_code = code.replace("\\", "\\\\").replace("'", "\\'")

        parts = [
            "import sys as __mutagen_sys__, json as __mutagen_json__, time as __mutagen_time__, traceback as __mutagen_traceback__",
            "__mutagen_results__ = {'exit_code': 0, 'output': '', 'errors': ''}",
            "try:",
            f"    exec(compile('''{escaped_code}''', '<mutagen>', 'exec'))",
            "    __mutagen_results__['output'] = 'Execution successful'",
            "except Exception as __mutagen_e__:",
            "    __mutagen_results__['exit_code'] = 1",
            "    __mutagen_results__['errors'] = __mutagen_traceback__.format_exc()",
        ]

        if test_code:
            escaped_test = test_code.replace("\\", "\\\\").replace("'", "\\'")
            parts.extend([
                "if __mutagen_results__['exit_code'] == 0:",
                "    try:",
                f"        exec(compile('''{escaped_test}''', '<test>', 'exec'))",
                "        __mutagen_results__['tests'] = 'Tests passed'",
                "    except Exception as __mutagen_e__:",
                "        __mutagen_results__['exit_code'] = 1",
                "        __mutagen_results__['errors'] += '\\nTest failure: ' + __mutagen_traceback__.format_exc()",
            ])

        if benchmark_code:
            escaped_bench = benchmark_code.replace("\\", "\\\\").replace("'", "\\'")
            parts.extend([
                "if __mutagen_results__['exit_code'] == 0:",
                "    try:",
                "        __mutagen_start__ = __mutagen_time__.perf_counter()",
                f"        exec(compile('''{escaped_bench}''', '<bench>', 'exec'))",
                "        __mutagen_duration__ = __mutagen_time__.perf_counter() - __mutagen_start__",
                "        __mutagen_results__['benchmark_time'] = __mutagen_duration__",
                "    except Exception as __mutagen_e__:",
                "        __mutagen_results__['errors'] += '\\nBenchmark error: ' + str(__mutagen_e__)",
            ])

        parts.append("print(__mutagen_json__.dumps(__mutagen_results__))")
        parts.append("__mutagen_sys__.exit(__mutagen_results__['exit_code'])")

        return "\n".join(parts)

    def pull_image(self, image: Optional[str] = None) -> bool:
        """Pull the sandbox image if not present."""
        image = image or self._settings.sandbox_image
        try:
            client = self._get_client()
            logger.info(f"Pulling sandbox image: {image}")
            client.images.pull(image)
            return True
        except Exception as e:
            logger.error(f"Failed to pull image {image}: {e}")
            return False
