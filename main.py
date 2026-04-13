import argparse
from datetime import datetime

from src.state import ResearcherState, AnalystState
from src.researcher.graph import researcher_graph
from src.analyst.graph import analyst_graph
from src.researcher.rag_store import search

TARGETS = [
    {"company_name": "삼성전자",   "ticker": "005930", "sector": "반도체"},
    {"company_name": "현대차",     "ticker": "005380", "sector": "자동차"},
    {"company_name": "SK하이닉스", "ticker": "000660", "sector": "반도체"},
]


def run_researcher(target: dict) -> dict:
    """단일 종목 Researcher 실행"""
    state = ResearcherState(
        topic=target["company_name"],
        company_name=target["company_name"],
        ticker=target["ticker"],
        sector=target["sector"],
        today=datetime.today().strftime("%Y-%m-%d"),
        report_date="",
        file_paths=[],
        raw_texts=[],
        parse_errors=[],
        raptor_chunks=[],
        report_chunks=[],
        news_chunks=[],
        issues=[],
    )
    thread_config = {"configurable": {
        "thread_id": f"researcher_{target['ticker']}_{datetime.today().strftime('%Y%m%d')}"
    }}
    return researcher_graph.invoke(state, config=thread_config)


def run_analyst(target: dict, research_result: dict,
                human_in_the_loop: bool = True,
                toc_max_retries: int = 2) -> dict:
    """
    단일 종목 Analyst 실행
    human_in_the_loop=True  → 목차 승인 대기 (기본값)
    human_in_the_loop=False → 자동 승인 (--no-hitl 옵션)
    """
    state = AnalystState(
        topic=target["company_name"],
        company_name=target["company_name"],
        ticker=target["ticker"],
        sector=target["sector"],
        today=datetime.today().strftime("%Y-%m-%d"),
        report_date=research_result.get("report_date", ""),
        report_chunks=research_result.get("report_chunks", []),
        news_chunks=research_result.get("news_chunks", []),
        issues=research_result.get("issues", []),
        data_assessment={},
        thesis_list=[],
        rag_context="",
        toc_draft=[],
        toc_iteration=0,
        toc_max_retries=toc_max_retries,
        review_feedback="",
        review_approved=False,
        toc=[],
        section_plans=[],
        global_context_seed="",
    )
    thread_id = f"analyst_{target['ticker']}_{datetime.today().strftime('%Y%m%d')}"
    thread_config = {"configurable": {"thread_id": thread_id}}

    # 1차 실행 — human_toc에서 interrupt 발생
    result = analyst_graph.invoke(state, config=thread_config)

    # Human-in-the-Loop 루프
    while True:
        snapshot = analyst_graph.get_state(thread_config)
        if not snapshot.next:
            break  # 완료

        if "human_toc" not in snapshot.next:
            break

        # 목차 출력
        toc_draft = snapshot.values.get("toc_draft", [])
        print(f"\n{'='*55}")
        print(f"[{target['company_name']}] 목차 초안")
        print(f"{'='*55}")
        for s in toc_draft:
            print(f"  {s.get('order')}. {s.get('title')}")
            print(f"     {s.get('description', '')}")
        print(f"{'='*55}")

        if human_in_the_loop:
            # 사용자 입력 대기
            user_input = input("명령 ('ok' 또는 Enter=승인 / 수정 내용 입력): ").strip()
        else:
            # 자동 승인
            user_input = "ok"
            print("  [자동 승인] --no-hitl 모드")

        result = analyst_graph.invoke(
            {"__resume__": user_input or "ok"},
            config=thread_config,
        )

    return result


def verify_rag(ticker: str, company_name: str):
    """RAG 저장 확인"""
    print(f"\n{'='*55}")
    print(f"[RAG 검증] {company_name} ({ticker})")
    print(f"{'='*55}")

    results = search("reports", f"{company_name} 영업이익", ticker, top_k=2, level=1)
    print(f"\n[reports L1] '{company_name} 영업이익'")
    for r in results:
        print(f"  score={r['score']:.4f} | {r['text'][:80]}...")

    results = search("news", f"{company_name} 최신 동향", ticker, top_k=2)
    print(f"\n[news] '{company_name} 최신 동향'")
    for r in results:
        print(f"  score={r['score']:.4f} | {r['text'][:80]}...")

    results = search("issues", f"{company_name} 성장 동력", ticker, top_k=2)
    print(f"\n[issues] '{company_name} 성장 동력'")
    for r in results:
        print(f"  score={r['score']:.4f} | {r['text'][:80]}...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="증권 리포트 자동 보고서 생성")
    parser.add_argument(
        "--no-hitl",
        action="store_true",
        default=False,
        help="Human-in-the-Loop 비활성화 (목차 자동 승인). 기본값: 활성화(사용자 승인 대기)",
    )
    parser.add_argument(
        "--toc-retries",
        type=int,
        default=2,
        help="build_toc 최대 재시도 횟수 (기본값: 2)",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default=None,
        help="특정 종목만 실행 (예: 005930). 미지정 시 전체 종목 실행",
    )
    args = parser.parse_args()

    hitl        = not args.no_hitl       # 기본값 True
    toc_retries = args.toc_retries       # 기본값 2

    print("시작 — 리포트 수집 + 뉴스 수집 → 이슈 추출 → Analyst")
    print(f"리포트 경로: /Users/boon/report/")
    print(f"DB 경로:     /Users/boon/report_db/")
    print(f"Human-in-the-Loop: {'활성화' if hitl else '비활성화 (자동 승인)'}")
    print(f"TOC 최대 시도: {toc_retries}회\n")

    targets = TARGETS
    if args.ticker:
        targets = [t for t in TARGETS if t["ticker"] == args.ticker]
        if not targets:
            print(f"[ERROR] 종목 {args.ticker}을 찾을 수 없습니다.")
            exit(1)

    for target in targets:
        print(f"\n{'#'*60}")
        print(f"# {target['company_name']} ({target['ticker']}) — Researcher")
        print(f"{'#'*60}")

        research_result = run_researcher(target)

        print(
            f"\n Researcher 완료: 청크 {len(research_result.get('report_chunks', []))}개"
            f" / 뉴스 {len(research_result.get('news_chunks', []))}개"
            f" / 이슈 {len(research_result.get('issues', []))}개"
        )
        verify_rag(target["ticker"], target["company_name"])

        print(f"\n{'#'*60}")
        print(f"# {target['company_name']} ({target['ticker']}) — Analyst")
        print(f"{'#'*60}")

        analyst_result = run_analyst(target, research_result,
                                     human_in_the_loop=hitl,
                                     toc_max_retries=toc_retries)

        section_plans = analyst_result.get("section_plans", [])
        print(f"\n Analyst 완료: 섹션 플랜 {len(section_plans)}개")

    print("\n\n 완료 — Writer 단계로 진행 가능")
    print("\nChromaDB 확인:")
    print("  python -c \"import chromadb; c=chromadb.PersistentClient('/Users/boon/report_db'); [print(col.name,':',col.count()) for col in c.list_collections()]\"")
