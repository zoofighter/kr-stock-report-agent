from datetime import datetime

from src.state import ResearcherState
from src.researcher.graph import researcher_graph
from src.researcher.rag_store import search

TARGETS = [
    {"company_name": "삼성전자",  "ticker": "005930", "sector": "반도체"},
    {"company_name": "현대차",    "ticker": "005380", "sector": "자동차"},
    {"company_name": "SK하이닉스","ticker": "000660", "sector": "반도체"},
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
        grouped_by_report={},
        qa_draft=[],
        report_chunks=[],
        summaries=[],
        qa_pairs=[],
    )

    thread_config = {
        "configurable": {
            "thread_id": f"{target['ticker']}_{datetime.today().strftime('%Y%m%d')}"
        }
    }

    return researcher_graph.invoke(state, config=thread_config)


def verify_rag(ticker: str, company_name: str):
    """RAG 저장 확인 — 검색 테스트"""
    print(f"\n{'='*55}")
    print(f"[RAG 검증] {company_name} ({ticker})")
    print(f"{'='*55}")

    results = search("reports", f"{company_name} 영업이익", ticker, top_k=2, level=1)
    print(f"\n[reports L1] '{company_name} 영업이익'")
    for r in results:
        print(f"  score={r['score']:.4f} | {r['text'][:80]}...")

    results = search("summaries", f"{company_name} 투자포인트", ticker, top_k=2)
    print(f"\n[summaries] '{company_name} 투자포인트'")
    for r in results:
        print(f"  score={r['score']:.4f} | {r['text'][:80]}...")

    results = search("qa_pairs", f"{company_name} 투자 근거", ticker, top_k=2)
    print(f"\n[qa_pairs] '{company_name} 투자 근거'")
    for r in results:
        print(f"  score={r['score']:.4f} | {r['text'][:80]}...")


if __name__ == "__main__":
    print("Phase 1 시작 — 리포트 수집 → RAG 저장 → QA 생성")
    print(f"리포트 경로: /Users/boon/report/")
    print(f"DB 경로:     /Users/boon/report_db/\n")

    for target in TARGETS:
        print(f"\n{'#'*60}")
        print(f"# {target['company_name']} ({target['ticker']}) 처리 시작")
        print(f"{'#'*60}")

        result = run_researcher(target)

        print(
            f"\n✅ 완료: 청크 {len(result['report_chunks'])}개 "
            f"/ 요약 {len(result['summaries'])}개 "
            f"/ QA {len(result['qa_pairs'])}개"
        )
        verify_rag(target["ticker"], target["company_name"])

    print("\n\n🎉 Phase 1 완료 — advanced_qa 단계로 진행 가능")
    print("\nChromaDB 확인 명령:")
    print("  python3 -c \"import chromadb; c=chromadb.PersistentClient('/Users/boon/report_db'); [print(col.name,':',col.count()) for col in c.list_collections()]\"")
