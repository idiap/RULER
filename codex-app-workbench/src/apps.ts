// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
// SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
// SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import { withAppServer } from "./app-server.js";

export async function installedApps(): Promise<unknown> {
  return withAppServer((client) => client.request("app/installed", {}));
}

export async function availableApps(limit = 100): Promise<unknown> {
  return withAppServer((client) => client.request("app/list", { limit }));
}

export function callableAppNames(payload: unknown): string[] {
  if (!payload || typeof payload !== "object" || !("apps" in payload)) return [];
  const apps = (payload as { apps?: unknown }).apps;
  if (!Array.isArray(apps)) return [];
  return apps.flatMap((app) => {
    if (!app || typeof app !== "object") return [];
    const value = app as Record<string, unknown>;
    return value.enabled === true && value.callable === true && typeof value.runtimeName === "string"
      ? [value.runtimeName]
      : [];
  });
}
