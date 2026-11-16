# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

# Lunar AI

"""Generate the locked Python and Node dependency license inventory."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from collections import deque
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

try:
    from packaging.requirements import Requirement
except Exception:  # pragma: no cover - fallback only for unusually minimal envs
    Requirement = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[4]
PYPROJECT = REPO_ROOT / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"
NPM_PROJECT = REPO_ROOT / "codex-app-workbench" / "package.json"
NPM_LOCK = REPO_ROOT / "codex-app-workbench" / "package-lock.json"
OUTPUT = REPO_ROOT / "docs" / "governance" / "LICENSES.md"
GENERATION_COMMAND = (
    "uv run python "
    "proj_skills/compliance/dependency-license-inventory/scripts/generate_licenses_md.py"
)


@dataclass(frozen=True)
class DependencyRow:
    ecosystem: str
    name: str
    normalized_name: str
    version: str
    scope: str
    license: str
    url: str


def normalize_name(name: str) -> str:
    """Apply Python packaging name normalization without importing private APIs."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str:
    """Extract a distribution name from a requirement string."""
    if Requirement is not None:
        return Requirement(requirement).name
    return re.split(r"\\s|;|<|>|=|!|~|\\[", requirement, maxsplit=1)[0]


def load_direct_dependencies(pyproject: Path = PYPROJECT) -> dict[str, str]:
    """Return all direct Python dependencies, including PEP 735 groups."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    direct_scopes: dict[str, str] = {}

    for requirement in project.get("dependencies", []):
        name = normalize_name(requirement_name(requirement))
        direct_scopes[name] = "direct runtime"

    for group, requirements in project.get("optional-dependencies", {}).items():
        for requirement in requirements:
            name = normalize_name(requirement_name(requirement))
            scope = f"direct {group}"
            direct_scopes.setdefault(name, scope)

    for group, requirements in data.get("dependency-groups", {}).items():
        for requirement in requirements:
            if not isinstance(requirement, str):
                raise ValueError(
                    f"dependency group {group!r} contains an unsupported non-string entry"
                )
            name = normalize_name(requirement_name(requirement))
            direct_scopes.setdefault(name, f"direct {group}")

    return direct_scopes


def installed_distributions() -> dict[str, metadata.Distribution]:
    """Index installed distributions by normalized package name."""
    distributions: dict[str, metadata.Distribution] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            distributions[normalize_name(name)] = distribution
    return distributions


def dependency_closure(
    direct_scopes: dict[str, str],
    distributions: dict[str, metadata.Distribution],
) -> set[str]:
    """Walk installed requirements reachable from direct dependencies."""
    seen: set[str] = set()
    queue: deque[str] = deque(direct_scopes)

    while queue:
        name = queue.popleft()
        if name in seen or name not in distributions:
            continue
        seen.add(name)
        for requirement in distributions[name].requires or []:
            try:
                parsed = Requirement(requirement) if Requirement is not None else None
                if parsed is not None and parsed.marker is not None:
                    # Evaluate optional-extra markers with no implicit extras enabled.
                    if not parsed.marker.evaluate({"extra": ""}):
                        continue
                required_name = normalize_name(
                    parsed.name if parsed is not None else requirement_name(requirement)
                )
            except Exception:
                continue
            if required_name in distributions and required_name not in seen:
                queue.append(required_name)

    return seen


def classifier_license(distribution: metadata.Distribution) -> str | None:
    """Extract the most specific license classifier when available."""
    classifiers = distribution.metadata.get_all("Classifier") or []
    for classifier in classifiers:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return None


def clean_license(distribution: metadata.Distribution) -> str:
    """Prefer concise license metadata and avoid dumping full license text into a table."""
    raw_license = (
        distribution.metadata.get("License-Expression")
        or distribution.metadata.get("License")
        or ""
    ).strip()
    if raw_license and len(raw_license) <= 80 and "\n" not in raw_license:
        return raw_license
    classifier = classifier_license(distribution)
    if classifier:
        return classifier
    if raw_license:
        return "See package metadata"
    return "UNKNOWN"


def project_urls(distribution: metadata.Distribution) -> list[tuple[str, str]]:
    """Parse project URL metadata into label/url pairs."""
    urls: list[tuple[str, str]] = []
    home_page = distribution.metadata.get("Home-page")
    if home_page:
        urls.append(("Homepage", home_page))
    for value in distribution.metadata.get_all("Project-URL") or []:
        if "," in value:
            label, url = value.split(",", 1)
            urls.append((label.strip(), url.strip()))
    return urls


def preferred_url(distribution: metadata.Distribution) -> str:
    """Select a stable package URL, preferring source or homepage over support pages."""
    urls = project_urls(distribution)
    preferred_labels = ("repository", "source", "homepage", "documentation", "docs")
    for preferred in preferred_labels:
        for label, url in urls:
            if preferred in label.lower():
                return url
    if urls:
        return urls[0][1]
    package_name = distribution.metadata.get("Name", "")
    if package_name:
        return f"https://pypi.org/project/{package_name}/"
    return "UNKNOWN"


def build_rows() -> list[DependencyRow]:
    """Build sorted dependency rows for direct and transitive installed packages."""
    direct_scopes = load_direct_dependencies()
    distributions = installed_distributions()
    names = dependency_closure(direct_scopes, distributions)
    missing_direct = set(direct_scopes) - set(distributions)
    locked_versions: dict[str, set[str]] = {}
    for package in tomllib.loads(UV_LOCK.read_text(encoding="utf-8")).get("package", []):
        locked_versions.setdefault(normalize_name(package["name"]), set()).add(package["version"])

    rows: list[DependencyRow] = []
    for normalized_name in sorted(names):
        distribution = distributions[normalized_name]
        name = distribution.metadata.get("Name", normalized_name)
        # CPU wheels retain the same upstream release/license but add a local
        # version suffix. List exact locked variants together so macOS and the
        # Linux deployment produce the same inventory without losing that suffix.
        base_version = distribution.version.split("+", 1)[0]
        variants = sorted(
            version
            for version in locked_versions.get(normalized_name, set())
            if version.split("+", 1)[0] == base_version
        )
        rows.append(
            DependencyRow(
                ecosystem="Python",
                name=name,
                normalized_name=normalized_name,
                version=" / ".join(variants) if variants else distribution.version,
                scope=direct_scopes.get(normalized_name, "transitive"),
                license=clean_license(distribution),
                url=preferred_url(distribution),
            )
        )

    for normalized_name in sorted(missing_direct):
        rows.append(
            DependencyRow(
                ecosystem="Python",
                name=normalized_name,
                normalized_name=normalized_name,
                version="not installed",
                scope=direct_scopes[normalized_name],
                license="UNKNOWN",
                url="UNKNOWN",
            )
        )

    return sorted(rows, key=row_sort_key)


def npm_name_from_lock_path(lock_path: str) -> str:
    """Return an npm package name from a package-lock v3 package path."""
    marker = "node_modules/"
    if marker not in lock_path:
        raise ValueError(f"unsupported npm lock package path: {lock_path}")
    return lock_path.rsplit(marker, maxsplit=1)[1]


def build_npm_rows(
    project_path: Path = NPM_PROJECT,
    lock_path: Path = NPM_LOCK,
) -> list[DependencyRow]:
    """Build deterministic rows from the committed npm lockfile."""
    if not project_path.exists() and not lock_path.exists():
        return []
    if not project_path.exists() or not lock_path.exists():
        raise FileNotFoundError("both package.json and package-lock.json must be committed")

    project = json.loads(project_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    runtime = set(project.get("dependencies", {}))
    development = set(project.get("devDependencies", {}))
    lock_root = lock.get("packages", {}).get("", {})
    for field in ("dependencies", "devDependencies"):
        if lock_root.get(field, {}) != project.get(field, {}):
            raise ValueError(f"package-lock.json is stale for package.json field {field!r}")
    rows: list[DependencyRow] = []
    for package_path, package in lock.get("packages", {}).items():
        if not package_path:
            continue
        name = npm_name_from_lock_path(package_path)
        is_top_level = package_path == f"node_modules/{name}"
        if is_top_level and name in runtime:
            scope = "direct runtime"
        elif is_top_level and name in development:
            scope = "direct dev"
        else:
            scope = "transitive"
        rows.append(
            DependencyRow(
                ecosystem="Node",
                name=name,
                normalized_name=name.lower(),
                version=package.get("version", "UNKNOWN"),
                scope=scope,
                license=package.get("license", "UNKNOWN"),
                url=f"https://www.npmjs.com/package/{name}",
            )
        )
    return sorted(rows, key=row_sort_key)


def row_sort_key(row: DependencyRow) -> tuple[str, tuple[int, str], str, str]:
    """Sort by ecosystem, scope, package name, and version."""
    return (row.ecosystem, scope_sort_key(row.scope), row.normalized_name, row.version)


def scope_sort_key(scope: str) -> tuple[int, str]:
    """Put direct runtime, direct development, then transitive dependencies in order."""
    if scope == "direct runtime":
        return (0, scope)
    if scope.startswith("direct "):
        return (1, scope)
    return (2, scope)


def markdown_table(rows: list[DependencyRow]) -> str:
    """Render the dependency rows as a Markdown table."""
    lines = [
        "| Ecosystem | Framework / package | Version | Scope | License | URL |",
        "|---|---|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{escape_cell(row.ecosystem)} | "
            f"{escape_cell(row.name)} | "
            f"{escape_cell(row.version)} | "
            f"{escape_cell(row.scope)} | "
            f"{escape_cell(row.license)} | "
            f"{format_url(row.url)} |"
        )
    return "\n".join(lines)


def escape_cell(value: str) -> str:
    """Escape table separators and normalize whitespace in Markdown cell values."""
    return " ".join(value.replace("|", "\\|").split())


def format_url(url: str) -> str:
    """Render known URLs as links while keeping UNKNOWN visible."""
    if url == "UNKNOWN":
        return url
    escaped = escape_cell(url)
    return f"[{escaped}]({escaped})"


def render_document(rows: list[DependencyRow]) -> str:
    """Render the complete license inventory document."""
    unknown_licenses = sum(1 for row in rows if row.license == "UNKNOWN")
    unknown_urls = sum(1 for row in rows if row.url == "UNKNOWN")
    direct_runtime = sum(1 for row in rows if row.scope == "direct runtime")
    direct_other = sum(
        1 for row in rows if row.scope.startswith("direct ") and row.scope != "direct runtime"
    )
    transitive = sum(1 for row in rows if row.scope == "transitive")
    python_packages = sum(1 for row in rows if row.ecosystem == "Python")
    node_packages = sum(1 for row in rows if row.ecosystem == "Node")

    return "\n".join(
        [
            "<!--",
            "SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>",
            "SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>",
            "SPDX-License-" "Identifier: LicenseRef-Idiap-Research-Education",
            "-->",
            "",
            "# Dependency Licenses",
            "",
            "This inventory is generated from the locked RULER dependency definitions:",
            "`pyproject.toml` with `uv.lock`, plus `codex-app-workbench/package.json` with",
            "its `package-lock.json`. Python license metadata comes from the active locked",
            "`uv` environment; Node metadata comes from the npm lockfile. It is an",
            "engineering attribution aid, not legal advice.",
            "",
            f"Generation command: `{GENERATION_COMMAND}`",
            "",
            "## Summary",
            "",
            f"- Total packages: {len(rows)}",
            f"- Python packages: {python_packages}",
            f"- Node packages: {node_packages}",
            f"- Direct runtime dependencies: {direct_runtime}",
            f"- Direct development dependencies: {direct_other}",
            f"- Transitive dependencies: {transitive}",
            f"- Packages with unknown license metadata: {unknown_licenses}",
            f"- Packages with unknown URL metadata: {unknown_urls}",
            "",
            "## Inventory",
            "",
            markdown_table(rows),
            "",
            "## Regeneration",
            "",
            "Run:",
            "",
            "```bash",
            GENERATION_COMMAND,
            "```",
            "",
            "To verify that the committed inventory is current without rewriting it, run:",
            "",
            "```bash",
            f"{GENERATION_COMMAND} --check",
            "```",
            "",
            "Review any `UNKNOWN` entries against upstream package metadata before external",
            "publication.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the committed inventory differs from generated content",
    )
    return parser.parse_args()


def main() -> None:
    """Generate the dependency license Markdown document."""
    args = parse_args()
    if not UV_LOCK.exists():
        raise FileNotFoundError("uv.lock is required for a reproducible Python inventory")
    rows = [*build_rows(), *build_npm_rows()]
    document = render_document(sorted(rows, key=row_sort_key))
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != document:
            raise SystemExit(
                "dependency license inventory is stale; run the generator without --check"
            )
        print(f"verified {OUTPUT.relative_to(REPO_ROOT)} with {len(rows)} packages")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(document, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} with {len(rows)} packages")


if __name__ == "__main__":
    main()
