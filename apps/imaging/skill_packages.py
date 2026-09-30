"""Safe import helpers for Markdown-based imaging Skills.

The importer deliberately stores instructions and references only. It never
executes scripts from a third-party repository.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen


MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 320 * 1024
MAX_MARKDOWN_FILES = 32
USER_AGENT = "KFlow-Imaging-Skill-Importer/1.0"


class SkillImportError(ValueError):
    pass


@dataclass(frozen=True)
class ImportedSkill:
    key: str
    name: str
    description: str
    source_url: str
    revision: str
    entrypoint: str
    files: dict[str, str]
    report: dict


def _github_headers() -> dict[str, str]:
    import os

    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch(url: str, *, json_response: bool = False, limit: int = MAX_FILE_BYTES):
    request = Request(url, headers=_github_headers())
    try:
        with urlopen(request, timeout=30) as response:
            content = response.read(limit + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SkillImportError(f"Skill 仓库读取失败：{exc}") from exc
    if len(content) > limit:
        raise SkillImportError("Skill 文件过大，已停止导入")
    if json_response:
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkillImportError("Skill 仓库返回了无法识别的数据") from exc
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SkillImportError("Skill 文件必须是 UTF-8 文本") from exc


def _parse_source_url(source_url: str) -> tuple[str, str, str | None, str]:
    parsed = urlparse(str(source_url or "").strip())
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise SkillImportError("目前只支持 https://github.com/ 仓库地址")
    parts = [unquote(item) for item in parsed.path.strip("/").split("/") if item]
    if len(parts) < 2:
        raise SkillImportError("GitHub 地址缺少 owner 或 repository")
    owner, repo = parts[0], parts[1]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise SkillImportError("GitHub owner 或 repository 格式不正确")
    repo = repo.removesuffix(".git")
    revision = None
    root = ""
    if len(parts) > 2:
        if len(parts) < 4 or parts[2] != "tree":
            raise SkillImportError("GitHub 地址只支持仓库首页或 /tree/<版本>/<子目录>")
        revision = parts[3]
        root = "/".join(parts[4:]).strip("/")
    return owner, repo, revision, root


def _frontmatter(markdown: str) -> dict[str, str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]{0,40})\s*:\s*(.*)$", line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"\'')
    return values


def _slug(value: str) -> str:
    value = value.lower().replace("_", "-")
    value = re.sub(r"[^a-z0-9-]+", "-", value).strip("-")
    return (value or "imported-skill")[:80].rstrip("-")


def import_github_skill(source_url: str) -> ImportedSkill:
    owner, repo, requested_revision, root = _parse_source_url(source_url)
    api_root = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
    repository = _fetch(api_root, json_response=True, limit=256 * 1024)
    if not isinstance(repository, dict):
        raise SkillImportError("无法读取 Skill 仓库信息")
    revision = requested_revision or str(repository.get("default_branch") or "main")
    commit = _fetch(f"{api_root}/commits/{quote(revision, safe='')}", json_response=True, limit=256 * 1024)
    revision = str(commit.get("sha") or "").strip() if isinstance(commit, dict) else ""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SkillImportError("无法确认 Skill 仓库版本")
    tree_url = f"{api_root}/git/trees/{quote(revision, safe='')}?recursive=1"
    tree_payload = _fetch(tree_url, json_response=True, limit=2 * 1024 * 1024)
    entries = tree_payload.get("tree") if isinstance(tree_payload, dict) else None
    if not isinstance(entries, list):
        raise SkillImportError("无法读取 Skill 仓库目录")
    if tree_payload.get("truncated"):
        raise SkillImportError("Skill 仓库目录过大，无法完整检查")
    prefix = f"{root}/" if root else ""
    files = [item for item in entries if item.get("type") == "blob" and str(item.get("path", "")).startswith(prefix)]
    skill_path = next((str(item["path"]) for item in files if str(item.get("path", "")).lower() == f"{prefix}skill.md".lower()), "")
    if not skill_path:
        raise SkillImportError("指定目录中没有找到 SKILL.md")
    markdown_paths = [skill_path]
    for item in files:
        path = str(item.get("path", ""))
        relative = path[len(prefix):] if prefix and path.startswith(prefix) else path
        if path == skill_path or (relative.lower().startswith("references/") and relative.lower().endswith(".md")):
            if path not in markdown_paths:
                markdown_paths.append(path)
    if len(markdown_paths) > MAX_MARKDOWN_FILES:
        raise SkillImportError(f"Skill 引用文件超过 {MAX_MARKDOWN_FILES} 个")
    imported_files: dict[str, str] = {}
    total_bytes = 0
    for path in markdown_paths:
        raw_url = f"https://raw.githubusercontent.com/{quote(owner)}/{quote(repo)}/{quote(revision, safe='')}/{quote(path, safe='/')}"
        content = _fetch(raw_url)
        total_bytes += len(content.encode("utf-8"))
        if total_bytes > MAX_TOTAL_BYTES:
            raise SkillImportError("Skill 文本资料总量过大，已停止导入")
        relative = path[len(prefix):] if prefix and path.startswith(prefix) else path
        imported_files[relative] = content
    entry = imported_files.get(skill_path[len(prefix):] if prefix and skill_path.startswith(prefix) else skill_path, "")
    metadata = _frontmatter(entry)
    skill_name = str(metadata.get("name") or repo).strip()[:120]
    description = str(metadata.get("description") or f"从 {owner}/{repo} 导入的显影 Skill").strip()[:500]
    all_paths = [str(item.get("path", "")) for item in files]
    script_paths = [path[len(prefix):] if prefix and path.startswith(prefix) else path for path in all_paths if re.search(r"(^|/)(scripts?|bin)/|\.(py|js|ts|sh|swift|rb)$", path, re.I)]
    lower_entry = entry.lower()
    multi_output = bool(re.search(r"two\s+(coordinated\s+)?images|front\s+and\s+back|正面.{0,20}背面", lower_entry, re.I))
    warnings: list[str] = []
    if script_paths:
        warnings.append("仓库包含脚本；当前仅导入 Markdown，不会执行脚本。")
    if multi_output:
        warnings.append("Skill 可能要求多张输出；当前显影任务默认生成一张图片。")
    report = {
        "compatibility": "partial" if warnings else "prompt",
        "warnings": warnings,
        "entrypoint": skill_path[len(prefix):] if prefix and skill_path.startswith(prefix) else skill_path,
        "markdownFileCount": len(imported_files),
        "assetFileCount": sum(1 for path in all_paths if not path.lower().endswith(".md")),
        "scriptFiles": script_paths[:20],
        "multiOutput": multi_output,
    }
    return ImportedSkill(
        key=_slug(skill_name),
        name=skill_name,
        description=description,
        source_url=source_url.strip(),
        revision=revision[:160],
        entrypoint=report["entrypoint"],
        files=imported_files,
        report=report,
    )
