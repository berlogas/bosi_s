"""Spike 01 — интроспекция фактического API paper-qa 2026.8.12.

Запуск: .venv/Scripts/python spikes/01_introspect.py
"""

from __future__ import annotations

import inspect
import json
import sys

import paperqa
from paperqa import Docs, Settings
from paperqa.settings import AgentSettings

print(f"python      : {sys.version.split()[0]}")
print(f"paper-qa    : {paperqa.__version__}")
print(f"module      : {paperqa.__file__}")
print(f"top-level   : {sorted(n for n in dir(paperqa) if not n.startswith('_'))}")
print()

print("=== Docs public API ===")
for name in sorted(n for n in dir(Docs) if not n.startswith("_")):
    obj = getattr(Docs, name)
    if callable(obj):
        try:
            sig = str(inspect.signature(obj))
        except (TypeError, ValueError):
            sig = "(?)"
        print(f"  {name}{sig}")
    else:
        print(f"  {name}  [attr]")
print()

REQUIRED = ["aadd", "aadd_file", "aadd_url", "aadd_texts", "aquery", "aget_evidence", "delete", "clear_docs"]
print("=== checklist из interface.md ===")
for name in REQUIRED:
    member = getattr(Docs, name, None)
    if member is None:
        print(f"  MISSING  {name}")
        continue
    kind = "async" if inspect.iscoroutinefunction(member) else "sync"
    try:
        ret = inspect.signature(member).return_annotation
    except (TypeError, ValueError):
        ret = "?"
    print(f"  OK       {name:15s} {kind:5s} -> {ret}")
print()

print("=== return type of Docs.aquery ===")
print(" ", inspect.signature(Docs.aquery))
print()

print("=== Settings fields (top level) ===")
for name, field in Settings.model_fields.items():
    print(f"  {name:35s} default={field.default!r}")
print()

print("=== Settings.answer fields ===")
answer_cls = Settings.model_fields["answer"].annotation
for name, field in answer_cls.model_fields.items():
    print(f"  {name:40s} default={field.default!r}")
print()

print("=== Settings.parsing fields ===")
parsing_cls = Settings.model_fields["parsing"].annotation
for name, field in parsing_cls.model_fields.items():
    print(f"  {name:40s} default={field.default!r}")
print()

print("=== Settings.agent (AgentSettings) fields ===")
for name, field in AgentSettings.model_fields.items():
    print(f"  {name:30s} default={field.default!r}")
print()

print("=== PQASession / Context / Doc fields ===")
from paperqa.types import Context, Doc, PQASession, Text

for cls in (PQASession, Context, Doc, Text):
    print(f"  -- {cls.__name__}")
    for name, field in cls.model_fields.items():
        print(f"     {name:25s} {field.annotation}")
print()

print("=== PQASession methods ===")
print(" ", sorted(n for n in dir(PQASession) if not n.startswith("_")))
print()

print("=== agent_query / ask signature ===")
from paperqa import agent_query, ask

print("  agent_query", inspect.signature(agent_query))
print("  ask        ", inspect.signature(ask))
print()

print("=== extras для msoffice ===")
from importlib.metadata import metadata

extras = metadata("paper-qa").get_all("Provides-Extra") or []
print("  Provides-Extra:", extras)
print()

print("=== models/embedding classes ===")
for name in ("HybridEmbeddingModel", "SparseEmbeddingModel", "LiteLLMEmbeddingModel", "NumpyVectorStore"):
    print(f"  {name:28s} {'present' if hasattr(paperqa, name) else 'ABSENT'}")

print()
print("=== Docs.__init__ / state attributes ===")
print(" ", inspect.signature(Docs.__init__))
docs = Docs()
print("  instance attrs:", sorted(vars(docs)))
print("  has __getstate__:", hasattr(docs, "__getstate__"), "| has __reduce__:",
      hasattr(docs, "__reduce__"), "| has model_dump:", hasattr(docs, "model_dump"))

print()
print("=== versions ===")
from importlib.metadata import version

for pkg in ("lmi", "fhlmi", "fhaviary", "litellm", "tantivy", "pypdf", "numpy"):
    try:
        print(f"  {pkg:12s} {version(pkg)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {pkg:12s} n/a ({type(exc).__name__})")

print()
print("=== pqa CLI ===")
try:
    import subprocess

    out = subprocess.run([sys.executable, "-m", "paperqa", "--help"], capture_output=True, text=True, timeout=120)
    print("  rc =", out.returncode)
    print("  " + (out.stdout or out.stderr)[:1200].replace("\n", "\n  "))
except Exception as exc:  # noqa: BLE001
    print("  CLI check failed:", exc)

print()
print("SPike 01 done. Machine-readable dump:")
dump = {
    "paper_qa_version": paperqa.__version__,
    "python": sys.version.split()[0],
    "docs_methods": sorted(n for n in dir(Docs) if not n.startswith("_")),
    "settings_top": {n: repr(f.default) for n, f in Settings.model_fields.items()},
    "answer": {n: repr(f.default) for n, f in answer_cls.model_fields.items()},
    "parsing": {n: repr(f.default) for n, f in parsing_cls.model_fields.items()},
    "agent": {n: repr(f.default) for n, f in AgentSettings.model_fields.items()},
    "pqasession": sorted(PQASession.model_fields),
    "context": sorted(Context.model_fields),
    "doc": sorted(Doc.model_fields),
    "extras": extras,
    "docs_instance_attrs": sorted(vars(docs)),
}
with open("spikes/01_introspect.json", "w", encoding="utf-8") as fh:
    json.dump(dump, fh, indent=2, ensure_ascii=False)
print("  -> spikes/01_introspect.json")