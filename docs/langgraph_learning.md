# LangGraph 학습 정리 — 이 프로젝트 코드 기반

## 개요

이 문서는 `a_0412_content_report` 프로젝트에서 실제 사용된 LangGraph 개념을
코드와 함께 설명한다.

---

## 1. State (상태)

**개념**: 그래프 전체에서 공유되는 데이터 컨테이너. 노드 간 데이터를 전달하는 유일한 통로.

```python
# src/state.py
class AnalystState(TypedDict):
    # 입력 (Researcher에서 받음)
    company_name: str
    report_chunks: list
    issues: list

    # 노드가 채워나가는 중간 결과
    thesis_list: list       # extract_thesis 노드가 채움
    toc_draft: list         # build_toc 노드가 채움
    review_approved: bool   # review_toc 노드가 채움
    human_input: str        # human_toc 노드가 소비

    # 최종 출력
    toc: list
    section_plans: list
```

**핵심 규칙**:
- 노드 함수는 `state` 를 받아 **변경된 키만** dict로 반환한다
- LangGraph가 반환값을 기존 state에 merge한다

```python
# 노드 함수 예시 — 전체 state를 반환하지 않아도 됨
def extract_thesis(state: AnalystState) -> dict:
    ...
    return {"thesis_list": result}   # 이 키만 state에 업데이트
```

---

## 2. Node (노드)

**개념**: 그래프의 실행 단위. 일반 Python 함수이며 state를 받아 state 업데이트를 반환한다.

```python
# src/analyst/assess_data.py
def assess_data(state: AnalystState) -> dict:
    report_chunks = state["report_chunks"]
    news_chunks   = state["news_chunks"]
    issues        = state["issues"]

    score = 0
    if len(report_chunks) >= 10: score += 40
    ...
    return {"data_assessment": {"score": score, "warnings": warnings}}
```

**그래프에 노드 등록**:

```python
# src/analyst/graph.py
builder = StateGraph(AnalystState)
builder.add_node("assess_data",    assess_data)
builder.add_node("extract_thesis", extract_thesis)
builder.add_node("build_toc",      build_toc)
```

---

## 3. Edge (엣지) — 노드 연결

### 3-1. 일반 엣지 (순차 실행)

```python
builder.add_edge(START,          "assess_data")
builder.add_edge("assess_data",  "extract_thesis")
builder.add_edge("extract_thesis","build_toc")
```

### 3-2. 병렬 엣지 (Fan-out / Fan-in)

```python
# src/researcher/graph.py
# collect_reports 완료 후 fetch_news와 extract_issues 병렬 실행
builder.add_edge(START,             "collect_reports")
builder.add_edge("collect_reports", "fetch_news")      # 병렬
builder.add_edge("collect_reports", "extract_issues")  # 병렬
builder.add_edge("fetch_news",      END)
builder.add_edge("extract_issues",  END)
```

### 3-3. 조건부 엣지 (Conditional Edge)

라우터 함수가 다음 노드 이름을 반환한다.

```python
# src/analyst/graph.py
def _route_after_build(state: AnalystState) -> str:
    if state["toc_iteration"] >= state["toc_max_retries"]:
        return "human_toc"   # 최대 재시도 초과 → 바로 승인
    return "review_toc"      # 아직 여유 있음 → LLM 검토

builder.add_conditional_edges("build_toc", _route_after_build)

def _route_review(state: AnalystState) -> str:
    return "human_toc" if state["review_approved"] else "build_toc"

builder.add_conditional_edges("review_toc", _route_review)
```

---

## 4. Memory / Checkpointer

**개념**: 그래프 실행 중간 상태를 저장해 재개(resume)를 가능하게 한다.
HITL interrupt가 바로 이 메커니즘을 이용한다.

```python
from langgraph.checkpoint.memory import MemorySaver

# MemorySaver = 프로세스 메모리에 저장 (재시작 시 소멸)
cp = MemorySaver()
graph = builder.compile(checkpointer=cp)
```

**thread_id**: 같은 그래프라도 독립적인 실행 흐름을 구분한다.

```python
# src/main.py
thread_config = {"configurable": {
    "thread_id": f"analyst_{ticker}_{datetime.today().strftime('%Y%m%d_%H%M%S')}"
}}

result = analyst_graph.invoke(state, config=thread_config)
```

**현재 한계**: `MemorySaver`는 in-memory라 프로세스 종료 시 체크포인트가 사라진다.
`SqliteSaver` 또는 `PostgresSaver`를 쓰면 디스크에 영구 저장 가능하다.

---

## 5. Human-in-the-Loop (HITL)

**개념**: 그래프 실행을 특정 노드 직전에 일시 중단하고, 사람의 입력을 받아 재개한다.

### 5-1. interrupt_before 설정

```python
# src/analyst/graph.py
graph = builder.compile(
    checkpointer=cp,
    interrupt_before=["human_toc"],   # 이 노드 실행 전 pause
)
```

### 5-2. 실행 흐름 (main.py)

```python
# 1차 실행 → human_toc 직전에서 일시 중단
result = analyst_graph.invoke(state, config=thread_config)

while True:
    snapshot = analyst_graph.get_state(thread_config)

    if not snapshot.next:
        break   # 완료

    # snapshot.next = ["human_toc"] 상태
    toc_draft = snapshot.values.get("toc_draft", [])

    # 사람이 목차 확인 후 입력
    user_input = input("명령 ('ok' 또는 수정 내용): ").strip()

    # 사람의 입력을 state에 주입
    analyst_graph.update_state(thread_config, {"human_input": user_input or "ok"})

    # 재개 — None을 넘기면 중단된 지점부터 이어서 실행
    result = analyst_graph.invoke(None, config=thread_config)
```

### 5-3. human_toc 노드 내부

```python
# src/analyst/human_toc.py
def human_toc(state: AnalystState) -> dict:
    human_input = state.get("human_input", "").strip().lower()

    if human_input in ("ok", "yes", "승인", ""):
        return {"toc": state["toc_draft"], "review_approved": True}
    else:
        # 수정 요청 → review_feedback에 담아 build_toc으로 돌아감
        return {"review_feedback": human_input, "review_approved": False}
```

### 5-4. --no-hitl 모드

```python
if human_in_the_loop:
    user_input = input("명령: ").strip()
else:
    user_input = "ok"   # 자동 승인
```

---

## 6. RAG (Retrieval-Augmented Generation)

**개념**: LLM 프롬프트에 관련 문서를 검색해 삽입, 환각 없이 사실 기반 답변 유도.

### 6-1. 저장 — upsert_chunks()

```python
# src/researcher/rag_store.py
def upsert_chunks(collection_name: str, chunks: list[dict]) -> int:
    collection  = get_collection(collection_name)
    embeddings  = emb_model.embed_documents(texts)   # 벡터 변환
    collection.upsert(ids, documents, embeddings, metadatas)
```

3개 컬렉션:
- `reports` : RAPTOR L0(원문) / L1(중간요약) / L2(전체요약)
- `news`    : 4개 소스 뉴스 기사
- `issues`  : LLM 추출 투자 이슈

### 6-2. 검색 — search()

```python
# 스코어 = 코사인유사도 × date_weight × source_reliability
def search(collection_name, query, ticker, top_k=5, level=None) -> list[dict]:
    query_emb = emb_model.embed_query(query)
    results   = collection.query(query_embeddings=[query_emb], ...)
    # 스코어 계산 후 상위 top_k 반환
```

### 6-3. 단계별 활용 패턴

```
extract_thesis  → search("reports", "투자 논지",   level=2)  # 전체 맥락
build_toc       → search("reports", "실적 전망",   level=1)  # 중간 논거
plan_sections   → search("reports", section_title, level=0)  # 구체 수치
write_sections  → search("reports", ..., level=0/1/2)        # 섹션 작성
                  search("news",    ...) ← tone=전망적일 때
                  search("issues",  ...) ← tone=경고적일 때
```

---

## 7. RAPTOR (계층적 청킹)

**개념**: RAG 품질 향상을 위해 원문을 3단계로 요약해 저장. 질문 유형에 따라 레벨 선택.

```
PDF 원문
  ↓ RecursiveCharacterTextSplitter (800자)
L0: 원문 청크 × N개          → 수치·사실 인용용
  ↓ LLM 요약 (5개씩 묶음)
L1: 중간 요약 × N/5개        → 논거 검색용
  ↓ LLM 전체 요약
L2: 전체 투자 논지 × 1개     → 전체 맥락 파악용
```

---

## 8. 서브그래프 패턴

**개념**: 복잡한 파이프라인을 독립적인 그래프로 분리해 각각 컴파일.
메인에서 순차적으로 invoke한다.

```python
# 각각 독립 그래프
researcher_graph = build_researcher_graph()   # PDF수집 + 뉴스 + 이슈
analyst_graph    = build_analyst_graph()      # thesis + TOC + plan
writer_graph     = build_writer_graph()       # 섹션작성 + 조립 + 저장

# main.py — 순차 실행, 이전 결과를 다음 state에 주입
research_result = researcher_graph.invoke(research_state, ...)
analyst_result  = analyst_graph.invoke(analyst_state, ...)    # research_result 사용
writer_result   = writer_graph.invoke(writer_state, ...)      # analyst_result 사용
```

---

## 9. 전체 흐름 한눈에 보기

```
main.py
│
├─ Researcher Graph (MemorySaver)
│    START
│      ├─→ collect_reports  (PDF → L0/L1/L2 → ChromaDB reports)
│      │       ↓
│      │   ├─→ fetch_news   (L2 키워드 → 뉴스수집 → ChromaDB news)
│      │   └─→ extract_issues (L1 소스별 → 이슈추출 → ChromaDB issues)
│      END
│
├─ Analyst Graph (MemorySaver + interrupt_before=["human_toc"])
│    START
│      → assess_data
│      → extract_thesis  ← search(reports, L2)
│      → build_toc       ← search(reports, L1)  ←──────────────┐
│      → [route] ──────────────────────────────────────┐        │
│                approved?                              │        │
│      → review_toc  ──── No ──→ build_toc ────────────┘        │
│           │ Yes                                                 │
│      ⚡ human_toc (INTERRUPT)                                   │
│           │ ok                         No (수정요청) ──────────┘
│      → plan_sections  ← search(reports, L0)
│    END
│
└─ Writer Graph (MemorySaver)
     START
       → write_sections   ← search(reports L0/L1/L2, news, issues)
       → assemble_report
       → save_report  →  /report_output/{ticker}/{date}_{company}_report.md
     END
```

---

## 10. 핵심 파일 위치

| 개념 | 파일 |
|------|------|
| State 정의 | `src/state.py` |
| Researcher 그래프 | `src/researcher/graph.py` |
| Analyst 그래프 + 라우터 | `src/analyst/graph.py` |
| Writer 그래프 | `src/writer/graph.py` |
| HITL 노드 | `src/analyst/human_toc.py` |
| RAG 저장/검색 | `src/researcher/rag_store.py` |
| RAPTOR 청킹 | `src/researcher/collect_reports.py` |
| 파이프라인 진입점 | `main.py` |
