# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Plugin discovery, isolated distribution and read-only drift validation."""

import json
import tomllib

import pytest
from reuse.global_licensing import ReuseTOML

from ruler.paths import REPO_ROOT
from ruler.runtime.plugins import (
    RUNTIME_INSTRUCTIONS,
    prepare_plugin_package,
    refresh_plugin_manifests,
    validate_plugin_catalogue,
)


@pytest.fixture
def catalogue(tmp_path):
    from shutil import copytree

    (tmp_path / "pyproject.toml").write_text('[project]\nname="ruler"\nversion="1.0.0"\n')
    (tmp_path / "REUSE.toml").write_text((REPO_ROOT / "REUSE.toml").read_text())
    copytree(REPO_ROOT / "LICENSES", tmp_path / "LICENSES")
    copytree(REPO_ROOT / "plugin", tmp_path / "plugin")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/private.txt").write_text("private")
    refresh_plugin_manifests(tmp_path)
    return tmp_path


def test_both_hosts_discover_only_the_four_product_skills():
    assert validate_plugin_catalogue() == []
    expected = {p.parent.name for p in (REPO_ROOT / "plugin/skills").glob("*/SKILL.md")}
    for host in ("codex", "claude"):
        manifest = json.loads((REPO_ROOT / f".{host}-plugin/plugin.json").read_text())
        paths = manifest["skills"]
        paths = [paths] if isinstance(paths, str) else paths
        discovered = {
            p.parent.name for relative in paths for p in (REPO_ROOT / relative).rglob("SKILL.md")
        }
        assert discovered == expected


def test_package_is_flat_self_contained_and_copies_skill_resources(catalogue):
    for name in ("data", "kb", "refs", ".claude", ".idiap-sd", "proj_skills"):
        private = catalogue / name / "private.txt"
        private.parent.mkdir(exist_ok=True)
        private.write_text("must not ship")
    package = prepare_plugin_package(catalogue) / "ruler"
    assert sorted(p.parent.name for p in (package / "skills").glob("*/SKILL.md")) == [
        "ruler-execute-reasoning",
        "ruler-prepare-knowledge",
        "ruler-prepare-request",
        "ruler-retrieve-results",
    ]
    for source in (catalogue / "plugin/skills").glob("*"):
        for file in source.rglob("*"):
            if file.is_file():
                assert (
                    package / "skills" / source.name / file.relative_to(source)
                ).read_bytes() == file.read_bytes()
    assert not any(p.name == "private.txt" for p in package.rglob("*"))
    assert not any(p.is_symlink() for p in package.rglob("*"))
    licensing = ReuseTOML.from_file(package / "REUSE.toml")
    for skill in (package / "skills").glob("*/SKILL.md"):
        annotation = licensing.find_annotations_item(skill.relative_to(package))
        assert annotation is not None
        assert {str(expression) for expression in annotation.spdx_expressions} == {"LicenseRef-Idiap-Research-Education"}
        assert annotation.copyright_notices
    license_name = "LicenseRef-Idiap-Research-Education.txt"
    assert (package / "LICENSES" / license_name).read_bytes() == (
        catalogue / "LICENSES" / license_name
    ).read_bytes()
    manifest = json.loads((package / "plugin.json").read_text())
    assert manifest["name"] == "ruler"
    assert manifest["license"] == "LicenseRef-Idiap-Research-Education"
    for host in ("codex", "claude"):
        manifest = json.loads((package / f".{host}-plugin/plugin.json").read_text())
        assert manifest["skills"] == "./skills/"
    marketplace = json.loads((package.parent / ".claude-plugin/marketplace.json").read_text())
    assert (package.parent / marketplace["plugins"][0]["source"]).resolve() == package


def test_validation_detects_drift_without_repairing_files(catalogue):
    path = catalogue / ".claude-plugin/plugin.json"
    value = json.loads(path.read_text())
    value["skills"].pop()
    path.write_text(json.dumps(value))
    before = {p: p.read_bytes() for p in catalogue.rglob("*") if p.is_file()}
    assert any("stale" in e for e in validate_plugin_catalogue(catalogue))
    assert {p: p.read_bytes() for p in before} == before


def test_rebuild_removes_stale_exports_and_is_deterministic(catalogue):
    output = prepare_plugin_package(catalogue)
    obsolete = output / "ruler/skills/stale/SKILL.md"
    obsolete.parent.mkdir()
    obsolete.write_text("old generated skill")
    prepare_plugin_package(catalogue)
    assert not obsolete.exists()
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    prepare_plugin_package(catalogue)
    assert {
        p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()
    } == before


def test_package_refuses_symlinks_and_unmanaged_output(catalogue, tmp_path):
    output = catalogue / "build/ruler/plugins"
    output.mkdir(parents=True)
    sentinel = output / "local.txt"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match="unmanaged"):
        prepare_plugin_package(catalogue)
    assert sentinel.read_text() == "keep"
    external = tmp_path / "external.txt"
    external.write_text("private")
    (catalogue / "plugin/skills/ruler-prepare-knowledge/leak").symlink_to(external)
    assert any("symlink" in e for e in validate_plugin_catalogue(catalogue))


def test_catalogue_rejects_extra_product_exports(catalogue):
    extra = catalogue / "plugin/skills/extra-tool/SKILL.md"
    extra.parent.mkdir(parents=True)
    extra.write_text(
        "---\nname: extra-tool\ndescription: Extra workflow\n---\n" + RUNTIME_INSTRUCTIONS
    )
    assert any("exactly the four" in e for e in validate_plugin_catalogue(catalogue))


def test_catalogue_rejects_nested_skill_exports(catalogue):
    extra = catalogue / "plugin/skills/ruler-prepare-knowledge/references/hidden/SKILL.md"
    extra.parent.mkdir(parents=True)
    extra.write_text("---\nname: hidden\ndescription: Hidden workflow\n---\n")
    assert any("nested skill exports" in e for e in validate_plugin_catalogue(catalogue))


def test_skill_definitions_use_exact_manifest_licensing():
    licensing = ReuseTOML.from_file(REPO_ROOT / "REUSE.toml")
    for root in ("skills", "proj_skills"):
        for skill in (REPO_ROOT / root).rglob("SKILL.md"):
            assert "SPDX-" not in skill.read_text()
            annotation = licensing.find_annotations_item(skill.relative_to(REPO_ROOT))
            assert annotation is not None
            assert {str(expression) for expression in annotation.spdx_expressions} == {"LicenseRef-Idiap-Research-Education"}
            assert annotation.copyright_notices


def test_commentable_skill_resources_use_headers():
    licensing = ReuseTOML.from_file(REPO_ROOT / "REUSE.toml")
    for directory in ("skills", "proj_skills"):
        for path in (REPO_ROOT / directory).rglob("*"):
            if not path.is_file() or path.suffix not in {".md", ".py", ".yaml", ".yml", ".json"}:
                continue
            annotation = licensing.find_annotations_item(path.relative_to(REPO_ROOT))
            if path.name == "SKILL.md" or path.suffix == ".json":
                assert annotation is not None, path
            else:
                assert annotation is None, path
                assert "SPDX-FileCopyrightText:" in path.read_text()



def test_generated_plugin_metadata_uses_exact_paths_and_readme_headers(catalogue):
    package = prepare_plugin_package(catalogue) / "ruler"
    for root in (package.parent, package):
        licensing = tomllib.loads((root / "REUSE.toml").read_text())
        for annotation in licensing["annotations"]:
            for relative in annotation["path"]:
                assert "*" not in relative
                assert (root / relative).is_file()
                assert relative != "README.md"
        assert "SPDX-FileCopyrightText:" in (root / "REUSE.toml").read_text()
    assert "SPDX-" not in (package / "plugin.json").read_text()
    assert "SPDX-FileCopyrightText:" in (package / "README.md").read_text()
