# Интерфейс работы с PaperQA2 для Python-разработки

Этот документ описывает рекомендуемый интерфейс работы с PaperQA2 / `paper-qa` для разработки на Python. Он предназначен для передачи агенту-разработчику как техническое задание или контекст для реализации интеграции.

---

## 1. Общая рекомендация

Для разработки на Python рекомендуется использовать **программный Python API** библиотеки `paper-qa`, а не только CLI `pqa`.

Причины:

1. **Контроль над документами**  
   Через объект `Docs` можно явно добавлять файлы, удалять документы, очищать базу и задавать вопросы.

2. **Асинхронность**  
   Основные методы обработки документов и запросов асинхронные, что удобно для сервисов, очередей, API и агентов.

3. **Детерминированность**  
   Для production-разработки лучше управлять документами вручную, а не полагаться только на автономный агентный поиск.

4. **Гибкость**  
   Можно использовать два уровня:
   - высокоуровневый: `ask()` / `agent_query()` — когда агент сам ищет и подтягивает документы;
   - низкоуровневый: `Docs.aadd()`, `Docs.aquery()`, `Docs.delete()` — когда вы сами управляете набором документов.

---

## 2. Название пакета

Проект может называться **PaperQA2**, но Python-пакет обычно импортируется как:

```python
from paperqa import Docs, Settings
```

или:

```python
from paperqa import ask, agent_query, Settings
```

То есть в коде нужно ориентироваться на модуль `paperqa`, а не `paperqa2`.

---

## 3. Требования к окружению

### Версия Python

Рекомендуется:

```text
Python 3.11+
```

### Установка

```bash
python -m venv .venv
source .venv/bin/activate

pip install paper-qa
```

Для воспроизводимости зафиксировать версию:

```bash
pip freeze > requirements.lock
```

### Переменные окружения

В зависимости от LLM-провайдера нужно задать ключи.

Пример для OpenAI:

```bash
export OPENAI_API_KEY="..."
```

Пример для Anthropic:

```bash
export ANTHROPIC_API_KEY="..."
```

Если используется другой провайдер через LiteLLM, нужно задать соответствующие переменные окружения.

Опционально можно задать домашнюю директорию PaperQA:

```bash
export PQA_HOME="$HOME/.pqa"
```

По умолчанию обычно используется `~/.pqa/`.

---

## 4. Рекомендуемая архитектура

Для интеграции лучше сделать отдельный сервис-обертку над `paperqa`.

Например:

```text
PaperQA2Service
├── add_files()
├── add_url()
├── delete_document()
├── clear_documents()
├── list_documents()
├── ask()
├── search()
└── get_status()
```

Это даст агенту понятный программный интерфейс и скроет детали внутренней реализации библиотеки.

---

## 5. Описание интерфейса

### 5.1. Инициализация

```python
class PaperQA2Service:
    def __init__(
        self,
        llm: str = "openai/gpt-4o-mini",
        temperature: float = 0.0,
        answer_max_sources: int = 5,
        paper_directory: str | None = None,
    ):
        ...
```

Назначение:

- создает объект `Docs`;
- настраивает `Settings`;
- хранит карту документов: путь → `dockey`;
- предоставляет методы добавления, удаления и запросов.

Пример использования:

```python
service = PaperQA2Service(
    llm="openai/gpt-4o-mini",
    temperature=0.0,
    answer_max_sources=5,
)
```

---

### 5.2. Добавление файлов

Метод:

```python
async def add_files(self, paths: list[str]) -> list[DocumentRef]:
    ...
```

Что должен делать:

1. Проверить, что файл существует.
2. Проверить расширение.
3. Добавить файл через `Docs.aadd()`.
4. Сохранить информацию о документе.
5. Вернуть список добавленных документов.

Рекомендуемые поддерживаемые типы:

```text
.pdf
.txt
.md
.html
.docx
.xlsx
.pptx
.py
.ts
.yaml
.json
```

Пример использования:

```python
documents = await service.add_files([
    "papers/paper1.pdf",
    "papers/paper2.pdf",
    "notes/summary.md",
])
```

Ожидаемый результат:

```python
[
    DocumentRef(
        dockey="abcd1234...",
        path="papers/paper1.pdf",
        title="Some paper title",
        status="ready",
    ),
    DocumentRef(
        dockey="efgh5678...",
        path="papers/paper2.pdf",
        title=None,
        status="ready",
    ),
]
```

---

### 5.3. Добавление документа по URL

Метод:

```python
async def add_url(self, url: str) -> DocumentRef:
    ...
```

Что должен делать:

1. Передать URL в `Docs.aadd_url()`, если метод доступен.
2. Дождаться обработки.
3. Вернуть `DocumentRef`.

Пример:

```python
document = await service.add_url("https://arxiv.org/pdf/2409.13740")
```

Если текущая версия `paper-qa` не поддерживает `aadd_url()`, агент должен реализовать альтернативу:

1. скачать файл во временную директорию;
2. добавить его через `add_files()`.

---

### 5.4. Удаление документа

Метод:

```python
async def delete_document(
    self,
    dockey: str | None = None,
    path: str | None = None,
) -> bool:
    ...
```

Поведение:

- удаляет документ из `Docs` по `dockey`;
- если передан только `path`, сначала находит соответствующий `dockey`;
- возвращает `True`, если документ удален;
- возвращает `False`, если документ не найден.

Примеры:

```python
deleted = await service.delete_document(path="papers/paper1.pdf")
```

или:

```python
deleted = await service.delete_document(dockey="abcd1234...")
```

Внутри можно использовать:

```python
docs.delete(dockey)
```

Если в новой версии метод стал асинхронным:

```python
await docs.delete(dockey)
```

Агент должен проверить фактическую сигнатуру в установленной версии.

---

### 5.5. Полная очистка документов

Метод:

```python
async def clear_documents(self) -> None:
    ...
```

Что должен делать:

- очищать все документы;
- очищать текстовые чанки;
- очищать векторный индекс, если он хранится в объекте `Docs`;
- сбрасывать внутренний реестр документов.

Внутри:

```python
docs.clear_docs()
```

Пример:

```python
await service.clear_documents()
```

---

### 5.6. Список документов

Метод:

```python
def list_documents(self) -> list[DocumentRef]:
    ...
```

Возвращает список добавленных документов.

Пример ответа:

```python
[
    {
        "dockey": "abcd1234",
        "path": "papers/paper1.pdf",
        "title": "Example scientific paper",
        "citation": "Author et al., Journal, 2024",
        "status": "ready",
    }
]
```

Рекомендуемая структура:

```python
@dataclass
class DocumentRef:
    dockey: str
    path: str | None = None
    url: str | None = None
    title: str | None = None
    citation: str | None = None
    status: str = "ready"
    error: str | None = None
```

---

### 5.7. Вопрос по документам

Метод:

```python
async def ask(
    self,
    question: str,
    max_sources: int | None = None,
    temperature: float | None = None,
) -> AnswerResult:
    ...
```

Что должен делать:

1. Взять объект `Docs`.
2. Применить `Settings`.
3. Выполнить запрос через:

```python
session = await docs.aquery(question, settings=settings)
```

4. Вернуть структурированный ответ.

Пример:

```python
result = await service.ask("What is PaperQA2?")
```

Ожидаемый формат ответа:

```python
@dataclass
class AnswerResult:
    question: str
    answer: str
    formatted_answer: str
    citations: list[str]
    context: list[dict]
```

Пример:

```python
{
    "question": "What is PaperQA2?",
    "answer": "PaperQA2 is a RAG system for scientific documents...",
    "formatted_answer": "PaperQA2 is ... [1]",
    "citations": [
        "PaperQA2: Language agents achieve superhuman..."
    ],
    "context": [
        {
            "source": "paper1.pdf",
            "text": "...",
            "score": 0.91,
        }
    ]
}
```

---

### 5.8. Поиск по документам

Если нужен не полный ответ, а только релевантные фрагменты:

```python
async def search(
    self,
    query: str,
    limit: int = 10,
) -> list[SearchResult]:
    ...
```

Назначение:

- найти релевантные документы или чанки;
- вернуть фрагменты текста и метаданные;
- не генерировать финальный ответ.

Пример:

```python
results = await service.search("thermoelectric materials", limit=5)
```

Формат:

```python
@dataclass
class SearchResult:
    dockey: str
    path: str | None
    text: str
    score: float | None
    citation: str | None
```

Если прямой поиск низкого уровня нестабилен, агент может реализовать `search()` как упрощенный `ask()` с просьбой вернуть только источники.

---

## 6. Пример минимального Python-кода

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from paperqa import Docs, Settings


@dataclass
class DocumentRef:
    dockey: str
    path: str | None = None
    url: str | None = None
    title: str | None = None
    citation: str | None = None
    status: str = "ready"
    error: str | None = None


@dataclass
class AnswerResult:
    question: str
    answer: str
    formatted_answer: str
    citations: list[str] = field(default_factory=list)
    context: list[dict] = field(default_factory=list)


class PaperQA2Service:
    def __init__(
        self,
        llm: str = "openai/gpt-4o-mini",
        temperature: float = 0.0,
        answer_max_sources: int = 5,
    ):
        self.docs = Docs()
        self._documents: dict[str, DocumentRef] = {}

        self.settings = Settings()
        self.settings.llm = llm
        self.settings.temperature = temperature

        # Если поле доступно в установленной версии
        try:
            self.settings.answer.answer_max_sources = answer_max_sources
        except Exception:
            pass

    def _file_dockey(self, path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()

    async def add_files(self, paths: Iterable[str | Path]) -> list[DocumentRef]:
        results: list[DocumentRef] = []

        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()

            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            dockey = self._file_dockey(path)

            await self.docs.aadd(str(path))

            document = DocumentRef(
                dockey=dockey,
                path=str(path),
                status="ready",
            )

            self._documents[dockey] = document
            results.append(document)

        return results

    async def add_url(self, url: str) -> DocumentRef:
        # Если метод существует в текущей версии
        await self.docs.aadd_url(url)

        dockey = hashlib.md5(url.encode()).hexdigest()

        document = DocumentRef(
            dockey=dockey,
            url=url,
            status="ready",
        )

        self._documents[dockey] = document
        return document

    async def delete_document(
        self,
        dockey: str | None = None,
        path: str | None = None,
    ) -> bool:
        target_dockey = dockey

        if target_dockey is None and path is not None:
            resolved_path = str(Path(path).expanduser().resolve())

            for existing_dockey, document in self._documents.items():
                if document.path == resolved_path:
                    target_dockey = existing_dockey
                    break

        if target_dockey is None:
            return False

        # В некоторых версиях метод может быть синхронным,
        # в некоторых — асинхронным.
        delete_method = getattr(self.docs, "delete", None)

        if delete_method is None:
            raise RuntimeError("Docs.delete() is not available in this paper-qa version")

        result = delete_method(target_dockey)

        # Если метод оказался корутиной
        if hasattr(result, "__await__"):
            await result

        self._documents.pop(target_dockey, None)

        return True

    async def clear_documents(self) -> None:
        self.docs.clear_docs()
        self._documents.clear()

    def list_documents(self) -> list[DocumentRef]:
        return list(self._documents.values())

    async def ask(
        self,
        question: str,
        max_sources: int | None = None,
        temperature: float | None = None,
    ) -> AnswerResult:
        if max_sources is not None:
            try:
                self.settings.answer.answer_max_sources = max_sources
            except Exception:
                pass

        if temperature is not None:
            self.settings.temperature = temperature

        session = await self.docs.aquery(question, settings=self.settings)

        citations = []

        if hasattr(session, "references") and session.references:
            citations = list(session.references)
        elif hasattr(session, "citations") and session.citations:
            citations = list(session.citations)

        context = []

        if hasattr(session, "context") and session.context:
            for item in session.context:
                if hasattr(item, "model_dump"):
                    context.append(item.model_dump())
                elif isinstance(item, dict):
                    context.append(item)
                else:
                    context.append({"raw": str(item)})

        return AnswerResult(
            question=question,
            answer=getattr(session, "answer", ""),
            formatted_answer=getattr(session, "formatted_answer", ""),
            citations=citations,
            context=context,
        )
```

Пример использования:

```python
import asyncio


async def main():
    service = PaperQA2Service(
        llm="openai/gpt-4o-mini",
        temperature=0.0,
        answer_max_sources=5,
    )

    await service.add_files([
        "papers/paper1.pdf",
        "papers/paper2.pdf",
    ])

    result = await service.ask("What is PaperQA2?")

    print(result.formatted_answer)

    await service.delete_document(path="papers/paper1.pdf")

    print(service.list_documents())


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 7. Компактный промпт для агента-разработчика

```text
You are implementing a Python integration with PaperQA2.

Use the official `paper-qa` Python package.
Import it as `paperqa`, not `paperqa2`.

Target Python version: 3.11+.

Implement a service class called PaperQA2Service.

The service must expose:

1. add_files(paths: list[str]) -> list[DocumentRef]
   - Adds local documents to PaperQA Docs.
   - Supports PDF, TXT, MD, HTML, DOCX, XLSX, PPTX, and code files if available.
   - Validates file existence.
   - Stores document metadata internally.
   - Returns added documents.

2. add_url(url: str) -> DocumentRef
   - Adds a remote document if supported by paperqa.
   - If not supported, downloads the file locally and uses add_files().

3. delete_document(dockey: str | None = None, path: str | None = None) -> bool
   - Deletes one document.
   - If only path is provided, resolves dockey first.
   - Uses Docs.delete() if available.
   - Returns True if deleted, False otherwise.

4. clear_documents() -> None
   - Clears all documents, chunks, and indexes.
   - Uses Docs.clear_docs() if available.

5. list_documents() -> list[DocumentRef]
   - Returns metadata about all currently added documents.

6. ask(question: str, max_sources: int | None = None, temperature: float | None = None) -> AnswerResult
   - Queries the document collection.
   - Uses Docs.aquery() with Settings.
   - Returns structured answer with citations and context.

7. search(query: str, limit: int = 10) -> list[SearchResult]
   - Optional.
   - Returns relevant chunks or sources.
   - If direct retrieval API is unstable, implement via ask() with a special prompt.

Implementation rules:

- Use async methods where paperqa exposes async APIs.
- Do not hardcode provider-specific logic unless necessary.
- Use LiteLLM-compatible model names if possible.
- Store an internal mapping of path -> dockey.
- Handle missing files, unsupported formats, API errors, and empty answers.
- Pin the package version in requirements.
- Add tests using temporary directories and small text files instead of large PDFs.
- Do not assume exact field names in Settings; check them at runtime.
- Prefer stable public APIs: Docs, Settings, Docs.aadd, Docs.aquery, Docs.delete, Docs.clear_docs.
- If a method is unavailable in the installed version, fail with a clear error or implement a fallback.

Expected data structures:

DocumentRef:
- dockey: str
- path: str | None
- url: str | None
- title: str | None
- citation: str | None
- status: str
- error: str | None

AnswerResult:
- question: str
- answer: str
- formatted_answer: str
- citations: list[str]
- context: list[dict]

SearchResult:
- dockey: str
- path: str | None
- text: str
- score: float | None
- citation: str | None
```

---

## 8. Рекомендуемые режимы работы

### Режим 1: Ручной контроль документов

Использовать, если нужны:

- добавление конкретных файлов;
- удаление конкретных документов;
- воспроизводимость;
- тесты;
- сервисный API.

Интерфейс:

```python
docs = Docs()
await docs.aadd("file.pdf")
session = await docs.aquery("Question", settings=settings)
```

Это рекомендуемый режим для разработки.

### Режим 2: Агентный поиск

Использовать, если система сама должна искать статьи и решать, какие документы добавить.

Интерфейс:

```python
from paperqa import ask, Settings

answer = ask(
    "What is PaperQA2?",
    settings=Settings(paper_directory="papers"),
)
```

или асинхронно:

```python
from paperqa import agent_query, Settings

answer = await agent_query(
    query="What is PaperQA2?",
    settings=Settings(paper_directory="papers"),
)
```

Этот режим хорош для исследовательских агентов, но менее детерминирован.

---

## 9. Проверка окружения перед разработкой

Перед началом интеграции агент должен выполнить:

```bash
python --version
pip show paper-qa
```

Затем проверить доступные объекты:

```python
import paperqa

print(paperqa.__version__)
print(dir(paperqa))
```

И отдельно проверить класс `Docs`:

```python
from paperqa import Docs

print(dir(Docs))
```

Нужно убедиться, что доступны методы:

```text
aadd
aadd_url
aquery
delete
clear_docs
```

Если каких-то методов нет, агент должен адаптировать код под установленную версию.

---

## 10. Требования к тестам

Агент должен добавить минимум следующие тесты.

### 10.1. Добавление текстового документа

```python
def test_add_file(tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("PaperQA2 is a testing system.")
```

Ожидание:

```python
document.status == "ready"
document.path == str(file_path)
```

### 10.2. Запрос по документу

Ожидание:

```python
result.answer != ""
result.formatted_answer != ""
```

### 10.3. Удаление документа

Ожидание:

```python
deleted is True
len(service.list_documents()) == 0
```

### 10.4. Ошибка при отсутствии файла

Ожидание:

```python
FileNotFoundError
```

### 10.5. Очистка

Ожидание:

```python
len(service.list_documents()) == 0
```

---

## 11. Формат ответа для конечного API

Если агент будет оборачивать сервис в HTTP API, рекомендуется такой JSON-формат.

### 11.1. Добавление документов

Запрос:

```json
{
  "paths": [
    "papers/paper1.pdf",
    "papers/paper2.pdf"
  ]
}
```

Ответ:

```json
{
  "documents": [
    {
      "dockey": "abcd1234",
      "path": "papers/paper1.pdf",
      "status": "ready"
    }
  ]
}
```

### 11.2. Удаление документа

Запрос:

```json
{
  "path": "papers/paper1.pdf"
}
```

Ответ:

```json
{
  "deleted": true
}
```

### 11.3. Вопрос по документам

Запрос:

```json
{
  "question": "What is PaperQA2?",
  "max_sources": 5,
  "temperature": 0.0
}
```

Ответ:

```json
{
  "question": "What is PaperQA2?",
  "answer": "PaperQA2 is a RAG system...",
  "formatted_answer": "PaperQA2 is ... [1]",
  "citations": [
    "PaperQA2: Language agents achieve superhuman..."
  ],
  "context": [
    {
      "source": "paper1.pdf",
      "text": "...",
      "score": 0.9
    }
  ]
}
```

---

## 12. Итоговая рекомендация

Для агента-разработчика лучше всего задать такой интерфейс:

```text
PaperQA2Service
- add_files(paths)
- add_url(url)
- delete_document(dockey=None, path=None)
- clear_documents()
- list_documents()
- ask(question)
- search(query)
```

Внутри использовать:

```python
from paperqa import Docs, Settings
```

Основные вызовы:

```python
docs = Docs()
await docs.aadd("file.pdf")
session = await docs.aquery("Question", settings=settings)
docs.delete(dockey)
docs.clear_docs()
```

