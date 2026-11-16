# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Domain-neutral, deterministic execution boundary for validated logical programs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import clingo

from ruler.kb.asp_compiler import compile_asp, render_asp_atom
from ruler.kb.formalization import PredicateRegistry
from ruler.kb.logical_ir import Atom, LogicalProgram


class RuleEngineError(ValueError):
    """Raised when a rule module cannot produce one deterministic, declared result."""


@dataclass(frozen=True)
class RuleModuleDescriptor:
    """Executable rule module and the complete public predicate boundary it declares."""

    module_id: str
    source: str
    shown_predicates: frozenset[str]
    source_path: Path | None = None

    @classmethod
    def from_path(
        cls, module_id: str, path: Path, *, shown_predicates: Iterable[str]
    ) -> "RuleModuleDescriptor":
        if not path.is_file():
            raise RuleEngineError(f"missing executable ASP rule module: {path}")
        return cls(
            module_id=module_id,
            source=path.read_text(encoding="utf-8"),
            shown_predicates=frozenset(shown_predicates),
            source_path=path,
        )


@dataclass(frozen=True)
class RuleScenarioResult:
    """Stable shown projection for one scenario."""

    module_id: str
    atoms: frozenset[str]


class RuleEngine:
    """Execute a declared ASP module or any registry-validated ``LogicalProgram``."""

    def __init__(self, descriptor: RuleModuleDescriptor) -> None:
        if not descriptor.module_id.strip():
            raise RuleEngineError("rule modules require a non-empty module_id")
        self.descriptor = descriptor

    @classmethod
    def from_logical_program(
        cls, program: LogicalProgram, registry: PredicateRegistry
    ) -> "RuleEngine":
        compiled = compile_asp(program, registry)
        source = compiled.text if program.show else compiled.text + "#show.\n"
        return cls(
            RuleModuleDescriptor(
                module_id=program.program_id,
                source=source,
                shown_predicates=frozenset(item.predicate for item in program.show),
            )
        )

    def run_atoms(
        self, facts: Iterable[Atom], *, registry: PredicateRegistry
    ) -> RuleScenarioResult:
        """Run typed facts; undeclared predicates and invalid types fail before solving."""
        fact_source = "\n".join(f"{render_asp_atom(item, registry)}." for item in facts)
        return self.run_source(fact_source)

    def run_source(self, fact_source: str = "") -> RuleScenarioResult:
        """Run pre-rendered facts at the repository CLI's trusted execution boundary."""
        control = clingo.Control(["--warn=none", "--models=0"])
        try:
            control.add("base", [], self.descriptor.source)
            control.add("scenario", [], fact_source)
            control.ground([("base", []), ("scenario", [])])
        except RuntimeError as exc:
            raise RuleEngineError(
                f"invalid rule scenario for {self.descriptor.module_id}: {exc}"
            ) from exc

        projections: set[frozenset[str]] = set()
        predicate_names: set[str] = set()
        with control.solve(yield_=True) as handle:
            for model in handle:
                symbols = model.symbols(shown=True)
                projections.add(frozenset(str(symbol) for symbol in symbols))
                predicate_names.update(
                    symbol.name for symbol in symbols if symbol.type == clingo.SymbolType.Function
                )
        if not projections:
            raise RuleEngineError(f"rule scenario is unsatisfiable: {self.descriptor.module_id}")
        if len(projections) != 1:
            raise RuleEngineError(
                f"rule scenario has ambiguous shown answer sets: {self.descriptor.module_id}"
            )
        unknown = predicate_names - self.descriptor.shown_predicates
        if unknown:
            raise RuleEngineError(
                "rule module emitted undeclared shown predicates: " + ", ".join(sorted(unknown))
            )
        return RuleScenarioResult(self.descriptor.module_id, next(iter(projections)))


def run_rule_scenario(
    program: LogicalProgram,
    facts: Iterable[Atom],
    *,
    registry: PredicateRegistry,
) -> RuleScenarioResult:
    """Compile and execute one typed program and scenario through the neutral boundary."""
    return RuleEngine.from_logical_program(program, registry).run_atoms(facts, registry=registry)
