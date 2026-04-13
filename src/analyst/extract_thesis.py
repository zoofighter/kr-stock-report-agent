import json

from src.models.llm import get_llm
from src.researcher.rag_store import search
from src.state import AnalystState


def extract_thesis(state: AnalystState) -> dict:
    """
    Analyst 노드: extract_thesis
    issues(growth/quality) + reports L2 + news 기반으로
    핵심 투자 논지 3~5개를 추출한다.
    """
    ticker       = state["ticker"]
    company_name = state["company_name"]
    today        = state["today"]
    issues       = state.get("issues", [])
    news_chunks  = state.get("news_chunks", [])

    print(f"[extract_thesis] {company_name} ({ticker}) 시작")

    llm = get_llm()

    # 이슈 텍스트 구성 (growth + quality 우선)
    priority_issues = [i for i in issues if i.get("category") in ("growth", "quality")]
    other_issues    = [i for i in issues if i.get("category") in ("risk", "catalyst")]
    issue_text = "\n".join(
        f"[{i.get('category')}] {i.get('issue')} — {i.get('detail', '')}"
        for i in (priority_issues + other_issues)[:12]
    )

    # L2 요약 검색
    l2_results = search("reports", f"{company_name} 투자 논지", ticker, top_k=2, level=2)
    l2_text = "\n".join(r["text"] for r in l2_results)

    # 최신 뉴스 상위 5개
    news_text = "\n".join(
        f"- {n.get('metadata', {}).get('title', n.get('text', ''))}"
        for n in news_chunks[:5]
    )

    prompt = (
        f"당신은 투자 리서치 수석 애널리스트입니다.\n"
        f"오늘 날짜: {today}\n\n"
        f"[핵심 이슈]\n{issue_text}\n\n"
        f"[리포트 전체 요약]\n{l2_text}\n\n"
        f"[최신 뉴스]\n{news_text}\n\n"
        f"위 데이터를 종합하여 {company_name}({ticker})에 대한 "
        "핵심 투자 논지(Investment Thesis)를 3~5개 도출하세요.\n\n"
        "각 논지 유형:\n"
        "- 핵심긍정: 주가 상승을 뒷받침하는 강력한 근거\n"
        "- 리스크: 하방 압력을 줄 수 있는 리스크 요인\n"
        "- 차별화: 경쟁사 대비 이 종목만의 강점\n"
        "- 전망: 중단기 이익 성장 또는 재평가 근거\n\n"
        "조건:\n"
        "- 각 논지는 수치나 구체적 사실 포함\n"
        "- 논지 간 중복 없음\n"
        "- importance: 1=가장 중요\n\n"
        "출력 형식 (JSON 배열만):\n"
        '[\n'
        '  {"type": "핵심긍정", "thesis": "...", "evidence": "근거 1~2줄", "importance": 1},\n'
        '  ...\n'
        ']'
    )

    response = llm.invoke(prompt).content.strip()

    try:
        start = response.find("[")
        end   = response.rfind("]") + 1
        thesis_list = json.loads(response[start:end])
    except Exception:
        thesis_list = [
            {"type": "핵심긍정", "thesis": f"{company_name} 실적 개선 기대",
             "evidence": "리포트 기반", "importance": 1}
        ]

    print(f"  논지 추출: {len(thesis_list)}개")
    for t in thesis_list:
        print(f"  [{t.get('type')}] {t.get('thesis', '')[:50]}")

    return {"thesis_list": thesis_list}
