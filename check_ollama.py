import httpx
import json

try:
    r = httpx.get('http://localhost:11434/api/tags', timeout=5.0)
    print(f"Status: {r.status_code}")
    print(json.dumps(r.json(), indent=2))
except Exception as e:
    print(f"Error connecting to Ollama: {e}")
