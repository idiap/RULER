// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
// SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
// SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

/** Stable methods that cannot mutate Codex, apps, accounts, or user data. */
export const READ_ONLY_METHODS = new Set([
  "account/read",
  "app/installed",
  "app/list",
  "app/read",
  "collaborationMode/list",
  "experimentalFeature/list",
  "hooks/list",
  "mcpServerStatus/list",
  "model/list",
  "permissionProfile/list",
  "skills/list",
  "thread/list",
  "thread/read",
]);

export function assertReadOnlyMethod(method: string): void {
  if (!READ_ONLY_METHODS.has(method)) {
    throw new Error(
      `Refusing non-read-only RPC method ${JSON.stringify(method)}. ` +
        "Add a purpose-built approval flow before enabling mutations.",
    );
  }
}
