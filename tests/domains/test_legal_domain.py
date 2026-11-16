# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from copy import deepcopy

import pytest
import yaml
from click.testing import CliRunner
from pydantic import ValidationError

from ruler.assurance import (
    BackendCapability,
    BackendProfile,
    BackendRouter,
    ProjectionLoss,
    ProjectionPolicy,
    ReasoningQuery,
    ReasoningResultAxes,
)
from ruler.cli import main
from ruler.domains.base import validate_domain_pack
from ruler.domains.legal import LEGAL_DOMAIN_PACK, LegalReasoningPacket, assess_legal_packet
from ruler.paths import REPO_ROOT

PACKET_PATH = REPO_ROOT / "kb/corpora/legal-sr101-art36/candidate/art36_packet.yaml"


def _payload() -> dict[str, object]:
    return yaml.safe_load(PACKET_PATH.read_text(encoding="utf-8"))


def test_legal_pack_and_candidate_packet_validate_without_promoting() -> None:
    validate_domain_pack(LEGAL_DOMAIN_PACK)
    packet = LegalReasoningPacket.model_validate(_payload())
    report = assess_legal_packet(packet)
    assert report.status == "blocked"
    assert not report.source_bound
    assert "material_legal_claim_not_exactly_source_bound" in report.blockers
    assert not report.fit_for_legal_reliance
    assert report.live_defeater_claim_ids == ("danger-exception",)
    assert "formal_proof_obligations_incomplete" in report.blockers


def test_exact_source_mutation_and_dangling_claim_fail_closed() -> None:
    changed = deepcopy(_payload())
    changed["source_spans"][0]["exact_text"] += " changed"
    with pytest.raises(ValidationError, match="digest mismatch"):
        LegalReasoningPacket.model_validate(changed)

    dangling = deepcopy(_payload())
    dangling["arguments"][0]["premise_claim_ids"].append("missing-claim")
    with pytest.raises(ValidationError, match="unknown claims"):
        LegalReasoningPacket.model_validate(dangling)


def test_duplicate_identity_and_temporal_reversal_fail_closed() -> None:
    duplicate = deepcopy(_payload())
    duplicate["claims"].append(deepcopy(duplicate["claims"][0]))
    with pytest.raises(ValidationError, match="identifiers must be unique"):
        LegalReasoningPacket.model_validate(duplicate)

    reversed_time = deepcopy(_payload())
    reversed_time["authorities"][0]["temporal_scope"]["valid_to"] = "1999-01-01"
    with pytest.raises(ValidationError, match="valid_from must not be after valid_to"):
        LegalReasoningPacket.model_validate(reversed_time)


def test_capability_router_rejects_projection_loss_and_routes_preserved_semantics() -> None:
    profile = BackendProfile(
        backend_id="asp",
        engine="clingo",
        capabilities=frozenset(
            {BackendCapability.STABLE_MODELS, BackendCapability.DEFAULT_NEGATION}
        ),
        native_execution="built_in",
        evidence_boundary="Stable-model evidence for the declared encoding only.",
    )
    query = ReasoningQuery(
        query_id="q1",
        target="candidate_conclusion",
        contrary="not_candidate_conclusion",
        world_policy="bounded",
        required_capabilities=frozenset({BackendCapability.DEFAULT_NEGATION}),
    )
    blocked = ProjectionPolicy(
        policy_id="lossy",
        source_semantics="defeasible",
        target_backend_id="asp",
        losses=(
            ProjectionLoss(
                construct_id="burden",
                disposition="unsupported",
                explanation="No burden encoding.",
                blocks_execution=True,
            ),
        ),
    )
    with pytest.raises(LookupError, match="no semantics-preserving backend"):
        BackendRouter((profile,)).route(query, (blocked,))

    preserved = ProjectionPolicy(
        policy_id="preserved",
        source_semantics="bounded_stable_model",
        target_backend_id="asp",
        losses=(
            ProjectionLoss(
                construct_id="default_negation",
                disposition="preserved",
                explanation="Native ASP semantics.",
                blocks_execution=False,
            ),
        ),
    )
    assert BackendRouter((profile,)).route(query, (preserved,)) == (profile,)


def test_non_execution_cannot_fabricate_support_or_output() -> None:
    with pytest.raises(ValidationError, match="non-completed execution cannot have an output"):
        ReasoningResultAxes(
            query_id="q1",
            backend_id="vampire",
            execution="unavailable",
            consistency="unknown",
            target_support="unknown",
            contrary_support="unknown",
            dependency_closure="blocked",
            proof_object="absent",
            output_digest="sha256:" + "0" * 64,
        )


def test_legal_cli_exposes_domain_and_assurance_boundary() -> None:
    runner = CliRunner()
    domains = runner.invoke(main, ["domains", "list"])
    assert domains.exit_code == 0
    assert "legal schema=1.0" in domains.output
    result = runner.invoke(main, ["legal", "validate-packet", str(PACKET_PATH)])
    assert result.exit_code == 0
    assert '"fit_for_legal_reliance": false' in result.output
