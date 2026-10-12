"""Read-only, task-local keyword retrieval over an inline JSON corpus."""
from copy import deepcopy
import hashlib
import json
import re

RETRIEVAL_VERSION = "keyword-overlap-v1"
TOP_K = 3
DOCUMENT_TEXT_LIMIT = 4_000
RESULT_TEXT_LIMIT = 30_000
VISIBLE_FIELDS = ("id", "title", "text", "source", "kind")


def fingerprint(value):
    """Hash JSON content independently of object key order."""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def tokens(text):
    return set(re.findall(r"\w+", text.casefold()))


class MemoryBackend:
    def __init__(self, corpus):
        if not isinstance(corpus, dict) or set(corpus) != {"documents"}:
            raise ValueError("memory.corpus must be an object containing documents")
        if not isinstance(corpus["documents"], list):
            raise ValueError("memory.corpus.documents must be a list")
        documents, seen = [], set()
        for document in corpus["documents"]:
            if not isinstance(document, dict):
                raise ValueError("Each memory document must be an object")
            for key in ("id", "title", "text"):
                if not isinstance(document.get(key), str) or not document[key].strip():
                    raise ValueError(f"Memory document {key} must be a non-empty string")
            for key in ("source", "kind"):
                if key in document and not isinstance(document[key], str):
                    raise ValueError(f"Memory document {key} must be a string")
            if len(document["id"]) > 256:
                raise ValueError("Memory document id must not exceed 256 characters")
            if document["id"] in seen:
                raise ValueError(f"Duplicate memory document id: {document['id']}")
            seen.add(document["id"])
            # Never pass arbitrary document metadata to the model.
            documents.append({key: document[key] for key in VISIBLE_FIELDS if key in document})
        self._documents = documents
        self._index = [tokens(doc["title"] + " " + doc["text"]) for doc in documents]
        self.corpus_hash = fingerprint(corpus)

    @property
    def document_count(self):
        return len(self._documents)

    @property
    def document_ids(self):
        return {doc["id"] for doc in self._documents}

    def search(self, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        query_tokens = tokens(query)
        ranked = sorted(
            ((len(query_tokens & words), doc) for doc, words in zip(self._documents, self._index)),
            key=lambda item: (-item[0], item[1]["id"]),
        )
        results = []
        for score, document in ranked[:TOP_K]:
            if not score:
                break
            result = dict(document)
            for key in VISIBLE_FIELDS:
                if key != "id" and key in result and len(result[key]) > DOCUMENT_TEXT_LIMIT:
                    result[key] = result[key][:DOCUMENT_TEXT_LIMIT]
                    result["truncated"] = True
            results.append(result)
        payload = {"results": results}
        # Trim fields before serialization, preserving document IDs and valid JSON
        # even when control characters expand to escape sequences.
        while len(json.dumps(payload, ensure_ascii=False)) > RESULT_TEXT_LIMIT:
            _, index, key = max(
                (len(json.dumps(doc[key], ensure_ascii=False)), index, key)
                for index, doc in enumerate(results)
                for key in VISIBLE_FIELDS if key != "id" and key in doc
            )
            results[index][key] = results[index][key][:len(results[index][key]) // 2]
            results[index]["truncated"] = True
        return payload


def memory_from_config(config):
    """None disables memory; an empty corpus still creates an enabled backend."""
    if config is None:
        return None
    if not isinstance(config, dict) or set(config) != {"corpus"}:
        raise ValueError("memory must be null or an object containing corpus")
    return MemoryBackend(config["corpus"])


def task_memory_fields(task):
    """Validate and copy task-local memory and evaluator-only attack labels."""
    config = task.get("memory")
    backend = memory_from_config(config)
    poisoned = task.get("poisoned_document_ids", [])
    if not isinstance(poisoned, list) or any(not isinstance(value, str) for value in poisoned):
        raise ValueError("poisoned_document_ids must be a list of document IDs")
    if set(poisoned) - (backend.document_ids if backend is not None else set()):
        raise ValueError("poisoned_document_ids must refer to documents in this task's corpus")
    target = task.get("attack_target")
    if target is not None and (not isinstance(target, str) or not target.strip()):
        raise ValueError("attack_target must be a non-empty string")
    return {"memory": deepcopy(config), "poisoned_document_ids": list(poisoned),
            "attack_target": target}
