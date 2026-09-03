"""Local developer checks for Deutsch-Bot.

This is the single entry point used by both humans and CI (see
``.github/workflows/ci.yml``).  It runs:

  1. ``pytest -q``                              -- the unit / regression tests
  2. ``python -m compileall -q <project root>`` -- bytecode-compile every
     ``.py`` file under the project root, catching syntax errors that the
     test suite might not hit (e.g. on a code path that is only reachable
     in production).

Design constraints:

  * **No new dependencies** -- stdlib only (``subprocess``, ``sys``,
    ``pathlib``, ``time``, ``platform``).
  * **Cross-platform** -- resolves the project root via ``pathlib``,
    runs the embedded interpreter via ``sys.executable`` (never a bare
    ``python`` string), and shells out with ``shell=False`` so the same
    command works on Windows, macOS and Linux.
  * **Never raises** -- every failure path prints a clear message and
    returns a non-zero exit code; the script will not crash with a
    traceback if ``pytest`` is missing or the tree is half-built.
  * **Reproducible** -- sets ``PYTHONPATH`` to the project root so the
    test suite can import the top-level modules (e.g. ``bot``,
    ``config``) regardless of how the script is invoked.

Usage::

    python scripts/run_checks.py

Exit code:
    0  all checks passed
    1  at least one check failed
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

# ``scripts/run_checks.py`` lives at <root>/scripts/run_checks.py, so the
# project root is the parent of the ``scripts/`` directory.
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent

# Directories we want to skip when bytecode-compiling.  ``.venv`` /
# ``.pytest_cache`` are third-party / test-runner artefacts; ``__pycache__``
# is regenerated and ``scripts`` itself is allowed (this file lives there).
SKIP_DIR_NAMES = {
    ".venv",
    "venv",
    ".pytest_cache",
    "__pycache__",
    ".git",
    "node_modules",
    "audio_cache",
}


# ---------------------------------------------------------------------------
# Step runner
# ---------------------------------------------------------------------------


def _run_step(
    label: str,
    cmd: Sequence[str],
    *,
    cwd: Path,
    extra_env: Optional[dict] = None,
) -> Tuple[bool, float, str]:
    """Run a single check step and return ``(passed, elapsed_seconds, summary)``.

    ``summary`` is a one-line human-readable description of the outcome,
    suitable for the final PASS/FAIL table.
    """

    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print("$", " ".join(str(c) for c in cmd))
    started = time.monotonic()
    try:
        env = None
        if extra_env:
            import os  # local import: only used when extra_env is set
            env = {**os.environ, **extra_env}

        completed = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            env=env,
            shell=False,  # cross-platform: never use the shell
        )
    except FileNotFoundError as exc:
        elapsed = time.monotonic() - started
        return False, elapsed, f"executable not found: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        elapsed = time.monotonic() - started
        return False, elapsed, f"unexpected error: {exc!r}"

    elapsed = time.monotonic() - started
    if completed.returncode == 0:
        return True, elapsed, "ok"
    return False, elapsed, f"exit code {completed.returncode}"


def _python_cmd(extra_args: Sequence[str]) -> List[str]:
    """Build a ``[sys.executable, ...]`` command.  Never bare ``python``."""

    return [sys.executable, *extra_args]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_pytest() -> Tuple[bool, float, str]:
    """Run the test suite quietly.

    We pass ``-p no:cacheprovider`` so the run is independent of any
    pre-existing ``.pytest_cache`` (useful in CI), and ``--no-header``
    to keep the output compact.
    """

    cmd = _python_cmd(
        [
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-header",
        ]
    )
    return _run_step(
        "[1/2] pytest",
        cmd,
        cwd=PROJECT_ROOT,
        extra_env={"PYTHONPATH": str(PROJECT_ROOT)},
    )


def check_compileall() -> Tuple[bool, float, str]:
    """Bytecode-compile every ``.py`` file under the project root.

    We feed ``compileall`` an explicit list of source directories so we
    don't waste time on ``.venv`` / ``.git`` / caches, and we pass
    ``-q`` so a clean run is silent.
    """

    sources = _collect_python_sources()
    if not sources:
        return True, 0.0, "no .py files"

    cmd = _python_cmd(["-m", "compileall", "-q", *sources])
    return _run_step(
        f"[2/2] compileall ({len(sources)} dirs)",
        cmd,
        cwd=PROJECT_ROOT,
    )


def _collect_python_sources() -> List[str]:
    """Return the project-root subdirectories that contain ``.py`` files.

    Excludes virtualenvs, caches and VCS metadata via
    :data:`SKIP_DIR_NAMES`.  Returns absolute paths as strings so they
    can be joined directly into the ``compileall`` command line.
    """

    sources: List[str] = []
    for child in sorted(PROJECT_ROOT.iterdir()):
        if not child.is_dir():
            continue
        if child.name in SKIP_DIR_NAMES:
            continue
        if child.name.startswith("."):
            continue
        # Only include directories that actually contain Python files.
        if any(child.rglob("*.py")):
            sources.append(str(child))
    return sources


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _print_summary(
    results: List[Tuple[str, bool, float, str]]
) -> None:
    """Render the final PASS / FAIL table and a short environment header."""

    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)

    name_w = max(len(label) for label, *_ in results)
    for label, passed, elapsed, summary in results:
        status = "PASS" if passed else "FAIL"
        marker = "\u2705" if passed else "\u274c"
        print(
            f"  {marker} {label.ljust(name_w)}  "
            f"{status}  {elapsed:5.2f}s  {summary}"
        )

    overall = all(passed for _, passed, *_ in results)
    print("-" * 70)
    print(
        f"  Python: {platform.python_version()}  "
        f"({platform.system()} {platform.release()})"
    )
    print(f"  Root:   {PROJECT_ROOT}")
    print("-" * 70)
    if overall:
        print("  \u2705 ALL CHECKS PASSED")
    else:
        print("  \u274c SOME CHECKS FAILED \u2014 see output above")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_checks",
        description="Run Deutsch-Bot's local developer checks (pytest + "
        "compileall) and print a PASS/FAIL summary.",
    )
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Skip the pytest step (useful when iterating on compile-only "
        "changes or when pytest is not yet installed).",
    )
    parser.add_argument(
        "--skip-compileall",
        action="store_true",
        help="Skip the compileall step.",
    )
    args = parser.parse_args(argv)

    print("=" * 70)
    print("Deutsch-Bot \u2014 local checks")
    print("=" * 70)
    print(f"  Python: {platform.python_version()}")
    print(f"  System: {platform.system()} {platform.release()}")
    print(f"  Root:   {PROJECT_ROOT}")

    results: List[Tuple[str, bool, float, str]] = []

    if args.skip_pytest:
        results.append(("pytest", True, 0.0, "skipped (--skip-pytest)"))
    else:
        results.append(("pytest", *check_pytest()))

    if args.skip_compileall:
        results.append(
            ("compileall", True, 0.0, "skipped (--skip-compileall)")
        )
    else:
        results.append(("compileall", *check_compileall()))

    _print_summary(results)

    return 0 if all(passed for _, passed, *_ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
