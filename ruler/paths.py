# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Central path registry for RULER. Keeping repository paths here makes generated
artifacts, KB files, hooks, and examples portable and easy to retarget.
"""

from __future__ import annotations

import os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(os.environ.get("RULER_WORKSPACE_ROOT", CODE_ROOT)).resolve()
DATA_DIR = REPO_ROOT / "data"
SOURCES_DIR = DATA_DIR / "sources"
SOURCE_RAW_DIR = SOURCES_DIR / "raw"
SOURCE_EXTRACTED_DIR = SOURCES_DIR / "extracted"
SOURCE_MANIFEST_DIR = SOURCES_DIR / "manifests"
SOURCE_INDEX_DIR = SOURCES_DIR / "index"
EXTRACTED_DIR = DATA_DIR / "extracted"
EXAMPLES_DIR = DATA_DIR / "examples"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
REFERENCE_DIR = DATA_DIR / "reference"
USE_CASES_DIR = DATA_DIR / "use_cases"
SKILLS_DIR = REPO_ROOT / "skills"
KB_DIR = REPO_ROOT / "kb"
KB_CORPORA_DIR = KB_DIR / "corpora"
KB_SHARED_DIR = KB_DIR / "shared"
KB_RELEASES_DIR = KB_DIR / "releases"
KB_FORMALIZED_DIR = KB_DIR / "formalized"
KB_FORMALIZED_REAL_DIR = KB_FORMALIZED_DIR / "real"
KB_FORMALIZED_SYNTHETIC_DIR = KB_FORMALIZED_DIR / "synthetic"
BUILD_DIR = REPO_ROOT / "build" / "ruler"
HOOKS_FILE = REPO_ROOT / ".ruler" / "hooks.yaml"
WORKFLOW_REGISTRY_FILE = REPO_ROOT / ".ruler" / "workflows.yaml"
SKILL_LIFECYCLE_FILE = REPO_ROOT / ".ruler" / "skill_lifecycle.yaml"
SKILL_HOOKS_FILE = SKILLS_DIR / "SKILL_HOOKS.yaml"
RULES_DIR = REPO_ROOT / "rules"
