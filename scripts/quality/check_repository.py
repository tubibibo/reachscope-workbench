"""Check repository boundaries, naming and local Markdown file links, offline.

This checks source-tree organization only. It neither reads private workspaces
nor validates external links, Markdown anchors or historical acceptance claims.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "config/repository-layout.json"


def source_files(root: Path, excluded: set[str]) -> list[Path]:
    files: list[Path] = []
    for directory, subdirectories, names in os.walk(root, followlinks=False):
        subdirectories[:] = sorted(name for name in subdirectories
                                   if name not in excluded and not name.endswith(".egg-info")
                                   and not (Path(directory) / name).is_symlink())
        files.extend(Path(directory) / name for name in sorted(names)
                     if not (Path(directory) / name).is_symlink())
    return files


def without_code_fences(text: str) -> str:
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            lines.append("")
        else:
            lines.append(line if fence is None else "")
    return "\n".join(lines)


def markdown_targets(text: str) -> list[str]:
    text = without_code_fences(text)
    inline = re.findall(r"\]\(\s*(<[^>]+>|[^\s)]+)", text)
    references = re.findall(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)", text, re.MULTILINE)
    return [target.strip("<>") for target in [*inline, *references]]


def check() -> dict[str, object]:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    migrations = json.loads((ROOT / "config/path-migrations.json").read_text(encoding="utf-8"))["paths"]
    script_modules = {Path(path).stem for pair in migrations.items() for path in pair
                      if path.endswith(".py") and path.startswith(("scripts/", "frontend/scripts/", "tests/browser/"))}
    errors: list[str] = []
    root_names = set(rules["root_files"])
    allowed_directories = set(rules["source_directories"] + rules["generated_directories"]
                              + rules["private_state_directories"] + [".git"])
    for path in sorted(ROOT.iterdir()):
        if path.is_dir():
            if path.name not in allowed_directories and not path.name.endswith(".egg-info"):
                errors.append("Unexpected root directory: " + path.name)
        elif (path.name not in root_names
              and not any(fnmatch.fnmatchcase(path.name, pattern)
                          for pattern in rules["generated_root_files"])):
            errors.append("Unexpected root file; move local outputs to artifacts/: " + path.name)
    for relative in rules["required_paths"]:
        if not (ROOT / relative).exists():
            errors.append("Missing required path: " + relative)
    excluded = set(rules["excluded_directory_names"])
    files = source_files(ROOT, excluded)
    markdown_count = 0
    local_link_count = 0
    local_import_count = 0
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix == ".py" and any(relative.startswith(prefix + "/")
                                        for prefix in rules["python_name_roots"]):
            if not re.fullmatch(r"[a-z_][a-z0-9_]*\.py", path.name):
                errors.append("Python filename must use snake_case: " + relative)
            # Check known moved local helpers without executing browser scripts.
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=relative)):
                modules = ([node.module] if isinstance(node, ast.ImportFrom) and node.level == 0
                           else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                for module in modules:
                    if module and module.split(".")[0] in script_modules:
                        local_import_count += 1
                        if not (path.parent / (module.split(".")[0] + ".py")).is_file():
                            errors.append("Missing local script import: " + relative + " -> " + module)
        if path.suffix != ".md":
            continue
        markdown_count += 1
        if (relative.startswith("docs/") and path.name not in rules["markdown_name_exceptions"]
                and not re.fullmatch(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*\.md", path.name)):
            errors.append("Documentation filename must use lowercase-kebab-case: " + relative)
        for target in markdown_targets(path.read_text(encoding="utf-8")):
            try:
                url = urlsplit(target)
            except ValueError:
                errors.append("Invalid Markdown target in " + relative)
                continue
            if url.scheme or url.netloc or not url.path:
                continue
            local_link_count += 1
            destination = ((ROOT / unquote(url.path).lstrip("/")) if url.path.startswith("/")
                           else path.parent / unquote(url.path)).resolve()
            if not destination.is_relative_to(ROOT):
                errors.append("Non-portable local link outside repository: " + relative + " -> " + target)
            elif not destination.exists():
                errors.append("Missing local Markdown link: " + relative + " -> " + target)
    return {"passed": not errors, "markdown_files": markdown_count,
            "local_links_checked": local_link_count, "local_script_imports_checked": local_import_count,
            "errors": errors,
            "external_requests": 0, "private_workspaces_read": False,
            "anchors_checked": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = check()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
