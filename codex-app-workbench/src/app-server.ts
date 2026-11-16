// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
// SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
// SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { EventEmitter } from "node:events";
import { createInterface } from "node:readline";

type JsonObject = Record<string, unknown>;

type Pending = {
  resolve(value: unknown): void;
  reject(error: Error): void;
  timer: NodeJS.Timeout;
};

type RpcResponse = {
  id?: number;
  result?: unknown;
  error?: { code?: number; message?: string };
  method?: string;
  params?: unknown;
};

export class AppServerClient extends EventEmitter {
  readonly #executable: string;
  readonly #timeoutMs: number;
  readonly #pending = new Map<number, Pending>();
  #process: ChildProcessWithoutNullStreams | undefined;
  #nextId = 1;

  constructor(options: { executable?: string; timeoutMs?: number } = {}) {
    super();
    this.#executable = options.executable ?? process.env.CODEX_BIN ?? "codex";
    this.#timeoutMs = options.timeoutMs ?? 20_000;
  }

  async start(): Promise<void> {
    if (this.#process) return;
    const child = spawn(this.#executable, ["app-server"], {
      stdio: ["pipe", "pipe", "pipe"],
      shell: false,
      env: { ...process.env, NO_COLOR: "1" },
    });
    this.#process = child;
    const stderr: string[] = [];
    createInterface({ input: child.stderr }).on("line", (line) => {
      stderr.push(line);
      if (stderr.length > 20) stderr.shift();
    });
    createInterface({ input: child.stdout }).on("line", (line) => this.#onLine(line));
    child.once("exit", (code) => {
      const suffix = stderr.length ? `: ${stderr.join("\n")}` : "";
      this.#rejectAll(new Error(`codex app-server exited with ${code ?? "signal"}${suffix}`));
      this.#process = undefined;
    });
    child.once("error", (error) => this.#rejectAll(error));

    await this.request("initialize", {
      clientInfo: {
        name: "codex_app_workbench",
        title: "Codex App Workbench",
        version: "1.0.0",
      },
      capabilities: { experimentalApi: true },
    });
    this.notify("initialized", {});
  }

  request(method: string, params: JsonObject = {}): Promise<unknown> {
    const processHandle = this.#process;
    if (!processHandle) throw new Error("app-server is not started");
    const id = this.#nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`RPC ${method} timed out after ${this.#timeoutMs}ms`));
      }, this.#timeoutMs);
      this.#pending.set(id, { resolve, reject, timer });
      processHandle.stdin.write(`${JSON.stringify({ method, id, params })}\n`);
    });
  }

  notify(method: string, params: JsonObject = {}): void {
    if (!this.#process) throw new Error("app-server is not started");
    this.#process.stdin.write(`${JSON.stringify({ method, params })}\n`);
  }

  async close(): Promise<void> {
    const child = this.#process;
    if (!child) return;
    this.#process = undefined;
    child.stdin.end();
    child.kill("SIGTERM");
    this.#rejectAll(new Error("app-server client closed"));
  }

  #onLine(line: string): void {
    let message: RpcResponse;
    try {
      message = JSON.parse(line) as RpcResponse;
    } catch {
      this.emit("protocolError", new Error("app-server emitted invalid JSON"));
      return;
    }
    if (typeof message.id === "number") {
      const pending = this.#pending.get(message.id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.#pending.delete(message.id);
      if (message.error) {
        pending.reject(
          new Error(`RPC error ${message.error.code ?? "unknown"}: ${message.error.message ?? "unknown"}`),
        );
      } else {
        pending.resolve(message.result);
      }
      return;
    }
    if (message.method) this.emit("notification", message);
  }

  #rejectAll(error: Error): void {
    for (const pending of this.#pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.#pending.clear();
  }
}

export async function withAppServer<T>(
  operation: (client: AppServerClient) => Promise<T>,
): Promise<T> {
  const client = new AppServerClient();
  await client.start();
  try {
    return await operation(client);
  } finally {
    await client.close();
  }
}
