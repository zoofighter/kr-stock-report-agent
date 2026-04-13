import json

from src.models.llm import get_llm
from src.researcher.rag_store import search
from src.state import AnalystState


def plan_sections(state: AnalystState) -> dict:
    """
    Analyst 노드: plan_sections
    확정 목차 기반으로 섹션별 작성 가이드 + global_context_seed 생성
    """
    ticker       = state["ticker"]
    company_name = state["company_name"]
    sector       = state.get("sector", "기본")
    today        = state["today"]
    toc          = state.get("toc") or state.get("toc_draft", [])
    thesis_list  = state.get("thesis_list", [])

    print(f"[plan_sections] {company_name} ({ticker}) 시작")

    llm = get_llm()

    # 섹션별 RAG 키 수치 미리 수집
    key_figures = []
    for section in toc[:3]:
        results = search("reports", section.get("title", ""), ticker, top_k=2, level=0)
        for r in results:
            key_figures.append(r["text"][:100])

    toc_json    = json.dumps(toc, ensure_ascii=False, indent=2)
    thesis_json = json.dumps(thesis_list, ensure_ascii=False, indent=2)
    figures_text = "\n".join(f"- {f}" for f in key_figures[:6])

    prompt = (
        f"확정된 목차와 핵심 투자 논지를 바탕으로 "
        f"{company_name}({ticker}) 보고서의 섹션별 작성 가이드를 생성하세요.\n\n"
        f"[확정 목차]\n{toc_json}\n\n"
        f"[핵심 투자 논지]\n{thesis_json}\n\n"
        f"[주요 수치 힌트]\n{figures_text}\n\n"
        "각 섹션별로 다음을 작성하세요:\n"
        "- key_message: 독자에게 전달할 핵심 1문장\n"
        "- thesis_link: 연결된 투자 논지 번호 (importance 기준)\n"
        "- required_data_points: 반드시 포함할 수치/사실 3개\n"
        "- rag_keywords: RAG 검색 키워드 3~5개\n"
        "- tone: 분석적 / 경고적 / 전망적 중 선택\n"
        "- approx_length: 예상 분량 (자수, 300~800 사이)\n\n"
        "출력 형식 (JSON 배열만):\n"
        '[\n'
        '  {\n'
        '    "order": 1,\n'
        '    "title": "섹션 제목",\n'
        '    "key_message": "...",\n'
        '    "thesis_link": [1, 2],\n'
        '    "required_data_points": ["수치1", "수치2", "수치3"],\n'
        '    "rag_keywords": ["키워드1", "키워드2"],\n'
        '    "tone": "분석적",\n'
        '    "approx_length": 500\n'
        '  },\n'
        '  ...\n'
        ']'
    )

    response = llm.invoke(prompt).content.strip()

    try:
        start = response.find("[")
        end   = response.rfind("]") + 1
        section_plans = json.loads(response[start:end])
    except Exception:
        # 파싱 실패 시 목차 기반 기본 플랜 생성
        section_plans = [
            {
                "order":                s.get("order"),
                "title":               s.get("title"),
                "key_message":         s.get("description", ""),
                "thesis_link":         [1],
                "required_data_points": [],
                "rag_keywords":        [s.get("title", "")],
                "tone":                "분석적",
                "approx_length":       500,
            }
            for s in toc
        ]

    # global_context_seed 생성
    thesis_summary = "\n".join(
        f"{i+1}. [{t.get('type')}] {t.get('thesis')}"
        for i, t in enumerate(thesis_list)
    )
    toc_summary = "\n".join(
        f"{s.get('order')}. {s.get('title')}"
        for s in toc
    )

    global_context_seed = (
        f"이 보고서는 {company_name}({ticker})에 대한 투자 분석 보고서입니다.\n"
        f"섹터: {sector} | 작성일: {today}\n\n"
        f"[핵심 투자 논지]\n{thesis_summary}\n\n"
        f"[보고서 구성]\n{toc_summary}\n\n"
        "[작성 원칙]\n"
        "- 모든 섹션은 핵심 논지와 일관성을 유지할 것\n"
        "- 수치 인용 시 반드시 출처를 명시할 것\n"
        "- 긍정 요인과 리스크를 균형 있게 서술할 것"
    )

    print(f"  섹션 플랜: {len(section_plans)}개 생성")

    return {
        "section_plans":       section_plans,
        "global_context_seed": global_context_seed,
        "toc":                 toc,
    }
