from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import config
from ..store import Store
from .embeddings import embed_query
from .search import search_web
from .tokens import compact_history, fit_content_items


class ContextBuildError(ValueError):
    pass


@dataclass
class AgentContext:
    history: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    web_results: list[dict[str, Any]]
    history_summary: str = ""

    def sources(self) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for item in self.documents:
            key = ("document", item["document_id"], item.get("page_number"))
            if key not in seen:
                seen.add(key)
                sources.append(
                    {
                        "type": "document",
                        "title": item["name"],
                        "page": item.get("page_number"),
                        "documentId": item["document_id"],
                    }
                )
        for item in self.web_results:
            key = ("web", item.get("url"))
            if item.get("url") and not item.get("error") and key not in seen:
                seen.add(key)
                sources.append({"type": "web", "title": item["title"], "url": item["url"]})
        return sources

    def provenance(self) -> dict[str, Any]:
        return {
            "sourceDocumentIds": list(dict.fromkeys(item["document_id"] for item in self.documents)),
            "memoryIds": [item["id"] for item in self.memories],
            "webSources": [
                item["url"] for item in self.web_results if item.get("url") and not item.get("error")
            ],
        }


def references_knowledge_file(content: str) -> bool:
    return bool(re.search(r"PDF|文档|文件|材料|刚才上传|刚上传|这份|该文件|第\s*\d+\s*页", content, re.I))


async def build_context(
    *,
    store: Store,
    conversation_id: int,
    project_id: int | None,
    query: str,
    document_ids: list[int],
    use_web_search: bool,
    force_document_fallback: bool = False,
) -> AgentContext:
    query_embedding = await embed_query(query)
    if document_ids and project_id is None:
        raise ContextBuildError("普通聊天不能引用项目文件")
    if project_id is not None and document_ids:
        documents = store.referenced_project_documents(project_id, document_ids)
        if len({item["document_id"] for item in documents}) != len(set(document_ids)):
            raise ContextBuildError("引用的文件不存在或不属于当前项目")
    elif project_id is not None:
        documents = store.search_project_chunks_hybrid(project_id, query, query_embedding)
        if not documents:
            documents = store.sample_project_document_chunks(project_id)
    else:
        documents = store.search_chunks_hybrid(conversation_id, query, query_embedding)
        if not documents and (force_document_fallback or references_knowledge_file(query)):
            page_match = re.search(r"第\s*(\d+)\s*页", query)
            page_number = int(page_match.group(1)) if page_match else None
            documents = store.sample_latest_document_chunks(conversation_id, page_number=page_number)
    memories = store.search_memories(
        query,
        project_id=project_id,
        query_embedding=query_embedding,
    )
    web_results = await search_web(query) if use_web_search else []
    history, history_summary = await compact_history(
        store.list_messages(conversation_id), config.history_token_budget
    )
    return AgentContext(
        history=history,
        documents=fit_content_items(documents, config.document_token_budget),
        memories=fit_content_items(memories, config.memory_token_budget),
        web_results=fit_content_items(web_results, config.web_token_budget),
        history_summary=history_summary,
    )


async def build_project_support_context(
    *, store: Store, project_id: int, query: str, use_web_search: bool
) -> dict[str, list[dict[str, Any]]]:
    query_embedding = await embed_query(query)
    return {
        "documents": fit_content_items(
            store.project_background_documents(project_id), config.document_token_budget
        ),
        "memories": fit_content_items(
            store.search_memories(query, project_id=project_id, query_embedding=query_embedding),
            config.memory_token_budget,
        ),
        "web_results": fit_content_items(
            await search_web(query) if use_web_search else [], config.web_token_budget
        ),
    }
