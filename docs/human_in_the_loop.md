# Human-in-the-Loop 상세 설계

**작성일:** 2026-04-13

---

## 1. Human-in-the-Loop란

LangGraph에서 Human-in-the-Loop(HITL)는 **그래프 실행 중간에 사람이 개입하여 검토·수정·승인하는 메커니즘**이다.

AI가 자동으로 처리하다가 특정 지점에서 일시 정지(interrupt)하고,  
사람의 입력을 기다린 후 재개(resume)하는 구조다.

```
그래프 실행 중
    ↓
interrupt 지점 도달
    ↓
실행 일시 정지 → State 체크포인트 저장
    ↓
사용자에게 결과 제시 (목차 or 초안)
    ↓
사용자 입력 (승인 / 수정 / 재작성 요청)
    ↓
resume → 입력 반영 후 다음 노드 실행
```

**핵심:** Checkpointer가 없으면 interrupt 상태를 저장할 수 없어 재개 자체가 불가능하다.

---

## 2. 이 시스템의 HITL 지점

총 **2개 지점**에서 사람이 개입한다.

| 지점 | 에이전트 | 노드 | 제시되는 내용 | 가능한 액션 |
|------|---------|------|------------|-----------|
| **HITL ①** | Analyst | `human_toc` | 목차 초안 (4~8개 항목) | 승인 / 항목 수정 / 전면 재작성 요청 |
| **HITL ②** | Writer | `human_draft` | 전체 보고서 초안 | 승인 / 섹션 재작성 요청 / 전면 재작성 요청 |

---

## 3. HITL ① — 목차 승인 (Analyst 내부)

### 3.1 흐름

```
assess_data → extract_thesis → build_toc → review_toc
                                                │
                                           (승인 시)
                                                ↓
                                        ✋ human_toc   ← interrupt
                                                │
                              ┌─────────────────┼─────────────────┐
                              │                 │                 │
                           승인              수정             재작성 요청
                              │                 │                 │
                         plan_sections    (수정 반영)         build_toc
                              │           plan_sections       (논지 유지)
                              ↓
                        AnalysisPackage → Writer
```

### 3.2 사용자에게 제시되는 내용

```
═══════════════════════════════════════════════════
📋 목차 검토 요청 — 삼성전자 (005930)
분석 기준일: 2026-04-13
═══════════════════════════════════════════════════

[핵심 투자 논지]
✅ HBM3E 공급 확대로 AI 반도체 수혜 본격화
✅ 1Q26 어닝 서프라이즈 — 시장 기대치 20% 상회
⚠️ 미국 대중 수출 규제 강화 리스크
📈 2H26 메모리 가격 반등 시 상승 여력 35%

[목차 초안]
1. 1Q26 실적 서프라이즈: 반도체 부문 6조 돌파
   → 시장 기대치를 20% 상회하는 영업이익으로 실적 모멘텀 확인

2. HBM3E 공급 확대로 AI 반도체 수혜 본격화
   → 엔비디아 향 HBM 공급 비중 확대가 2H26 실적을 견인할 전망

3. 파운드리 경쟁 심화: TSMC와의 격차 분석
   → 2nm 공정 격차 축소 진행 중, 수율 개선이 관건

4. 미국 대중 수출 규제 리스크 점검
   → 중국 매출 비중 15% — 추가 규제 시 연간 영업이익 약 1조 영향

5. 목표 주가 상향 근거와 밸류에이션 분석
   → PBR 1.4배 수준, 역사적 저점 구간 — 상승 여력 35%

═══════════════════════════════════════════════════
[1] 승인  [2] 항목 수정  [3] 전면 재작성 요청
선택: _
```

### 3.3 가능한 액션별 처리

```python
# 승인
human_input = {"action": "approve"}
→ plan_sections 노드로 진행

# 항목 수정 (특정 항목 교체/추가/삭제)
human_input = {
    "action": "edit",
    "edits": [
        {"idx": 2, "new_title": "파운드리 2nm 수율 경쟁 — TSMC 격차 좁히기"},
        {"action": "add", "after": 4, "title": "외국인 수급 동향 및 기관 포지션 분석"},
    ]
}
→ 수정 항목만 반영 후 plan_sections 진행

# 전면 재작성 (방향 자체를 바꾸고 싶을 때)
human_input = {
    "action": "rewrite",
    "instruction": "리스크보다 HBM 성장 스토리에 더 집중해서 목차를 다시 짜줘"
}
→ build_toc로 돌아가서 instruction을 프롬프트에 추가하여 재생성
```

---

## 4. HITL ② — 초안 승인 (Writer 내부)

### 4.1 흐름

```
write_section(반복) → edit_draft
                          │
                     ✋ human_draft   ← interrupt
                          │
          ┌───────────────┼───────────────────┐
          │               │                   │
        승인          섹션 재작성          전면 재작성
          │               │                   │
      finalize     해당 섹션만           write_section
      (최종 출력)   write_section        (전체 처음부터)
                   → edit_draft 재실행
```

### 4.2 사용자에게 제시되는 내용

```
═══════════════════════════════════════════════════
📝 보고서 초안 검토 요청 — 삼성전자 (005930)
총 5개 섹션 / 약 3,200자
═══════════════════════════════════════════════════

[섹션 1] 1Q26 실적 서프라이즈: 반도체 부문 6조 돌파
삼성전자의 2026년 1분기 반도체 부문 영업이익은 6.2조 원으로,
시장 컨센서스(5.1조 원)를 약 22% 상회했다. 이는 HBM3E 공급
확대와 메모리 평균판매가격(ASP) 반등이 동시에 반영된 결과다...
[한국경제, 2026-04-10] [KB증권 리포트, 2026-04-08]

[섹션 2] HBM3E 공급 확대로 AI 반도체 수혜 본격화
...

[섹션 3] 파운드리 경쟁 심화: TSMC와의 격차 분석
...

[섹션 4] 미국 대중 수출 규제 리스크 점검
...

[섹션 5] 목표 주가와 밸류에이션
...

═══════════════════════════════════════════════════
[1] 승인 (최종 출력)
[2] 특정 섹션 재작성
[3] 전면 재작성
선택: _

# [2] 선택 시
재작성할 섹션 번호: 3
수정 지시사항: TSMC와의 기술 격차를 더 구체적인 수치로 설명해줘.
              CoWoS 패키징 비교도 포함해줘.
```

### 4.3 가능한 액션별 처리

```python
# 승인
human_input = {"action": "approve"}
→ finalize 노드 → 최종 보고서 출력

# 특정 섹션 재작성
human_input = {
    "action": "rewrite_section",
    "section_idx": 2,              # 0-based index
    "instruction": "TSMC 비교 수치 추가, CoWoS 패키징 언급"
}
→ WriterState에서 해당 섹션만 instruction 포함하여 재작성
→ edit_draft 재실행 (나머지 섹션은 기존 결과 유지)
→ human_draft 다시 interrupt

# 전면 재작성
human_input = {
    "action": "full_rewrite",
    "instruction": "전체적으로 더 간결하게, 분량을 절반으로 줄여줘"
}
→ global_context에 instruction 주입 후 write_section 처음부터 재실행
```

---

## 5. LangGraph 구현 패턴

### 5.1 interrupt 설정

```python
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph, END

checkpointer = PostgresSaver.from_conn_string(PG_URL)

# Analyst 서브그래프
analyst_graph = analyst_flow.compile(
    checkpointer=checkpointer,
    interrupt_before=["human_toc"]    # 이 노드 실행 직전에 멈춤
)

# Writer 서브그래프
writer_graph = writer_flow.compile(
    checkpointer=checkpointer,
    interrupt_before=["human_draft"]
)
```

### 5.2 interrupt → resume 사이클

```python
from langgraph.types import Command

thread_config = {"configurable": {"thread_id": f"{ticker}_{today}"}}

# ① 실행 시작 → human_toc에서 자동 정지
analyst_graph.invoke(analyst_input, config=thread_config)

# ② 현재 State 읽기 (사용자에게 보여줄 내용 추출)
current_state = analyst_graph.get_state(config=thread_config)
toc_draft = current_state.values["toc_draft"]
thesis_list = current_state.values["thesis_list"]
# → UI에 toc_draft, thesis_list 표시

# ③ 사용자 입력 수신 후 resume
analyst_graph.invoke(
    Command(resume=human_input),    # human_input: approve / edit / rewrite
    config=thread_config
)
# → plan_sections 실행 후 AnalysisPackage 반환
```

### 5.3 human_toc 노드 구현

```python
from langgraph.types import interrupt

def human_toc(state: AnalystState) -> dict:
    """
    interrupt()를 호출하면 실행이 여기서 멈추고
    resume 시 human_input 값이 반환된다.
    """
    human_input = interrupt({
        "type": "toc_review",
        "toc_draft": state["toc_draft"],
        "thesis_list": state["thesis_list"],
        "data_assessment": state["data_assessment"],
        "message": "목차를 검토하고 승인 또는 수정해주세요."
    })

    # resume 시 이 아래 코드가 실행됨
    action = human_input.get("action")

    if action == "approve":
        return {"toc": state["toc_draft"], "human_edits": []}

    elif action == "edit":
        updated_toc = apply_edits(state["toc_draft"], human_input["edits"])
        return {"toc": updated_toc, "human_edits": human_input["edits"]}

    elif action == "rewrite":
        # build_toc로 돌아가기 위해 플래그 설정
        return {
            "toc_draft": [],
            "rewrite_instruction": human_input.get("instruction", ""),
            "toc_approved": False
        }
```

### 5.4 human_draft 노드 구현

```python
def human_draft(state: WriterState) -> dict:
    human_input = interrupt({
        "type": "draft_review",
        "sections": state["sections"],
        "merged_draft": state["merged_draft"],
        "message": "보고서 초안을 검토하고 승인 또는 수정해주세요."
    })

    action = human_input.get("action")

    if action == "approve":
        return {"draft_approved": True, "human_edits": {}}

    elif action == "rewrite_section":
        return {
            "draft_approved": False,
            "human_edits": {
                human_input["section_idx"]: human_input["instruction"]
            }
        }

    elif action == "full_rewrite":
        return {
            "draft_approved": False,
            "sections": [],
            "current_section_idx": 0,
            "global_context": state["global_context"] + f"\n[재작성 지시] {human_input['instruction']}"
        }
```

---

## 6. 조건부 라우팅 (resume 후 다음 노드 결정)

```python
# Analyst: human_toc 이후 라우팅
def route_after_human_toc(state: AnalystState) -> str:
    if state.get("rewrite_instruction"):
        return "build_toc"          # 재작성 요청 → TOC 재생성
    return "plan_sections"          # 승인/수정 → 다음 단계

# Writer: human_draft 이후 라우팅
def route_after_human_draft(state: WriterState) -> str:
    if state.get("draft_approved"):
        return "finalize"           # 승인 → 최종 출력

    edits = state.get("human_edits", {})
    if edits and len(edits) < len(state["toc"]):
        return "write_section"      # 특정 섹션만 재작성
    return "write_section"          # 전면 재작성 (current_section_idx=0으로 리셋됨)
```

---

## 7. Thread ID 설계

여러 보고서를 동시에 생성하거나 같은 보고서를 나중에 재개하려면  
**Thread ID로 실행 컨텍스트를 구분**해야 한다.

```python
# Thread ID 설계 규칙
thread_id = f"{ticker}_{today}_{version}"
# 예: "005930_20260413_v1"

# 같은 종목을 당일 다시 만들면
thread_id = f"005930_20260413_v2"

# 목차만 다시 수정하고 싶을 때
# → 같은 thread_id로 analyst_graph만 다시 invoke
analyst_graph.update_state(
    config=thread_config,
    values={"toc_draft": [], "toc_iteration": 0}   # 목차 초기화
)
analyst_graph.invoke(None, config=thread_config)    # 이어서 실행
```

---

## 8. UI 옵션별 구현 방식

### 8.1 CLI (개발·테스트용)

```python
# 가장 단순한 구현 — 터미널에서 직접 입력
import json

# 실행 및 정지
analyst_graph.invoke(analyst_input, config=thread)

# State 읽기
state = analyst_graph.get_state(config=thread)
print("\n=== 목차 검토 ===")
for i, item in enumerate(state.values["toc_draft"], 1):
    print(f"{i}. {item['title']}")
    print(f"   → {item['key_message']}")

# 사용자 입력
print("\n[1] 승인  [2] 수정  [3] 재작성")
choice = input("선택: ")

if choice == "1":
    analyst_graph.invoke(Command(resume={"action": "approve"}), config=thread)
elif choice == "2":
    edits_json = input("수정 내용 (JSON): ")
    analyst_graph.invoke(Command(resume={"action": "edit", "edits": json.loads(edits_json)}), config=thread)
```

### 8.2 Streamlit (운영 권장)

```python
import streamlit as st
from langgraph.types import Command

st.title("📊 보고서 생성 시스템")

# 목차 검토 화면
if st.session_state.get("waiting_toc"):
    state = analyst_graph.get_state(config=thread)
    toc = state.values["toc_draft"]

    st.subheader("목차 초안")
    edited_toc = []
    for i, item in enumerate(toc):
        col1, col2 = st.columns([3, 1])
        with col1:
            new_title = st.text_input(f"항목 {i+1}", value=item["title"], key=f"toc_{i}")
        with col2:
            if st.button("삭제", key=f"del_{i}"):
                continue
        edited_toc.append({**item, "title": new_title})

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("✅ 승인"):
            analyst_graph.invoke(Command(resume={"action": "approve"}), config=thread)
    with col2:
        if st.button("✏️ 수정 반영"):
            analyst_graph.invoke(Command(resume={"action": "edit", "edits": edited_toc}), config=thread)
    with col3:
        if st.button("🔄 재작성"):
            instruction = st.text_area("재작성 지시사항")
            analyst_graph.invoke(Command(resume={"action": "rewrite", "instruction": instruction}), config=thread)
```

### 8.3 Telegram 봇 (모바일 승인용)

```python
# Telegram으로 목차를 전송하고 버튼으로 승인
async def send_toc_for_review(chat_id: str, toc: list, thread_id: str):
    text = "📋 *목차 검토 요청*\n\n"
    for i, item in enumerate(toc, 1):
        text += f"{i}\\. {item['title']}\n"
        text += f"   _{item['key_message']}_\n\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 승인", callback_data=f"approve|{thread_id}")],
        [InlineKeyboardButton("✏️ 항목 수정", callback_data=f"edit|{thread_id}")],
        [InlineKeyboardButton("🔄 전면 재작성", callback_data=f"rewrite|{thread_id}")],
    ])
    await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="MarkdownV2")

# 버튼 콜백 처리
async def handle_callback(query):
    action, thread_id = query.data.split("|")
    thread_config = {"configurable": {"thread_id": thread_id}}

    if action == "approve":
        analyst_graph.invoke(Command(resume={"action": "approve"}), config=thread_config)
        await query.answer("승인 완료! 보고서 작성을 시작합니다.")
```

---

## 9. 예외 상황 처리

| 상황 | 처리 방법 |
|------|----------|
| 사용자가 장시간 응답 없음 | Thread는 Checkpointer에 영구 저장 — 언제든 재개 가능 |
| 앱 재시작 후 재개 | 동일 thread_id로 `get_state()` 후 interrupt 상태 복원 |
| 목차 재작성 3회 초과 | 강제로 human_toc로 넘겨 사람이 직접 결정 |
| 섹션 재작성 루프 | 동일 섹션 재작성 3회 이상 시 경고 메시지 추가 후 사용자에게 재확인 |
| 잘못된 섹션 번호 입력 | 유효성 검사 후 오류 메시지 반환, interrupt 상태 유지 |

---

## 10. 전체 HITL 타임라인

```
[시작]
  │
  ├── Researcher 실행 (자동, 약 2~5분)
  │
  ├── Analyst 실행
  │     ├── assess_data    (자동)
  │     ├── extract_thesis (자동)
  │     ├── build_toc      (자동)
  │     ├── review_toc     (자동, 최대 3회)
  │     │
  │     ├── ✋ HITL ①: 목차 검토  ← 사람 개입 (수초~수분)
  │     │      사용자: 목차 확인 → 승인 or 수정 or 재작성 요청
  │     │
  │     └── plan_sections  (자동)
  │
  ├── Writer 실행
  │     ├── write_section × N (자동, 섹션당 30초~2분)
  │     ├── edit_draft         (자동)
  │     │
  │     ├── ✋ HITL ②: 초안 검토  ← 사람 개입 (수분~수십분)
  │     │      사용자: 전체 초안 읽기 → 승인 or 섹션 재작성 or 전면 재작성
  │     │
  │     └── finalize           (자동)
  │
[완료] 최종 보고서 출력
```
