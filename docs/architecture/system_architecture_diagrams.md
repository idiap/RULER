<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# RULER Architecture Diagrams

These diagrams provide project-management views of the RULER system. They are
kept separate from the main README so architecture communication can evolve
without changing the user-facing project entrypoint.

## System Context

```mermaid
flowchart LR
  Sources[Policy PDFs, product spreadsheets, reference docs]
  PM[Project communication skills]
  CLI[CLI workflows]
  MCP[MCP server]
  Hooks[Hook control plane]
  Ruler[RULER controlled reasoning system]
  Human[Human advisor or reviewer]
  Artifacts[Build artifacts and docs]

  Sources -->|ingested and sampled| Ruler
  CLI -->|runs workflows| Ruler
  MCP -->|exposes bounded tools| Ruler
  Hooks -->|validates stages| Ruler
  PM -->|documents and diagrams| Artifacts
  Ruler -->|writes traceable outputs| Artifacts
  Artifacts -->|reviewed by| Human
  Human -->|approves or rejects| Ruler
```

## Component View

```mermaid
flowchart TB
  subgraph Core[ruler package]
    Shared[schemas, paths, io]
    Source[source package]
    KB[kb package]
    Reasoning[reasoning package]
    Solvers[solvers package]
    Interfaces[interfaces package]
    Runtime[runtime package]
    CLI[cli.py]
  end

  Data[data and refs]
  KBFiles[kb formalized artifacts]
  Hooks[.ruler hooks and skills bindings]
  Build[build/ruler artifacts]
  Docs[docs]

  CLI -->|dispatches| Source
  CLI -->|dispatches| Reasoning
  CLI -->|dispatches| Interfaces
  CLI -->|dispatches| Runtime
  Source -->|reads| Data
  Source -->|writes extracted candidates| Data
  KB -->|loads and validates| KBFiles
  Reasoning -->|reads promoted evidence| KB
  Reasoning -->|uses| Solvers
  Reasoning -->|uses typed contracts| Shared
  Interfaces -->|renders| Build
  Runtime -->|validates| Hooks
  Runtime -->|validates| Build
  Runtime -->|validates| KBFiles
  Docs -->|explains| Core
```

## Source to KB Flow

```mermaid
flowchart LR
  Raw[Raw source documents]
  Extracted[Extracted text and workbook samples]
  Candidates[Formalizable units and draft predicates]
  Vocabulary[Vocabulary normalization and translation controls]
  Gates[Semantic and drift validation gates]
  Promoted[Promoted KB clauses, rules, predicates]
  Reasoner[Reasoning cases and policy effects]

  Raw -->|download and extract| Extracted
  Extracted -->|sample and structure| Candidates
  Candidates -->|harmonize terms| Vocabulary
  Vocabulary -->|validate preservation| Gates
  Gates -->|promote only accepted artifacts| Promoted
  Promoted -->|grounds| Reasoner
```

## Reasoning Control Flow

```mermaid
flowchart TB
  Case[Reasoning case]
  Facts[Fact activation]
  Eligibility[Eligibility and hard blockers]
  Effects[Policy effects with provenance]
  Solver[MaxSMT and package solvers]
  Contrast[Contrasts and counterfactuals]
  Packet[Decision packet]
  Logs[Reasoning logs]
  Dashboard[Inference dashboard]
  Advisor[Human-gated advisor output]

  Case --> Facts
  Facts --> Eligibility
  Eligibility -->|feasible options| Effects
  Effects --> Solver
  Solver --> Contrast
  Contrast --> Packet
  Packet --> Logs
  Packet --> Dashboard
  Packet --> Advisor
  Eligibility -->|blocked option| Packet
```

## Runtime Integration View

```mermaid
flowchart LR
  CLI[ruler CLI]
  MCP[FastMCP stdio server]
  Claude[Claude Code bridge]
  OpenCode[OpenCode bridge]
  Hooks[Git and workflow hooks]
  Validation[Validation control plane]
  Workflows[Known workflow writers]
  Config[Redacted generative API config]

  CLI -->|runs| Workflows
  CLI -->|runs| Validation
  MCP -->|allowlisted validation| Validation
  MCP -->|allowlisted workflows with write approval| Workflows
  MCP -->|reads redacted| Config
  Claude -->|documents local skill entrypoints| CLI
  OpenCode -->|documents local commands| CLI
  Hooks -->|call| Validation
  Hooks -->|call| Workflows
```

## Source Notes

These diagrams are derived from:

- `ruler/cli.py`
- `ruler/runtime/validation.py`
- `ruler/runtime/mcp_server.py`
- `ruler/reasoning/`
- `ruler/kb/`
- `ruler/source/`
- `ruler/interfaces/`
- `.ruler/hooks.yaml`
- `skills/SKILL_HOOKS.yaml`
