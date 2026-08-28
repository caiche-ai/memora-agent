from __future__ import annotations

import asyncio
from pathlib import Path

from memora.evaluation import evaluate_intent_scenarios, load_markdown_scenarios
from memora.services.documents import chunk_pages
from memora.services.tokens import compact_history, estimate_tokens, fit_content_items
from memora.store import Store


def test_pro_markdown_intent_evaluation() -> None:
    scenarios = load_markdown_scenarios(Path(__file__).resolve().parents[2] / "pro.md")
    report = evaluate_intent_scenarios(scenarios)
    assert len(scenarios) == 34
    assert report["total"] >= 25
    assert report["accuracy"] == 1.0, report["failures"]


def test_markdown_heading_and_hybrid_document_retrieval() -> None:
    store = Store(":memory:")
    project = store.create_project("混合检索")
    document = store.add_document(
        project_id=project["id"],
        name="验收方案.md",
        mime_type="text/markdown",
        kind="knowledge",
        text="# 验收标准\n平台需要完成安全评审。\n# 部署要求\n平台部署在校内服务器。",
    )
    chunks = chunk_pages(
        [
            {
                "page_number": 1,
                "text": "# 验收标准\n平台需要完成安全评审。\n# 部署要求\n平台部署在校内服务器。",
            }
        ]
    )
    assert chunks[0]["heading"] == "验收标准"
    store.add_chunks(document["id"], chunks)
    store.set_chunk_embeddings(document["id"], [[1.0, 0.0], [0.0, 1.0]])

    lexical = store.search_project_chunks_hybrid(project["id"], "安全验收")
    assert lexical and lexical[0]["heading"] == "验收标准"
    assert lexical[0]["retrieval"]["lexical"] > 0 or lexical[0]["retrieval"]["fts"] > 0

    semantic = store.search_project_chunks_hybrid(
        project["id"], "没有任何词面匹配", query_embedding=[0.0, 1.0]
    )
    assert semantic and semantic[0]["heading"] == "部署要求"
    assert semantic[0]["retrieval"]["semantic"] == 1.0
    store.close()


def test_memory_supersession_expiration_and_semantic_recall() -> None:
    store = Store(":memory:")
    first = store.add_memory(
        {
            "type": "fact",
            "subject": "项目验收日期",
            "content": "项目计划在2026年9月30日验收",
            "source_type": "manual",
            "confidence": 1.0,
            "embedding": [1.0, 0.0],
        }
    )
    second = store.add_memory(
        {
            "type": "fact",
            "subject": "项目验收日期",
            "content": "项目延期到2026年10月15日验收",
            "source_type": "manual",
            "confidence": 1.0,
            "embedding": [0.9, 0.1],
        }
    )
    assert store.get_memory(first["id"])["status"] == "superseded"
    assert [item["id"] for item in store.list_memories()] == [second["id"]]

    expired = store.add_memory(
        {
            "type": "topic",
            "subject": "临时主题",
            "content": "已经结束的临时事项",
            "source_type": "manual",
            "valid_until": "2020-01-01",
        }
    )
    assert expired["id"] not in {item["id"] for item in store.list_memories()}
    assert store.get_memory(expired["id"])["status"] == "expired"

    recalled = store.search_memories("词面完全无关", query_embedding=[1.0, 0.0])
    assert recalled and recalled[0]["id"] == second["id"]
    assert recalled[0]["semantic_score"] > 0.9
    store.close()


def test_context_token_budget_and_history_compaction(monkeypatch) -> None:
    async def no_summary(*args, **kwargs):
        return None

    monkeypatch.setattr("memora.services.tokens.complete", no_summary)
    messages = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"第{index}轮" + "内容" * 180}
        for index in range(18)
    ]
    recent, summary = asyncio.run(compact_history(messages, 900))
    assert recent
    assert summary
    assert sum(estimate_tokens(item["content"]) for item in recent) + estimate_tokens(summary) <= 910

    fitted = fit_content_items(
        [{"content": "甲" * 1000}, {"content": "乙" * 1000}],
        500,
    )
    assert len(fitted) == 2
    assert sum(estimate_tokens(item["content"]) for item in fitted) <= 505
