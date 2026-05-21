import type { DomainConfig } from "../../types";

export const chatDomain: DomainConfig = {
  id: "chat",
  title: "Chat",
  description: "LLM chat completions.",
  operations: [
    {
      id: "chat-completions",
      title: "Chat Completion",
      method: "POST",
      path: "/v1/chat/completions",
      description: "OpenAI-compatible chat completion.",
      instructionalText: "Submit a direct prompt to the large language model exactly as you would through the main chat interface. Useful for testing raw response speed and model capabilities.",
      schemaInfo: {
        body: {
          description: "An array of conversation messages identical to the standard OpenAI API format requesting a model response.",
          example: '{\n  "model": "openrouter/auto",\n  "messages": [\n    { "role": "system", "content": "You are a helpful assistant." },\n    { "role": "user", "content": "Hello, how are you?" }\n  ],\n  "temperature": 0.2\n}'
        }
      },
      defaultBody: JSON.stringify(
        {
          model: "openrouter/auto",
          messages: [{ role: "user", content: "Summarize AGENT-33 status." }],
          temperature: 0.2
        },
        null,
        2
      )
    }
  ]
};
