#!/usr/bin/env python3
"""Update the profile README from GitHub's public user-events feed."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

USERNAME = "samiashi"
PROFILE_REPOSITORY = f"{USERNAME}/{USERNAME}"
MAX_ITEMS = 6
README_PATH = Path(__file__).resolve().parents[1] / "README.md"
ACTIVITY_START = "<!--RECENT_ACTIVITY:start-->"
ACTIVITY_END = "<!--RECENT_ACTIVITY:end-->"
UPDATED_START = "<!--RECENT_ACTIVITY:last_update-->"
UPDATED_END = "<!--RECENT_ACTIVITY:last_update_end-->"


def api_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{USERNAME}-profile-activity",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_events() -> list[dict]:
    result = api_json(f"https://api.github.com/users/{USERNAME}/events/public?per_page=100")
    return result if isinstance(result, list) else []


def fetch_original_repositories() -> set[str]:
    result = api_json(f"https://api.github.com/users/{USERNAME}/repos?type=owner&per_page=100")
    if not isinstance(result, list):
        return set()
    return {
        repository["full_name"]
        for repository in result
        if repository.get("full_name") and not repository.get("fork")
    }


def link(label: str, url: str) -> str:
    return f"[{label}]({url})"


def pull_request_details(payload: dict, cache: dict[str, dict]) -> dict:
    summary = payload.get("pull_request") or {}
    api_url = summary.get("url") or (payload.get("review") or {}).get("pull_request_url")
    if not api_url:
        return summary
    if api_url not in cache:
        try:
            result = api_json(api_url)
            cache[api_url] = result if isinstance(result, dict) else {}
        except (OSError, ValueError):
            cache[api_url] = {}
    return {**summary, **cache[api_url]}


def render_event(
    event: dict,
    original_repositories: set[str],
    pull_request_cache: dict[str, dict],
) -> tuple[str, tuple] | None:
    event_type = event.get("type")
    payload = event.get("payload") or {}
    repository = (event.get("repo") or {}).get("name")
    if not repository or repository == PROFILE_REPOSITORY:
        return None

    repository_url = f"https://github.com/{repository}"
    repository_link = link(repository, repository_url)

    if event_type == "PullRequestEvent":
        pull_request = pull_request_details(payload, pull_request_cache)
        number = pull_request.get("number") or payload.get("number")
        title = pull_request.get("title") or "Pull request"
        url = pull_request.get("html_url") or f"{repository_url}/pull/{number}"
        pull_request_link = link(f"PR #{number}: {title}", url)
        action = payload.get("action")
        if action == "closed" and pull_request.get("merged"):
            return f"🎉 Merged {pull_request_link} in {repository_link}", (event_type, url, "merged")
        if action in {"opened", "reopened"}:
            return f"💪 Opened {pull_request_link} in {repository_link}", (event_type, url, "opened")
        return None

    if event_type == "PullRequestReviewEvent":
        pull_request = pull_request_details(payload, pull_request_cache)
        review = payload.get("review") or {}
        number = pull_request.get("number")
        title = pull_request.get("title") or "Pull request"
        url = pull_request.get("html_url") or f"{repository_url}/pull/{number}"
        state = str(review.get("state") or "reviewed").lower()
        verb = {
            "approved": "Approved",
            "changes_requested": "Requested changes on",
            "commented": "Reviewed",
        }.get(state, "Reviewed")
        return (
            f"🔎 {verb} {link(f'PR #{number}: {title}', url)} in {repository_link}",
            (event_type, url, state),
        )

    if event_type == "IssuesEvent":
        issue = payload.get("issue") or {}
        number = issue.get("number")
        title = issue.get("title") or "Issue"
        url = issue.get("html_url") or f"{repository_url}/issues/{number}"
        action = payload.get("action")
        if action not in {"opened", "closed", "reopened"}:
            return None
        verb = "Closed" if action == "closed" else "Opened"
        return f"❗ {verb} {link(f'issue #{number}: {title}', url)} in {repository_link}", (event_type, url, action)

    if event_type == "ReleaseEvent" and payload.get("action") == "published":
        release = payload.get("release") or {}
        name = release.get("name") or release.get("tag_name") or "a new release"
        url = release.get("html_url") or f"{repository_url}/releases"
        return f"🚀 Released {link(name, url)} in {repository_link}", (event_type, url)

    if event_type == "CreateEvent" and payload.get("ref_type") == "repository":
        return f"📦 Created {repository_link}", (event_type, repository)

    if event_type == "PushEvent":
        if repository not in original_repositories:
            return None
        return f"⬆️ Pushed updates to {repository_link}", (event_type, repository)

    return None


def render_activity(events: list[dict], original_repositories: set[str]) -> list[str]:
    items: list[str] = []
    seen: set[tuple] = set()
    pull_request_cache: dict[str, dict] = {}
    for event in events:
        rendered = render_event(event, original_repositories, pull_request_cache)
        if not rendered:
            continue
        text, identity = rendered
        if identity in seen:
            continue
        seen.add(identity)
        items.append(f"- {text}<br>")
        if len(items) == MAX_ITEMS:
            break
    return items


def replace_section(document: str, start: str, end: str, content: str) -> str:
    pattern = rf"({re.escape(start)}\n).*?(\n{re.escape(end)})"
    updated, count = re.subn(pattern, rf"\g<1>{content}\g<2>", document, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"README marker pair is missing: {start} / {end}")
    return updated


def main() -> int:
    items = render_activity(fetch_events(), fetch_original_repositories())
    if not items:
        items = ["- No recent public activity found.<br>"]

    activity = "\n".join(items)
    if "--dry-run" in sys.argv:
        print(activity)
        return 0

    document = README_PATH.read_text(encoding="utf-8")
    current_match = re.search(
        rf"{re.escape(ACTIVITY_START)}\n(.*?)\n{re.escape(ACTIVITY_END)}",
        document,
        flags=re.DOTALL,
    )
    if not current_match:
        raise RuntimeError("README activity markers are missing")
    if current_match.group(1) == activity:
        print("Recent activity is unchanged.")
        return 0

    now = datetime.now(ZoneInfo("Asia/Dubai"))
    timestamp = f"Last updated: {now.strftime('%B')} {now.day}, {now.year}, {now.strftime('%I:%M %p').lstrip('0')} Dubai time"
    document = replace_section(document, ACTIVITY_START, ACTIVITY_END, activity)
    document = replace_section(document, UPDATED_START, UPDATED_END, timestamp)
    README_PATH.write_text(document, encoding="utf-8")
    print(f"Updated README with {len(items)} public activity items.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
