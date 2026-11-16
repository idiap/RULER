# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

# Lunar AI

"""Render RULER AI Act/GDPR architecture analysis.

This report maps regulatory design criteria to concrete RULER architecture
choices and contrasts them with a pure RAG+LLM architecture. It is deliberately
framed as engineering readiness analysis, not legal advice or a deployment-level
compliance certification.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

AI_ACT = "EU AI Act"
GDPR = "GDPR"

SOURCES = {
    "ai_act_article_9": "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-9",
    "ai_act_article_10": "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-10",
    "ai_act_article_11": "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-11",
    "ai_act_article_12": "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-12",
    "ai_act_article_13": "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-13",
    "ai_act_article_14": "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14",
    "ai_act_article_15": "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-15",
    "gdpr_article_5": "https://gdpr-info.eu/art-5-gdpr/",
    "gdpr_article_22": "https://gdpr-info.eu/art-22-gdpr/",
    "gdpr_article_25": "https://gdpr-info.eu/art-25-gdpr/",
    "gdpr_article_30": "https://gdpr-info.eu/art-30-gdpr/",
    "gdpr_article_32": "https://gdpr-info.eu/art-32-gdpr/",
    "gdpr_article_35": "https://gdpr-info.eu/art-35-gdpr/",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to build/ruler/architecture_compliance under --root.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    output_dir = args.output_dir or root / "build" / "ruler" / "architecture_compliance"
    report = build_analysis(root)
    write_analysis(report, output_dir)
    print(f"json: {output_dir / 'architecture_compliance_analysis.json'}")
    print(f"html: {output_dir / 'architecture_compliance_analysis.html'}")


def _default_root() -> Path:
    return Path(__file__).resolve().parents[4]


def build_analysis(root: Path) -> dict[str, Any]:
    criteria = _criteria(root)
    status_counts: dict[str, int] = {}
    for criterion in criteria:
        status_counts[criterion["status"]] = status_counts.get(criterion["status"], 0) + 1

    return {
        "report_id": "ruler_ai_act_gdpr_architecture_analysis",
        "status": "engineering_readiness_analysis",
        "not_legal_advice": True,
        "scope": {
            "system": "RULER controlled neuro-symbolic reasoning framework",
            "deployment_assumption": "Architecture-level assessment before customer-specific production deployment.",
            "contrast_baseline": "Pure RAG+LLM architecture over full-text policy and customer-context documents.",
            "classification_note": "This report does not determine final EU AI Act role, risk class, GDPR lawful basis, or DPIA outcome for a concrete deployment.",
        },
        "status_counts": status_counts,
        "criteria": criteria,
        "architecture_summary": _architecture_summary(),
        "rag_llm_contrast_summary": _rag_llm_contrast_summary(),
        "recommended_next_actions": _recommended_next_actions(),
        "source_catalog": SOURCES,
    }


def write_analysis(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "architecture_compliance_analysis.json"
    html_path = output_dir / "architecture_compliance_analysis.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")


def _criteria(root: Path) -> list[dict[str, Any]]:
    return [
        _criterion(
            AI_ACT,
            "Risk management system",
            SOURCES["ai_act_article_9"],
            "High-risk AI systems require a documented, iterative risk-management system across the lifecycle.",
            [
                "Hook-controlled workflows separate source ingestion, promotion, reasoning, dashboards, and runtime bridges.",
                "Validation commands and pre-commit/pre-push hooks enforce repeatable gates before publication.",
                "Reasoning maturity checks cover non-vacuity, robustness, temporal reasoning, portfolio breadth, and solver cross-checks.",
            ],
            [
                ".ruler/hooks.yaml",
                "skills/SKILL_HOOKS.yaml",
                "ruler/runtime/validation.py",
                "ruler/reasoning/reasoning_controls.py",
                "tests/reasoning/test_reasoning_controls.py",
            ],
            "A pure RAG+LLM path can document risks, but the risk controls usually sit around the model call rather than inside explicit typed gates, promoted facts, solver constraints, and replayable validation commands.",
            "designed_strength",
            [
                "Deployment-specific risk classification and conformity workflow still require legal/product review.",
                "Add incident-management and post-deployment monitoring owners for production use.",
            ],
        ),
        _criterion(
            AI_ACT,
            "Data governance and source quality",
            SOURCES["ai_act_article_10"],
            "Training, validation, and operational data governance should address relevance, representativeness, errors, completeness, and bias risks.",
            [
                "Source documents are ingested once, sectioned, normalized, and promoted through explicit source-span and vocabulary controls.",
                "Candidate-only extractions are kept separate from promoted solver truth.",
                "Customer-profile abstractions distinguish observed facts, inferred needs, preferences, unknowns, and sensitive fields.",
            ],
            [
                "ruler/source/source_corpus.py",
                "kb/formalized/real/autoformalization/",
                "kb/customer_profile/",
                "tests/kb/test_customer_profile_preference_kb.py",
                "tests/reasoning/test_reasoning_maturity.py",
            ],
            "RAG+LLM systems often re-process retrieved passages at query time; retrieved chunks can drift, be incomplete, or be treated as context without a persistent promotion boundary.",
            "designed_strength",
            [
                "Add dataset-card style records for each provider/product corpus.",
                "Add fairness and bias tests once real demographic or proxy attributes enter scope.",
            ],
        ),
        _criterion(
            AI_ACT,
            "Technical documentation",
            SOURCES["ai_act_article_11"],
            "Technical documentation should describe system purpose, design, development, operation, and controls.",
            [
                "Architecture docs, workflow graphs, skill contracts, KB manifests, and generated reports describe components and data/control flow.",
                "The project-summary report inventories skills, prompts, code metrics, workflows, and solver surfaces.",
            ],
            [
                "docs/architecture/system_architecture.md",
                "docs/architecture/system_architecture_diagrams.md",
                "docs/architecture/directory_structure_walkthrough.md",
                "proj_skills/project-management/project-summary-stats-reporter/",
                "build/ruler/project_summary_stats/",
            ],
            "RAG+LLM documentation can describe retrieval and prompting, but it can be harder to document the exact reasoning path when conclusions depend on generated text over changing context windows.",
            "designed_strength",
            [
                "Keep versioned release snapshots of generated architecture and compliance reports when preparing external releases.",
            ],
        ),
        _criterion(
            AI_ACT,
            "Record keeping and event logs",
            SOURCES["ai_act_article_12"],
            "High-risk AI systems should enable automatic event recording and traceability appropriate to their purpose.",
            [
                "Reasoning logs are human-readable and machine-processable, with event types, artifacts, gates, solver backends, and telemetry.",
                "Dashboards surface facts, rules, inferences, solver variables, constraints, and package decisions.",
            ],
            [
                "ruler/interfaces/reasoning_log.py",
                "docs/guides/reasoning_logs.md",
                "build/ruler/reasoning_logs/",
                "ruler/interfaces/inference_dashboard.py",
            ],
            "A RAG+LLM transcript can log prompts and responses, but unless carefully engineered it does not naturally separate source facts, rule activations, solver constraints, rejected candidates, and human gates.",
            "designed_strength",
            [
                "Define retention periods and access controls for logs that include customer data.",
            ],
        ),
        _criterion(
            AI_ACT,
            "Transparency to deployers and users",
            SOURCES["ai_act_article_13"],
            "Systems should be sufficiently transparent for deployers to interpret outputs and use them appropriately.",
            [
                "Customer-facing reports avoid solver jargon while preserving evidence, caveats, and advisor-review status.",
                "Inference dashboards and workflow graphs expose model-independent reasoning controls.",
                "Bilingual comments preserve original and controlled-English source statements for formalized rules.",
            ],
            [
                "proj_skills/communication/business-customer-comparison-report-builder/",
                "ruler/interfaces/inference_dashboard.py",
                "ruler/interfaces/workflow_graphs.py",
                "kb/formalized/real/rules/prolog/",
            ],
            "RAG+LLM explanations can be fluent but may blend retrieval, inference, and speculation unless the system separately enforces source spans and rule/solver trace objects.",
            "designed_strength",
            [
                "Add end-user wording review for production reports in each supported language.",
            ],
        ),
        _criterion(
            AI_ACT,
            "Human oversight",
            SOURCES["ai_act_article_14"],
            "High-risk AI systems should be designed so natural persons can oversee them and intervene appropriately.",
            [
                "Advisor review gates are explicit in customer reports, customer-profile KB, validation rules, and runtime adoption decisions.",
                "Customer-profile logic remains out-of-core until deterministic workflow adoption is approved.",
                "Reports separate recommendation, caveats, unsupported claims, and what could change the recommendation.",
            ],
            [
                "kb/customer_profile/profile_runtime_adoption_decision.yaml",
                "kb/customer_profile/profile_customer_report_schema.yaml",
                "kb/customer_profile/profile_validation_rules.yaml",
                "proj_skills/communication/business-customer-comparison-report-reviewer/",
            ],
            "RAG+LLM assistants can include human-in-the-loop policy, but the boundary is often procedural rather than encoded in artifacts, validators, and report schemas.",
            "designed_strength",
            [
                "Define role-based permissions for advisor approval, override, and customer release.",
            ],
        ),
        _criterion(
            AI_ACT,
            "Accuracy, robustness, and cybersecurity",
            SOURCES["ai_act_article_15"],
            "Systems should achieve appropriate accuracy, robustness, and cybersecurity for their intended purpose.",
            [
                "Deterministic validators, solver cross-checks, robustness checks, and semantic-preservation checks constrain reasoning drift.",
                "API config separates provider settings and redacts secrets; MCP/API bridges have validation gates.",
            ],
            [
                "ruler/runtime/api_config.py",
                "ruler/runtime/mcp_server.py",
                "tests/runtime/test_api_config.py",
                "tests/runtime/test_mcp_server.py",
                "tests/reasoning/test_reasoning_controls.py",
            ],
            "RAG+LLM systems can be robustly engineered, but repeated generative inference increases exposure to prompt injection, context manipulation, stochastic variance, and provider/runtime drift.",
            "partially_addressed",
            [
                "Add adversarial prompt-injection tests for external document ingestion and customer descriptions.",
                "Add production security controls for authentication, authorization, and audit-log access.",
            ],
        ),
        _criterion(
            AI_ACT,
            "Post-market monitoring readiness",
            "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-72",
            "Providers of high-risk AI systems need post-market monitoring proportionate to risk and based on lifecycle data.",
            [
                "The architecture already emits validation, reasoning, dashboard, and workflow artifacts that can become monitoring signals.",
                "Source freshness auditing and workflow hooks provide a basis for change-triggered revalidation.",
            ],
            [
                "skills/source/provider-document-freshness-auditor/SKILL.md",
                "ruler/source/source_corpus.py",
                "build/ruler/reasoning_controls/",
                "build/ruler/workflow_router/",
            ],
            "RAG+LLM monitoring often focuses on output evaluation and usage logs; RULER can additionally monitor formalized-source drift, rule promotion, and solver-result changes.",
            "partially_addressed",
            [
                "Define production incident taxonomy, severity thresholds, and monitoring cadence.",
            ],
        ),
        _criterion(
            GDPR,
            "Lawfulness, fairness, transparency, purpose limitation, minimization, accuracy, storage limitation, integrity, and accountability",
            SOURCES["gdpr_article_5"],
            "GDPR Article 5 defines core processing principles and accountability.",
            [
                "The architecture minimizes repeated processing by extracting once and monitoring source changes.",
                "Customer-profile artifacts separate observed facts from inferred needs and require source spans, unknowns, and sensitivity review.",
                "Generated reports preserve evidence paths and caveats rather than exposing hidden model reasoning.",
            ],
            [
                "kb/customer_profile/profile_abstraction_schema.yaml",
                "kb/customer_profile/profile_validation_rules.yaml",
                "kb/customer_profile/profile_generative_test_cases.yaml",
                "ruler/source/source_corpus.py",
            ],
            "A pure RAG+LLM system often sends larger retrieved contexts per query and may repeatedly process personal data unless caching, minimization, and retention controls are explicitly engineered.",
            "partially_addressed",
            [
                "Lawful basis, notices, retention periods, and data-subject-right procedures must be set per deployment.",
            ],
        ),
        _criterion(
            GDPR,
            "Data protection by design and by default",
            SOURCES["gdpr_article_25"],
            "Controllers should implement appropriate technical and organizational measures designed to implement data-protection principles.",
            [
                "Out-of-core customer-profile adoption, advisor gates, sensitive-field handling, source-span policies, and local validation favor privacy-by-design.",
                "API config uses redaction-aware provider settings and can default to local stubs.",
            ],
            [
                "kb/customer_profile/profile_runtime_adoption_decision.yaml",
                "kb/customer_profile/profile_extraction_normalization_rules.yaml",
                "ruler/runtime/api_config.py",
                "tests/runtime/test_api_config.py",
            ],
            "RAG+LLM can be privacy-by-design if engineered carefully, but its natural implementation pattern tends toward sending broad context to a model endpoint at every query.",
            "designed_strength",
            [
                "Add deployment templates for retention, redaction, pseudonymization, and data-subject access workflows.",
            ],
        ),
        _criterion(
            GDPR,
            "Records of processing activities",
            SOURCES["gdpr_article_30"],
            "Controllers and processors may need records describing processing purposes, categories, recipients, transfers, retention, and safeguards.",
            [
                "Reasoning logs, workflow manifests, source manifests, and generated compliance reports provide raw material for processing records.",
                "The architecture records what artifacts were used and what controls ran.",
            ],
            [
                "build/ruler/reasoning_logs/",
                "data/sources/manifests/",
                "build/ruler/workflow_router/",
                "build/ruler/architecture_compliance/",
            ],
            "RAG+LLM deployments need additional records for prompt contents, retrieved documents, model providers, subprocessor flows, and retention settings; these are often spread across vendor and app logs.",
            "partially_addressed",
            [
                "Create a formal ROPA/DPIA export once processing roles and customer-data categories are fixed.",
            ],
        ),
        _criterion(
            GDPR,
            "Security of processing",
            SOURCES["gdpr_article_32"],
            "Processing should use appropriate security measures considering risk, including confidentiality, integrity, availability, and resilience.",
            [
                "Cross-platform runtime checks, API secret redaction, MCP validation, and hook gates support secure engineering practice.",
                "Build artifacts are generated locally and can be reviewed before exposure.",
            ],
            [
                "ruler/runtime/cross_platform.py",
                "ruler/runtime/api_config.py",
                "ruler/runtime/mcp_server.py",
                "tests/runtime/",
            ],
            "RAG+LLM introduces additional security surfaces: retrieval index access, prompt injection, model-provider API handling, and possible leakage through generated responses.",
            "partially_addressed",
            [
                "Add threat model, access-control matrix, encryption/backup plan, and prompt-injection hardening tests for deployment.",
            ],
        ),
        _criterion(
            GDPR,
            "DPIA readiness for high-risk processing",
            SOURCES["gdpr_article_35"],
            "A DPIA is required where processing is likely to result in high risk to natural persons, including some profiling contexts.",
            [
                "The architecture produces structured evidence for necessity, proportionality, risks, controls, residual gaps, and human-review boundaries.",
                "Customer-profile reports keep recommendations advisor-gated and avoid final automated customer-facing deployment by default.",
            ],
            [
                "kb/customer_profile/profile_customer_report_schema.yaml",
                "kb/customer_profile/profile_validation_rules.yaml",
                "proj_skills/compliance/ai-act-gdpr-architecture-assessor/",
                "build/ruler/architecture_compliance/",
            ],
            "RAG+LLM DPIA evidence must often reconstruct why a model generated a recommendation from prompts, retrieval state, and provider behavior after the fact.",
            "requires_legal_review",
            [
                "Conduct a real DPIA before using personal data in production recommendation or profiling workflows.",
            ],
        ),
        _criterion(
            GDPR,
            "Automated decision-making and profiling safeguards",
            SOURCES["gdpr_article_22"],
            "GDPR includes safeguards around decisions based solely on automated processing, including profiling, where legal or similarly significant effects arise.",
            [
                "RULER explicitly positions outputs as advisor-review recommendations with human gates, caveats, and review status.",
                "Solver traces and report schemas make recommendation drivers inspectable before customer release.",
            ],
            [
                "kb/customer_profile/profile_customer_report_schema.yaml",
                "proj_skills/communication/business-customer-comparison-report-builder/SKILL.md",
                "ruler/interfaces/inference_dashboard.py",
                "tests/kb/test_customer_profile_preference_kb.py",
            ],
            "A direct RAG+LLM recommender can drift toward de facto automated decisions if customers receive model-generated recommendations without explicit human review, appeal, and explanation controls.",
            "designed_strength",
            [
                "Define production policy for human review, contestability, customer explanation, and advisor override records.",
            ],
        ),
    ]


def _criterion(
    regulation: str,
    criterion: str,
    source_url: str,
    regulatory_expectation: str,
    ruler_design_strategies: list[str],
    evidence_paths: list[str],
    rag_llm_contrast: str,
    status: str,
    residual_gaps: list[str],
) -> dict[str, Any]:
    return {
        "regulation": regulation,
        "criterion": criterion,
        "source_url": source_url,
        "regulatory_expectation": regulatory_expectation,
        "ruler_design_strategies": ruler_design_strategies,
        "evidence_paths": evidence_paths,
        "rag_llm_contrast": rag_llm_contrast,
        "status": status,
        "residual_gaps": residual_gaps,
    }


def _architecture_summary() -> dict[str, list[str]]:
    return {
        "control_strategy": [
            "Extract once, monitor for changes, and promote only reviewed source-derived facts.",
            "Represent customer descriptions as observed facts, inferred needs, preferences, unknowns, and review gates.",
            "Separate hard constraints, soft objectives, solver traces, and customer-readable explanations.",
            "Expose runtime behavior through validation hooks, reasoning logs, dashboards, workflow graphs, and reports.",
        ],
        "privacy_strategy": [
            "Minimize repeated token/API processing of source and customer context.",
            "Keep sensitive profile abstractions out of runtime hooks until adoption criteria are met.",
            "Preserve source spans and evidence paths so claims can be inspected without revealing hidden reasoning.",
        ],
    }


def _rag_llm_contrast_summary() -> list[str]:
    return [
        "RAG+LLM can be made compliant, but it normally needs extra scaffolding for traceability, minimization, prompt-injection resistance, logging, and human review.",
        "RULER moves recurring reasoning from opaque generation into typed artifacts, formalized rules, solver inputs, and replayable logs.",
        "The neuro-symbolic path gives clearer evidence for why a recommendation was made, which facts were active, which rules fired, and which constraints blocked alternatives.",
    ]


def _recommended_next_actions() -> list[str]:
    return [
        "Run legal review before claiming compliance for a concrete deployment.",
        "Define controller/processor roles, lawful basis, data retention, and data-subject rights workflows.",
        "Add DPIA and ROPA export templates once deployment context and customer data categories are fixed.",
        "Add production threat model, access-control policy, retention schedule, incident-response workflow, and prompt-injection tests.",
        "Version compliance reports alongside release snapshots and source-corpus manifests.",
    ]


def render_html(report: dict[str, Any]) -> str:
    cards = "\n".join(_render_criterion_card(item) for item in report["criteria"])
    status_rows = "\n".join(
        f"<li><strong>{html.escape(status)}</strong>: {count}</li>"
        for status, count in sorted(report["status_counts"].items())
    )
    payload = html.escape(json.dumps(report, indent=2, sort_keys=True))
    next_actions = "".join(
        f"<li>{html.escape(action)}</li>" for action in report["recommended_next_actions"]
    )
    contrast = "".join(
        f"<li>{html.escape(item)}</li>" for item in report["rag_llm_contrast_summary"]
    )
    control = "".join(
        f"<li>{html.escape(item)}</li>"
        for item in report["architecture_summary"]["control_strategy"]
    )
    privacy = "".join(
        f"<li>{html.escape(item)}</li>"
        for item in report["architecture_summary"]["privacy_strategy"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RULER AI Act and GDPR Architecture Analysis</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #071018;
      --panel: #0d1722;
      --panel-2: #112232;
      --text: #eef7ff;
      --muted: #a8b8c8;
      --line: #24384c;
      --accent: #5ee0b5;
      --accent-2: #7ab0ff;
      --warn: #ffd166;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1240px; margin: 0 auto; padding: 32px 20px 56px; }}
    h1, h2, h3 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: 34px; }}
    h2 {{ font-size: 20px; margin-top: 26px; margin-bottom: 12px; }}
    h3 {{ font-size: 16px; }}
    p, li {{ color: var(--muted); }}
    header {{ display: grid; gap: 10px; margin-bottom: 24px; }}
    .grid {{ display: grid; gap: 14px; }}
    .two {{ grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .criterion {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 12px;
    }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }}
    .pill {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      color: var(--muted);
      font-size: 12px;
    }}
    .status {{ color: var(--accent); border-color: #2c715f; }}
    a {{ color: var(--accent-2); }}
    ul {{ margin: 8px 0 0; padding-left: 18px; }}
    .columns {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    details {{ margin-top: 18px; }}
    summary {{ cursor: pointer; color: var(--accent); }}
    pre {{
      max-height: 430px;
      overflow: auto;
      padding: 14px;
      background: #050b11;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: #c9e5ff;
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>RULER AI Act and GDPR Architecture Analysis</h1>
    <p>This is engineering readiness analysis for architecture design. It is not legal advice and does not certify compliance for a concrete deployment.</p>
  </header>

  <section class="grid two">
    <div class="card">
      <h2>Status Summary</h2>
      <ul>{status_rows}</ul>
    </div>
    <div class="card">
      <h2>RAG + LLM Contrast</h2>
      <ul>{contrast}</ul>
    </div>
  </section>

  <section class="grid two">
    <div class="card">
      <h2>RULER Control Strategy</h2>
      <ul>{control}</ul>
    </div>
    <div class="card">
      <h2>Privacy Strategy</h2>
      <ul>{privacy}</ul>
    </div>
  </section>

  <section>
    <h2>Criteria Deep Dive</h2>
    {cards}
  </section>

  <section class="card">
    <h2>Recommended Next Actions</h2>
    <ul>{next_actions}</ul>
  </section>

  <details>
    <summary>Embedded Machine-Readable JSON</summary>
    <pre>{payload}</pre>
  </details>
</main>
</body>
</html>
"""


def _render_criterion_card(item: dict[str, Any]) -> str:
    strategies = "".join(
        f"<li>{html.escape(strategy)}</li>" for strategy in item["ruler_design_strategies"]
    )
    evidence = "".join(
        f'<span class="pill">{html.escape(path)}</span>' for path in item["evidence_paths"]
    )
    gaps = "".join(f"<li>{html.escape(gap)}</li>" for gap in item["residual_gaps"])
    return f"""
    <article class="criterion">
      <h3>{html.escape(item["criterion"])}</h3>
      <div class="meta">
        <span class="pill">{html.escape(item["regulation"])}</span>
        <span class="pill status">{html.escape(item["status"])}</span>
        <a class="pill" href="{html.escape(item["source_url"])}">source</a>
      </div>
      <p>{html.escape(item["regulatory_expectation"])}</p>
      <div class="columns">
        <div>
          <h3>RULER design strategies</h3>
          <ul>{strategies}</ul>
        </div>
        <div>
          <h3>RAG + LLM contrast</h3>
          <p>{html.escape(item["rag_llm_contrast"])}</p>
        </div>
        <div>
          <h3>Residual gaps</h3>
          <ul>{gaps}</ul>
        </div>
      </div>
      <div class="meta">{evidence}</div>
    </article>"""


if __name__ == "__main__":
    main()
