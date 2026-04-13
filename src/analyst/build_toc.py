import json

from src.models.llm import get_llm
from src.researcher.rag_store import search
from src.state import AnalystState

SECTOR_GUIDELINES = {
    "반도체": "메모리/파운드리 구분, HBM·AI 수요, 재고 사이클, 경쟁사(TSMC·Micron) 비교",
    "자동차": "전기차 전환 속도, 배터리 원가, 글로벌 판매량, 수익성(ASP·믹스)",
    "기본":   "매출 성장, 영업이익률, 경쟁 환경, 리스크 요인",
}


def build_toc(state: AnalystState) -> dict:
    """
    Analyst 노드: build_toc
    3단계 CoT + thesis_list + 섹터 가이드라인으로 목차 초안 생성
    """
    ticker          = state["ticker"]
    company_name    = state["company_name"]
    sector          = state.get("sector", "기본")
    today           = state["today"]
    thesis_list     = state.get("thesis_list", [])
    data_assessment = state.get("data_assessment", {})
    toc_iteration   = state.get("toc_iteration", 0)
    review_feedback = state.get("review_feedback", "")

    print(f"[build_toc] {company_name} ({ticker}) — {toc_iteration+1}차 시도")

    llm = get_llm()

    # RAG 컨텍스트 수집
    rag_results = search("reports", f"{company_name} 실적 전망 투자포인트",
                         ticker, top_k=3, level=1)
    rag_context = "\n".join(r["text"] for r in rag_results)

    # 논지 텍스트
    thesis_text = "\n".join(
        f"{i+1}. [{t.get('type')}] {t.get('thesis')} — {t.get('evidence', '')}"
        for i, t in enumerate(thesis_list)
    )

    # 경고 텍스트
    warnings_text = "\n".join(data_assessment.get("warnings", [])) or "없음"

    # 섹터 가이드라인
    guideline = SECTOR_GUIDELINES.get(sector, SECTOR_GUIDELINES["기본"])

    # 이전 리뷰 피드백 포함
    feedback_block = ""
    if review_feedback:
        feedback_block = f"\n[이전 목차 리뷰 피드백 — 반드시 반영]\n{review_feedback}\n"

    prompt = (
        f"당신은 투자 리서치 보고서 편집장입니다.\n"
        f"작성일: {today} | 종목: {company_name}({ticker}) | 섹터: {sector}\n\n"
        "## 1단계: 데이터 파악\n"
        f"[핵심 투자 논지]\n{thesis_text}\n\n"
        f"[RAG 컨텍스트]\n{rag_context}\n\n"
        f"[데이터 경고]\n{warnings_text}\n"
        f"{feedback_block}\n"
        "## 2단계: 섹터 체크\n"
        f"섹터 가이드라인: {guideline}\n\n"
        "## 3단계: 목차 생성\n"
        "위 논지와 데이터를 바탕으로 투자 분석 보고서 목차를 4~7개 섹션으로 생성하세요.\n\n"
        "조건:\n"
        "- 각 섹션은 핵심 논지 중 하나와 연결될 것\n"
        "- 데이터 경고가 있으면 해당 섹션 제외 또는 축소\n"
        "- 마지막 섹션은 반드시 '리스크' 또는 '결론' 포함\n"
        "- order: 1부터 시작하는 순서\n\n"
        "출력 형식 (JSON 배열만):\n"
        '[\n'
        '  {"order": 1, "title": "섹션 제목", "description": "이 섹션에서 다룰 내용 1~2줄"},\n'
        '  ...\n'
        ']'
    )

    response = llm.invoke(prompt).content.strip()

    try:
        start = response.find("[")
        end   = response.rfind("]") + 1
        toc_draft = json.loads(response[start:end])
    except Exception:
        toc_draft = [
            {"order": 1, "title": "투자 포인트 요약",   "description": "핵심 논지 종합"},
            {"order": 2, "title": "실적 및 재무 분석",  "description": "최근 실적 검토"},
            {"order": 3, "title": "성장 동력",          "description": "중장기 성장 요인"},
            {"order": 4, "title": "리스크 요인",        "description": "주요 하방 리스크"},
            {"order": 5, "title": "결론 및 투자 의견",  "description": "종합 판단"},
        ]

    print(f"  목차 생성: {len(toc_draft)}개 섹션")
    for s in toc_draft:
        print(f"  {s.get('order')}. {s.get('title')}")

    return {
        "toc_draft":     toc_draft,
        "rag_context":   rag_context,
        "toc_iteration": toc_iteration + 1,
    }
