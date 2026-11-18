import http.client, json, os, time

KEY = os.environ.get("NUMES_API_KEY", "sk-numes-v1-adfca4c956fdd6300419ebb9a84f8aeb0396ef9a722bd5da329bc196ae40981c")
HOST = "api.numes.ai"
MODEL = "deepseek/deepseek-v4.1-flash:free"
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

print("=== A. Keep-alive: переживает ли соединение паузы 15/45/90 с ===", flush=True)
conn = http.client.HTTPSConnection(HOST, timeout=30)
try:
    for pause in (0, 15, 45, 90):
        if pause:
            print(f"  ...пауза {pause} с...", flush=True)
            time.sleep(pause)
        conn.request("GET", "/api/v1/models", headers=H)
        r = conn.getresponse(); r.read()
        print(f"  [OK] запрос по ТОМУ ЖЕ соединению после паузы {pause} с: HTTP {r.status}", flush=True)
    print("  ==> соединение выдержало все паузы", flush=True)
except Exception as e:
    print(f"  [!] соединение умерло: {type(e).__name__}: {e}", flush=True)
    print("  ==> шлюз закрывает idle-соединения; Bun, переиспользуя мёртвый сокет, даст ECONNRESET", flush=True)
finally:
    conn.close()

print("\n=== B. Длинный стрим: эссе ~2000 слов, до 10000 токенов ===", flush=True)
payload = {"model": MODEL, "stream": True, "max_tokens": 10000,
           "messages": [{"role": "user", "content":
               "Напиши подробное связное эссе примерно на 2000 слов об истории навигации: "
               "от компаса до GPS. Сплошным текстом, без списков."}]}
conn = http.client.HTTPSConnection(HOST, timeout=300)
t0 = time.time(); n = 0; last_t = t0; max_gap = 0.0; done = False
try:
    conn.request("POST", "/api/v1/chat/completions", body=json.dumps(payload), headers=H)
    r = conn.getresponse()
    print("  HTTP", r.status, "|", r.getheader("content-type"), flush=True)
    while True:
        line = r.readline()
        if not line:
            break
        if line.startswith(b"data:"):
            now = time.time()
            max_gap = max(max_gap, now - last_t); last_t = now; n += 1
            if b"[DONE]" in line:
                done = True
                break
            if n % 200 == 0:
                print(f"  ...{n} чанков, {now - t0:.0f} с", flush=True)
    tag = "OK" if done else "!"
    print(f"  [{tag}] чанков: {n}, всего {time.time() - t0:.1f} с, "
          f"макс. пауза между чанками {max_gap:.1f} с, [DONE]: {done}", flush=True)
except Exception as e:
    print(f"  [FAIL] обрыв на {time.time() - t0:.1f} с, чанков {n}: {type(e).__name__}: {e}", flush=True)
finally:
    conn.close()