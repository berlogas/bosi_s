import json, os, time, urllib.request, urllib.error

KEY = os.environ.get("NUMES_API_KEY", "sk-numes-v1-adfca4c956fdd6300419ebb9a84f8aeb0396ef9a722bd5da329bc196ae40981c")
URL = "https://api.numes.ai/api/v1/chat/completions"
MODEL = "deepseek/deepseek-v4.1-flash:free"

def probe(name, payload, stream=False, timeout=120):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if stream:
                print(f"       {name}: HTTP {r.status}, content-type: {r.headers.get('content-type')}")
                n, first, last, raw_head = 0, None, None, b""
                for line in r:
                    if len(raw_head) < 200:
                        raw_head += line
                    s = line.decode(errors="replace").strip()
                    if s.startswith("data:"):
                        n += 1
                        if first is None:
                            first = time.time() - t0
                        last = s[5:].strip()
                        if last == "[DONE]":
                            break
                if n:
                    print(f"[OK]   {name}: {n} SSE-чанков, первый через {first:.1f}s, всего {time.time()-t0:.1f}s")
                    print(f"       последний data: {(last or '')[:200]}")
                else:
                    print(f"[FAIL] {name}: ни одного SSE-чанка; начало ответа: {raw_head[:200]!r}")
            else:
                d = json.loads(r.read())
                txt = (d["choices"][0]["message"].get("content") or "")[:80]
                print(f"[OK]   {name}: {time.time()-t0:.1f}s, ответ: {txt!r}")
    except urllib.error.HTTPError as e:
        print(f"[FAIL] {name}: HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {e} (через {time.time()-t0:.1f}s)")

base = {"model": MODEL, "max_tokens": 32, "reasoning": {"enabled": False},
        "messages": [{"role": "user", "content": "Ответь одним словом: пинг"}]}

probe("1. маленький запрос", base)
probe("2. стриминг", {**base, "stream": True}, stream=True)  # <-- вот он, исправленный вызов
probe("3. большое тело ~200KB", {**base, "messages": [
    {"role": "system", "content": "x" * 200000}, *base["messages"]]})

tools = [{"type": "function", "function": {
    "name": "get_weather", "description": "Get current weather for a city",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
probe("4. как opencode: стрим+tools+reasoning", {
    "model": MODEL, "stream": True, "max_tokens": 800, "tools": tools, "tool_choice": "auto",
    "messages": [
        {"role": "system", "content": "You are a coding agent. Use tools when needed. " * 100},
        {"role": "user", "content": "Какая погода в Москве? Вызови инструмент."}]},
    stream=True)