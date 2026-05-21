import asyncio
import json

import httpx


async def run_test():
    print("Testing Phase 34 Mechanics: AST Extraction, A2A Subordinate, Handoff Context Wipe")

    # Needs the backend running.
    async with httpx.AsyncClient() as client:
        # 1. Start a workflow or chat that forces these mechanics
        payload = {
             "messages": [
                 {
                     "role": "user",
                     "content": "Please analyze the `d:\\GITHUB\\AGENT33\\engine\\src\\agent33\\config.py` file using the tldr_read_enforcer tool to understand its structure, then use deploy_a2a_subordinate to write a regex to parse environment variables from it, and finally handoff the results to an implementor agent."
                 }
             ],
             "model": "gpt-4o", # or whatever default
             "stream": False
        }

        try:
            print("Sending request to /v1/chat/completions...")
            response = await client.post("http://localhost:8000/v1/chat/completions", json=payload, timeout=120)
            print("Response:", response.status_code)
            print(json.dumps(response.json(), indent=2))
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())
