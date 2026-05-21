import asyncio

import httpx


async def main():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post('http://host.docker.internal:8033/v1/chat/completions', json={'model': 'Qwen3-Coder-Next-Q4_K_M.gguf', 'messages': [{'role': 'user', 'content': 'hi'}]})
            print(r.status_code, r.text)
    except Exception as e:
        print(f"ERROR: {type(e).__name__} - {e}")

asyncio.run(main())
