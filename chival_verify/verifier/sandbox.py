"""
Execution sandboxes.

Two backends with one interface (`Sandbox.run`):

  DockerSandbox  — preferred. Runs pytest inside a throwaway python:3.12-slim
                   container with no network, capped memory/CPU, and a hard
                   timeout. The container is removed on exit (`--rm`); on
                   timeout it is force-killed.

  LocalSandbox   — fallback when the Docker daemon isn't available. Runs pytest
                   in a subprocess against a temp dir with a hard timeout and
                   process kill. Weaker isolation (no network/mem caps), but
                   keeps the pipeline working on any machine.

`get_sandbox()` auto-selects: Docker if reachable, else local. Override with
CHIVAL_SANDBOX=docker|local.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Machine-readable per-test results are written here inside the sandbox and read
# back out by the runner for mutation-strength scoring.
JUNIT_FILE = "report.xml"


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    backend: str
    artifacts: dict[str, str] = field(default_factory=dict)


class Sandbox(ABC):
    backend: str = "base"

    @abstractmethod
    def run(self, files: dict[str, str], timeout: float = 30.0) -> SandboxResult:
        """Write `files` (name -> content) into an isolated dir and run pytest."""
        raise NotImplementedError

    @staticmethod
    def _write_files(workdir: str, files: dict[str, str]) -> None:
        for name, content in files.items():
            path = os.path.join(workdir, name)
            os.makedirs(os.path.dirname(path) or workdir, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)

    @staticmethod
    def _read_artifacts(workdir: str, names: tuple[str, ...]) -> dict[str, str]:
        out: dict[str, str] = {}
        for name in names:
            path = os.path.join(workdir, name)
            try:
                with open(path, encoding="utf-8") as f:
                    out[name] = f.read()
            except OSError:
                pass  # missing artifact (e.g. collection crashed before write)
        return out


class LocalSandbox(Sandbox):
    backend = "local"

    # pytest args shared by both backends; junitxml gives per-test results.
    PYTEST_ARGS = ["-q", "-p", "no:cacheprovider", "--no-header", f"--junitxml={JUNIT_FILE}"]

    def run(self, files: dict[str, str], timeout: float = 30.0) -> SandboxResult:
        workdir = tempfile.mkdtemp(prefix="chival_")
        try:
            self._write_files(workdir, files)
            cmd = [sys.executable, "-m", "pytest", *self.PYTEST_ARGS]
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    # pytest output can contain non-UTF-8 bytes; on Windows the
                    # default locale (cp1252) raises UnicodeDecodeError. Force
                    # UTF-8 with replacement so capture never crashes a worker.
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    # Don't inherit the parent's env tweaks that could leak state.
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                return SandboxResult(
                    returncode=proc.returncode,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    timed_out=False,
                    backend=self.backend,
                    artifacts=self._read_artifacts(workdir, (JUNIT_FILE,)),
                )
            except subprocess.TimeoutExpired as e:
                return SandboxResult(
                    returncode=-1,
                    stdout=e.stdout or "" if isinstance(e.stdout, str) else "",
                    stderr=f"TIMEOUT after {timeout}s (likely infinite loop)",
                    timed_out=True,
                    backend=self.backend,
                )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


class DockerSandbox(Sandbox):
    backend = "docker"

    def __init__(self, image: str | None = None):
        self.image = image or os.getenv("CHIVAL_IMAGE", "python:3.12-slim")

    def run(self, files: dict[str, str], timeout: float = 30.0) -> SandboxResult:
        workdir = tempfile.mkdtemp(prefix="chival_")
        try:
            self._write_files(workdir, files)
            # Ensure pytest exists, then run it. Network stays off for the test
            # run; we only allow the brief pip install if pytest is missing.
            # If pytest is missing and the network is off, pip install can't help —
            # emit a loud marker instead of silently producing "0 tests passed".
            inner = (
                "if ! python -m pytest --version >/dev/null 2>&1; then "
                "pip install -q pytest >/dev/null 2>&1 || "
                "{ echo CHIVAL_NO_PYTEST 1>&2; exit 99; }; fi; "
                f"python -m pytest -q -p no:cacheprovider --no-header --junitxml=/work/{JUNIT_FILE}"
            )
            cmd = [
                "docker", "run", "--rm",
                "--network", "none",
                "--memory", "256m",
                "--cpus", "1",
                "--pids-limit", "128",
                "-v", f"{workdir}:/work",
                "-w", "/work",
                self.image,
                "sh", "-c", inner,
            ]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout + 15,
                )
                if "CHIVAL_NO_PYTEST" in proc.stderr:
                    raise RuntimeError(
                        f"Sandbox image '{self.image}' lacks pytest and the network "
                        "is disabled. Build the sandbox image and point to it:\n"
                        "  docker build -f Dockerfile.sandbox -t chival-sandbox .\n"
                        "  set CHIVAL_IMAGE=chival-sandbox   (PowerShell: $env:CHIVAL_IMAGE=...)"
                    )
                return SandboxResult(
                    returncode=proc.returncode,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    timed_out=False,
                    backend=self.backend,
                    artifacts=self._read_artifacts(workdir, (JUNIT_FILE,)),
                )
            except subprocess.TimeoutExpired:
                # --rm cleans the container once docker run is killed.
                return SandboxResult(
                    returncode=-1,
                    stdout="",
                    stderr=f"TIMEOUT after {timeout}s (container killed)",
                    timed_out=True,
                    backend=self.backend,
                )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def docker_available() -> bool:
    """True if the Docker CLI is installed AND the daemon is reachable."""
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def get_sandbox(prefer: str | None = None) -> Sandbox:
    """
    Select a backend. `prefer` / CHIVAL_SANDBOX may force docker|local.
    Auto mode uses Docker when the daemon is reachable, else local.
    """
    prefer = (prefer or os.getenv("CHIVAL_SANDBOX") or "auto").lower()
    if prefer == "docker":
        return DockerSandbox()
    if prefer == "local":
        return LocalSandbox()
    return DockerSandbox() if docker_available() else LocalSandbox()
