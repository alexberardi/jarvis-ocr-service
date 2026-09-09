"""The image must contain every file something actually runs.

This image is used by two containers: the API (its own CMD) and the sibling
worker, which compose starts with `python worker.py`. worker.py lives at the
repo root, and the Dockerfile only copied `app/`, so the worker crash-looped on

    python: can't open file '/app/worker.py': [Errno 2] No such file or directory

It went unnoticed because the worker container had never actually run -- the
image could not be pulled at all until the package was made public. Migrations
had the same problem: alembic/ was never copied either, so the service had no
schema management in-container.

Parsing the Dockerfile is a weak check compared to building the image, but it
runs in a second and catches the whole class: a runtime entry point that was
never shipped.
"""

import re
from pathlib import Path

import pytest

DOCKERFILE = Path(__file__).resolve().parent.parent / "Dockerfile"

# Paths something invokes at runtime, and who invokes them.
REQUIRED_AT_RUNTIME = [
    ("worker.py", "the jarvis-ocr-worker container runs `python worker.py`"),
    ("app/", "the API's CMD serves app.main:app"),
    ("alembic/", "the CMD runs `alembic upgrade head` before serving"),
    ("alembic.ini", "alembic needs its config to find the migration scripts"),
]


def copied_paths() -> set[str]:
    """Source paths named by COPY instructions, ignoring --from stages."""
    paths: set[str] = set()
    for line in DOCKERFILE.read_text().splitlines():
        line = line.strip()
        if not line.startswith("COPY "):
            continue
        args = re.sub(r"^COPY\s+(--\S+\s+)*", "", line).split()
        # Everything but the final argument (the destination) is a source.
        paths.update(args[:-1])
    return paths


def test_dockerfile_exists():
    assert DOCKERFILE.is_file()


@pytest.mark.parametrize("path,why", REQUIRED_AT_RUNTIME)
def test_runtime_path_is_copied_into_the_image(path, why):
    copied = copied_paths()
    normalized = {p.rstrip("/") for p in copied}
    assert path.rstrip("/") in normalized, (
        f"Dockerfile never copies {path!r}, but {why}. Copied: {sorted(copied)}"
    )


def test_every_required_path_exists_in_the_repo():
    """A COPY of a path that does not exist fails the build, not the container."""
    root = DOCKERFILE.parent
    for path, _ in REQUIRED_AT_RUNTIME:
        assert (root / path.rstrip("/")).exists(), f"{path} is missing from the repo"
