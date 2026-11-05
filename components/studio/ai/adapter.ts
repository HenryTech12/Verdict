"use client";

import type { AgAiEvent, AgAiOutputItem, AgLlmAdapter, AgLlmRequest, AgLlmResponseHandler } from "ag-studio";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const token = process.env.NEXT_PUBLIC_API_TOKEN ?? "verdict-demo-token";

function messageContent(message: AgLlmRequest["input"][number]): string {
  if ("content" in message && Array.isArray(message.content)) return message.content.map((part) => "text" in part ? part.text : "").join("\n");
  return "";
}

export const groqStudioAdapter: AgLlmAdapter = {
  executeTurn(request: AgLlmRequest): AgLlmResponseHandler {
    let responseText = "";
    const messageId = `msg-${Date.now()}`;
    const complete = fetch(`${apiUrl}/ai/proxy`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ messages: request.input.map((message) => ({ role: "role" in message ? message.role : "user", content: messageContent(message) })), instructions: request.instructions, tools: request.tools, tool_choice: request.toolChoice, response_format: request.responseFormat.type === "text" ? undefined : { type: "json_object" } }) }).then(async (result) => {
      if (!result.ok) throw new Error("The analyst agent is unavailable");
      const payload = await result.json() as { choices?: { message?: { content?: string } }[] };
      responseText = payload.choices?.[0]?.message?.content ?? "";
      const output: AgAiOutputItem = { id: messageId, kind: "output", type: "message", role: "assistant", status: "completed", content: [{ type: "text", text: responseText, annotations: [] }] };
      return { id: `response-${messageId}`, createdAt: Date.now(), status: "completed" as const, output: [output] };
    });
    const stream: AsyncIterable<AgAiEvent> = { async *[Symbol.asyncIterator]() { yield { type: "TEXT_MESSAGE_START", messageId, role: "assistant" }; await complete; if (responseText) yield { type: "TEXT_MESSAGE_CONTENT", messageId, delta: responseText }; yield { type: "TEXT_MESSAGE_END", messageId }; } };
    return { stream, complete };
  },
};
