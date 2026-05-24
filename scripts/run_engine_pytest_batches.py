"""Run the engine pytest suite as deterministic file batches.

The engine suite is large enough that one monolithic pytest process can time
out before producing useful proof. This runner covers the pytest-configured
``engine/tests`` tree by sorted test file, runs bounded subprocess batches, and
prints a compact coverage/result summary without writing report artifacts.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=40,
        help="Number of test files per pytest subprocess.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        help="Timeout for each pytest subprocess batch.",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="Python executable to use. Defaults to engine/.venv/Scripts/python.exe when present.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List deterministic batches without running pytest.",
    )
    parser.add_argument(
        "--only-batch",
        type=int,
        default=None,
        help="Run or list only the 1-based batch index after deterministic batching.",
    )
    parser.add_argument(
        "--start-batch",
        type=int,
        default=None,
        help="Run or list from this 1-based batch index after deterministic batching.",
    )
    parser.add_argument(
        "--end-batch",
        type=int,
        default=None,
        help="Run or list through this 1-based batch index after deterministic batching.",
    )
    parser.add_argument(
        "--show-files",
        action="store_true",
        help="Print every file in each selected batch.",
    )
    return parser.parse_args()


def _discover_tests(engine_dir: Path) -> list[Path]:
    tests_dir = engine_dir / "tests"
    return sorted(
        (path.relative_to(engine_dir) for path in tests_dir.rglob("test_*.py")),
        key=lambda path: path.as_posix(),
    )


def _python_executable(engine_dir: Path, requested: str | None) -> str:
    if requested:
        return requested
    venv_python = engine_dir / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _tail(text: str | None, line_count: int = 18) -> str:
    if not text:
        return ""
    lines = text.strip().splitlines()
    return "\n".join(lines[-line_count:])


def main() -> int:
    args = _parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")

    repo_root = args.repo_root.resolve()
    engine_dir = repo_root / "engine"
    test_files = _discover_tests(engine_dir)
    if not test_files:
        raise SystemExit(f"No engine test files found under {engine_dir / 'tests'}")

    batch_count = math.ceil(len(test_files) / args.batch_size)
    python_exe = _python_executable(engine_dir, args.python)
    print(
        "engine pytest batch plan: "
        f"{len(test_files)} files, batch_size={args.batch_size}, batches={batch_count}"
    )
    print(f"engine cwd: {engine_dir}")
    print(f"python: {python_exe}")

    all_batches = [
        test_files[index : index + args.batch_size]
        for index in range(0, len(test_files), args.batch_size)
    ]
    indexed_batches = list(enumerate(all_batches, start=1))
    if args.only_batch is not None and (
        args.start_batch is not None or args.end_batch is not None
    ):
        raise SystemExit("--only-batch cannot be combined with --start-batch or --end-batch")
    if args.only_batch is not None:
        if args.only_batch < 1 or args.only_batch > batch_count:
            raise SystemExit(f"--only-batch must be between 1 and {batch_count}")
        indexed_batches = [indexed_batches[args.only_batch - 1]]
    else:
        start_batch = args.start_batch or 1
        end_batch = args.end_batch or batch_count
        if start_batch < 1 or end_batch > batch_count or start_batch > end_batch:
            raise SystemExit(f"batch range must be between 1 and {batch_count}")
        indexed_batches = indexed_batches[start_batch - 1 : end_batch]

    for index, batch in indexed_batches:
        first = batch[0].as_posix()
        last = batch[-1].as_posix()
        print(f"batch {index:02d}/{batch_count}: {len(batch)} files [{first} .. {last}]")
        if args.show_files:
            for path in batch:
                print(f"  {path.as_posix()}")

    if args.list_only:
        return 0

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONPATH"] = (
        "src"
        if not env.get("PYTHONPATH")
        else os.pathsep.join(["src", str(env["PYTHONPATH"])])
    )

    total_start = time.monotonic()
    summaries: list[tuple[int, int, float, str]] = []
    for index, batch in indexed_batches:
        command = [
            python_exe,
            "-m",
            "pytest",
            *(path.as_posix() for path in batch),
            "--no-cov",
            "-q",
            "-p",
            "no:cacheprovider",
            "--color=no",
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=engine_dir,
                env=env,
                text=True,
                capture_output=True,
                timeout=args.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            print(
                f"batch {index:02d}/{batch_count} TIMEOUT after {duration:.1f}s "
                f"(limit {args.timeout_seconds}s)"
            )
            tail = _tail("\n".join([stdout, stderr]))
            if tail:
                print(tail)
            return 124

        duration = time.monotonic() - started
        output_tail = _tail("\n".join([completed.stdout, completed.stderr]), line_count=8)
        status = "PASS" if completed.returncode == 0 else f"FAIL({completed.returncode})"
        summaries.append((index, len(batch), duration, status))
        print(f"batch {index:02d}/{batch_count} {status} in {duration:.1f}s")
        if output_tail:
            print(output_tail)
        if completed.returncode != 0:
            return completed.returncode

    total_duration = time.monotonic() - total_start
    print("engine pytest batch summary:")
    for index, file_count, duration, status in summaries:
        print(f"  batch {index:02d}: {status}, files={file_count}, duration={duration:.1f}s")
    selected_file_count = sum(len(batch) for _, batch in indexed_batches)
    print(
        f"engine pytest batched proof complete: {selected_file_count}/{len(test_files)} "
        f"selected files passed in {total_duration:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
