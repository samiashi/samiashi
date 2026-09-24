#!/usr/bin/env python3
"""Update the profile README with public pull requests and recent activity."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

USERNAME = "samiashi"
PROFILE_REPOSITORY = f"{USERNAME}/{USERNAME}"
MAX_ITEMS = 25
MAX_PULL_REQUESTS = 100
LOOKBACK_DAYS = 90
SEARCH_PAGE_LIMIT = 10
STAR_LINK_LIMIT = 3
STAR_KIND = "WatchEvent"
COMMENT_KIND = "comment"
REVIEW_KIND = "review"
IGNORED_REPOSITORIES: frozenset[str] = frozenset()
IGNORED_OWNERS: frozenset[str] = frozenset()
DUBAI = ZoneInfo("Asia/Dubai")
README_PATH = Path(__file__).resolve().parents[1] / "README.md"
PULL_REQUEST_SEARCH_URL = "https://api.github.com/search/issues"
PULL_REQUEST_BROWSE_URL = f"https://github.com/search?q=author%3A{USERNAME}&type=pullrequests"
PULL_REQUEST_START = "<!--OPEN_SOURCE_PRS:start-->"
PULL_REQUEST_END = "<!--OPEN_SOURCE_PRS:end-->"
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


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def event_timestamp(event: dict) -> datetime:
    created_at = event.get("created_at")
    if not created_at:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parse_timestamp(created_at)


def fetch_events() -> list[dict]:
    events: list[dict] = []
    for page in range(1, 4):
        result = api_json(
            f"https://api.github.com/users/{USERNAME}/events/public?per_page=100&page={page}"
        )
        if not isinstance(result, list):
            break
        events.extend(result)
        if len(result) < 100:
            break

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    recent_events = [
        event
        for event in events
        if event.get("created_at")
        and event_timestamp(event) >= cutoff
    ]
    return sorted(recent_events, key=event_timestamp, reverse=True)


def fetch_original_repositories() -> set[str]:
    result = api_json(f"https://api.github.com/users/{USERNAME}/repos?type=owner&per_page=100")
    if not isinstance(result, list):
        return set()
    return {
        repository["full_name"]
        for repository in result
        if repository.get("full_name") and not repository.get("fork")
    }


def fetch_pull_requests() -> list[dict]:
    items: list[dict] = []
    for page in range(1, SEARCH_PAGE_LIMIT + 1):
        query = urllib.parse.urlencode(
            {
                "q": f"author:{USERNAME} is:pr is:public",
                "sort": "created",
                "order": "desc",
                "per_page": 100,
                "page": page,
            }
        )
        result = api_json(f"{PULL_REQUEST_SEARCH_URL}?{query}")
        page_items = result.get("items") if isinstance(result, dict) else None
        if not page_items:
            break
        items.extend(page_items)
        if len(page_items) < 100:
            break
    return items


def pull_request_repository(item: dict) -> str:
    repository = item.get("repository") or {}
    if repository.get("full_name"):
        return str(repository["full_name"])
    return str(item.get("repository_url") or "").rsplit("/repos/", 1)[-1]


def link(label: str, url: str) -> str:
    return f"[{label}]({url})"


def event_moment(event: dict) -> datetime:
    return event_timestamp(event).astimezone(DUBAI)


def moment_datetime(moment: datetime) -> str:
    local_time = moment.astimezone(DUBAI)
    clock = local_time.strftime("%I:%M %p").lstrip("0")
    return f"{local_time.strftime('%b')} {local_time.day}, {local_time.year} · {clock} Dubai"


def event_datetime(event: dict) -> str:
    return moment_datetime(event_timestamp(event))


def moment_range(moments: list[datetime]) -> str:
    newest, oldest = moments[0], moments[-1]
    if newest.date() == oldest.date():
        return f"{oldest.strftime('%b')} {oldest.day}, {oldest.year} Dubai"
    if newest.year == oldest.year and newest.month == oldest.month:
        return f"{oldest.strftime('%b')} {oldest.day}–{newest.day}, {newest.year} Dubai"
    if newest.year == oldest.year:
        return (
            f"{oldest.strftime('%b')} {oldest.day} – "
            f"{newest.strftime('%b')} {newest.day}, {newest.year} Dubai"
        )
    return (
        f"{oldest.strftime('%b')} {oldest.day}, {oldest.year} – "
        f"{newest.strftime('%b')} {newest.day}, {newest.year} Dubai"
    )


def optional_api_json(url: str) -> object | None:
    try:
        return api_json(url)
    except urllib.error.HTTPError as error:
        if error.code in {403, 429}:
            raise
        return None
    except (OSError, ValueError):
        return None


def fetch_public_repositories(repositories: set[str]) -> set[str]:
    public: set[str] = set()
    for repository in sorted(repositories):
        details = optional_api_json(f"https://api.github.com/repos/{repository}")
        if isinstance(details, dict) and details.get("visibility") == "public":
            public.add(repository)
    return public


def pull_request_details(payload: dict, cache: dict[str, dict]) -> dict:
    summary = payload.get("pull_request") or {}
    api_url = summary.get("url") or (payload.get("review") or {}).get("pull_request_url")
    if not api_url:
        return summary
    if api_url not in cache:
        result = optional_api_json(api_url)
        cache[api_url] = result if isinstance(result, dict) else {}
    return {**summary, **cache[api_url]}


def pull_requests_from_events(events: list[dict]) -> list[dict]:
    cache: dict[str, dict] = {}
    items: list[dict] = []
    seen: set[str] = set()
    for event in events:
        if event.get("type") != "PullRequestEvent":
            continue
        payload = event.get("payload") or {}
        if payload.get("action") not in {"opened", "reopened", "closed"}:
            continue
        pull_request = pull_request_details(payload, cache)
        url = pull_request.get("html_url")
        if not url or url in seen:
            continue
        seen.add(url)
        items.append(
            {
                "html_url": url,
                "title": pull_request.get("title") or "Pull request",
                "number": pull_request.get("number") or payload.get("number"),
                "state": pull_request.get("state") or "open",
                "created_at": pull_request.get("created_at") or event.get("created_at"),
                "repository": {"full_name": (event.get("repo") or {}).get("name") or ""},
                "pull_request": {"merged_at": pull_request.get("merged_at")},
            }
        )
    return items


def push_commit_count(payload: dict, repository: str, cache: dict[str, int]) -> int:
    count = payload.get("size") or payload.get("distinct_size")
    if count:
        return int(count)
    commits = payload.get("commits") or []
    if commits:
        return len(commits)
    before = str(payload.get("before") or "")
    head = str(payload.get("head") or "")
    if not before or not head or before == head or set(before) == {"0"}:
        return 0
    key = f"{repository}@{before}...{head}"
    if key not in cache:
        result = optional_api_json(
            f"https://api.github.com/repos/{repository}/compare/{before}...{head}"
        )
        total = result.get("total_commits") if isinstance(result, dict) else 0
        cache[key] = int(total or 0)
    return cache[key]


def render_event(
    event: dict,
    original_repositories: set[str],
    pull_request_cache: dict[str, dict],
    commit_count_cache: dict[str, int],
) -> tuple[str, tuple] | None:
    event_type = event.get("type")
    payload = event.get("payload") or {}
    repository = (event.get("repo") or {}).get("name")
    if not repository or repository == PROFILE_REPOSITORY:
        return None
    if repository in IGNORED_REPOSITORIES or repository.split("/", 1)[0] in IGNORED_OWNERS:
        return None

    repository_url = f"https://github.com/{repository}"
    repository_link = link(repository, repository_url)

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
            (REVIEW_KIND, repository, number, state),
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

    if event_type == "IssueCommentEvent" and payload.get("action") == "created":
        issue = payload.get("issue") or {}
        number = issue.get("number")
        title = issue.get("title") or "Discussion"
        url = (
            (payload.get("comment") or {}).get("html_url")
            or issue.get("html_url")
            or f"{repository_url}/issues/{number}"
        )
        kind = "PR" if issue.get("pull_request") else "issue"
        identity = (COMMENT_KIND, repository, number) if number is not None else (event_type, url)
        return f"💬 Commented on {link(f'{kind} #{number}: {title}', url)} in {repository_link}", identity

    if event_type == "PullRequestReviewCommentEvent" and payload.get("action") == "created":
        pull_request = pull_request_details(payload, pull_request_cache)
        number = pull_request.get("number")
        title = pull_request.get("title") or "Pull request"
        url = (
            (payload.get("comment") or {}).get("html_url")
            or pull_request.get("html_url")
            or f"{repository_url}/pull/{number}"
        )
        identity = (COMMENT_KIND, repository, number) if number is not None else (event_type, url)
        return f"💬 Commented on {link(f'PR #{number}: {title}', url)} in {repository_link}", identity

    if event_type == "CommitCommentEvent":
        comment = payload.get("comment") or {}
        commit_id = str(comment.get("commit_id") or "")
        short_id = commit_id[:7] or "commit"
        url = comment.get("html_url") or f"{repository_url}/commit/{commit_id}"
        return f"💬 Commented on {link(f'commit {short_id}', url)} in {repository_link}", (event_type, url)

    if event_type == "GollumEvent":
        pages = payload.get("pages") or []
        if not pages:
            return None
        page = pages[0]
        title = page.get("page_name") or "a wiki page"
        url = page.get("html_url") or f"{repository_url}/wiki"
        action = str(page.get("action") or "updated").capitalize()
        return f"📖 {action} {link(title, url)} in {repository_link}", (event_type, url, action)

    if event_type == "MemberEvent" and payload.get("action") == "added":
        member = payload.get("member") or {}
        login = member.get("login") or "a collaborator"
        url = member.get("html_url") or f"https://github.com/{login}"
        return f"🤝 Added {link(f'@{login}', url)} to {repository_link}", (event_type, repository, login)

    if event_type == "PublicEvent":
        return f"🌍 Made {repository_link} public", (event_type, repository)

    if event_type == "ForkEvent":
        fork = payload.get("forkee") or {}
        fork_name = fork.get("full_name") or f"{USERNAME}/{repository.rsplit('/', 1)[-1]}"
        fork_url = fork.get("html_url") or f"https://github.com/{fork_name}"
        return f"🍴 Forked {repository_link} to {link(fork_name, fork_url)}", (event_type, repository, fork_name)

    if event_type == "WatchEvent" and payload.get("action") == "started":
        return f"⭐ Starred {repository_link}", (STAR_KIND, repository)

    if event_type == "PushEvent":
        if repository not in original_repositories:
            return None
        commits = push_commit_count(payload, repository, commit_count_cache)
        if commits > 1:
            text = f"⬆️ Pushed {commits} commits to {repository_link}"
        elif commits == 1:
            text = f"⬆️ Pushed 1 commit to {repository_link}"
        else:
            text = f"⬆️ Pushed updates to {repository_link}"
        return text, (event_type, repository)

    return None


def render_pull_request(item: dict) -> tuple[str, datetime, str] | None:
    summary = item.get("pull_request") or {}
    if summary.get("merged_at"):
        status = "merged"
        moment = parse_timestamp(summary["merged_at"])
    elif item.get("state") == "open" and item.get("created_at"):
        status = "open"
        moment = parse_timestamp(item["created_at"])
    else:
        return None

    repository = pull_request_repository(item)
    number = item.get("number")
    title = item.get("title") or "Pull request"
    url = item.get("html_url") or f"https://github.com/{repository}/pull/{number}"
    emoji = "🎉" if status == "merged" else "💪"
    line = (
        f"- {emoji} {link(f'PR #{number}: {title}', url)} "
        f"in {link(repository, f'https://github.com/{repository}')} "
        f"<sub>· {moment_datetime(moment)}</sub><br>"
    )
    return status, moment, line


def render_pull_requests(items: list[dict], public_repositories: set[str]) -> list[str]:
    opened: list[tuple[datetime, str]] = []
    merged: list[tuple[datetime, str]] = []
    seen: set[str] = set()
    for item in items:
        repository = pull_request_repository(item)
        if not repository or repository == PROFILE_REPOSITORY:
            continue
        if repository in IGNORED_REPOSITORIES or repository.split("/", 1)[0] in IGNORED_OWNERS:
            continue
        if repository not in public_repositories:
            continue
        url = str(item.get("html_url") or "")
        if url:
            if url in seen:
                continue
            seen.add(url)
        rendered = render_pull_request(item)
        if not rendered:
            continue
        status, moment, line = rendered
        (opened if status == "open" else merged).append((moment, line))

    opened.sort(key=lambda entry: entry[0], reverse=True)
    merged.sort(key=lambda entry: entry[0], reverse=True)

    visible_merged = merged[: max(MAX_PULL_REQUESTS - len(opened), 0)]
    hidden = len(merged) - len(visible_merged)

    lines: list[str] = []
    if opened:
        lines.append(f"**Open ({len(opened)})**")
        lines.append("")
        lines.extend(line for _, line in opened)
    if merged:
        if lines:
            lines.append("")
        lines.append(f"**Merged ({len(merged)})**")
        lines.append("")
        lines.extend(line for _, line in visible_merged)
        if hidden:
            plural = "s" if hidden != 1 else ""
            lines.append(
                f"- [{hidden} more pull request{plural} on GitHub]({PULL_REQUEST_BROWSE_URL})<br>"
            )
    return lines


def render_activity(events: list[dict], original_repositories: set[str]) -> list[str]:
    rendered: list[tuple[dict, str, tuple]] = []
    seen: set[tuple] = set()
    pull_request_cache: dict[str, dict] = {}
    commit_count_cache: dict[str, int] = {}
    for event in events:
        result = render_event(
            event, original_repositories, pull_request_cache, commit_count_cache
        )
        if not result:
            continue
        text, identity = result
        if identity in seen:
            continue
        seen.add(identity)
        rendered.append((event, text, identity))

    reviewed = {identity[1:3] for _, _, identity in rendered if identity[0] == REVIEW_KIND}
    rendered = [
        (event, text, identity)
        for event, text, identity in rendered
        if identity[0] != COMMENT_KIND or identity[1:3] not in reviewed
    ]

    lines: list[str] = []
    star_run: list[tuple[dict, str, tuple]] = []

    def flush_stars() -> None:
        if not star_run:
            return
        if len(star_run) == 1:
            event, text, _ = star_run[0]
            lines.append(f"- {text} <sub>· {event_datetime(event)}</sub><br>")
            star_run.clear()
            return
        repositories = [identity[1] for _, _, identity in star_run]
        labels = ", ".join(
            link(repository, f"https://github.com/{repository}")
            for repository in repositories[:STAR_LINK_LIMIT]
        )
        hidden = len(repositories) - STAR_LINK_LIMIT
        if hidden > 0:
            labels += f" and {hidden} more"
        timestamp = moment_range([event_moment(event) for event, _, _ in star_run])
        lines.append(f"- ⭐ Starred {labels} <sub>· {timestamp}</sub><br>")
        star_run.clear()

    for event, text, identity in rendered:
        if identity[0] == STAR_KIND:
            star_run.append((event, text, identity))
            continue
        flush_stars()
        lines.append(f"- {text} <sub>· {event_datetime(event)}</sub><br>")
    flush_stars()

    return lines[:MAX_ITEMS]


def replace_section(document: str, start: str, end: str, content: str) -> str:
    pattern = rf"({re.escape(start)}\n).*?(\n{re.escape(end)})"
    updated, count = re.subn(pattern, rf"\g<1>{content}\g<2>", document, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"README marker pair is missing: {start} / {end}")
    return updated


def section_content(document: str, start: str, end: str) -> str:
    match = re.search(
        rf"{re.escape(start)}\n(.*?)\n{re.escape(end)}", document, flags=re.DOTALL
    )
    if not match:
        raise RuntimeError(f"README marker pair is missing: {start} / {end}")
    return match.group(1)


def main() -> int:
    events = fetch_events()

    pull_requests = fetch_pull_requests()
    if not pull_requests:
        pull_requests = pull_requests_from_events(events)
    public_repositories = fetch_public_repositories(
        {pull_request_repository(item) for item in pull_requests} - {""}
    )
    pull_request_lines = render_pull_requests(pull_requests, public_repositories)
    if not pull_request_lines:
        pull_request_lines = ["- No public pull requests found.<br>"]

    activity_lines = render_activity(events, fetch_original_repositories())
    if not activity_lines:
        activity_lines = ["- No recent public activity found.<br>"]

    pull_requests_section = "\n".join(pull_request_lines)
    activity_section = "\n".join(activity_lines)

    if "--dry-run" in sys.argv:
        print(pull_requests_section)
        print()
        print(activity_section)
        return 0

    document = README_PATH.read_text(encoding="utf-8")
    if (
        section_content(document, PULL_REQUEST_START, PULL_REQUEST_END) == pull_requests_section
        and section_content(document, ACTIVITY_START, ACTIVITY_END) == activity_section
    ):
        print("Profile activity is unchanged.")
        return 0

    now = datetime.now(DUBAI)
    timestamp = f"Last updated: {now.strftime('%B')} {now.day}, {now.year}, {now.strftime('%I:%M %p').lstrip('0')} Dubai time"
    document = replace_section(document, PULL_REQUEST_START, PULL_REQUEST_END, pull_requests_section)
    document = replace_section(document, ACTIVITY_START, ACTIVITY_END, activity_section)
    document = replace_section(document, UPDATED_START, UPDATED_END, timestamp)
    README_PATH.write_text(document, encoding="utf-8")
    pull_request_count = sum(
        1 for line in pull_request_lines if line.startswith(("- 💪", "- 🎉"))
    )
    print(
        f"Updated README with {pull_request_count} public pull requests "
        f"and {len(activity_lines)} public activity items."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
