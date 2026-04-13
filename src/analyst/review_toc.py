import json

from src.models.llm import get_llm
from src.state import AnalystState

def review_toc(state: AnalystState) -> dict:
    """
    Analyst 노드: review_toc
    독립 LLM이 목차를 검토하여 승인 또는 재작성 요청.
    toc_max_retries 초과 시 강제 승인.
    """
    toc_draft       = state.get("toc_draft", [])
    thesis_list     = state.get("thesis_list", [])
    toc_iteration   = state.get("toc_iteration", 1)
    toc_max_retries = state.get("toc_max_retries", 2)
    company_name    = state["company_name"]

    print(f"[review_toc] {company_name} — {toc_iteration}/{toc_max_retries}차 검토")

    llm = get_llm(temperature=0.0)

    toc_text = "\n".join(
        f"{s.get('order')}. {s.get('title')} — {s.get('description', '')}"
        for s in toc_draft
    )
    thesis_text = "\n".join(
        f"- [{t.get('type')}] {t.get('thesis')}"
        for t in thesis_list
    )

    prompt = (
        "당신은 투자 보고서 품질 검토 전문가입니다.\n"
        "아래 목차가 핵심 투자 논지를 잘 반영하는지 평가하세요.\n\n"
        f"[핵심 투자 논지]\n{thesis_text}\n\n"
        f"[목차 초안]\n{toc_text}\n\n"
        "평가 기준:\n"
        "1. 모든 핵심 긍정 논지가 목차에 반영되었는가?\n"
        "2. 리스크 섹션이 포함되어 있는가?\n"
        "3. 섹션 순서가 논리적인가? (요약 → 분석 → 리스크 → 결론)\n"
        "4. 섹션 수가 4~7개로 적절한가?\n\n"
        "출력 형식 (JSON):\n"
        '{"approved": true/false, "feedback": "개선 사항 (approved=true이면 빈 문자열)"}'
    )

    response = llm.invoke(prompt).content.strip()

    try:
        start  = response.find("{")
        end    = response.rfind("}") + 1
        result = json.loads(response[start:end])
        approved = result.get("approved", False)
        feedback = result.get("feedback", "")
    except Exception:
        approved = True
        feedback = ""

    print(f"  검토 결과: {'승인' if approved else '재작성 요청'}")
    if not approved:
        print(f"  피드백: {feedback[:80]}")

    return {
        "review_approved": approved,
        "review_feedback": feedback,
    }
