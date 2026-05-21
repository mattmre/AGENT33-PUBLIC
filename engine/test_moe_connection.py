import json
import time
import urllib.error
import urllib.request

url = "http://127.0.0.1:8033/v1/chat/completions"
headers = {"Content-Type": "application/json"}
data = {
    "model": "qwen3-coder-next",
    "messages": [
        {"role": "system", "content": "You are AGENT-33. Answer concisely."},
        {"role": "user", "content": "What is the primary advantage of a Mixture of Experts (MoE) architecture for local execution?"}
    ],
    "temperature": 0.2,
    "max_tokens": 100
}

req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)

print("🚀 Sending test completion request to Qwen 80B MoE backend...")
start_time = time.time()

try:
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode("utf-8"))
        end_time = time.time()
        print(f"\n✅ Connection Successful! (Latency: {end_time - start_time:.2f}s)\n")
        print("Response from Qwen3-Coder-Next:")
        print("-" * 50)
        print(result["choices"][0]["message"]["content"])
        print("-" * 50)
except urllib.error.URLError as e:
    print(f"\n❌ Connection Failed: {e}")
    print("Ensure the server says 'HTTP server is listening' in the Powershell window.")
