# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Candidate KB visualization stays grounded, executable, and uncommitted."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from types import SimpleNamespace

import clingo
import pytest

from ruler.applications.resource_portfolio.demonstrator_formal_kb import (
    verify_candidate_formal_kb,
    write_candidate_formal_kb,
)
from ruler.applications.resource_portfolio.demonstrator_approved_kb import (
    ACCEPTANCE_RECEIPT_FILENAME,
    ACCEPTED_ASP_FILENAME,
    ACCEPTED_PROLOG_FILENAME,
    FORMAL_LOGIC_RELEASE_FILENAME,
    AcceptedFormalKBReceipt,
    assess_formal_kb_acceptance,
    verify_approved_formal_kb,
    write_approved_formal_kb,
)
from ruler.interfaces.autoformalization_visualizer import (
    build_autoformalization_visualization,
    write_autoformalization_visualizer_artifact,
)
from ruler.ingestion.contracts import canonical_sha256
from ruler.io import read_yaml
from ruler.kb.formalization import (
    PredicateRegistry,
    PredicateSignature,
    ValueType,
    WorldAssumption,
)
from ruler.kb.generative_autoformalization import (
    AutoformalizationRequest,
    parse_autoformalization_candidate,
)

SOURCE = "Excavator alpha (excavator_alpha) provides digging. </script>"


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _request() -> AutoformalizationRequest:
    return AutoformalizationRequest(
        request_id="visual-candidate-1",
        artifact_id="synthetic:fleet-dossier",
        artifact_sha256=_sha(SOURCE),
        source_text=SOURCE,
        source_version="v1",
        context_id="fleet-demo",
        domain_id="construction_fleet",
        allowed_predicates=("resource_provides",),
        predicate_registry=PredicateRegistry(
            signatures=(
                PredicateSignature(
                    name="resource_provides",
                    argument_names=("resource", "capability"),
                    argument_types=(ValueType.ENTITY_ID, ValueType.ENTITY_ID),
                    family="fleet-demo",
                    world_assumption=WorldAssumption.OPEN,
                ),
            )
        ),
    )


def _candidate(request: AutoformalizationRequest):
    return parse_autoformalization_candidate(
        request,
        {
            "request_id": request.request_id,
            "basis_id": "basis-1",
            "program_id": "fleet-candidate-1",
            "program_version": "candidate-1",
            "spans": [
                {
                    "span_id": "span-capability",
                    "section_id": "fleet",
                    "exact_text": SOURCE,
                    "start_char": 0,
                    "end_char": len(SOURCE),
                }
            ],
            "elements": [
                {
                    "element_id": "element-capability",
                    "kind": "proposition",
                    "predicate": "resource_provides",
                    "modality": "asserted",
                    "polarity": "positive",
                    "connective": "none",
                    "value": None,
                    "unit": None,
                    "source_span_ids": ["span-capability"],
                    "temporal": None,
                }
            ],
            "rules": [
                {
                    "statement_id": "fact-resource-capability",
                    "modality": "fact",
                    "head": {
                        "predicate": "resource_provides",
                        "arguments": [
                            {
                                "kind": "constant",
                                "role": "resource",
                                "value_type": "entity_id",
                                "name": None,
                                "value": "excavator_alpha",
                                "unit": None,
                            },
                            {
                                "kind": "constant",
                                "role": "capability",
                                "value_type": "entity_id",
                                "name": None,
                                "value": "digging",
                                "unit": None,
                            },
                        ],
                        "classical_negation": False,
                    },
                    "body_connective": "atom",
                    "body_atoms": [],
                    "source_element_ids": ["element-capability"],
                    "source_span_ids": ["span-capability"],
                }
            ],
            "dimensions": [
                {
                    "dimension": "actors",
                    "disposition": "represented",
                    "explanation": "Resource and capability are explicit.",
                    "query_affecting": True,
                    "element_ids": ["element-capability"],
                }
            ],
            "represented_element_ids": ["element-capability"],
            "omitted_element_ids": [],
            "symbol_mappings": [
                {
                    "element_id": "element-capability",
                    "engine_symbol": "resource_provides/2",
                }
            ],
            "uncertainties": [],
        },
        provider="test-contract",
        model="not-invoked",
    )


def _formalization_run(request: AutoformalizationRequest):
    """Provide the exact artifact-writer surface without fabricating a full workflow."""

    return SimpleNamespace(
        request=request,
        source_digest=request.artifact_sha256,
        candidate=_candidate(request),
        refinement=SimpleNamespace(run_sha256=_sha("refinement-run")),
        solver_authority=SimpleNamespace(solver_use_permitted=False),
        kb_profile="compact",
        expected_claim_coverage=(
            SimpleNamespace(
                claim_id="claim-resource-capability",
                candidate_element_ids=("element-capability",),
            ),
        ),
        run_digest=_sha("formalization-run"),
    )


def test_candidate_visualization_is_source_verified_and_compiler_backed() -> None:
    request = _request()
    model = build_autoformalization_visualization(request, _candidate(request))

    assert model.lifecycle == "candidate_uncommitted"
    assert model.publication_status == "not_published"
    assert model.solver_authority == "blocked"
    assert model.spans[0].verification == "exact_source_match"
    assert model.rules[0].compiled_asp == 'resource_provides("excavator_alpha","digging").'
    assert {(edge.relation, edge.source_id, edge.target_id) for edge in model.graph_edges} >= {
        ("grounds", "span-capability", "element-capability"),
        ("supports", "element-capability", "fact-resource-capability"),
        (
            "concludes",
            "fact-resource-capability",
            "predicate:resource_provides",
        ),
    }


def test_candidate_visualizer_is_self_contained_and_script_safe(tmp_path) -> None:
    request = _request()
    candidate = _candidate(request)
    output = write_autoformalization_visualizer_artifact(
        request, candidate, tmp_path / "candidate_rules.html"
    )
    html = output.read_text(encoding="utf-8")

    assert "CANDIDATE · UNCOMMITTED · SOLVER AUTHORITY BLOCKED" in html
    assert "Autoformalized rule graph" in html
    assert "Compiler-validated ASP" in html
    assert "<script src=" not in html
    assert "<link rel=" not in html
    assert SOURCE not in html  # the source's closing script marker is JSON-escaped
    match = re.search(
        r'<script id="candidate-kb-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert payload["source_text"] == SOURCE
    assert payload["rules"][0]["source_span_ids"] == ["span-capability"]


def test_accepted_visualizer_presents_release_status_not_candidate_status(tmp_path) -> None:
    request = _request()
    output = write_autoformalization_visualizer_artifact(
        request,
        _candidate(request),
        tmp_path / "accepted_rules.html",
        accepted=True,
    )
    rendered = output.read_text(encoding="utf-8")

    assert "RULER / Accepted knowledge explorer" in rendered
    assert "ACCEPTED · ACTIVE · LOGICAL-RUNTIME AUTHORITY" in rendered
    assert "<h2>Accepted rules</h2>" in rendered
    assert "Every source-linked statement passed automatic acceptance" in rendered
    assert "CANDIDATE · UNCOMMITTED · SOLVER AUTHORITY BLOCKED" not in rendered


def test_candidate_formal_kbs_are_solver_native_executable_artifacts(tmp_path) -> None:
    request = _request()
    run = _formalization_run(request)
    receipt = write_candidate_formal_kb(run, tmp_path)
    asp_path = tmp_path / "candidate_kb.lp"
    prolog_path = tmp_path / "candidate_kb.pl"
    asp = asp_path.read_text(encoding="utf-8")
    prolog = prolog_path.read_text(encoding="utf-8")

    assert [item.filename for item in receipt.artifacts] == [
        "candidate_kb.lp",
        "candidate_kb.pl",
    ]
    for source in (asp, prolog):
        assert "SPDX-" not in source
        assert "% lifecycle: candidate_uncommitted" in source
        assert "% activation-status: blocked" in source
        assert "% solver-use-permitted: false" in source
        assert "% authority: none_candidate_artifact" in source
        assert not source.lstrip().startswith(("{", "[", "---"))

    control = clingo.Control(["--warn=none", "--models=1"])
    control.load(str(asp_path))
    control.ground([("base", [])])
    assert control.solve().satisfiable

    swipl = shutil.which("swipl")
    if swipl is None:
        pytest.skip("SWI-Prolog is unavailable; canonical compilation was still exercised")
    completed = subprocess.run(
        [swipl, "--quiet", "--no-signals", "-t", "halt", "-s", str(prolog_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("filename", ["candidate_kb.lp", "candidate_kb.pl"])
def test_candidate_formal_kb_verifier_rejects_json_masquerading_as_logic(
    tmp_path, filename: str
) -> None:
    request = _request()
    run = _formalization_run(request)
    receipt = write_candidate_formal_kb(run, tmp_path)
    (tmp_path / filename).write_text(
        json.dumps({"logical_program": run.candidate.logical_program.model_dump(mode="json")}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="differs from typed IR"):
        verify_candidate_formal_kb(run, tmp_path, receipt)


def test_automatic_acceptance_covers_every_statement_and_writes_real_kbs(tmp_path) -> None:
    run = _formalization_run(_request())
    receipt = write_approved_formal_kb(run, tmp_path)
    statement_ids = tuple(
        sorted(item.statement_id for item in run.candidate.logical_program.statements)
    )

    assert receipt.approved_statement_ids == statement_ids
    assert receipt.accepted_claim_ids == ("claim-resource-capability",)
    assert receipt.accepted_claim_count == len(receipt.accepted_claim_ids)
    assert tuple(item.statement_id for item in receipt.statement_assessments) == statement_ids
    assert all(item.accepted for item in receipt.statement_assessments)
    assert all(
        item.passed_gate_ids
        == (
            "static_semantics",
            "asp_compile_execute",
            "prolog_compile_load",
            "asp_prolog_crosscheck",
        )
        for item in receipt.statement_assessments
    )
    assert receipt.automatic_review_decision.logical_unit_ids == statement_ids
    assert receipt.lifecycle == "accepted"
    assert receipt.acceptance_status == "accepted"
    assert receipt.activation_status == "active"
    assert receipt.solver_use_permitted is True
    assert receipt.portfolio_optimization_authority is False

    asp_path = tmp_path / ACCEPTED_ASP_FILENAME
    prolog_path = tmp_path / ACCEPTED_PROLOG_FILENAME
    assert asp_path.is_file()
    assert prolog_path.is_file()
    assert (tmp_path / FORMAL_LOGIC_RELEASE_FILENAME).is_file()
    assert (tmp_path / ACCEPTANCE_RECEIPT_FILENAME).is_file()
    assert receipt.formal_logic_release_sha256 == canonical_sha256(
        read_yaml(tmp_path / FORMAL_LOGIC_RELEASE_FILENAME)
    )
    for path in (asp_path, prolog_path):
        commented = path.read_text(encoding="utf-8")
        assert "% formal-kind: fact" in commented
        assert f"% natural-language: {SOURCE}" in commented

    control = clingo.Control(["--warn=none", "--models=1"])
    control.load(str(asp_path))
    control.ground([("base", [])])
    assert control.solve().satisfiable

    swipl = shutil.which("swipl")
    assert swipl is not None, "accepted formal KB validation requires SWI-Prolog"
    completed = subprocess.run(
        [
            swipl,
            "--quiet",
            "--no-signals",
            "-s",
            str(prolog_path),
            "-g",
            "resource_provides(excavator_alpha,digging)",
            "-t",
            "halt",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr

    for path in (
        asp_path,
        prolog_path,
        tmp_path / FORMAL_LOGIC_RELEASE_FILENAME,
        tmp_path / ACCEPTANCE_RECEIPT_FILENAME,
    ):
        rendered = path.read_text(encoding="utf-8").lower()
        assert "candidate_uncommitted" not in rendered
        assert "activation-status: blocked" not in rendered
        assert "none_candidate_artifact" not in rendered


@pytest.mark.parametrize(
    "filename",
    [
        ACCEPTED_ASP_FILENAME,
        ACCEPTED_PROLOG_FILENAME,
        FORMAL_LOGIC_RELEASE_FILENAME,
        ACCEPTANCE_RECEIPT_FILENAME,
    ],
)
def test_accepted_formal_kb_verification_fails_closed_on_tampering(tmp_path, filename: str) -> None:
    run = _formalization_run(_request())
    receipt = write_approved_formal_kb(run, tmp_path)
    path = tmp_path / filename
    comment = "% tampered" if path.suffix in {".lp", ".pl"} else "# tampered"
    path.write_text(path.read_text(encoding="utf-8") + f"\n{comment}\n", encoding="utf-8")

    with pytest.raises((ValueError, TypeError), match="differs|invalid|mapping|Extra inputs"):
        verify_approved_formal_kb(run, tmp_path, receipt)


def test_partial_automatic_approval_cannot_be_verified(tmp_path) -> None:
    run = _formalization_run(_request())
    receipt = write_approved_formal_kb(run, tmp_path)
    partial = receipt.model_copy(update={"approved_statement_ids": ()})

    with pytest.raises(ValueError, match="differs from deterministic regeneration"):
        verify_approved_formal_kb(run, tmp_path, partial)

    payload = receipt.model_dump(mode="json")
    payload["approved_statement_ids"] = []
    with pytest.raises(ValueError, match="at least 1 item|exactly cover"):
        AcceptedFormalKBReceipt.model_validate(payload)


def test_partial_claim_to_statement_closure_is_never_accepted(tmp_path) -> None:
    run = _formalization_run(_request())
    partial_run = SimpleNamespace(
        **{
            **vars(run),
            "expected_claim_coverage": (
                *run.expected_claim_coverage,
                SimpleNamespace(
                    claim_id="claim-without-logical-statement",
                    candidate_element_ids=("element-not-formalized",),
                ),
            ),
        }
    )

    with pytest.raises(ValueError, match="accepted claim has no approved logical statement"):
        write_approved_formal_kb(partial_run, tmp_path)
    assert not any(tmp_path.iterdir())


def test_final_invalid_program_is_assessed_for_repair_and_never_accepted(tmp_path) -> None:
    run = _formalization_run(_request())
    statement = run.candidate.logical_program.statements[0]
    invalid_head = statement.head.model_copy(update={"predicate": "invented_predicate"})
    invalid_statement = statement.model_copy(update={"head": invalid_head})
    invalid_program = run.candidate.logical_program.model_copy(
        update={"statements": (invalid_statement,)}
    )
    invalid_candidate = run.candidate.model_copy(update={"logical_program": invalid_program})
    invalid_run = SimpleNamespace(**{**vars(run), "candidate": invalid_candidate})

    assessment = assess_formal_kb_acceptance(invalid_run)
    assert assessment.promotable is False
    assert assessment.findings
    assert assessment.statements[0].accepted is False
    with pytest.raises(ValueError, match="formal KB acceptance failed"):
        write_approved_formal_kb(invalid_run, tmp_path)
    assert not any(tmp_path.iterdir())


def test_candidate_visualization_rejects_a_foreign_request() -> None:
    request = _request()
    candidate = _candidate(request)
    other = request.model_copy(update={"request_id": "foreign-request"})

    with pytest.raises(ValueError, match="request_id"):
        build_autoformalization_visualization(other, candidate)


def test_candidate_visualization_rejects_a_stale_projection_digest() -> None:
    request = _request()
    candidate = _candidate(request)
    changed_program = candidate.logical_program.model_copy(
        update={"version": "candidate-mutated-after-projection"}
    )
    mutated = candidate.model_copy(update={"logical_program": changed_program})

    with pytest.raises(ValueError, match="program_digest"):
        build_autoformalization_visualization(request, mutated)


def test_candidate_visualization_rejects_a_foreign_request_receipt() -> None:
    request = _request()
    candidate = _candidate(request)
    foreign_receipt = candidate.receipt.model_copy(
        update={"request_sha256": _sha("foreign request")}
    )
    mutated = candidate.model_copy(update={"receipt": foreign_receipt})

    with pytest.raises(ValueError, match="complete request"):
        build_autoformalization_visualization(request, mutated)
