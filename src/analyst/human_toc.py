from langgraph.types import interrupt

from src.state import AnalystState


def human_toc(state: AnalystState) -> dict:
    """
    Analyst 노드: human_toc (Human-in-the-Loop)
    목차를 사용자에게 보여주고 승인/수정을 기다린다.
    LangGraph interrupt()를 사용하여 실행을 일시 중단한다.
    """
    toc_draft    = state.get("toc_draft", [])
    company_name = state["company_name"]

    # 목차 출력
    toc_display = "\n".join(
        f"  {s.get('order')}. {s.get('title')}\n"
        f"     {s.get('description', '')}"
        for s in toc_draft
    )

    # interrupt()로 실행 중단 — 사용자 입력 대기
    user_input = interrupt({
        "message": (
            f"\n{'='*55}\n"
            f"[{company_name}] 목차 초안을 검토해주세요.\n"
            f"{'='*55}\n"
            f"{toc_display}\n"
            f"{'='*55}\n"
            "명령: 'ok' = 승인 | 수정 내용 직접 입력 = 재생성 요청\n"
        )
    })

    if str(user_input).strip().lower() in ("ok", "승인", "y", "yes", ""):
        print(f"[human_toc] 목차 승인됨")
        return {"toc": toc_draft, "review_approved": True}

    # 수정 요청 → review_feedback에 저장 후 build_toc 재실행
    # toc_iteration은 리셋하지 않음 — 최대 횟수 초과 시 LLM 검토 없이 바로 human_toc으로 복귀
    print(f"[human_toc] 수정 요청: {user_input}")
    return {
        "review_feedback": str(user_input),
        "review_approved": False,
    }
