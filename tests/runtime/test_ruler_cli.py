# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Neutral Ruler CLI surfaces remain additive to the RULER compatibility CLI."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ruler.cli import main


def test_semantic_and_argumentation_cli_execute_real_checks(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("A must act.", encoding="utf-8")
    import hashlib

    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    basis = tmp_path / "basis.yaml"
    basis.write_text(
        "\n".join(
            [
                "basis_id: basis-1",
                "context_id: case-1",
                "spans:",
                "  - span_id: s1",
                "    artifact_id: law",
                f"    artifact_sha256: {digest}",
                "    exact_text: A must act.",
                "    start_char: 0",
                "    end_char: 11",
                "elements:",
                "  - element_id: e1",
                "    kind: proposition",
                "    predicate: must_act",
                "    source_span_ids: [s1]",
            ]
        ),
        encoding="utf-8",
    )
    semantic = CliRunner().invoke(
        main, ["semantic", "validate", str(basis), "--artifact", f"law={source}"]
    )
    assert semantic.exit_code == 0, semantic.output
    assert '"source_bound": true' in semantic.output

    framework = tmp_path / "arguments.yaml"
    framework.write_text(
        """framework_id: f1
context_id: case-1
finite_assumption: bounded complete graph
arguments:
  - argument_id: a1
    conclusion: allowed
    contrary: forbidden
    premise_ids: [p1]
    source_refs: [s1]
    context_id: case-1
relations: []
""",
        encoding="utf-8",
    )
    argumentation = CliRunner().invoke(
        main, ["arguments", "evaluate", str(framework), "--target", "allowed"]
    )
    assert argumentation.exit_code == 0, argumentation.output
    assert '"backend_equivalent": true' in argumentation.output


def test_formal_flow_cli_validates_digest_handoffs(tmp_path: Path) -> None:
    flow = tmp_path / "flow.yaml"
    digest = "sha256:" + "1" * 64
    flow.write_text(
        "\n".join(
            [
                "run_id: flow-1",
                "stages:",
                "  - stage_id: source",
                "    kind: source",
                "    performed_by: source-curator",
                "    input_digests: []",
                f"    output_digest: {digest}",
                "    status: completed",
                "handoffs: []",
                "release_authorized: false",
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, ["formal-flow", "validate", str(flow)])

    assert result.exit_code == 0, result.output
    assert '"status": "valid"' in result.output
    assert '"release_authorized": false' in result.output


def test_legal_cli_authenticates_source_against_manifest() -> None:
    result = CliRunner().invoke(
        main,
        [
            "legal",
            "validate-packet",
            "kb/corpora/legal-sr101-art36/candidate/art36_packet.yaml",
            "--manifest",
            "kb/corpora/legal-sr101-art36/manifest.yaml",
            "--repo-root",
            ".",
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"source_bound": true' in result.output
    assert '"proofs_verified": false' in result.output


def test_domain_and_corpus_commands_expose_all_verticals() -> None:
    runner = CliRunner()

    domains = runner.invoke(main, ["domains", "list"])
    assert domains.exit_code == 0, domains.output
    assert "retired_application" not in domains.output
    assert "legal" in domains.output
    assert "regulatory" in domains.output

    corpora = runner.invoke(main, ["corpora", "list"])
    assert corpora.exit_code == 0, corpora.output
    assert "regulatory-proof" in corpora.output
    assert "legal-sr101-art36" in corpora.output
    assert "regulatory-proof" in corpora.output

    validation = runner.invoke(main, ["corpora", "validate"])
    assert validation.exit_code == 0, validation.output
    assert "corpora=12" in validation.output
    assert "artifacts=21" in validation.output


def test_regulatory_proof_evaluates_without_recommendation() -> None:
    result = CliRunner().invoke(
        main, ["evaluate", "regulatory-proof", "--case", "satisfied_boundary"]
    )
    assert result.exit_code == 0, result.output
    assert '"case_id": "satisfied_boundary"' in result.output
    assert '"status": "satisfied"' in result.output
    assert "customer" not in result.output.lower()
    assert "product" not in result.output.lower()


def test_ruler_script_and_safe_migration_surface_are_declared() -> None:
    payload = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'ruler = "ruler.cli:main"' in payload

    help_result = CliRunner().invoke(main, ["migrate", "artifacts", "--help"])
    assert help_result.exit_code == 0
    assert "--apply" in help_result.output
    assert "--accept-ambiguities" in help_result.output
    assert "--accept-losses" in help_result.output


def test_deterministic_workflow_executes_every_registered_validator(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "ruler.runtime.workflow_registry.load_workflow_registry",
        lambda: {
            "workflows": [
                {
                    "id": "test-deterministic",
                    "validators": ["uv run pytest -q", "uv run ruff check .", "git diff --check"],
                }
            ]
        },
    )
    monkeypatch.setattr(
        "ruler.runtime.workflow_registry.resolve_cli_command", lambda _command: None
    )

    def run(args, **_kwargs):
        calls.append(args)
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("ruler.cli.subprocess.run", run)
    result = CliRunner().invoke(main, ["workflow", "test-deterministic"])

    assert result.exit_code == 0, result.output
    assert calls == [
        ["uv", "run", "pytest", "-q"],
        ["uv", "run", "ruff", "check", "."],
        ["git", "diff", "--check"],
    ]
