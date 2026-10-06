import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from circlesearch.core.cards import Action, Card
from circlesearch.core.net import get_json, safe
from circlesearch.core.pipeline import enricher


@dataclass(kw_only=True)
class RepoCard(Card):
    kind = "repo"
    priority = 2

    description: str = ""
    stars: int | None = None
    language: str = ""
    release: str = ""
    pushed: str = ""
    open_issues: int | None = None


@dataclass(kw_only=True)
class PackageCard(Card):
    kind = "package"
    priority = 3
    accent = "green"

    registry: str
    command: str
    version: str = ""
    summary: str = ""
    released: str = ""
    python: str = ""


def ago(iso):
    then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    s = (datetime.now(timezone.utc) - then).total_seconds()
    for size, unit in ((365 * 86400, "year"), (30 * 86400, "month"), (7 * 86400, "week"), (86400, "day"), (3600, "hour")):
        if s >= size:
            n = int(s // size)
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"


@enricher("github", needs={"github_repo"}, order=40)
def github_repo(facts):
    repo = facts["github_repo"]
    headers = {"Accept": "application/vnd.github+json"}
    with ThreadPoolExecutor(2) as pool:
        info_f = pool.submit(get_json, f"https://api.github.com/repos/{repo}", headers)
        rel_f = pool.submit(safe, get_json, f"https://api.github.com/repos/{repo}/releases/latest", headers)
        info, release = info_f.result(), rel_f.result()
    if not info:
        return deps_dev_repo(repo)
    url = info.get("html_url", f"https://github.com/{repo}")
    return [RepoCard(title=info.get("full_name", repo), description=info.get("description") or "",
                     stars=info.get("stargazers_count", 0), language=info.get("language") or "",
                     release=f"{release['tag_name']} · {ago(release['published_at'])}"
                     if release and release.get("tag_name") else "",
                     pushed=ago(info["pushed_at"]) if info.get("pushed_at") else "",
                     open_issues=info.get("open_issues_count", 0),
                     actions=[Action("Open on GitHub", "open", url)], source="GitHub",
                     url=info.get("html_url", ""))], {}


def deps_dev_repo(repo):
    info = get_json("https://api.deps.dev/v3/projects/" + urllib.parse.quote(f"github.com/{repo}", safe=""))
    if not info:
        return [], {}
    url = f"https://github.com/{repo}"
    return [RepoCard(title=repo, description=info.get("description") or "", stars=info.get("starsCount", 0),
                     open_issues=info.get("openIssuesCount", 0),
                     actions=[Action("Open on GitHub", "open", url)], source="deps.dev", url=url)], {}


@enricher("npm", needs={"npm"}, order=90)
def npm_package(facts):
    name = facts["npm"]
    meta = get_json(f"https://registry.npmjs.org/{name}/latest")
    if not meta:
        return [], {}
    return [PackageCard(title=name, registry="npm", command=f"npm i {name}", version=meta.get("version", ""),
                        actions=[Action("Copy install command", "copy", f"npm i {name}")],
                        source="npm", url=f"https://www.npmjs.com/package/{name}")], {}


@enricher("pypi", needs={"pypi"}, order=80)
def pypi_package(facts):
    name = facts["pypi"]
    meta = get_json(f"https://pypi.org/pypi/{name}/json")
    if not meta:
        return [], {}
    info = meta["info"]
    released = meta.get("urls", [{}])[0].get("upload_time_iso_8601", "") if meta.get("urls") else ""
    return [PackageCard(title=name, registry="PyPI", command=f"pip install {name}", version=info.get("version", ""),
                        summary=info.get("summary") or "", released=ago(released) if released else "",
                        python=info.get("requires_python") or "",
                        actions=[Action("Copy install command", "copy", f"pip install {name}")],
                        source="PyPI", url=f"https://pypi.org/project/{name}/")], {}
