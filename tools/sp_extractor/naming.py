"""Naming conventions, output directory resolution, and path sanitization for sp_extractor."""

from __future__ import annotations

import re
from pathlib import Path


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Sanitize string for use as a filesystem file/folder name.

    Converts illegal characters and whitespace to underscores, matching the manual's safe() helper.
    Strips leading/trailing underscores and periods.
    """
    cleaned = re.sub(r'[^\w.-]+', "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._")
    if not cleaned:
        cleaned = "unnamed"
    return cleaned[:max_length]



def get_next_output_dir(base_dir: Path | str = ".", prefix: str = "DaneZeSkryptu") -> Path:
    """Find the next sequential output directory name (e.g. DaneZeSkryptu_001, DaneZeSkryptu_002).

    Scans base_dir for directories matching prefix_nnn.
    Returns the next Path with 3-digit zero-padded index (or wider if > 999).
    """
    target_base = Path(base_dir)
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$", re.IGNORECASE)

    highest_index = 0
    if target_base.exists() and target_base.is_dir():
        for entry in target_base.iterdir():
            if entry.is_dir():
                match = pattern.match(entry.name)
                if match:
                    highest_index = max(highest_index, int(match.group(1)))

    next_index = highest_index + 1
    return target_base / f"{prefix}_{next_index:03d}"


def resolve_output_dir(
    output: Path | str | None = None,
    base_dir: Path | str = ".",
    create: bool = True,
    prefix: str = "DaneZeSkryptu",
) -> Path:
    """Resolve output directory path and optionally create it.

    If output is provided, uses it directly.
    Otherwise, generates the next DaneZeSkryptu_nnn path.
    """
    if output:
        out_path = Path(output)
    else:
        out_path = get_next_output_dir(base_dir=base_dir, prefix=prefix)

    if create:
        out_path.mkdir(parents=True, exist_ok=True)

    return out_path
