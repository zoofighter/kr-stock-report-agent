"""
rag_store.py — ChromaDB 기반 RAG(검색 증강 생성) 저장소 인터페이스

역할:
  - 리서처 단계에서 생성된 청크(보고서·뉴스·이슈)를 ChromaDB에 벡터 임베딩으로 저장
  - 애널리스트·라이터 단계에서 LLM 프롬프트 컨텍스트를 위해 의미론적 유사도 검색 제공
  - 최종 스코어 = 코사인 유사도 × 날짜 가중치 × 출처 신뢰도

컬렉션 구조 (DB_PATH 하위 3개 컬렉션):
  reports  : PDF 리포트 청크 (RAPTOR L0=원문, L1=중간요약, L2=전체요약)
  news     : 4개 소스에서 수집한 뉴스 기사
  issues   : LLM이 추출한 투자 이슈 (growth / risk / catalyst / quality)

모든 청크는 ticker 필드로 종목별 격리되며, upsert 방식으로 중복 삽입을 방지한다.
"""

import math
from datetime import datetime
from typing import Optional

import chromadb
from chromadb.config import Settings

from src.models.llm import get_embeddings
from src.state import DB_PATH

# 프로세스 내 ChromaDB 클라이언트 싱글턴 — 파일 핸들을 재사용해 연결 오버헤드 방지
_client: Optional[chromadb.PersistentClient] = None


def get_client() -> chromadb.PersistentClient:
    """DB_PATH에 연결된 ChromaDB 영구 클라이언트를 반환한다 (최초 1회만 생성)."""
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
    청크 목록을 임베딩하여 컬렉션에 저장한다. 동일 id가 이미 존재하면 덮어쓴다.

    chunks 형식: [{"id": str, "text": str, "metadata": {"ticker": str, "published_date": str, ...}}]
    - published_date가 있으면 date_weight를 자동 계산해 metadata에 추가
    - ChromaDB 제약으로 list 타입 metadata 값은 str으로 변환
    반환: 실제로 upsert된 청크 수
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


def count_by_ticker(collection_name: str, ticker: str) -> int:
    """해당 종목이 컬렉션에 저장된 청크 수 반환 (0이면 미처리)"""
    try:
        collection = get_collection(collection_name)
        result = collection.get(where={"ticker": {"$eq": ticker}}, include=[])
        return len(result["ids"])
    except Exception:
        return 0


def search(
    collection_name: str,
    query: str,
    ticker: str,
    top_k: int = 5,
    level: Optional[int] = None,
) -> list[dict]:
    """
    쿼리와 의미적으로 유사한 청크를 검색해 스코어 내림차순으로 반환한다.

    스코어 공식: (1 - cosine_distance) × date_weight × source_reliability
      - cosine_distance 0 = 완전일치, 2 = 완전반대 → 1-dist로 유사도(0~1) 변환
      - date_weight: 최신 문서일수록 높음 (date_weight() 참고)
      - source_reliability: metadata에 저장된 출처 신뢰도 가중치 (기본 1.0)

    level 필터:
      None = 전체 레벨, 0 = 원문 청크, 1 = 중간 요약, 2 = 전체 요약(RAPTOR)

    반환: [{"id", "text", "metadata", "score"}, ...]  길이 ≤ top_k
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
