from src.state import AnalystState


def human_toc(state: AnalystState) -> dict:
    """
    Analyst 노드: human_toc (Human-in-the-Loop)
    main.py가 interrupt_before로 일시 중단 후 update_state()로 human_input을 주입하면
    이 노드가 실행되어 승인/재작성을 결정한다.
    interrupt()를 사용하지 않아 resume 값 전달 문제를 회피.
    """
    toc_draft   = state.get("toc_draft", [])
    user_input  = state.get("human_input", "").strip()
    company_name = state["company_name"]

    if user_input.lower() in ("ok", "승인", "y", "yes", ""):
        print(f"[human_toc] {company_name} — 목차 승인됨")
        return {"toc": toc_draft, "review_approved": True}

    # 수정 요청 — toc_iteration 리셋 없이 유지
    print(f"[human_toc] {company_name} — 수정 요청: {user_input[:60]}")
    return {
        "review_feedback": user_input,
        "review_approved": False,
    }
