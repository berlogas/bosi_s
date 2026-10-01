"""Spike 04 — бенчмарк эмбеддингов на CPU: стоимость зависит от размера чанка и батча.

Проверяет, почему /api/embed для PDF занял 10m42s, и ищет приемлемую конфигурацию:
  * одиночные input разного размера (500..8000 символов)
  * батчи (5/10/20 чанков по 5000 символов)
  * влияние параметра truncate (ollama /api/embed)
  * оценка числа токенов и throughput

Запуск: PYTHONIOENCODING=utf-8 .venv/Scripts/python spikes/04_embed_bench.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:11434"
MODEL = "nomic-embed-text"

RUSSIAN_SEED = (
    "Измерение биомассы водорослей в Баренцевом море выполняется тремя базовыми методами: "
    "хлорофилл-а метод, стеклянные фильтры GF/F и сожжение с потерей сухого вещества. "
)


def embed(inputs: list[str], truncate: bool | None = None) -> tuple[float, int]:
    payload: dict[str, object] = {"model": MODEL, "input": inputs}
    if truncate is not None:
        payload["truncate"] = truncate
    t0 = time.perf_counter()
    r = httpx.post(f"{BASE}/api/embed", json=payload, timeout=3600)
    r.raise_for_status()
    dt = time.perf_counter() - t0
    return dt, len(r.json().get("embeddings", []))


def main() -> None:
    print("=== SPike 04 | ollama nomic-embed-text, CPU ===", flush=True)
    info = httpx.get(f"{BASE}/api/ps", timeout=30).json()
    print("loaded:", [m["name"] for m in info.get("models", [])], flush=True)
    print()

    results: list[dict[str, object]] = []

    print("--- одиночные input, truncate не задан (по умолчанию) ---")
    for chars in (500, 1000, 2000, 3000, 5000, 8000):
        text = (RUSSIAN_SEED * 40)[:chars]
        dt, n = embed([text])
        approx_tokens = chars / 2.2  # русский текст ~2.2 симв./токен
        print(f"  {chars:5d} симв (~{approx_tokens:6.0f} ток) -> {dt:7.2f}s  "
              f"({approx_tokens / dt:6.1f} ток/с)", flush=True)
        results.append({"chars": chars, "mode": "single", "truncate": None, "seconds": round(dt, 2),
                        "count": n})

    print("\n--- одиночные input, truncate=true ---")
    for chars in (2000, 5000, 8000):
        text = (RUSSIAN_SEED * 40)[:chars]
        dt, n = embed([text], truncate=True)
        print(f"  {chars:5d} симв, truncate=true -> {dt:7.2f}s", flush=True)
        results.append({"chars": chars, "mode": "single", "truncate": True, "seconds": round(dt, 2),
                        "count": n})

    print("\n--- батчи по 5000 символов (как chunking бумаги: chunk_chars=5000) ---")
    for batch in (5, 10, 20):
        inputs = [(RUSSIAN_SEED * 40)[:5000] for _ in range(batch)]
        dt, n = embed(inputs)
        print(f"  batch={batch:3d} x 5000 симв -> {dt:7.2f}s  ({dt / batch:6.2f}s/чанк)", flush=True)
        results.append({"chars": 5000, "mode": "batch", "batch": batch, "seconds": round(dt, 2),
                        "count": n})

    print("\n--- батчи по 2000 символов (chunk_chars=2000) ---")
    for batch in (10, 25):
        inputs = [(RUSSIAN_SEED * 40)[:2000] for _ in range(batch)]
        dt, n = embed(inputs)
        print(f"  batch={batch:3d} x 2000 симв -> {dt:7.2f}s  ({dt / batch:6.2f}s/чанк)", flush=True)
        results.append({"chars": 2000, "mode": "batch", "batch": batch, "seconds": round(dt, 2),
                        "count": n})

    out = ROOT / "spikes" / "04_embed_bench.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[saved] {out.relative_to(ROOT)}")
    print("SPike 04 done.")


if __name__ == "__main__":
    main()