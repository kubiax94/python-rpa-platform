from __future__ import annotations

import json
import os
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


SECTION_ORDER = ["Frontend", "Backend", "Agent", "Shared", "Infra", "Other"]
SCOPE_TO_SECTION = {
    "frontend": "Frontend",
    "ui": "Frontend",
    "web": "Frontend",
    "backend": "Backend",
    "server": "Backend",
    "api": "Backend",
    "agent": "Agent",
    "vm_agent": "Agent",
    "shared": "Shared",
    "infra": "Infra",
    "ci": "Infra",
    "build": "Infra",
    "release": "Infra",
    "docker": "Infra",
}
PATH_PREFIX_TO_SECTION = OrderedDict(
    {
        "frontend/": "Frontend",
        "vm_agent_server/": "Backend",
        "vm_agent/": "Agent",
        "shared/": "Shared",
        ".github/": "Infra",
        "docker/": "Infra",
        "docs/": "Other",
    }
)
FILE_TO_SECTION = {
    "agent_service.spec": "Agent",
    "docker-compose.yml": "Infra",
    "pyproject.toml": "Infra",
    "README.md": "Other",
}
IGNORED_SUBJECT_PREFIXES = (
    "merge pull request",
    "merge branch",
    "chore(main): release ",
)
CONVENTIONAL_SCOPE_RE = re.compile(r"^[a-z]+\(([^)]+)\):\s+(.+)$", re.IGNORECASE)


@dataclass
class CommitEntry:
    sha: str
    subject: str
    url: str
    section: str


def _github_request(url: str, token: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "python-rpa-platform-release-notes",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_scope(scope: str) -> str:
    return scope.strip().lower().replace("-", "_")


def _classify_from_scope(subject: str) -> str | None:
    match = CONVENTIONAL_SCOPE_RE.match(subject.strip())
    if not match:
        return None
    normalized_scope = _normalize_scope(match.group(1))
    return SCOPE_TO_SECTION.get(normalized_scope)


def _classify_from_files(files: list[dict[str, Any]]) -> str:
    scores = {section: 0 for section in SECTION_ORDER}
    for file_entry in files:
        filename = str(file_entry.get("filename") or "")
        if not filename:
            continue
        direct = FILE_TO_SECTION.get(filename)
        if direct:
            scores[direct] += 3
            continue
        matched = False
        for prefix, section in PATH_PREFIX_TO_SECTION.items():
            if filename.startswith(prefix):
                scores[section] += 2
                matched = True
                break
        if not matched:
            scores["Other"] += 1
    best_section = max(scores.items(), key=lambda item: item[1])[0]
    return best_section if scores[best_section] > 0 else "Other"


def _release_body(tag_name: str, compare_url: str, commits: list[CommitEntry]) -> str:
    grouped: dict[str, list[CommitEntry]] = {section: [] for section in SECTION_ORDER}
    for commit in commits:
        grouped[commit.section].append(commit)

    lines = [f"## What changed in {tag_name}", ""]
    for section in SECTION_ORDER:
        entries = grouped[section]
        if not entries:
            continue
        lines.append(f"### {section} changelog")
        lines.append("")
        for entry in entries:
            lines.append(f"- {entry.subject} ([{entry.sha[:7]}]({entry.url}))")
        lines.append("")

    lines.append(f"Full diff: {compare_url}")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    tag_name = os.getenv("RELEASE_TAG_NAME", "").strip()

    if not token or not repository or not tag_name:
        print("Missing GITHUB_TOKEN, GITHUB_REPOSITORY, or RELEASE_TAG_NAME", file=sys.stderr)
        return 1

    owner_repo = repository
    api_base = f"https://api.github.com/repos/{owner_repo}"

    releases = _github_request(f"{api_base}/releases?per_page=20", token)
    if not isinstance(releases, list):
        print("Unexpected releases payload", file=sys.stderr)
        return 1

    current_release = next((item for item in releases if str(item.get("tag_name") or "").strip() == tag_name), None)
    if not current_release:
        print(f"Release {tag_name} not found", file=sys.stderr)
        return 1

    current_index = releases.index(current_release)
    previous_release = next(
        (
            item
            for item in releases[current_index + 1 :]
            if not bool(item.get("draft")) and str(item.get("tag_name") or "").strip()
        ),
        None,
    )

    if previous_release is None:
        print("No previous release found, leaving release notes unchanged")
        return 0

    previous_tag = str(previous_release.get("tag_name") or "").strip()
    compare = _github_request(f"{api_base}/compare/{quote(previous_tag)}...{quote(tag_name)}", token)
    commits_payload = compare.get("commits") if isinstance(compare, dict) else None
    if not isinstance(commits_payload, list):
        print("Unexpected compare payload", file=sys.stderr)
        return 1

    commits: list[CommitEntry] = []
    for raw_commit in commits_payload:
        sha = str(raw_commit.get("sha") or "").strip()
        message = str((((raw_commit.get("commit") or {}).get("message")) or "")).strip()
        subject = message.splitlines()[0].strip()
        if not sha or not subject:
            continue
        lowered = subject.lower()
        if any(lowered.startswith(prefix) for prefix in IGNORED_SUBJECT_PREFIXES):
            continue

        section = _classify_from_scope(subject)
        if section is None:
            commit_detail = _github_request(f"{api_base}/commits/{quote(sha)}", token)
            files = commit_detail.get("files") if isinstance(commit_detail, dict) else []
            section = _classify_from_files(files if isinstance(files, list) else [])

        commits.append(
            CommitEntry(
                sha=sha,
                subject=subject,
                url=str(raw_commit.get("html_url") or f"https://github.com/{owner_repo}/commit/{sha}"),
                section=section,
            )
        )

    if not commits:
        print("No relevant commits found, leaving release notes unchanged")
        return 0

    compare_url = str(compare.get("html_url") or f"https://github.com/{owner_repo}/compare/{previous_tag}...{tag_name}")
    body = _release_body(tag_name, compare_url, commits)

    release_id = current_release.get("id")
    if not release_id:
        print("Current release has no id", file=sys.stderr)
        return 1

    payload = json.dumps({"body": body}).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "python-rpa-platform-release-notes",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    request = Request(f"{api_base}/releases/{release_id}", data=payload, headers=headers, method="PATCH")
    try:
        with urlopen(request, timeout=30):
            pass
    except HTTPError as exc:
        print(f"Failed to update release notes: {exc.read().decode('utf-8', errors='ignore')}", file=sys.stderr)
        return 1

    print(f"Updated release notes for {tag_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())