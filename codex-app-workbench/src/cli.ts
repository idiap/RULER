#!/usr/bin/env node
// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
// SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
// SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import { availableApps, callableAppNames, installedApps } from "./apps.js";
import { withAppServer } from "./app-server.js";
import { runCodexThread } from "./codex-thread.js";
import { assertReadOnlyMethod } from "./policy.js";

function usage(): never {
  console.error(`Usage:
  npm run apps
  npm run app-catalog
  npm run brief
  npm run chat -- "Use my installed apps to prepare today's briefing"
  npm run chat -- --resume <thread-id> "Continue the briefing"
  node dist/src/cli.js rpc <read-only-method> [json-params]`);
  process.exit(2);
}

function print(value: unknown): void {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

async function main(args: string[]): Promise<void> {
  const [command, subcommand, ...rest] = args;
  if (command === "apps" && subcommand === "installed") {
    print(await installedApps());
    return;
  }
  if (command === "apps" && subcommand === "list") {
    print(await availableApps());
    return;
  }
  if (command === "brief") {
    const inventory = await installedApps();
    const apps = callableAppNames(inventory);
    if (!apps.length) throw new Error("No enabled, callable apps were discovered");
    const prompt = [
      "Prepare a concise personal operations briefing using only relevant installed apps.",
      `The live app inventory is: ${apps.join(", ")}.`,
      "Use read operations only. Do not send messages, create or modify events, edit files,",
      "change settings, or install plugins. Cover urgent email, the next 48 hours of calendar,",
      "Slack mentions/action items, and relevant documents or sites when those apps exist.",
      "State clearly when an app has no relevant data or cannot be accessed.",
    ].join(" ");
    print(await runCodexThread(prompt));
    return;
  }
  if (command === "chat") {
    const resumeIndex = args.indexOf("--resume");
    const resume = resumeIndex >= 0 ? args[resumeIndex + 1] : undefined;
    const promptParts = args.slice(1).filter((_, index) => {
      const absolute = index + 1;
      return absolute !== resumeIndex && absolute !== resumeIndex + 1;
    });
    const prompt = promptParts.join(" ");
    if (!prompt || (resumeIndex >= 0 && !resume)) usage();
    print(await runCodexThread(prompt, resume ? { resume } : {}));
    return;
  }
  if (command === "rpc" && subcommand) {
    assertReadOnlyMethod(subcommand);
    const params = rest[0] ? (JSON.parse(rest[0]) as Record<string, unknown>) : {};
    print(await withAppServer((client) => client.request(subcommand, params)));
    return;
  }
  usage();
}

main(process.argv.slice(2)).catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`codex-app-workbench: ${message}`);
  process.exitCode = 1;
});
