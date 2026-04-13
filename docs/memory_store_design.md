# LangGraph Memory & Store 설계

**작성일:** 2026-04-13  
**수정일:** 2026-04-13  
**버전:** 0.2 (Researcher / Analyst / Writer 3-에이전트 구조)

---

## 1. LangGraph 메모리 개념 정리

| 구분 | Checkpointer (단기 메모리) | Store (장기 메모리) |
|------|--------------------------|-------------------|
| 범위 | 단일 실행(thread) 내 | 여러 실행(thread) 간 공유 |
| 수명 | 그래프 실행 종료 시 만료 가능 | 영구 지속 |
| 저장 단위 | State 스냅샷 (체크포인트) | Key-Value 또는 문서 |
| 주요 용도 | Human-in-the-Loop, 재개, 에러 복구 | 학습, 캐시, 사용자 프로파일 |
| LangGraph API | `checkpointer=` 파라미터 | `store=` 파라미터 |

---

## 2. Checkpointer가 필요한 곳

### 2.1 Analyst — Human-in-the-Loop 목차 승인 (필수)

Analyst 서브그래프 내부의 `human_toc` 노드에서 interrupt된다.  
**Checkpointer 없이는 재개 불가능.**

```python
analyst_graph = analyst_flow.compile(
    checkpointer=checkpointer,
    interrupt_before=["human_toc"]
)

# Supervisor에서 Analyst 호출
thread = {"configurable": {"thread_id": f"report_{ticker}_{today}"}}
analyst_graph.invoke(analyst_input, config=thread)

# 사용자가 목차 수정 후 재개
analyst_graph.invoke(
    Command(resume={"toc": ["수정된 항목1", ...]}),
    config=thread
)
```

### 2.2 Writer — Human-in-the-Loop 초안 승인 (필수)

Writer 서브그래프 내부의 `human_draft` 노드에서 interrupt된다.

```python
writer_graph = writer_flow.compile(
    checkpointer=checkpointer,
    interrupt_before=["human_draft"]
)

# 사용자가 섹션 재작성 요청 후 재개
writer_graph.invoke(
    Command(resume={"human_edits": {2: "리스크 섹션을 더 구체적으로 수정"}}),
    config=thread
)
```

### 2.3 Writer — 섹션 반복 에러 복구

Writer는 섹션 수만큼 반복 실행된다.  
5번째 섹션 작성 중 에러가 나도 처음부터 재실행하지 않아도 된다.

```python
# 에러 복구
last_state = writer_graph.get_state(config=thread)
print(f"마지막 완료 섹션: {last_state.values['current_section_idx']}")
writer_graph.invoke(None, config=thread)   # 해당 섹션부터 이어서
```

### 2.4 Researcher — 병렬 수집 부분 실패 복구

리포트 수집과 뉴스 수집이 병렬 실행될 때, 하나가 실패해도 성공한 결과는 보존된다.

```
실행 중:
  collect_reports → 완료 ✓ (체크포인트)
  fetch_news      → 실패 ✗

재실행 시:
  collect_reports → 체크포인트에서 복원
  fetch_news      → 재실행
```

---

## 3. Store가 필요한 곳

### 3.1 Researcher — 뉴스 캐시

같은 날 동일 키워드로 재실행 시 중복 검색을 방지한다.

```python
# Researcher 내 fetch_news 노드
async def get_or_fetch_news(store, topic: str, keywords: list):
    namespace = ("news_cache", topic)
    cache_key = hash_keywords(keywords)

    cached = await store.aget(namespace, cache_key)
    if cached and hours_since(cached.value["fetched_at"]) < 1:
        return cached.value["news_chunks"]   # 1시간 이내 캐시

    news_chunks = await fetch_from_all_sources(topic, keywords)
    await store.aput(namespace, cache_key, {
        "news_chunks": news_chunks,
        "fetched_at": now()
    })
    return news_chunks
```

### 3.2 Researcher — QA 캐시

같은 종목 보고서를 일주일 후 다시 생성할 때, 기존 QA를 재활용한다.  
LLM 호출 비용을 절감하고 일관된 논지를 유지한다.

```python
# Researcher 내 generate_qa 노드 — 저장
async def save_qa(store, ticker: str, qa_pairs: list[dict]):
    namespace = ("qa_cache", ticker)
    for i, qa in enumerate(qa_pairs):
        await store.aput(namespace, f"qa_{i:03d}", {
            "question": qa["question"],
            "answer": qa["answer"],
            "source": qa["source"],
            "created_at": today,
        })

# 재실행 시 — 조회
async def load_cached_qa(store, ticker: str, max_age_days: int = 7):
    namespace = ("qa_cache", ticker)
    items = await store.asearch(namespace)
    return [
        item.value for item in items
        if days_since(item.value["created_at"]) <= max_age_days
    ]
```

### 3.3 Researcher — AdvancedQA 캐시

인터넷 검색 비용이 높으므로 질문 유형별 TTL을 다르게 적용한다.

```python
TTL_BY_TYPE = {
    "정책규제형":   24,   # 하루
    "최신뉴스형":    1,   # 1시간
    "거시환경형":    6,   # 6시간
    "경쟁사비교형": 12,   # 12시간
    "미래전망형":   48,   # 이틀
    "투자자반응형":  3,   # 3시간
}
namespace = ("advanced_qa_cache", ticker)
```

### 3.4 Analyst — TOC 편집 히스토리

Human-in-the-Loop에서 사용자가 목차를 어떻게 수정했는지 기록한다.  
다음 보고서 생성 시 Analyst가 이 패턴을 참고하여 처음부터 더 나은 목차를 생성한다.

```python
# Analyst 내 human_toc 노드 — 저장
async def save_toc_history(store, ticker: str, sector: str, draft, final):
    await store.aput(("toc_history", ticker), f"edit_{today}", {
        "draft": draft,
        "final": final,
        "diff": compute_diff(draft, final),
        "date": today,
        "sector": sector,
    })

# Analyst 내 build_toc 노드 — 조회 및 프롬프트 주입
async def load_toc_patterns(store, ticker: str, sector: str):
    history = await store.asearch(("toc_history", ticker))
    if not history:
        history = await store.asearch(("toc_history", f"sector_{sector}"))
    return history
```

**TOC 생성 프롬프트에 주입:**
```
[이전 편집 패턴]
사용자가 이전 보고서에서 목차를 다음과 같이 수정했습니다:
- "실적 요약" → "1Q26 실적 서프라이즈: 6조 돌파"  (제목을 더 구체적으로)
- "리스크 요인" 항목을 항상 마지막에서 두 번째로 배치

이 패턴을 반영하여 처음부터 좋은 목차를 생성하세요.
```

### 3.5 Writer — 보고서 아카이브

최종 보고서를 저장하여 이후 비교·참조에 활용한다.

```python
# Writer finalize 노드
async def archive_report(store, ticker: str, toc, report):
    await store.aput(("report_archive", ticker), f"report_{today}", {
        "toc": toc,
        "report": report,
        "date": today,
        "word_count": len(report),
    })
```

---

## 4. 전체 적용 지점 요약

```
[Checkpointer]

Supervisor Graph
  │
  ├── Researcher 서브그래프
  │     ├── collect_reports  ← 체크포인트 (병렬 실패 복구)
  │     └── fetch_news       ← 체크포인트 (병렬 실패 복구)
  │
  ├── Analyst 서브그래프
  │     ├── build_toc        ← 체크포인트
  │     ├── review_toc       ← 체크포인트
  │     └── ✋ human_toc     ← interrupt_before (필수)
  │
  └── Writer 서브그래프
        ├── write_section (반복) ← 섹션별 체크포인트 (에러 복구)
        ├── edit_draft           ← 체크포인트
        └── ✋ human_draft       ← interrupt_before (필수)


[Store]

에이전트         네임스페이스                   TTL
─────────────────────────────────────────────────────
Researcher      (news_cache, ticker)           1시간
Researcher      (qa_cache, ticker)             7일
Researcher      (advanced_qa_cache, ticker)    유형별 1~48시간
Analyst         (toc_history, ticker)          영구 (편집 패턴 학습)
Writer/Supervisor (report_archive, ticker)     영구 (보고서 아카이브)
```

---

## 5. 구현 스택

| 환경 | Checkpointer | Store |
|------|-------------|-------|
| 개발·테스트 | `MemorySaver` | `InMemoryStore` |
| 운영 | `PostgresSaver` | `PostgresStore` |
| TTL 관리 필요 시 | `RedisSaver` | `RedisStore` |

```python
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

checkpointer = PostgresSaver.from_conn_string(PG_URL)
store = PostgresStore.from_conn_string(PG_URL)

# 각 서브그래프에 개별 적용
analyst_graph = analyst_flow.compile(
    checkpointer=checkpointer,
    store=store,
    interrupt_before=["human_toc"]
)

writer_graph = writer_flow.compile(
    checkpointer=checkpointer,
    store=store,
    interrupt_before=["human_draft"]
)
```

---

## 6. RAG DB vs Store 역할 구분

| 항목 | RAG DB (`/user/boon/report_db`) | LangGraph Store |
|------|--------------------------------|-----------------|
| 저장 형태 | 벡터 + 메타데이터 | Key-Value / 문서 |
| 검색 방식 | 유사도(벡터) 검색 | 네임스페이스 + 키 직접 조회 |
| 주요 용도 | 의미 기반 청크 검색 (글 쓸 때) | 캐시, 히스토리, 아카이브 |
| 저장 주체 | Researcher 에이전트 | 각 에이전트 노드에서 명시적 저장 |
| 갱신 빈도 | 리포트/뉴스 수집 시마다 | 이벤트 발생 시 (Human 승인, 완료 등) |
