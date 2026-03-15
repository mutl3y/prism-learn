"""Batch helper utilities for the learning-loop scaffold."""

from __future__ import annotations

from pathlib import Path

from .reporting import fetch_fresh_targets


def load_repo_urls(repo_urls: list[str], repo_url_file: str | None) -> list[str]:
    """Merge CLI-provided repository URLs with file-based inputs."""
    merged = list(repo_urls)

    if repo_url_file:
        path = Path(repo_url_file).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"repo URL file not found: {repo_url_file}")

        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            merged.append(stripped)

    deduped: list[str] = []
    seen: set[str] = set()
    for url in merged:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def split_fresh_repo_urls(
    dsn: str,
    repo_urls: list[str],
    *,
    skip_if_fresh_days: int,
    force_rescan: bool,
) -> tuple[list[str], list[dict[str, str]]]:
    """Partition repo URLs into stale targets to scan and fresh targets to skip."""
    if force_rescan or skip_if_fresh_days <= 0 or not repo_urls:
        return repo_urls, []

    fresh_rows = fetch_fresh_targets(
        dsn,
        target_type="repo_url",
        targets=repo_urls,
        max_age_days=skip_if_fresh_days,
    )
    if not fresh_rows:
        return repo_urls, []

    fresh_targets = {str(row["target"]) for row in fresh_rows}
    filtered = [url for url in repo_urls if url not in fresh_targets]
    return filtered, fresh_rows
