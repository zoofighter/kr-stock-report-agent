import math
from datetime import datetime
from typing import Optional

import chromadb
from chromadb.config import Settings

from src.models.llm import get_embeddings
from src.state import DB_PATH

_client: Optional[chromadb.PersistentClient] = None


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=DB_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def get_collection(collection_name: str):
    """컬렉션 가져오기 (없으면 생성). cosine 거리 사용."""
    client = get_client()
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def date_weight(published_date: str, lambda_: float = 0.01) -> float:
    """w(d) = exp(-λ × 경과일수) — 최신일수록 1에 가까움"""
    try:
        pub_dt = datetime.strptime(published_date, "%Y-%m-%d")
        days = (datetime.today() - pub_dt).days
        return round(math.exp(-lambda_ * max(days, 0)), 4)
    except Exception:
        return 0.5


def upsert_chunks(collection_name: str, chunks: list[dict]) -> int:
    """
    chunks: [{"id", "text", "metadata": {...}}]
    date_weight를 metadata에 자동 계산하여 삽입 (중복 id는 덮어씀)
    """
    if not chunks:
        return 0

    collection = get_collection(collection_name)
    emb_model = get_embeddings()

    texts     = [c["text"] for c in chunks]
    ids       = [c["id"] for c in chunks]
    metadatas = []

    for c in chunks:
        meta = {k: v for k, v in c["metadata"].items()}
        if "published_date" in meta and "date_weight" not in meta:
            meta["date_weight"] = date_weight(meta["published_date"])
        # chromadb metadata 값은 str/int/float/bool만 허용
        for k, v in list(meta.items()):
            if isinstance(v, list):
                meta[k] = str(v)
        metadatas.append(meta)

    embeddings = emb_model.embed_documents(texts)

    collection.upsert(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(ids)


def search(
    collection_name: str,
    query: str,
    ticker: str,
    top_k: int = 5,
    level: Optional[int] = None,
) -> list[dict]:
    """
    RAG 검색 — 최종 스코어 = (1 - cosine_distance) × date_weight × source_reliability
    level: None=전체, 0=원문청크, 1=중간요약, 2=전체요약
    """
    collection = get_collection(collection_name)
    emb_model  = get_embeddings()

    # where 필터 구성
    if level is not None:
        where = {"$and": [
            {"ticker":       {"$eq": ticker}},
            {"raptor_level": {"$eq": level}},
        ]}
    else:
        where = {"ticker": {"$eq": ticker}}

    query_emb = emb_model.embed_query(query)

    results = collection.query(
        query_embeddings=[query_emb],
        n_results=min(top_k * 2, max(collection.count(), 1)),
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    scored = []
    ids       = results["ids"][0]
    docs      = results["documents"][0]
    metas     = results["metadatas"][0]
    distances = results["distances"][0]

    for doc_id, text, meta, dist in zip(ids, docs, metas, distances):
        dw = float(meta.get("date_weight", 0.5))
        sr = float(meta.get("source_reliability", 1.0))
        # cosine distance: 0(완전일치) ~ 2(완전반대), 1-dist로 유사도 변환
        similarity = max(1.0 - dist, 0.0)
        final_score = round(similarity * dw * sr, 4)
        scored.append({
            "id":       doc_id,
            "text":     text,
            "metadata": meta,
            "score":    final_score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
