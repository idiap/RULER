// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
// SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
// SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import assert from "node:assert/strict";
import test from "node:test";

import { callableAppNames } from "../src/apps.js";
import { assertReadOnlyMethod, READ_ONLY_METHODS } from "../src/policy.js";

test("the explorer admits app discovery", () => {
  assert.doesNotThrow(() => assertReadOnlyMethod("app/installed"));
  assert.doesNotThrow(() => assertReadOnlyMethod("app/list"));
});

test("the generic explorer rejects mutations", () => {
  for (const method of [
    "account/logout",
    "config/value/write",
    "mcpServer/tool/call",
    "thread/delete",
  ]) {
    assert.throws(() => assertReadOnlyMethod(method), /Refusing non-read-only RPC/);
  }
});

test("the allowlist contains only read- or list-shaped methods", () => {
  for (const method of READ_ONLY_METHODS) {
    assert.match(method, /\/(read|list|installed)$/);
  }
});

test("briefing inventory includes only enabled and callable apps", () => {
  assert.deepEqual(
    callableAppNames({
      apps: [
        { runtimeName: "Gmail", enabled: true, callable: true },
        { runtimeName: "Slack", enabled: true, callable: false },
        { runtimeName: "Calendar", enabled: false, callable: true },
      ],
    }),
    ["Gmail"],
  );
});
