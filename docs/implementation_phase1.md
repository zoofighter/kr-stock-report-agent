# 구현 설계도 — Phase 1: 리포트 수집 → RAG 저장 → QA 생성

**작성일:** 2026-04-13  
**범위:** Researcher 내부 `collect_reports` → `generate_qa` (advanced_qa 직전까지)  
**모델:** 로컬 Gemma (Ollama)  
**대상 종목:** 삼성전자 / 현대차 / SK하이닉스

---

## 1. 전체 흐름

```
/user/boon/report/
  ├── samsung/   ← 삼성전자 리포트 PDF
  ├── hyundai/   ← 현대차 리포트 PDF
  └── hynix/     ← SK하이닉스 리포트 PDF
          │
          ▼ collect_reports
  [파일 로드 → 청크 분할 → RAPTOR 계층 생성 → 날짜 가중치]
          │
          ▼ rag_store
  /user/boon/report_db/  (ChromaDB)
  ├── reports      (Level 0 청크)
  ├── summaries    (Level 1/2 요약)
  └── qa_pairs     (자기 질문 + 답변)
          │
          ▼ generate_qa
  [리포트 요약 생성 → 자기 질문 생성 → 답변 생성]
          │
          ▼
  ResearchPackage 반환
  (advanced_qa는 다음 단계)
```

---

## 2. 디렉터리 및 프로젝트 구조

```
a_0412_content_report/
├── src/
│   ├── researcher/
│   │   ├── __init__.py
│   │   ├── collect_reports.py   ← 리포트 로드 + 청크 + RAPTOR
│   │   ├── rag_store.py         ← ChromaDB 저장/조회
│   │   ├── generate_qa.py       ← 요약 + 자기 질문
│   │   └── graph.py             ← Researcher LangGraph 서브그래프
│   ├── models/
│   │   └── llm.py               ← Gemma (Ollama) 초기화
│   └── state.py                 ← ResearcherState, ResearchPackage
├── data/
│   └── reports/
│       ├── samsung/
│       ├── hyundai/
│       └── hynix/
├── report_db/                   ← ChromaDB 저장 위치
├── requirements.txt
└── main.py
```

---

## 3. 의존성

```txt
# requirements.txt

# LangGraph / LangChain
langgraph>=0.2.0
langchain>=0.2.0
langchain-community>=0.2.0
langchain-ollama>=0.1.0        # Gemma 로컬 모델

# 문서 처리
pypdf>=4.0.0                   # PDF 파싱
unstructured>=0.12.0           # 다양한 문서 포맷
python-docx>=1.0.0             # docx 지원

# 벡터 DB
chromadb>=0.5.0

# 임베딩 (로컬)
# Ollama의 nomic-embed-text 사용 (추가 설치 불필요)

# 유틸
python-dateutil>=2.9.0
tqdm>=4.66.0
pydantic>=2.0.0
```

**Ollama 설치 및 모델 준비:**
```bash
# Ollama 설치 (https://ollama.ai)
brew install ollama        # macOS

# 모델 다운로드
ollama pull gemma3:12b     # 추론용 (권장)
ollama pull gemma3:2b      # 요약/QA용 (경량, 비용 절감)
ollama pull nomic-embed-text  # 임베딩용
```

---

## 4. 모델 초기화 (`src/models/llm.py`)

```python
from langchain_ollama import ChatOllama, OllamaEmbeddings

def get_llm(model: str = "gemma3:12b", temperature: float = 0.1):
    """추론용 LLM — TOC 생성, QA 답변 등"""
    return ChatOllama(
        model=model,
        temperature=temperature,
        num_ctx=8192,          # 컨텍스트 윈도우
    )

def get_small_llm(model: str = "gemma3:2b"):
    """요약·쿼리 변환 등 단순 작업용 경량 모델"""
    return ChatOllama(
        model=model,
        temperature=0.0,
        num_ctx=4096,
    )

def get_embeddings(model: str = "nomic-embed-text"):
    """로컬 임베딩 모델"""
    return OllamaEmbeddings(model=model)
```

---

## 5. State 정의 (`src/state.py`)

```python
from typing import TypedDict, Optional

TICKERS = {
    "삼성전자": "005930",
    "현대차":   "005380",
    "SK하이닉스": "000660",
}

REPORT_DIRS = {
    "005930": "data/reports/samsung",
    "005380": "data/reports/hyundai",
    "000660": "data/reports/hynix",
}

class ResearcherState(TypedDict):
    # 입력
    topic: str            # 예: "삼성전자"
    company_name: str
    ticker: str           # 예: "005930"
    sector: str
    today: str
    report_date: str      # 가장 최근 리포트 발행일 (collect_reports에서 채움)

    # collect_reports 내부
    file_paths: list[str]
    raw_texts: list[dict]       # [{"text", "source", "date", "page"}]
    parse_errors: list[str]
    raptor_chunks: list[dict]   # Level 0/1/2 포함

    # generate_qa 내부
    grouped_by_report: dict
    qa_draft: list[dict]

    # 출력
    report_chunks: list[dict]
    summaries: list[str]
    qa_pairs: list[dict]

class ResearchPackage(TypedDict):
    report_chunks: list[dict]
    summaries: list[str]
    qa_pairs: list[dict]
    # news_chunks, advanced_qa_pairs는 다음 단계
```

---

## 6. RAG 저장소 초기화 (`src/researcher/rag_store.py`)

```python
import chromadb
from chromadb.config import Settings
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
import math
from datetime import datetime

DB_PATH = "report_db"

def get_chroma_client():
    return chromadb.PersistentClient(
        path=DB_PATH,
        settings=Settings(anonymized_telemetry=False)
    )

def get_collection(collection_name: str) -> Chroma:
    """컬렉션별 Chroma 인스턴스 반환"""
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=DB_PATH,
    )

def date_weight(published_date: str, lambda_: float = 0.01) -> float:
    """날짜 가중치: 최신일수록 높음 w(d) = exp(-λ × 경과일수)"""
    try:
        pub_dt = datetime.strptime(published_date, "%Y-%m-%d")
        days = (datetime.today() - pub_dt).days
        return round(math.exp(-lambda_ * days), 4)
    except Exception:
        return 0.5

def upsert_chunks(collection_name: str, chunks: list[dict]) -> int:
    """
    chunks: [{"id", "text", "metadata": {...}}]
    metadata에 date_weight 자동 계산 포함
    """
    store = get_collection(collection_name)
    texts, ids, metadatas = [], [], []

    for chunk in chunks:
        meta = chunk["metadata"].copy()
        # 날짜 가중치 자동 계산
        if "published_date" in meta and "date_weight" not in meta:
            meta["date_weight"] = date_weight(meta["published_date"])

        texts.append(chunk["text"])
        ids.append(chunk["id"])
        metadatas.append(meta)

    store.add_texts(texts=texts, ids=ids, metadatas=metadatas)
    return len(texts)

def search(
    collection_name: str,
    query: str,
    ticker: str,
    top_k: int = 5,
    level: Optional[int] = None,
) -> list[dict]:
    """
    RAG 검색 — 날짜 가중치 × 소스 신뢰도 적용
    level: None=전체, 0=청크, 1=중간요약, 2=전체요약
    """
    store = get_collection(collection_name)

    where = {"ticker": ticker}
    if level is not None:
        where["raptor_level"] = level

    results = store.similarity_search_with_score(
        query=query,
        k=top_k * 2,      # 가중치 재정렬을 위해 더 많이 가져옴
        filter=where,
    )

    # 최종 스코어 = 유사도 × 날짜 가중치 × 소스 신뢰도
    scored = []
    for doc, sim_score in results:
        meta = doc.metadata
        dw = meta.get("date_weight", 0.5)
        sr = meta.get("source_reliability", 1.0)
        final_score = (1 - sim_score) * dw * sr  # chroma는 거리 반환이므로 1-dist
        scored.append({
            "text": doc.page_content,
            "metadata": meta,
            "score": round(final_score, 4),
        })

    # 점수 내림차순 정렬 후 top_k 반환
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
```

---

## 7. 리포트 수집 및 RAPTOR 인덱싱 (`src/researcher/collect_reports.py`)

```python
import os
import re
import hashlib
from pathlib import Path
from datetime import datetime

from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_ollama import ChatOllama

from src.models.llm import get_small_llm
from src.researcher.rag_store import upsert_chunks
from src.state import ResearcherState, REPORT_DIRS

# ── 청크 설정 ────────────────────────────────────────────
CHUNK_SIZE    = 800    # Level 0 청크 크기 (자)
CHUNK_OVERLAP = 100
CLUSTER_SIZE  = 5      # Level 1 요약: 청크 5개씩 묶음


def extract_date_from_filename(filename: str) -> str:
    """파일명에서 날짜 추출. 예: samsung_report_20260410.pdf → 2026-04-10"""
    match = re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})', filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return datetime.today().strftime("%Y-%m-%d")


def load_reports(ticker: str) -> list[dict]:
    """PDF 파일 로드 및 메타데이터 추출"""
    report_dir = REPORT_DIRS[ticker]
    raw_docs = []

    for pdf_path in Path(report_dir).glob("**/*.pdf"):
        try:
            loader = PyPDFLoader(str(pdf_path))
            pages = loader.load()
            pub_date = extract_date_from_filename(pdf_path.name)

            for page in pages:
                raw_docs.append({
                    "text": page.page_content,
                    "source": pdf_path.name,
                    "published_date": pub_date,
                    "page": page.metadata.get("page", 0),
                    "ticker": ticker,
                })
        except Exception as e:
            print(f"[WARN] {pdf_path.name} 파싱 실패: {e}")

    return raw_docs


def make_chunks(raw_docs: list[dict], ticker: str) -> list[dict]:
    """Level 0: 원문 청크 생성"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " "],
    )
    chunks = []
    for doc in raw_docs:
        parts = splitter.split_text(doc["text"])
        for i, part in enumerate(parts):
            chunk_id = hashlib.md5(
                f"{doc['source']}_{i}_{part[:30]}".encode()
            ).hexdigest()[:16]

            chunks.append({
                "id": f"l0_{ticker}_{chunk_id}",
                "text": part,
                "metadata": {
                    "ticker": ticker,
                    "source": doc["source"],
                    "published_date": doc["published_date"],
                    "page": doc["page"],
                    "raptor_level": 0,
                    "source_reliability": 1.0,  # 증권사 리포트
                },
            })
    return chunks


def summarize_cluster(texts: list[str], llm: ChatOllama) -> str:
    """청크 묶음 → Level 1 중간 요약"""
    joined = "\n\n".join(texts)
    prompt = f"""다음 증권사 리포트 내용을 3~5문장으로 요약하세요.
핵심 수치(영업이익, 목표주가, 성장률 등)를 반드시 포함하세요.

[내용]
{joined}

요약:"""
    response = llm.invoke(prompt)
    return response.content.strip()


def summarize_all(summaries: list[str], llm: ChatOllama) -> str:
    """Level 1 요약들 → Level 2 전체 요약"""
    joined = "\n\n".join(summaries)
    prompt = f"""다음 리포트 요약들을 종합하여 전체 투자 논지를 2~3문장으로 작성하세요.

[요약 목록]
{joined}

전체 요약:"""
    response = llm.invoke(prompt)
    return response.content.strip()


def build_raptor(chunks: list[dict], ticker: str) -> tuple[list[dict], list[dict]]:
    """
    RAPTOR 계층 구성
    Returns: (level1_chunks, level2_chunks)
    """
    llm = get_small_llm()
    level1_chunks, level1_texts = [], []

    # Level 1: CHUNK_SIZE 청크 N개씩 묶어 중간 요약
    l0_texts = [c["text"] for c in chunks]
    for i in range(0, len(l0_texts), CLUSTER_SIZE):
        cluster = l0_texts[i : i + CLUSTER_SIZE]
        if not cluster:
            continue

        summary = summarize_cluster(cluster, llm)
        chunk_ids = [chunks[j]["id"] for j in range(i, min(i + CLUSTER_SIZE, len(chunks)))]

        level1_chunks.append({
            "id": f"l1_{ticker}_{i:04d}",
            "text": summary,
            "metadata": {
                "ticker": ticker,
                "raptor_level": 1,
                "child_ids": chunk_ids,
                "source_reliability": 1.0,
                # published_date는 하위 청크 중 최신 날짜 사용
                "published_date": max(
                    chunks[j]["metadata"]["published_date"]
                    for j in range(i, min(i + CLUSTER_SIZE, len(chunks)))
                ),
            },
        })
        level1_texts.append(summary)

    # Level 2: Level 1 요약들 → 전체 요약 1개
    if level1_texts:
        top_summary = summarize_all(level1_texts, llm)
        level2_chunk = [{
            "id": f"l2_{ticker}_top",
            "text": top_summary,
            "metadata": {
                "ticker": ticker,
                "raptor_level": 2,
                "child_ids": [c["id"] for c in level1_chunks],
                "source_reliability": 1.0,
                "published_date": datetime.today().strftime("%Y-%m-%d"),
            },
        }]
    else:
        level2_chunk = []

    return level1_chunks, level2_chunk


def collect_reports(state: ResearcherState) -> dict:
    """
    Researcher 서브그래프 노드 — collect_reports
    1. PDF 로드
    2. 청크 분할 (Level 0)
    3. RAPTOR 계층 생성 (Level 1, 2)
    4. ChromaDB 저장
    """
    ticker = state["ticker"]
    print(f"[collect_reports] {state['company_name']} ({ticker}) 시작")

    # 1. PDF 로드
    raw_docs = load_reports(ticker)
    if not raw_docs:
        return {"parse_errors": [f"{ticker}: 리포트 파일 없음"], "report_chunks": []}

    # 2. Level 0 청크
    l0_chunks = make_chunks(raw_docs, ticker)
    print(f"  Level 0 청크: {len(l0_chunks)}개")

    # 3. RAPTOR 계층 생성
    l1_chunks, l2_chunks = build_raptor(l0_chunks, ticker)
    print(f"  Level 1 요약: {len(l1_chunks)}개 / Level 2 요약: {len(l2_chunks)}개")

    all_chunks = l0_chunks + l1_chunks + l2_chunks

    # 4. ChromaDB 저장
    saved = upsert_chunks("reports", all_chunks)
    print(f"  RAG 저장 완료: {saved}개")

    # 가장 최근 리포트 발행일
    latest_date = max(
        c["metadata"]["published_date"]
        for c in l0_chunks
    )

    return {
        "report_chunks": all_chunks,
        "raptor_chunks": all_chunks,
        "report_date": latest_date,
        "raw_texts": raw_docs,
        "parse_errors": [],
    }
```

---

## 8. QA 생성 (`src/researcher/generate_qa.py`)

```python
import json
from langchain_ollama import ChatOllama
from src.models.llm import get_llm, get_small_llm
from src.researcher.rag_store import upsert_chunks, search
from src.state import ResearcherState

QUESTION_TYPES = ["사실확인형", "판단근거형", "리스크형"]


def generate_summary(report_chunks: list[dict], ticker: str, llm: ChatOllama) -> list[str]:
    """리포트 단위로 그룹화하여 요약 생성"""
    # Level 1 청크(중간 요약)만 사용 — 이미 요약되어 있으므로 효율적
    l1_chunks = [c for c in report_chunks if c["metadata"].get("raptor_level") == 1]

    if not l1_chunks:
        # Level 1 없으면 Level 0 사용
        l1_chunks = [c for c in report_chunks if c["metadata"].get("raptor_level") == 0][:10]

    summaries = []
    # 소스 파일별로 그룹화
    by_source = {}
    for c in l1_chunks:
        src = c["metadata"].get("source", "unknown")
        by_source.setdefault(src, []).append(c["text"])

    for source, texts in by_source.items():
        combined = "\n\n".join(texts[:5])  # 최대 5개 중간 요약
        prompt = f"""증권사 리포트 요약을 읽고 투자자용 최종 요약을 작성하세요.

[리포트: {source}]
{combined}

요약 형식:
- 핵심 투자 포인트: (1~2문장)
- 목표주가/투자의견: (수치 포함)
- 주요 리스크: (1문장)"""

        response = llm.invoke(prompt)
        summary_text = response.content.strip()
        summaries.append(summary_text)

        # summaries 컬렉션에 저장
        upsert_chunks("summaries", [{
            "id": f"sum_{ticker}_{source[:20]}",
            "text": summary_text,
            "metadata": {
                "ticker": ticker,
                "source": source,
                "published_date": l1_chunks[0]["metadata"].get("published_date", ""),
                "raptor_level": 1,
            }
        }])

    return summaries


def generate_questions(summaries: list[str], ticker: str, company_name: str, llm: ChatOllama) -> list[dict]:
    """요약 기반 핵심 질문 생성"""
    combined_summaries = "\n\n---\n\n".join(summaries)

    prompt = f"""당신은 투자 리서치 전문가입니다.
아래 {company_name}({ticker}) 리포트 요약을 읽고
투자 판단에 중요한 질문을 9개 생성하세요.

[요약]
{combined_summaries}

조건:
- 사실확인형 3개: 구체적 수치나 날짜를 확인하는 질문
- 판단근거형 3개: 왜 그런 판단을 내렸는지 이유를 묻는 질문
- 리스크형 3개: 하방 리스크와 주의사항을 묻는 질문
- 각 질문은 단독으로 의미가 통할 것
- 중복 없을 것

출력 형식 (JSON 배열):
[
  {{"type": "사실확인형", "question": "..."}},
  {{"type": "판단근거형", "question": "..."}},
  ...
]"""

    response = llm.invoke(prompt)
    try:
        # JSON 파싱
        text = response.content.strip()
        start = text.find("[")
        end = text.rfind("]") + 1
        questions = json.loads(text[start:end])
    except Exception:
        # 파싱 실패 시 기본 질문
        questions = [
            {"type": "사실확인형", "question": f"{company_name}의 최근 분기 영업이익은?"},
            {"type": "판단근거형", "question": f"{company_name} 매수 의견의 핵심 근거는?"},
            {"type": "리스크형",   "question": f"{company_name}의 주요 하방 리스크는?"},
        ]

    return questions


def answer_question(question: dict, ticker: str, report_chunks: list[dict], llm: ChatOllama) -> dict:
    """RAG 검색으로 질문에 답변"""
    # Level 0 청크에서 관련 내용 검색
    rag_results = search(
        collection_name="reports",
        query=question["question"],
        ticker=ticker,
        top_k=3,
        level=0,  # 수치 정확성을 위해 원문 청크 사용
    )

    context = "\n\n".join([r["text"] for r in rag_results])
    sources = [r["metadata"].get("source", "") for r in rag_results]

    prompt = f"""아래 컨텍스트를 바탕으로 질문에 답변하세요.
컨텍스트에 없는 내용은 추측하지 말고 "정보 없음"으로 답하세요.

[질문]
{question["question"]}

[컨텍스트]
{context}

답변 (2~3문장, 수치 포함):"""

    response = llm.invoke(prompt)
    answer = response.content.strip()

    return {
        **question,
        "answer": answer,
        "sources": list(set(sources)),
        "ticker": ticker,
    }


def generate_qa(state: ResearcherState) -> dict:
    """
    Researcher 서브그래프 노드 — generate_qa
    1. 리포트 요약 생성 → summaries 컬렉션 저장
    2. 핵심 질문 생성
    3. RAG 검색으로 답변 생성 → qa_pairs 컬렉션 저장
    """
    ticker = state["ticker"]
    company_name = state["company_name"]
    report_chunks = state["report_chunks"]

    print(f"[generate_qa] {company_name} ({ticker}) 시작")

    llm = get_llm("gemma3:12b")      # 답변 생성: 큰 모델
    small_llm = get_small_llm()       # 요약·질문: 작은 모델

    # 1. 요약 생성
    summaries = generate_summary(report_chunks, ticker, small_llm)
    print(f"  요약 생성: {len(summaries)}개")

    # 2. 질문 생성
    questions = generate_questions(summaries, ticker, company_name, small_llm)
    print(f"  질문 생성: {len(questions)}개")

    # 3. 답변 생성 및 저장
    qa_pairs = []
    for q in questions:
        qa = answer_question(q, ticker, report_chunks, llm)
        qa_pairs.append(qa)

        # qa_pairs 컬렉션에 저장
        upsert_chunks("qa_pairs", [{
            "id": f"qa_{ticker}_{hash(q['question']) & 0xFFFF:04x}",
            "text": f"Q: {qa['question']}\nA: {qa['answer']}",
            "metadata": {
                "ticker": ticker,
                "question_type": qa["type"],
                "question": qa["question"],
                "answer": qa["answer"],
                "sources": str(qa["sources"]),
                "published_date": state.get("report_date", ""),
            }
        }])

    print(f"  QA 저장: {len(qa_pairs)}개")

    return {
        "summaries": summaries,
        "qa_pairs": qa_pairs,
        "qa_draft": qa_pairs,
    }
```

---

## 9. Researcher LangGraph 서브그래프 (`src/researcher/graph.py`)

```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langgraph.checkpoint.memory import MemorySaver  # 개발용

from src.state import ResearcherState
from src.researcher.collect_reports import collect_reports
from src.researcher.generate_qa import generate_qa

def build_researcher_graph(checkpointer=None):
    """
    Researcher 서브그래프 빌드
    collect_reports → generate_qa
    (fetch_news, advanced_qa는 다음 단계)
    """
    builder = StateGraph(ResearcherState)

    # 노드 등록
    builder.add_node("collect_reports", collect_reports)
    builder.add_node("generate_qa", generate_qa)

    # 엣지 연결
    builder.add_edge(START, "collect_reports")
    builder.add_edge("collect_reports", "generate_qa")
    builder.add_edge("generate_qa", END)

    cp = checkpointer or MemorySaver()
    return builder.compile(checkpointer=cp)


researcher_graph = build_researcher_graph()
```

---

## 10. 실행 진입점 (`main.py`)

```python
from datetime import datetime
from src.state import ResearcherState, TICKERS
from src.researcher.graph import researcher_graph
from src.researcher.rag_store import search

TARGETS = [
    {"company_name": "삼성전자", "ticker": "005930", "sector": "반도체"},
    {"company_name": "현대차",   "ticker": "005380", "sector": "자동차"},
    {"company_name": "SK하이닉스","ticker": "000660", "sector": "반도체"},
]

def run_researcher(target: dict) -> dict:
    """단일 종목 Researcher 실행"""
    state = ResearcherState(
        topic=target["company_name"],
        company_name=target["company_name"],
        ticker=target["ticker"],
        sector=target["sector"],
        today=datetime.today().strftime("%Y-%m-%d"),
        report_date="",
        # 내부 필드 초기화
        file_paths=[], raw_texts=[], parse_errors=[], raptor_chunks=[],
        grouped_by_report={}, qa_draft=[],
        report_chunks=[], summaries=[], qa_pairs=[],
    )

    thread_config = {
        "configurable": {
            "thread_id": f"{target['ticker']}_{datetime.today().strftime('%Y%m%d')}"
        }
    }

    result = researcher_graph.invoke(state, config=thread_config)
    return result


def verify_rag(ticker: str, company_name: str):
    """RAG 저장 확인 — 검색 테스트"""
    print(f"\n{'='*50}")
    print(f"[RAG 검증] {company_name} ({ticker})")
    print(f"{'='*50}")

    # reports 컬렉션 검색
    results = search("reports", f"{company_name} 영업이익", ticker, top_k=2, level=1)
    print(f"\n[reports 검색] '{company_name} 영업이익'")
    for r in results:
        print(f"  score: {r['score']:.4f} | {r['text'][:100]}...")

    # qa_pairs 컬렉션 검색
    results = search("qa_pairs", f"{company_name} 투자 근거", ticker, top_k=2)
    print(f"\n[qa_pairs 검색] '{company_name} 투자 근거'")
    for r in results:
        print(f"  score: {r['score']:.4f} | {r['text'][:100]}...")


if __name__ == "__main__":
    # 3개 종목 순차 실행
    for target in TARGETS:
        print(f"\n{'#'*60}")
        print(f"# {target['company_name']} ({target['ticker']}) 처리 시작")
        print(f"{'#'*60}")

        result = run_researcher(target)

        print(f"\n✅ 완료: 청크 {len(result['report_chunks'])}개 "
              f"/ 요약 {len(result['summaries'])}개 "
              f"/ QA {len(result['qa_pairs'])}개")

        # RAG 저장 확인
        verify_rag(target["ticker"], target["company_name"])

    print("\n\n🎉 Phase 1 완료 — advanced_qa 단계로 진행 가능")
```

---

## 11. 실행 방법

```bash
# 1. Ollama 서비스 시작
ollama serve

# 2. 보고서 파일 배치
# data/reports/samsung/*.pdf
# data/reports/hyundai/*.pdf
# data/reports/hynix/*.pdf

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 실행
python main.py

# 5. ChromaDB 저장 확인
python -c "
import chromadb
client = chromadb.PersistentClient('report_db')
for col in client.list_collections():
    print(col.name, ':', col.count(), '건')
"
```

---

## 12. 예상 출력

```
######################################################
# 삼성전자 (005930) 처리 시작
######################################################
[collect_reports] 삼성전자 (005930) 시작
  Level 0 청크: 284개
  Level 1 요약: 57개 / Level 2 요약: 1개
  RAG 저장 완료: 342개
[generate_qa] 삼성전자 (005930) 시작
  요약 생성: 8개
  질문 생성: 9개
  QA 저장: 9개

✅ 완료: 청크 342개 / 요약 8개 / QA 9개

==================================================
[RAG 검증] 삼성전자 (005930)
==================================================
[reports 검색] '삼성전자 영업이익'
  score: 0.8124 | 삼성전자 1Q26 반도체 영업이익 6.2조 원으로 컨센서스 22% 상회...
  score: 0.7831 | HBM3E 공급 확대로 메모리 ASP 반등, 영업이익률 개선...

[qa_pairs 검색] '삼성전자 투자 근거'
  score: 0.7912 | Q: 삼성전자 매수 의견의 핵심 근거는?
A: HBM3E 공급 확대와 AI 반도체 수요 증가로...

🎉 Phase 1 완료 — advanced_qa 단계로 진행 가능
```

---

## 13. Phase 2 연결 포인트

이 Phase 1이 완료된 후 `advanced_qa` 노드에서 다음을 입력으로 받는다.

```python
# Phase 2 (advanced_qa) 시작 시 사용할 데이터
from src.researcher.rag_store import search

# 이미 저장된 summaries 불러오기
summaries = search("summaries", company_name, ticker, top_k=10)

# 이미 저장된 qa_pairs 불러오기
qa_pairs = search("qa_pairs", company_name, ticker, top_k=10)

# → AdvancedQA는 이 두 컬렉션에서 갭을 분석하여
#   리포트 밖 질문을 생성하고 인터넷으로 답변
```
