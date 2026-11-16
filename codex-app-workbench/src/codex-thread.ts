// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
// SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
// SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import { Codex } from "@openai/codex-sdk";

export type ThreadRun = {
  threadId?: string;
  finalResponse: string;
};

export async function runCodexThread(
  prompt: string,
  options: { resume?: string } = {},
): Promise<ThreadRun> {
  if (!prompt.trim()) throw new Error("A non-empty prompt is required");
  const codex = new Codex();
  const thread = options.resume
    ? codex.resumeThread(options.resume)
    : codex.startThread();
  const result = await thread.run(prompt);
  const threadId =
    "id" in thread && typeof thread.id === "string" ? thread.id : options.resume;
  return {
    ...(threadId ? { threadId } : {}),
    finalResponse: result.finalResponse,
  };
}
