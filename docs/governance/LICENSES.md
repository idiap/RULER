<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Dependency Licenses

This inventory is generated from the locked RULER dependency definitions:
`pyproject.toml` with `uv.lock`, plus `codex-app-workbench/package.json` with
its `package-lock.json`. Python license metadata comes from the active locked
`uv` environment; Node metadata comes from the npm lockfile. It is an
engineering attribution aid, not legal advice.

Generation command: `uv run python proj_skills/compliance/dependency-license-inventory/scripts/generate_licenses_md.py`

## Summary

- Total packages: 148
- Python packages: 108
- Node packages: 40
- Direct runtime dependencies: 24
- Direct development dependencies: 12
- Transitive dependencies: 112
- Packages with unknown license metadata: 0
- Packages with unknown URL metadata: 0

## Inventory

| Ecosystem | Framework / package | Version | Scope | License | URL |
|---|---|---:|---|---|---|
| Node | @openai/codex-sdk | 0.152.0 | direct runtime | Apache-2.0 | [https://www.npmjs.com/package/@openai/codex-sdk](https://www.npmjs.com/package/@openai/codex-sdk) |
| Node | @types/node | 24.13.3 | direct dev | MIT | [https://www.npmjs.com/package/@types/node](https://www.npmjs.com/package/@types/node) |
| Node | tsx | 4.23.13 | direct dev | MIT | [https://www.npmjs.com/package/tsx](https://www.npmjs.com/package/tsx) |
| Node | typescript | 5.9.3 | direct dev | Apache-2.0 | [https://www.npmjs.com/package/typescript](https://www.npmjs.com/package/typescript) |
| Node | @esbuild/aix-ppc64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/aix-ppc64](https://www.npmjs.com/package/@esbuild/aix-ppc64) |
| Node | @esbuild/android-arm | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/android-arm](https://www.npmjs.com/package/@esbuild/android-arm) |
| Node | @esbuild/android-arm64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/android-arm64](https://www.npmjs.com/package/@esbuild/android-arm64) |
| Node | @esbuild/android-x64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/android-x64](https://www.npmjs.com/package/@esbuild/android-x64) |
| Node | @esbuild/darwin-arm64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/darwin-arm64](https://www.npmjs.com/package/@esbuild/darwin-arm64) |
| Node | @esbuild/darwin-x64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/darwin-x64](https://www.npmjs.com/package/@esbuild/darwin-x64) |
| Node | @esbuild/freebsd-arm64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/freebsd-arm64](https://www.npmjs.com/package/@esbuild/freebsd-arm64) |
| Node | @esbuild/freebsd-x64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/freebsd-x64](https://www.npmjs.com/package/@esbuild/freebsd-x64) |
| Node | @esbuild/linux-arm | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/linux-arm](https://www.npmjs.com/package/@esbuild/linux-arm) |
| Node | @esbuild/linux-arm64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/linux-arm64](https://www.npmjs.com/package/@esbuild/linux-arm64) |
| Node | @esbuild/linux-ia32 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/linux-ia32](https://www.npmjs.com/package/@esbuild/linux-ia32) |
| Node | @esbuild/linux-loong64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/linux-loong64](https://www.npmjs.com/package/@esbuild/linux-loong64) |
| Node | @esbuild/linux-mips64el | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/linux-mips64el](https://www.npmjs.com/package/@esbuild/linux-mips64el) |
| Node | @esbuild/linux-ppc64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/linux-ppc64](https://www.npmjs.com/package/@esbuild/linux-ppc64) |
| Node | @esbuild/linux-riscv64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/linux-riscv64](https://www.npmjs.com/package/@esbuild/linux-riscv64) |
| Node | @esbuild/linux-s390x | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/linux-s390x](https://www.npmjs.com/package/@esbuild/linux-s390x) |
| Node | @esbuild/linux-x64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/linux-x64](https://www.npmjs.com/package/@esbuild/linux-x64) |
| Node | @esbuild/netbsd-arm64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/netbsd-arm64](https://www.npmjs.com/package/@esbuild/netbsd-arm64) |
| Node | @esbuild/netbsd-x64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/netbsd-x64](https://www.npmjs.com/package/@esbuild/netbsd-x64) |
| Node | @esbuild/openbsd-arm64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/openbsd-arm64](https://www.npmjs.com/package/@esbuild/openbsd-arm64) |
| Node | @esbuild/openbsd-x64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/openbsd-x64](https://www.npmjs.com/package/@esbuild/openbsd-x64) |
| Node | @esbuild/openharmony-arm64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/openharmony-arm64](https://www.npmjs.com/package/@esbuild/openharmony-arm64) |
| Node | @esbuild/sunos-x64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/sunos-x64](https://www.npmjs.com/package/@esbuild/sunos-x64) |
| Node | @esbuild/win32-arm64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/win32-arm64](https://www.npmjs.com/package/@esbuild/win32-arm64) |
| Node | @esbuild/win32-ia32 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/win32-ia32](https://www.npmjs.com/package/@esbuild/win32-ia32) |
| Node | @esbuild/win32-x64 | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/@esbuild/win32-x64](https://www.npmjs.com/package/@esbuild/win32-x64) |
| Node | @openai/codex | 0.152.0 | transitive | Apache-2.0 | [https://www.npmjs.com/package/@openai/codex](https://www.npmjs.com/package/@openai/codex) |
| Node | @openai/codex-darwin-arm64 | 0.152.0-darwin-arm64 | transitive | Apache-2.0 | [https://www.npmjs.com/package/@openai/codex-darwin-arm64](https://www.npmjs.com/package/@openai/codex-darwin-arm64) |
| Node | @openai/codex-darwin-x64 | 0.152.0-darwin-x64 | transitive | Apache-2.0 | [https://www.npmjs.com/package/@openai/codex-darwin-x64](https://www.npmjs.com/package/@openai/codex-darwin-x64) |
| Node | @openai/codex-linux-arm64 | 0.152.0-linux-arm64 | transitive | Apache-2.0 | [https://www.npmjs.com/package/@openai/codex-linux-arm64](https://www.npmjs.com/package/@openai/codex-linux-arm64) |
| Node | @openai/codex-linux-x64 | 0.152.0-linux-x64 | transitive | Apache-2.0 | [https://www.npmjs.com/package/@openai/codex-linux-x64](https://www.npmjs.com/package/@openai/codex-linux-x64) |
| Node | @openai/codex-win32-arm64 | 0.152.0-win32-arm64 | transitive | Apache-2.0 | [https://www.npmjs.com/package/@openai/codex-win32-arm64](https://www.npmjs.com/package/@openai/codex-win32-arm64) |
| Node | @openai/codex-win32-x64 | 0.152.0-win32-x64 | transitive | Apache-2.0 | [https://www.npmjs.com/package/@openai/codex-win32-x64](https://www.npmjs.com/package/@openai/codex-win32-x64) |
| Node | esbuild | 0.28.2 | transitive | MIT | [https://www.npmjs.com/package/esbuild](https://www.npmjs.com/package/esbuild) |
| Node | fsevents | 2.3.3 | transitive | MIT | [https://www.npmjs.com/package/fsevents](https://www.npmjs.com/package/fsevents) |
| Node | undici-types | 7.18.2 | transitive | MIT | [https://www.npmjs.com/package/undici-types](https://www.npmjs.com/package/undici-types) |
| Python | alembic | 1.20.0 | direct runtime | MIT | [https://github.com/sqlalchemy/alembic/](https://github.com/sqlalchemy/alembic/) |
| Python | click | 8.4.1 | direct runtime | BSD-3-Clause | [https://github.com/pallets/click/](https://github.com/pallets/click/) |
| Python | clingo | 5.8.0 | direct runtime | MIT | [https://github.com/potassco/clingo](https://github.com/potassco/clingo) |
| Python | docling | 2.106.0 | direct runtime | MIT | [https://github.com/docling-project/docling](https://github.com/docling-project/docling) |
| Python | fastapi | 0.139.0 | direct runtime | MIT | [https://github.com/fastapi/fastapi](https://github.com/fastapi/fastapi) |
| Python | highspy | 1.15.1 | direct runtime | MIT | [https://github.com/ERGO-Code/HiGHS](https://github.com/ERGO-Code/HiGHS) |
| Python | jsonschema | 4.26.0 | direct runtime | MIT | [https://github.com/python-jsonschema/jsonschema](https://github.com/python-jsonschema/jsonschema) |
| Python | mcp | 1.28.0 | direct runtime | MIT | [https://github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) |
| Python | openpyxl | 3.1.5 | direct runtime | MIT | [https://foss.heptapod.net/openpyxl/openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) |
| Python | ortools | 9.15.6755 | direct runtime | Apache 2.0 | [https://developers.google.com/optimization/](https://developers.google.com/optimization/) |
| Python | pg8000 | 1.31.6 | direct runtime | BSD 3-Clause License | [https://codeberg.org/tlocke/pg8000](https://codeberg.org/tlocke/pg8000) |
| Python | pydantic | 2.13.4 | direct runtime | MIT | [https://github.com/pydantic/pydantic](https://github.com/pydantic/pydantic) |
| Python | pyomo | 6.10.1 | direct runtime | BSD-3-Clause | [https://github.com/Pyomo/pyomo](https://github.com/Pyomo/pyomo) |
| Python | pypdf | 6.14.2 | direct runtime | BSD-3-Clause | [https://github.com/py-pdf/pypdf](https://github.com/py-pdf/pypdf) |
| Python | PyYAML | 6.0.3 | direct runtime | MIT | [https://github.com/yaml/pyyaml](https://github.com/yaml/pyyaml) |
| Python | rdflib | 7.6.0 | direct runtime | BSD-3-Clause | [https://github.com/RDFLib/rdflib](https://github.com/RDFLib/rdflib) |
| Python | rich | 15.0.0 | direct runtime | MIT | [https://github.com/Textualize/rich](https://github.com/Textualize/rich) |
| Python | scipy | 1.18.0 | direct runtime | BSD License | [https://github.com/scipy/scipy](https://github.com/scipy/scipy) |
| Python | SQLAlchemy | 2.1.4 | direct runtime | MIT | [https://github.com/sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) |
| Python | torch | 2.12.1 / 2.12.1+cpu | direct runtime | BSD-3-Clause | [https://github.com/pytorch/pytorch](https://github.com/pytorch/pytorch) |
| Python | torchvision | 0.27.1 / 0.27.1+cpu | direct runtime | BSD | [https://github.com/pytorch/vision](https://github.com/pytorch/vision) |
| Python | uvicorn | 0.49.0 | direct runtime | BSD-3-Clause | [https://github.com/Kludex/uvicorn](https://github.com/Kludex/uvicorn) |
| Python | z3-solver | 4.16.0.0 | direct runtime | MIT License | [https://github.com/Z3Prover/z3](https://github.com/Z3Prover/z3) |
| Python | black | 26.10.1 | direct dev | MIT | [https://github.com/psf/black](https://github.com/psf/black) |
| Python | hypothesis | 6.165.5 | direct dev | MPL-2.0 | [https://github.com/HypothesisWorks/hypothesis](https://github.com/HypothesisWorks/hypothesis) |
| Python | packaging | 26.2 | direct dev | Apache-2.0 OR BSD-2-Clause | [https://github.com/pypa/packaging](https://github.com/pypa/packaging) |
| Python | playwright | 1.60.0 | direct dev | Apache-2.0 | [https://github.com/Microsoft/playwright-python](https://github.com/Microsoft/playwright-python) |
| Python | pyright | 1.1.414 | direct dev | MIT | [https://github.com/RobertCraigie/pyright-python](https://github.com/RobertCraigie/pyright-python) |
| Python | pytest | 9.1.1 | direct dev | MIT | [https://github.com/pytest-dev/pytest](https://github.com/pytest-dev/pytest) |
| Python | reuse | 6.2.0 | direct dev | Apache-2.0 AND CC0-1.0 AND CC-BY-SA-4.0 AND GPL-3.0-or-later | [https://github.com/fsfe/reuse-tool](https://github.com/fsfe/reuse-tool) |
| Python | ruff | 0.15.18 | direct dev | MIT | [https://github.com/astral-sh/ruff](https://github.com/astral-sh/ruff) |
| Python | vulture | 2.16 | direct dev | MIT License | [https://github.com/jendrikseipp/vulture](https://github.com/jendrikseipp/vulture) |
| Python | absl-py | 2.4.0 | transitive | Apache-2.0 | [https://github.com/abseil/abseil-py](https://github.com/abseil/abseil-py) |
| Python | annotated-doc | 0.0.4 | transitive | MIT | [https://github.com/fastapi/annotated-doc](https://github.com/fastapi/annotated-doc) |
| Python | annotated-types | 0.7.0 | transitive | MIT License | [https://github.com/annotated-types/annotated-types](https://github.com/annotated-types/annotated-types) |
| Python | anyio | 4.14.0 | transitive | MIT | [https://github.com/agronholm/anyio](https://github.com/agronholm/anyio) |
| Python | asn1crypto | 1.5.1 | transitive | MIT | [https://github.com/wbond/asn1crypto](https://github.com/wbond/asn1crypto) |
| Python | attrs | 26.1.0 | transitive | MIT | [https://www.attrs.org/](https://www.attrs.org/) |
| Python | boolean.py | 5.0 | transitive | BSD-2-Clause | [https://github.com/bastikr/boolean.py](https://github.com/bastikr/boolean.py) |
| Python | certifi | 2026.6.17 | transitive | MPL-2.0 | [https://github.com/certifi/python-certifi](https://github.com/certifi/python-certifi) |
| Python | cffi | 2.0.0 | transitive | MIT | [https://github.com/python-cffi/cffi](https://github.com/python-cffi/cffi) |
| Python | charset-normalizer | 3.4.7 | transitive | MIT | [https://charset-normalizer.readthedocs.io/](https://charset-normalizer.readthedocs.io/) |
| Python | defusedxml | 0.7.1 | transitive | PSFL | [https://github.com/tiran/defusedxml](https://github.com/tiran/defusedxml) |
| Python | docling-core | 2.84.0 | transitive | MIT | [https://github.com/docling-project/docling-core](https://github.com/docling-project/docling-core) |
| Python | docling-slim | 2.106.0 | transitive | MIT | [https://github.com/docling-project/docling](https://github.com/docling-project/docling) |
| Python | et_xmlfile | 2.0.0 | transitive | MIT | [https://foss.heptapod.net/openpyxl/et_xmlfile](https://foss.heptapod.net/openpyxl/et_xmlfile) |
| Python | filelock | 3.29.4 | transitive | MIT | [https://github.com/tox-dev/py-filelock](https://github.com/tox-dev/py-filelock) |
| Python | filetype | 1.2.0 | transitive | MIT | [https://github.com/h2non/filetype.py](https://github.com/h2non/filetype.py) |
| Python | fsspec | 2026.6.0 | transitive | BSD-3-Clause | [https://github.com/fsspec/filesystem_spec](https://github.com/fsspec/filesystem_spec) |
| Python | greenlet | 3.5.2 | transitive | MIT AND PSF-2.0 | [https://github.com/python-greenlet/greenlet](https://github.com/python-greenlet/greenlet) |
| Python | h11 | 0.16.0 | transitive | MIT | [https://github.com/python-hyper/h11](https://github.com/python-hyper/h11) |
| Python | httpcore | 1.0.9 | transitive | BSD-3-Clause | [https://github.com/encode/httpcore](https://github.com/encode/httpcore) |
| Python | httpx | 0.28.1 | transitive | BSD-3-Clause | [https://github.com/encode/httpx](https://github.com/encode/httpx) |
| Python | httpx-sse | 0.4.3 | transitive | MIT | [https://github.com/florimondmanca/httpx-sse](https://github.com/florimondmanca/httpx-sse) |
| Python | idna | 3.18 | transitive | BSD-3-Clause | [https://github.com/kjd/idna](https://github.com/kjd/idna) |
| Python | immutabledict | 4.3.1 | transitive | MIT | [https://github.com/corenting/immutabledict](https://github.com/corenting/immutabledict) |
| Python | iniconfig | 2.3.0 | transitive | MIT | [https://github.com/pytest-dev/iniconfig](https://github.com/pytest-dev/iniconfig) |
| Python | Jinja2 | 3.1.6 | transitive | BSD License | [https://github.com/pallets/jinja/](https://github.com/pallets/jinja/) |
| Python | jsonref | 1.1.0 | transitive | MIT | [https://github.com/gazpachoking/jsonref](https://github.com/gazpachoking/jsonref) |
| Python | jsonschema-specifications | 2025.9.1 | transitive | MIT | [https://github.com/python-jsonschema/jsonschema-specifications](https://github.com/python-jsonschema/jsonschema-specifications) |
| Python | latex2mathml | 3.81.0 | transitive | MIT | [https://github.com/roniemartinez/latex2mathml](https://github.com/roniemartinez/latex2mathml) |
| Python | license-expression | 30.4.4 | transitive | Apache-2.0 | [https://github.com/aboutcode-org/license-expression](https://github.com/aboutcode-org/license-expression) |
| Python | Mako | 1.4.3 | transitive | MIT | [https://www.makotemplates.org/](https://www.makotemplates.org/) |
| Python | markdown-it-py | 4.2.0 | transitive | MIT License | [https://github.com/executablebooks/markdown-it-py](https://github.com/executablebooks/markdown-it-py) |
| Python | MarkupSafe | 3.0.3 | transitive | BSD-3-Clause | [https://github.com/pallets/markupsafe/](https://github.com/pallets/markupsafe/) |
| Python | mdurl | 0.1.2 | transitive | MIT License | [https://github.com/executablebooks/mdurl](https://github.com/executablebooks/mdurl) |
| Python | mpmath | 1.3.0 | transitive | BSD | [https://github.com/fredrik-johansson/mpmath](https://github.com/fredrik-johansson/mpmath) |
| Python | mypy_extensions | 1.1.0 | transitive | MIT | [https://github.com/python/mypy_extensions](https://github.com/python/mypy_extensions) |
| Python | networkx | 3.6.1 | transitive | BSD-3-Clause | [https://github.com/networkx/networkx](https://github.com/networkx/networkx) |
| Python | nodeenv | 1.11.0 | transitive | BSD | [https://github.com/ekalinin/nodeenv](https://github.com/ekalinin/nodeenv) |
| Python | numpy | 2.5.0 | transitive | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | [https://github.com/numpy/numpy](https://github.com/numpy/numpy) |
| Python | pandas | 3.0.3 | transitive | BSD License | [https://github.com/pandas-dev/pandas](https://github.com/pandas-dev/pandas) |
| Python | pathspec | 1.1.1 | transitive | Mozilla Public License 2.0 (MPL 2.0) | [https://github.com/cpburnz/python-pathspec](https://github.com/cpburnz/python-pathspec) |
| Python | pillow | 12.2.0 | transitive | MIT-CMU | [https://github.com/python-pillow/Pillow](https://github.com/python-pillow/Pillow) |
| Python | platformdirs | 4.13.5 | transitive | MIT | [https://github.com/tox-dev/platformdirs](https://github.com/tox-dev/platformdirs) |
| Python | pluggy | 1.6.0 | transitive | MIT | [https://pypi.org/project/pluggy/](https://pypi.org/project/pluggy/) |
| Python | protobuf | 6.33.6 | transitive | 3-Clause BSD License | [https://developers.google.com/protocol-buffers/](https://developers.google.com/protocol-buffers/) |
| Python | pycparser | 3.0 | transitive | BSD-3-Clause | [https://github.com/eliben/pycparser](https://github.com/eliben/pycparser) |
| Python | pydantic_core | 2.46.4 | transitive | MIT | [https://github.com/pydantic/pydantic/tree/main/pydantic-core](https://github.com/pydantic/pydantic/tree/main/pydantic-core) |
| Python | pydantic-settings | 2.14.2 | transitive | MIT | [https://github.com/pydantic/pydantic-settings](https://github.com/pydantic/pydantic-settings) |
| Python | pyee | 13.0.1 | transitive | MIT | [https://github.com/jfhbrook/pyee](https://github.com/jfhbrook/pyee) |
| Python | Pygments | 2.20.0 | transitive | BSD-2-Clause | [https://github.com/pygments/pygments](https://github.com/pygments/pygments) |
| Python | PyJWT | 2.13.0 | transitive | MIT | [https://github.com/jpadilla/pyjwt](https://github.com/jpadilla/pyjwt) |
| Python | pyparsing | 3.3.2 | transitive | MIT | [https://github.com/pyparsing/pyparsing.git](https://github.com/pyparsing/pyparsing.git) |
| Python | python-dateutil | 2.9.0.post0 | transitive | Dual License | [https://github.com/dateutil/dateutil](https://github.com/dateutil/dateutil) |
| Python | python-debian | 1.1.1 | transitive | GPL-2.0-or-later | [https://salsa.debian.org/python-debian-team/python-debian](https://salsa.debian.org/python-debian-team/python-debian) |
| Python | python-dotenv | 1.2.2 | transitive | BSD-3-Clause | [https://github.com/theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) |
| Python | python-magic | 0.4.27 | transitive | MIT | [http://github.com/ahupp/python-magic](http://github.com/ahupp/python-magic) |
| Python | python-multipart | 0.0.32 | transitive | Apache-2.0 | [https://github.com/Kludex/python-multipart](https://github.com/Kludex/python-multipart) |
| Python | pytokens | 0.4.1 | transitive | MIT License | [https://github.com/tusharsadhwani/pytokens](https://github.com/tusharsadhwani/pytokens) |
| Python | referencing | 0.37.0 | transitive | MIT | [https://github.com/python-jsonschema/referencing](https://github.com/python-jsonschema/referencing) |
| Python | requests | 2.34.2 | transitive | Apache-2.0 | [https://github.com/psf/requests](https://github.com/psf/requests) |
| Python | rpds-py | 2026.5.1 | transitive | MIT | [https://github.com/crate-py/rpds](https://github.com/crate-py/rpds) |
| Python | scramp | 1.5.0 | transitive | MIT-0 | [https://codeberg.org/tlocke/scramp](https://codeberg.org/tlocke/scramp) |
| Python | setuptools | 81.0.0 | transitive | MIT | [https://github.com/pypa/setuptools](https://github.com/pypa/setuptools) |
| Python | shellingham | 1.5.4 | transitive | ISC License | [https://github.com/sarugaku/shellingham](https://github.com/sarugaku/shellingham) |
| Python | six | 1.17.0 | transitive | MIT | [https://github.com/benjaminp/six](https://github.com/benjaminp/six) |
| Python | sortedcontainers | 2.4.0 | transitive | Apache 2.0 | [http://www.grantjenks.com/docs/sortedcontainers/](http://www.grantjenks.com/docs/sortedcontainers/) |
| Python | sse-starlette | 3.4.5 | transitive | BSD-3-Clause | [https://github.com/sysid/sse-starlette](https://github.com/sysid/sse-starlette) |
| Python | starlette | 1.3.1 | transitive | BSD-3-Clause | [https://github.com/Kludex/starlette](https://github.com/Kludex/starlette) |
| Python | sympy | 1.14.0 | transitive | BSD | [https://github.com/sympy/sympy](https://github.com/sympy/sympy) |
| Python | tabulate | 0.10.0 | transitive | MIT | [https://github.com/astanin/python-tabulate](https://github.com/astanin/python-tabulate) |
| Python | tomlkit | 0.15.2 | transitive | MIT | [https://github.com/python-poetry/tomlkit](https://github.com/python-poetry/tomlkit) |
| Python | tqdm | 4.68.3 | transitive | MPL-2.0 AND MIT | [https://github.com/tqdm/tqdm](https://github.com/tqdm/tqdm) |
| Python | typer | 0.24.2 | transitive | MIT | [https://github.com/fastapi/typer](https://github.com/fastapi/typer) |
| Python | typing_extensions | 4.15.0 | transitive | PSF-2.0 | [https://github.com/python/typing_extensions](https://github.com/python/typing_extensions) |
| Python | typing-inspection | 0.4.2 | transitive | MIT | [https://github.com/pydantic/typing-inspection](https://github.com/pydantic/typing-inspection) |
| Python | urllib3 | 2.7.0 | transitive | MIT | [https://urllib3.readthedocs.io](https://urllib3.readthedocs.io) |

## Regeneration

Run:

```bash
uv run python proj_skills/compliance/dependency-license-inventory/scripts/generate_licenses_md.py
```

To verify that the committed inventory is current without rewriting it, run:

```bash
uv run python proj_skills/compliance/dependency-license-inventory/scripts/generate_licenses_md.py --check
```

Review any `UNKNOWN` entries against upstream package metadata before external
publication.
