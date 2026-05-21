import json
import time
import urllib.error
import urllib.request

url = "http://127.0.0.1:8033/v1/chat/completions"
headers = {"Content-Type": "application/json"}
data = {
    "model": "qwen3-coder-next",
    "messages": [
        {"role": "user", "content": "Write a highly detailed explanation of the history of the Linux kernel, including code architecture decisions, spanning at least 4 paragraphs."}
    ],
    "temperature": 0.4,
    "max_tokens": 512,
    "stream": True
}

req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)

print("🚀 Starting TPS Benchmark on Qwen 80B MoE...")
print("-" * 50)

start_time = time.time()
first_token_time = None
token_count = 0

try:
    with urllib.request.urlopen(req) as response:
        for line in response:
            line = line.decode('utf-8').strip()
            if not line or line == "data: [DONE]":
                continue

            if line.startswith("data: "):
                chunk = json.loads(line[6:])

                # Check if we got content
                if len(chunk["choices"]) > 0 and "delta" in chunk["choices"][0]:
                    content = chunk["choices"][0]["delta"].get("content", "")
                    if content:
                        if first_token_time is None:
                            first_token_time = time.time()
                            print(f"\n[Time to First Token (TTFT): {first_token_time - start_time:.2f}s]")
                            print("\nGenerating", end="", flush=True)

                        token_count += 1
                        if token_count % 10 == 0:
                            print(".", end="", flush=True)

        end_time = time.time()

        # Calculate metrics
        total_time = end_time - start_time
        decode_time = end_time - first_token_time if first_token_time else 0
        tps = token_count / decode_time if decode_time > 0 else 0

        print(f"\n\n{'='*50}")
        print("📊 Benchmark Results:")
        print(f"Total Tokens Generated : {token_count}")
        print(f"Time to First Token    : {first_token_time - start_time:.2f} seconds")
        print(f"Total Decoding Time    : {decode_time:.2f} seconds")
        print(f"Tokens Per Second (TPS): {tps:.2f} tokens/sec")
        print(f"{'='*50}")

except urllib.error.URLError as e:
    print(f"\n❌ Connection Failed: {e}")
except Exception as e:
    print(f"\n❌ Error occurred: {e}")
