"use client";

import type { AgAiEvent, AgAiOutputItem, AgLlmAdapter, AgLlmRequest, AgLlmResponseHandler } from "ag-studio";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const token = process.env.NEXT_PUBLIC_API_TOKEN ?? "verdict-demo-token";
type LooseMessage = { role?: string; content?: unknown; type?: string; call_id?: string; name?: string; arguments?: string; output?: unknown; tool_calls?: unknown[]; [key: string]: unknown };
type AgTool = { name?: string; description?: string; parameters?: Record<string, unknown>; kind?: string; provider?: unknown };
type GroqToolCall = { id: string; type: "function"; function: { name: string; arguments: string } };

function textContent(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((part) => part && typeof part === "object" && "text" in part ? String((part as { text: unknown }).text) : "").filter(Boolean).join("\n");
  return value == null ? "" : JSON.stringify(value);
}

function normalizeMessages(request: AgLlmRequest): Record<string, unknown>[] {
  const raw = request as unknown as { input?: LooseMessage[]; instructions?: unknown };
  const messages: Record<string, unknown>[] = [];
  const instructions = typeof raw.instructions === "string" ? raw.instructions.trim() : "";
  if (instructions) messages.push({ role: "system", content: instructions });
  for (const item of raw.input ?? []) {
    if (item.type === "function_call_output") {
      messages.push({ role: "tool", tool_call_id: String(item.call_id ?? ""), content: textContent(item.output) });
      continue;
    }
    if (item.type === "function_call") {
      const previous = messages[messages.length - 1];
      const call = { id: String(item.call_id ?? item.id ?? ""), type: "function", function: { name: String(item.name ?? ""), arguments: String(item.arguments ?? "{}") } };
      if (previous?.role === "assistant") previous.tool_calls = [...((previous.tool_calls as unknown[]) ?? []), call];
      else messages.push({ role: "assistant", content: null, tool_calls: [call] });
      continue;
    }
    const role = ["system", "user", "assistant", "tool"].includes(String(item.role)) ? String(item.role) : "user";
    const content = textContent(item.content);
    if (content || role === "assistant") messages.push({ role, content });
  }
  return messages;
}

function normalizeTools(tools: unknown): Record<string, unknown>[] {
  if (!Array.isArray(tools)) return [];
  return (tools as AgTool[]).slice(0, 8).flatMap((tool) => {
    if (tool.kind === "provided" && tool.provider && typeof tool.provider === "object") return [tool.provider as Record<string, unknown>];
    if (!tool.name || !tool.parameters || typeof tool.parameters !== "object") return [];
    return [{ type: "function", function: { name: tool.name, description: tool.description ?? "", parameters: tool.parameters } }];
  });
}

function normalizeToolChoice(choice: unknown): unknown {
  if (choice === "none" || choice === "auto" || choice === "required") return choice;
  if (choice && typeof choice === "object") {
    const value = choice as { name?: unknown; function?: { name?: unknown } };
    const name = value.function?.name ?? value.name;
    if (typeof name === "string") return { type: "function", function: { name } };
  }
  return "auto";
}

export const groqStudioAdapter: AgLlmAdapter = {
  executeTurn(request: AgLlmRequest): AgLlmResponseHandler {
    let responseText = "";
    let toolCalls: GroqToolCall[] = [];
    const messageId = `msg-${Date.now()}`;
    const raw = request as unknown as { tools?: unknown[]; toolChoice?: unknown; responseFormat?: { type?: string } };
    const tools = normalizeTools(raw.tools);
    const complete = fetch(`${apiUrl}/ai/proxy`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: normalizeMessages(request),
        tools,
        tool_choice: normalizeToolChoice(raw.toolChoice),
        response_format: raw.responseFormat && raw.responseFormat.type !== "text" ? { type: "json_object" } : undefined,
      }),
    }).then(async (result) => {
      if (!result.ok) {
        const detail = await result.json().catch(() => ({})) as { error?: { message?: string } };
        throw new Error(detail.error?.message ?? "The analyst agent is unavailable");
      }
      const payload = await result.json() as { choices?: { message?: { content?: string | null; tool_calls?: GroqToolCall[] } }[] };
      const message = payload.choices?.[0]?.message;
      responseText = message?.content ?? "";
      toolCalls = message?.tool_calls ?? [];
      const output: unknown[] = [];
      if (responseText) output.push({ id: messageId, kind: "output", type: "message", role: "assistant", status: "completed", content: [{ type: "text", text: responseText, annotations: [] }] });
      // Keep structured function calls in the completed response so the AG Studio harness can process them.
      for (const call of toolCalls) output.push({ id: `call-${call.id}`, kind: "output", type: "function_call", call_id: call.id, name: call.function.name, arguments: call.function.arguments, status: "completed" });
      return { id: `response-${messageId}`, createdAt: Date.now(), status: "completed" as const, output: output as AgAiOutputItem[] };
    });
    const stream: AsyncIterable<AgAiEvent> = { async *[Symbol.asyncIterator]() {
      if (responseText || !toolCalls.length) yield { type: "TEXT_MESSAGE_START", messageId, role: "assistant" };
      await complete;
      if (responseText) yield { type: "TEXT_MESSAGE_CONTENT", messageId, delta: responseText };
      if (responseText || !toolCalls.length) yield { type: "TEXT_MESSAGE_END", messageId };
      for (const call of toolCalls) {
        yield { type: "TOOL_CALL_START", toolCallId: call.id, toolCallName: call.function.name } as AgAiEvent;
        yield { type: "TOOL_CALL_ARGS", toolCallId: call.id, delta: call.function.arguments } as AgAiEvent;
        yield { type: "TOOL_CALL_END", toolCallId: call.id } as AgAiEvent;
      }
    } };
    return { stream, complete };
  },
};
