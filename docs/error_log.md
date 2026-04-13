# 에러 로그 및 해결 이력

**작성일:** 2026-04-13  
**프로젝트:** 증권 리포트 자동 보고서 생성 시스템

---

## E-01. ModuleNotFoundError: langchain.text_splitter

**발생 위치:** `src/researcher/collect_reports.py`

**에러 메시지:**
```
ModuleNotFoundError: No module named 'langchain.text_splitter'
```

**원인:** LangChain 0.3+ 이후 텍스트 분할기가 별도 패키지로 분리됨

**해결:**
```python
# 변경 전
from langchain.text_splitters import RecursiveCharacterTextSplitter

# 변경 후
from langchain_text_splitters import RecursiveCharacterTextSplitter
```
```bash
pip install langchain-text-splitters>=0.3.0
```

---

## E-02. ModuleNotFoundError: langchain_ollama

**발생 위치:** `src/models/llm.py` 실행 시

**에러 메시지:**
```
ModuleNotFoundError: No module named 'langchain_ollama'
```

**원인:** `python`(Anaconda)과 `python3`(macOS 시스템) 환경이 달라 패키지가 다른 환경에 설치됨

**해결:**
```bash
# Anaconda 환경에서 설치 (프로젝트 실행 환경)
pip install langchain-ollama pypdf
```

**참고:** `python` = Anaconda (이 프로젝트 실행용), `python3` = macOS 시스템 Python

---

## E-03. RAPTOR 처리 시간 736초

**발생 위치:** `build_raptor()` 실행 중

**증상:** Level 1 LLM 호출 1회에 736초 소요

**원인:** 모델 스왑으로 인한 콜드 스타트. `gemma4:26b` 메모리 상주 중 `qwen3.5:27b` 호출 시 기존 모델 언로드 + 신규 모델 디스크→메모리 로딩(약 700초) 포함

**해결:** 모든 모델을 `gemma4:26b` 단일 모델로 통일. 임베딩만 `gte-qwen2` 유지

**웜 기준 실측값:**
- LLM 호출 1회 (gemma4:26b): 13.1초
- 임베딩 20개: 7.7초

---

## E-04. llm.py SMALL_MODEL 오타

**발생 위치:** `src/models/llm.py`

**증상:** `gemma4:e2b` 모델 없음 오류 또는 잘못된 모델 실행

**원인:** 직접 수정 중 오타 발생

**해결:**
```python
# 변경 전
SMALL_MODEL = "gemma4:e2b"

# 변경 후
SMALL_MODEL = "gemma4:26b"
```

---

## E-05. ModuleNotFoundError: pdfplumber

**발생 위치:** `src/researcher/collect_reports.py` — `PyPDFLoader` → `pdfplumber` 교체 후

**에러 메시지:**
```
ModuleNotFoundError: No module named 'pdfplumber'
```

**해결:**
```bash
pip install pdfplumber
```

---

## E-06. SQL 에러 — fts.content 컬럼 없음

**발생 위치:** `chromadb_sql_guide.md` SQL 실행 시

**증상:** `embedding_fulltext_search_content` 테이블에서 `content` 컬럼 조회 실패

**원인:** ChromaDB FTS5 테이블의 실제 텍스트 컬럼명은 `c0` (FTS5 내부 규칙)

**확인 방법:**
```sql
SELECT name FROM pragma_table_info('embedding_fulltext_search_content');
-- 결과: c0
```

**해결:**
```sql
-- 변경 전
fts.content AS text

-- 변경 후
fts.c0 AS text
```

---

## E-07. build_toc 최대 시도 횟수 초과

**발생 위치:** `src/analyst/graph.py` + `src/analyst/review_toc.py`

**증상:** `--toc-retries 2` 옵션에도 불구하고 4차, 3차 시도까지 실행됨

**원인 1 — 체크포인트 재사용:**  
`MemorySaver`가 같은 날 동일 `thread_id`로 재실행 시 이전 실행의 `toc_iteration` 값을 복원. 이전 상태의 카운터가 이어져 횟수가 누적됨

**원인 2 — 횟수 체크 위치:**  
`review_toc` 내부에서 횟수 체크 시 LLM 호출 이후에 체크가 되는 구조적 문제. `review_toc`가 먼저 실행된 후 라우팅 판단이 이루어져 1회 초과 발생

**해결 1 — thread_id 유일화:**
```python
# 변경 전 (날짜만)
thread_id = f"analyst_{ticker}_{datetime.today().strftime('%Y%m%d')}"

# 변경 후 (초 단위 포함)
thread_id = f"analyst_{ticker}_{datetime.today().strftime('%Y%m%d_%H%M%S')}"
```

**해결 2 — 횟수 체크를 build_toc 직후 라우터로 이동:**
```python
# graph.py — build_toc 직후 라우터
def _route_after_build(state):
    if state.get("toc_iteration", 1) >= state.get("toc_max_retries", 2):
        return "human_toc"   # review 생략, 강제 승인
    return "review_toc"
```

**흐름 (toc_max_retries=2 기준):**
```
1차 시도 → toc_iteration=1 → 1>=2? No → review_toc → 재작성
2차 시도 → toc_iteration=2 → 2>=2? Yes → human_toc (강제 승인)
```

---

## E-08. build_toc 시도 횟수 초과 (human 거부 시 리셋)

**발생 위치:** `src/analyst/human_toc.py`

**증상:** `--toc-retries 2` 설정에도 불구하고 사람이 수정 요청 입력 시 카운터가 초기화되어 2회씩 추가 시도 발생 (예: 2+2+1 = 5차 시도)

**원인:** `human_toc.py` 수정 요청 반환 시 `toc_iteration=0` 하드코딩으로 카운터 초기화

**해결:**
```python
# 변경 전
return {
    "review_feedback": str(user_input),
    "review_approved": False,
    "toc_iteration":   0,   # 초기화 → 문제 원인
}

# 변경 후
return {
    "review_feedback": str(user_input),
    "review_approved": False,
    # toc_iteration 유지 → 최대 횟수 초과 시 review_toc 생략하고 바로 human_toc 복귀
}
```

**결과:** 최대 횟수 초과 후 human 거부 시 `_route_after_build`가 바로 `human_toc`으로 라우팅하여 추가 LLM 호출 없음

---

## E-09. `--no-hitl` 모드에서 자동 승인 미작동 (이중 인터럽트)

**발생 위치:** `src/analyst/graph.py` + `src/analyst/human_toc.py`

**증상:** `--no-hitl` 옵션 지정 시에도 `build_toc` 5차 시도까지 반복됨. 자동 승인("ok") 전송 후 `plan_sections`로 진행되지 않음

**원인:** `interrupt_before=["human_toc"]` (graph.py 컴파일 옵션) + `interrupt()` 내부 호출(human_toc.py) **이중 인터럽트** 발생

```
invoke(state)
  → interrupt_before fires → pause #1 (snapshot.next = ["human_toc"])
while: "ok" 전송
  → human_toc 실행 → interrupt() fires → pause #2
  → snapshot.next 변경 → while break
  → human_toc 미완료 → build_toc 재실행 (무한 루프)
```

**해결:** `interrupt_before` 제거, `interrupt()` 단독 사용
```python
# 변경 전
return builder.compile(checkpointer=cp, interrupt_before=["human_toc"])

# 변경 후
return builder.compile(checkpointer=cp)
```

**정상 흐름:**
```
invoke(state)
  → human_toc 실행 → interrupt() fires → pause
  → snapshot.next = ["human_toc"]
while: "ok" 전송
  → human_toc 재실행 → interrupt() returns "ok" → 승인
  → plan_sections → END
```

---

## E-10. `--no-hitl` 자동 승인 미작동 — interrupt() resume 값 미전달

**발생 위치:** `src/analyst/human_toc.py` + `main.py`

**증상:** E-09 수정(interrupt_before 제거) 이후에도 `--no-hitl --toc-retries 2` 옵션에서 4차 시도까지 반복됨

**원인:** `invoke({"__resume__": "ok"})` 방식이 LangGraph 버전에 따라 `interrupt()` 반환값에 전달되지 않음. `interrupt()`가 `None`을 반환하면 `str(None)` = `"none"`이 수정 요청으로 처리됨

```python
# human_toc.py — 수정 요청 분기
if str(user_input).strip().lower() in ("ok", ...):  # "none" → 해당 없음
    return {"toc": ..., "review_approved": True}

# 수정 요청으로 처리 → build_toc 재실행 → 4차 시도
return {"review_feedback": "None", "review_approved": False}
```

**해결: `interrupt()` 제거, `update_state()` + `invoke(None)` 방식으로 교체**

```python
# human_toc.py — interrupt() 완전 제거, 상태에서 읽기
def human_toc(state: AnalystState) -> dict:
    user_input = state.get("human_input", "").strip()
    if user_input.lower() in ("ok", "승인", "y", "yes", ""):
        return {"toc": toc_draft, "review_approved": True}
    return {"review_feedback": user_input, "review_approved": False}

# graph.py — interrupt_before 복구
builder.compile(checkpointer=cp, interrupt_before=["human_toc"])

# main.py — update_state로 입력 주입 후 invoke(None)으로 재개
analyst_graph.update_state(thread_config, {"human_input": user_input or "ok"})
result = analyst_graph.invoke(None, config=thread_config)
```

**상태 흐름:**
```
invoke(state) → interrupt_before["human_toc"] → pause
  snapshot.next = ["human_toc"]
update_state({"human_input": "ok"})
invoke(None) → human_toc 실행 → state["human_input"] = "ok" → 승인
  → plan_sections → END
```

**state.py 추가 필드:**
```python
human_input: str   # main.py가 update_state()로 주입하는 사용자 입력
```

---

## E-11. LLM 호출 무한 대기 — 타임아웃 미설정

**발생 위치:** `src/models/llm.py` → 전체 LLM 호출 노드

**증상:**
- `[write_sections]` 섹션 4 작성 중 30분 이상 응답 없음
- `[extract_thesis]` SK하이닉스 시작 후 무한 대기

**원인:** `ChatOllama` 생성 시 `timeout` 미설정. Ollama가 응답을 지연하거나 멈춰도 `llm.invoke()` 블로킹 호출이 무한 대기

**해결 1 — 타임아웃 추가 (`src/models/llm.py`)**
```python
# 변경 전
return ChatOllama(model=model, temperature=temperature, num_ctx=8192)

# 변경 후
return ChatOllama(model=model, temperature=temperature, num_ctx=8192, timeout=120)
```
`get_llm()`, `get_small_llm()` 모두 적용 (120초)

**해결 2 — 에러 발생 시 중단 (`src/writer/write_sections.py`)**

기존에는 타임아웃/오류 발생 시 `key_message`로 대체하고 계속 진행하는 fallback 로직이 있었으나 제거. 예외를 그대로 전파하여 파이프라인 중단.

```python
# 변경 전 — 오류 무시하고 대체 콘텐츠로 진행
except Exception as e:
    fallback = plan.get("key_message", ...)
    written_sections.append({... "content": fallback})

# 변경 후 — 예외 전파, 즉시 중단
content = llm.invoke(prompt).content.strip()  # try/except 없음
```

**추가 — 섹션별 소요 시간 출력**
```
섹션 1: 펀더멘털의 질적·양적 도약...
  완료 — 399자 / 15.3초
섹션 2: 글로벌 Peer 대비 저평가...
  완료 — 512자 / 28.7초
[write_sections] 완료: 4개 / 총 92.4초
```

**참고:** 현재 실행 중인 프로세스는 수정 전 코드 — `Ctrl+C` 후 재실행 필요

---

## 미해결 이슈

| 이슈 | 설명 | 상태 |
|------|------|------|
| summaries 컬렉션 `source=unknown` | L1 청크에 `source` 메타데이터가 propagate되지 않아 summaries 저장 시 source가 unknown으로 기록됨 | 미수정 |
