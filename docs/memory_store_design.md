# LangGraph Memory & Store 설계

**작성일:** 2026-04-13

---

## 1. LangGraph 메모리 개념 정리

LangGraph는 두 가지 지속성 메커니즘을 제공한다.

| 구분 | Checkpointer (단기 메모리) | Store (장기 메모리) |
|------|--------------------------|-------------------|
| 범위 | 단일 실행(thread) 내 | 여러 실행(thread) 간 공유 |
| 수명 | 그래프 실행 종료 시 만료 가능 | 영구 지속 |
| 저장 단위 | State 스냅샷 (체크포인트) | Key-Value 또는 문서 |
| 주요 용도 | Human-in-the-Loop, 재개, 에러 복구 | 학습, 캐시, 사용자 프로파일 |
| LangGraph API | `checkpointer=` 파라미터 | `store=` 파라미터 |

---

## 2. Checkpointer가 필요한 곳

### 2.1 Human-in-the-Loop — 필수

현재 설계에서 Human-in-the-Loop가 두 곳에 있다.  
**Checkpointer 없이는 interrupt() 후 재개가 불가능하다.**

```python
from langgraph.checkpoint.postgres import PostgresSaver  # 운영
from langgraph.checkpoint.memory import MemorySaver      # 개발/테스트

checkpointer = PostgresSaver.from_conn_string(DB_URL)

graph = supervisor_graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["human_toc_approval", "human_draft_approval"]
)

# 실행 → 목차 생성 후 자동 중단
thread = {"configurable": {"thread_id": "report_삼성전자_20260413"}}
graph.invoke({"topic": "삼성전자"}, config=thread)

# 사용자가 목차를 확인하고 수정 후 재개
graph.invoke(Command(resume={"toc": ["수정된 항목1", ...]}), config=thread)
```

**interrupt 지점:**

```
supervisor
    │
    ├── [collect_group]  ← interrupt 불필요
    ├── [toc_agent]      ← interrupt 불필요
    ├── [reviewer_agent] ← interrupt 불필요
    │
    ├── [human_toc_approval]   ◀── interrupt_before 설정
    │
    ├── [writer_agent]   ← interrupt 불필요
    ├── [editor_agent]   ← interrupt 불필요
    │
    └── [human_draft_approval] ◀── interrupt_before 설정
```

---

### 2.2 긴 파이프라인 중간 에러 복구

WriterAgent는 섹션 수만큼 반복 실행된다.  
섹터 5번째 섹션 작성 중 에러가 나도 **처음부터 재실행할 필요 없이 체크포인트에서 재개**할 수 있다.

```python
# 섹션별 체크포인트 저장 → 에러 발생 시 해당 섹션부터 재시작
graph = writer_agent_graph.compile(checkpointer=checkpointer)

# 에러 복구 시
last_state = graph.get_state(config=thread)
print(f"마지막 완료 섹션: {last_state.values['current_section_idx']}")
graph.invoke(None, config=thread)  # 이어서 실행
```

---

### 2.3 병렬 수집 중 부분 실패 복구

ReportCollect / News / QA 세 에이전트를 병렬로 실행할 때,  
하나가 실패해도 **성공한 에이전트의 결과는 보존**된다.

```
실행 중:
  ReportCollectAgent → 완료 ✓ (체크포인트 저장)
  NewsAgent          → 완료 ✓ (체크포인트 저장)
  QAAgent            → 실패 ✗

재실행 시:
  ReportCollect, News는 체크포인트에서 결과 불러옴
  QAAgent만 재실행
```

---

## 3. Store가 필요한 곳

### 3.1 QA 캐시 — 동일 종목 재분석 시 재활용

**가장 효과적인 Store 활용처.**  
같은 종목 보고서를 일주일 후 다시 생성할 때, 이전 QA를 재활용하면 LLM 호출 비용과 시간을 절약한다.

```python
from langgraph.store.memory import InMemoryStore    # 개발
from langgraph.store.postgres import PostgresStore  # 운영

store = PostgresStore.from_conn_string(DB_URL)

# QAAgent: 저장
async def save_qa_to_store(store, ticker: str, qa_pairs: list[dict]):
    namespace = ("qa_cache", ticker)
    for i, qa in enumerate(qa_pairs):
        await store.aput(
            namespace,
            key=f"qa_{i:03d}",
            value={
                "question": qa["question"],
                "answer": qa["answer"],
                "source": qa["source"],
                "created_at": today,
                "report_date": qa["report_date"],
            }
        )

# QAAgent: 조회 (재실행 시)
async def load_cached_qa(store, ticker: str, max_age_days: int = 7):
    namespace = ("qa_cache", ticker)
    items = await store.asearch(namespace)
    # 7일 이내 항목만 반환
    return [
        item.value for item in items
        if days_since(item.value["created_at"]) <= max_age_days
    ]
```

---

### 3.2 뉴스 캐시 — 동일 키워드 중복 검색 방지

NewsAgent가 같은 날 같은 키워드로 중복 실행되는 경우를 방지한다.

```python
# NewsAgent: 캐시 확인 후 검색 또는 캐시 반환
async def get_or_fetch_news(store, topic: str, keywords: list):
    namespace = ("news_cache", topic)
    cache_key = hash_keywords(keywords)  # 키워드 조합의 해시

    cached = await store.aget(namespace, cache_key)
    if cached and hours_since(cached.value["fetched_at"]) < 1:
        return cached.value["news_chunks"]  # 1시간 이내 캐시 사용

    # 캐시 없으면 실제 검색 실행
    news_chunks = await fetch_from_all_sources(topic, keywords)

    await store.aput(namespace, cache_key, {
        "news_chunks": news_chunks,
        "fetched_at": now()
    })
    return news_chunks
```

---

### 3.3 사용자 편집 히스토리 — TOCAgent 학습

Human-in-the-Loop에서 사용자가 목차를 어떻게 수정했는지 기록하면,  
다음 보고서 생성 시 TOCAgent가 그 패턴을 참고할 수 있다.

```python
# human_toc_approval 노드에서 저장
async def save_toc_edit_history(store, ticker: str, toc_draft, toc_final):
    namespace = ("toc_history", ticker)
    key = f"edit_{today}"

    await store.aput(namespace, key, {
        "draft": toc_draft,
        "final": toc_final,
        "diff": compute_diff(toc_draft, toc_final),
        "date": today,
        "sector": get_sector(ticker),
    })

# TOCAgent: 이전 편집 패턴 참고
async def load_toc_edit_patterns(store, ticker: str, sector: str):
    # 동일 종목 히스토리
    ticker_history = await store.asearch(("toc_history", ticker))
    # 동일 섹터 히스토리 (종목 히스토리 없을 때 폴백)
    sector_history = await store.asearch(("toc_history", f"sector_{sector}"))
    return ticker_history or sector_history
```

**TOCAgent 프롬프트에 주입:**
```
[과거 편집 패턴]
이 종목의 이전 보고서에서 사용자가 다음과 같이 수정했습니다:
- "실적 요약" → "1Q26 실적 서프라이즈" (제목을 더 구체적으로)
- "리스크 요인" 항목을 항상 마지막에서 두 번째로 이동

이 패턴을 반영하여 목차를 생성하세요.
```

---

### 3.4 보고서 아카이브 — 생성된 보고서 이력 관리

최종 생성된 보고서를 Store에 저장하여 이후 비교·참조에 활용한다.

```python
# finalize_report 노드에서 저장
async def archive_report(store, ticker: str, report: str, toc: list):
    namespace = ("report_archive", ticker)
    key = f"report_{today}"

    await store.aput(namespace, key, {
        "toc": toc,
        "report": report,
        "date": today,
        "word_count": len(report),
    })

# WriterAgent: 이전 보고서의 특정 섹션 참고 (선택적)
async def get_previous_section(store, ticker: str, section_title: str):
    namespace = ("report_archive", ticker)
    reports = await store.asearch(namespace, limit=3)  # 최근 3개
    # 유사한 섹션 제목 찾아 반환
    ...
```

---

### 3.5 AdvancedQA 캐시 — 인터넷 검색 결과 재활용

AdvancedQAAgent의 인터넷 검색 비용은 높다.  
같은 질문에 대한 검색 결과를 일정 기간 캐싱한다.

```python
namespace = ("advanced_qa_cache", ticker)
# TTL: 정책·규제형 24시간, 뉴스형 1시간, 거시지표형 6시간
TTL_BY_TYPE = {
    "정책규제형": 24,
    "최신뉴스형": 1,
    "거시환경형": 6,
    "경쟁사비교형": 12,
    "미래전망형": 48,
    "투자자반응형": 3,
}
```

---

## 4. 전체 적용 지점 요약

```
[Checkpointer 적용]

START
  │
  ├── collect_group ─────────── 체크포인트 저장 (병렬 실패 복구)
  │     ├── ReportCollectAgent ─ 체크포인트 저장
  │     ├── NewsAgent ──────── 체크포인트 저장
  │     └── QAAgent ─────────── 체크포인트 저장
  │
  ├── toc_agent ──────────────── 체크포인트 저장
  ├── reviewer_agent ─────────── 체크포인트 저장
  │
  ├── ✋ human_toc_approval ─── interrupt_before ← 반드시 체크포인트
  │
  ├── writer_agent (반복) ────── 섹션별 체크포인트 저장 (에러 복구)
  ├── editor_agent ───────────── 체크포인트 저장
  │
  └── ✋ human_draft_approval ── interrupt_before ← 반드시 체크포인트


[Store 적용]

에이전트           Store 네임스페이스           TTL / 영구
─────────────────────────────────────────────────────
NewsAgent        (news_cache, ticker)          1시간
QAAgent          (qa_cache, ticker)            7일
AdvancedQAAgent  (advanced_qa_cache, ticker)   질문 유형별 1~48시간
TOCAgent         (toc_history, ticker)         영구 (학습용)
human_toc        (toc_history, ticker)         영구 (학습용)
finalize         (report_archive, ticker)      영구 (아카이브)
```

---

## 5. 구현 스택 권장

| 환경 | Checkpointer | Store |
|------|-------------|-------|
| 개발·테스트 | `MemorySaver` | `InMemoryStore` |
| 운영 | `PostgresSaver` | `PostgresStore` |
| 대안 (운영) | `RedisSaver` | `RedisStore` (TTL 관리 용이) |

```python
# 운영 환경 초기화 예시
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

checkpointer = PostgresSaver.from_conn_string(PG_URL)
store = PostgresStore.from_conn_string(PG_URL)

graph = supervisor_graph.compile(
    checkpointer=checkpointer,
    store=store,
    interrupt_before=["human_toc_approval", "human_draft_approval"]
)
```

---

## 6. RAG DB vs Store 역할 구분

혼동하기 쉬운 두 저장소의 역할을 명확히 구분한다.

| 항목 | RAG DB (`/user/boon/report_db`) | LangGraph Store |
|------|--------------------------------|-----------------|
| 저장 형태 | 벡터 + 메타데이터 | Key-Value / 문서 |
| 검색 방식 | 유사도(벡터) 검색 | 네임스페이스 + 키 직접 조회 |
| 주요 용도 | 의미 기반 청크 검색 (글 쓸 때) | 캐시, 히스토리, 아카이브 |
| 저장 주체 | 모든 수집 에이전트 | 특정 노드에서 명시적 저장 |
| 갱신 빈도 | 리포트/뉴스 수집 시마다 | 이벤트 발생 시 (Human 승인 등) |
