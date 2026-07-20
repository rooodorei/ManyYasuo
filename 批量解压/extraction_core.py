"""Filesystem rules shared by the extractor UI and its tests."""

import re
import shutil
from pathlib import Path


def parse_block_terms(value):
    """Split configurable terms; every returned term must match one filename."""
    return tuple(term.casefold() for term in re.split(r"[,，;；\s]+", value) if term)


def find_tag_marker(root, prefix):
    candidates = [
        path for path in root.rglob("*")
        if path.is_dir() and path.name.startswith(prefix) and len(path.name) > len(prefix)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda path: (len(path.relative_to(root).parts), path.name.casefold()))


def find_blocking_file(root, terms):
    """Match one filename containing every term, at depth one or two only."""
    first_level = list(root.iterdir())
    candidates = [path for path in first_level if path.is_file()]
    for directory in (path for path in first_level if path.is_dir()):
        candidates.extend(path for path in directory.iterdir() if path.is_file())
    for path in candidates:
        folded_name = path.name.casefold()
        if all(term in folded_name for term in terms):
            return path
    return None


def sanitize_name(value):
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value).strip().rstrip(".")
    if not value:
        value = "未命名"
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if value.upper() in reserved:
        value = f"_{value}"
    return value[:120]


def unique_destination(parent, name):
    candidate = parent / name
    index = 2
    while candidate.exists():
        candidate = parent / f"{name} ({index})"
        index += 1
    return candidate


def preserve_partial(staging, output_parent, archive_stem):
    if not staging.exists():
        return None
    try:
        if not any(staging.iterdir()):
            staging.rmdir()
            return None
        destination = unique_destination(output_parent, f"{sanitize_name(archive_stem)}_解压未完成")
        staging.rename(destination)
        return destination
    except OSError:
        return staging


def finalize_extraction(staging, output_parent, archive, options):
    entries = list(staging.iterdir())
    payload = entries[0] if len(entries) == 1 and entries[0].is_dir() else staging
    original_name = payload.name if payload != staging else archive.stem
    block_terms = parse_block_terms(options["block_terms"])
    blocker = find_blocking_file(payload, block_terms) if block_terms else None
    prefix = options["tag_prefix"]
    marker = find_tag_marker(payload, prefix) if prefix else None
    tag = marker.name[len(prefix):].strip() if marker else ""

    if blocker:
        final_name = original_name
        message = f"已解压 · 检测到“{blocker.name}”，保留原名"
    elif tag:
        final_name = sanitize_name(tag)
        message = f"已按标签改名为 {final_name}"
        try:
            marker.rmdir()  # Only remove an empty marker made by the compressor.
        except OSError:
            pass
    else:
        final_name = original_name
        message = "已解压 · 未找到有效标签，保留原名"

    destination = unique_destination(output_parent, sanitize_name(final_name))
    if payload == staging:
        staging.rename(destination)
    else:
        shutil.move(str(payload), str(destination))
        try:
            staging.rmdir()
        except OSError:
            pass
    return destination, message
