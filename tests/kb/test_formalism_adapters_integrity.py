# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Executable-integrity checks for optional formalism adapters."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ruler.kb.formalism_adapters import (
    LeanAdapter,
    PrologCrosscheckAdapter,
    VampireAdapter,
    default_formalism_adapters,
)
from ruler.kb.prolog_compiler import ConclusionCheck, MirrorCrosscheckReport
from ruler.kb.workspace_contracts import KBInferenceRequest
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_inference import KBInferenceService


def _context(tmp_path: Path, source: str = ""):
    path = tmp_path / "artifact.txt"
    path.write_text(source, encoding="utf-8")
    kb = SimpleNamespace(kb_id="test-kb", current_version_id="v1", domain_id="general")
    artifact = SimpleNamespace(artifact_id="artifact", sha256="sha256:" + "a" * 64)
    catalog = SimpleNamespace(artifact_path=lambda _artifact: path)
    return kb, artifact, catalog


def test_prolog_crosscheck_requires_expectations_before_claiming_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    kb, artifact, catalog = _context(tmp_path)
    monkeypatch.setattr("ruler.kb.formalism_adapters.shutil.which", lambda _name: "/usr/bin/swipl")
    monkeypatch.setattr(
        "ruler.kb.formalism_adapters._logical_envelope",
        lambda _payload: (SimpleNamespace(statements=()), object()),
    )
    monkeypatch.setattr("ruler.kb.formalism_adapters._payload", lambda *_args: {})
    request = KBInferenceRequest(request_id="p", operation="crosscheck")

    with pytest.raises(ValueError, match="expectations"):
        PrologCrosscheckAdapter().execute(
            kb=kb, artifact=artifact, request=request, catalog=catalog
        )


def test_prolog_crosscheck_returns_only_after_backend_equivalence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    kb, artifact, catalog = _context(tmp_path)
    monkeypatch.setattr("ruler.kb.formalism_adapters.shutil.which", lambda _name: "/usr/bin/swipl")
    monkeypatch.setattr(
        "ruler.kb.formalism_adapters._logical_envelope",
        lambda _payload: (SimpleNamespace(statements=()), object()),
    )
    monkeypatch.setattr("ruler.kb.formalism_adapters._payload", lambda *_args: {})
    called = []

    def crosscheck(program, expectations, registry):
        called.append((program, expectations, registry))
        return MirrorCrosscheckReport(
            program_id="p",
            checks=(
                ConclusionCheck(
                    expectation_id="allowed-alice",
                    expected=True,
                    asp_observed=True,
                    prolog_observed=True,
                ),
            ),
        )

    monkeypatch.setattr("ruler.kb.formalism_adapters.crosscheck_asp_prolog", crosscheck)
    request = KBInferenceRequest(
        request_id="p",
        operation="crosscheck",
        query="allowed-alice",
        parameters={
            "expectations": [
                {
                    "expectation_id": "allowed-alice",
                    "expected": True,
                    "atom": {
                        "predicate": "allowed",
                        "arguments": [
                            {"kind": "constant", "value_type": "subject", "value": "alice"}
                        ],
                    },
                }
            ]
        },
    )

    result = PrologCrosscheckAdapter().execute(
        kb=kb, artifact=artifact, request=request, catalog=catalog
    )
    assert called
    assert result.status == "completed"
    assert result.conclusion == "supported"
    assert result.result["equivalent"] is True


@pytest.mark.parametrize(
    ("adapter", "source", "message"),
    [
        (VampireAdapter(), "fof(other,conjecture,$true).", "not declared"),
        (LeanAdapter(), "theorem other : True := by trivial", "not declared"),
    ],
)
def test_verify_refuses_an_unbound_requested_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    adapter,
    source: str,
    message: str,
) -> None:
    kb, artifact, catalog = _context(tmp_path, source)
    executable = "vampire" if isinstance(adapter, VampireAdapter) else "lean"
    monkeypatch.setattr(
        "ruler.kb.formalism_adapters.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == executable else None,
    )
    request = KBInferenceRequest(request_id="v", operation="verify", query="requested")
    with pytest.raises(ValueError, match=message):
        adapter.execute(kb=kb, artifact=artifact, request=request, catalog=catalog)


def test_default_adapters_do_not_advertise_non_executable_legacy_cp_sat() -> None:
    backend_ids = {adapter.backend_id for adapter in default_formalism_adapters()}
    assert "retired_application-cp-sat-legacy-v1" not in backend_ids


def test_structured_case_files_are_not_advertised_as_executable_models() -> None:
    service = KBInferenceService(KnowledgeBaseCatalog())
    capabilities = service.capabilities("cbr-fiscal-cases")
    assert capabilities == ()
