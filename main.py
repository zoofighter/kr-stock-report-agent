import argparse
import csv
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)  # Ollama HTTP 소켓 미종료 경고 억제

from src.state import ResearcherState, AnalystState, WriterState
from src.researcher.graph import researcher_graph
from src.analyst.graph import analyst_graph
from src.writer.graph import writer_graph
from src.researcher.rag_store import search

TARGETS = [
    {"company_name": "삼성전자",   "ticker": "005930", "sector": "반도체"},
    {"company_name": "현대차",     "ticker": "005380", "sector": "자동차"},
    {"company_name": "SK하이닉스", "ticker": "000660", "sector": "반도체"},
    {"company_name": "NAVER",      "ticker": "035420", "sector": "인터넷/플랫폼"},
]

COM_LIST_CSV = Path(__file__).parent / "com_list.csv"


def load_targets_from_csv(csv_path: Path) -> list[dict]:
    """
    com_list.csv 에서 종목 목록을 읽는다.
    컬럼: company_name, ticker, file_count (sector 없으면 빈 문자열)
    ticker 가 비어 있는 행은 건너뛴다.
    """
    targets = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").strip()
            if not ticker:
                continue
            targets.append({
                "company_name": row.get("company_name", "").strip(),
                "ticker":       ticker,
                "sector":       row.get("sector", "").strip(),
            })
    return targets


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
        human_input="",
        toc_iteration=0,
        toc_max_retries=toc_max_retries,
        review_feedback="",
        review_approved=False,
        toc=[],
        section_plans=[],
        global_context_seed="",
    )
    thread_id = f"analyst_{target['ticker']}_{datetime.today().strftime('%Y%m%d_%H%M%S')}"
    thread_config = {"configurable": {"thread_id": thread_id}}

    # 1차 실행 — interrupt_before["human_toc"]에서 pause
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

        # 사용자 입력을 상태에 주입 후 재개 (interrupt() 없이 안정적으로 동작)
        analyst_graph.update_state(thread_config, {"human_input": user_input or "ok"})
        result = analyst_graph.invoke(None, config=thread_config)

    return result


def run_writer(target: dict, analyst_result: dict) -> dict:
    """단일 종목 Writer 실행"""
    state = WriterState(
        company_name=target["company_name"],
        ticker=target["ticker"],
        sector=target["sector"],
        today=datetime.today().strftime("%Y-%m-%d"),
        report_date=analyst_result.get("report_date", ""),
        toc=analyst_result.get("toc", []),
        thesis_list=analyst_result.get("thesis_list", []),
        section_plans=analyst_result.get("section_plans", []),
        global_context_seed=analyst_result.get("global_context_seed", ""),
        written_sections=[],
        write_errors=[],
        report_markdown="",
        output_path="",
    )
    thread_config = {"configurable": {
        "thread_id": f"writer_{target['ticker']}_{datetime.today().strftime('%Y%m%d_%H%M%S')}"
    }}
    return writer_graph.invoke(state, config=thread_config)


def save_debug(target: dict, research_result: dict, analyst_result: dict) -> str:
    """
    디버깅용 텍스트 파일 저장 — 리포트 출력 폴더와 동일 경로
    저장 내용: L2 요약 / 이슈 키워드 / thesis / TOC / 섹션 플랜 핵심
    반환: 저장된 파일 경로
    """
    ticker       = target["ticker"]
    company_name = target["company_name"]
    today        = datetime.today().strftime("%Y%m%d")

    out_dir = Path(f"/Users/boon/report_output/{ticker}")
    out_dir.mkdir(parents=True, exist_ok=True)
    debug_path = out_dir / f"{today}_{company_name}_debug.txt"

    lines = []

    # ── 1. RAPTOR L2 전체 요약 ──────────────────────────────────────
    lines.append("=" * 60)
    lines.append("[ RAPTOR L2 — 전체 투자 논지 요약 ]")
    lines.append("=" * 60)
    l2_chunks = [
        c for c in research_result.get("report_chunks", [])
        if c.get("metadata", {}).get("raptor_level") == 2
    ]
    if l2_chunks:
        lines.append(l2_chunks[0]["text"])
    else:
        lines.append("(없음)")

    # ── 2. 추출된 이슈 키워드 ────────────────────────────────────────
    lines.append("\n" + "=" * 60)
    lines.append("[ 이슈 키워드 (category / issue / detail) ]")
    lines.append("=" * 60)
    issues = research_result.get("issues", [])
    if issues:
        for iss in sorted(issues, key=lambda x: (x.get("category", ""), x.get("importance", 9))):
            lines.append(
                f"[{iss.get('category','?'):8s}] imp={iss.get('importance','?')}  "
                f"{iss.get('issue','')}"
            )
            lines.append(f"          → {iss.get('detail','')}")
    else:
        lines.append("(없음)")

    # ── 3. Thesis 목록 ───────────────────────────────────────────────
    lines.append("\n" + "=" * 60)
    lines.append("[ Thesis 목록 ]")
    lines.append("=" * 60)
    for i, th in enumerate(analyst_result.get("thesis_list", []), 1):
        lines.append(f"{i}. [{th.get('type','')}] {th.get('thesis','')}")
        lines.append(f"   근거: {th.get('evidence','')}")

    # ── 4. 최종 TOC ──────────────────────────────────────────────────
    lines.append("\n" + "=" * 60)
    lines.append("[ 최종 TOC ]")
    lines.append("=" * 60)
    for s in analyst_result.get("toc", []):
        lines.append(f"  {s.get('order')}. {s.get('title')}")
        lines.append(f"     {s.get('description','')}")

    # ── 5. 섹션 플랜 핵심 (key_message + rag_keywords) ──────────────
    lines.append("\n" + "=" * 60)
    lines.append("[ 섹션 플랜 — key_message / rag_keywords ]")
    lines.append("=" * 60)
    for sp in analyst_result.get("section_plans", []):
        lines.append(f"\n{sp.get('order')}. {sp.get('title')}  (tone={sp.get('tone','')}, ~{sp.get('approx_length','')}자)")
        lines.append(f"   핵심: {sp.get('key_message','')}")
        lines.append(f"   RAG 키워드: {sp.get('rag_keywords','')}")

    debug_path.write_text("\n".join(lines), encoding="utf-8")
    return str(debug_path)


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
        nargs="+",
        default=None,
        help="실행할 종목 티커 (예: 005930  또는  005930 000660). 미지정 시 전체 종목 실행",
    )
    args = parser.parse_args()

    hitl        = not args.no_hitl       # 기본값 True
    toc_retries = args.toc_retries       # 기본값 2

    print("시작 — 리포트 수집 + 뉴스 수집 → 이슈 추출 → Analyst → Writer")
    print(f"리포트 경로: /Users/boon/report/")
    print(f"DB 경로:     /Users/boon/report_db/")
    print(f"Human-in-the-Loop: {'활성화' if hitl else '비활성화 (자동 승인)'}")
    print(f"TOC 최대 시도: {toc_retries}회\n")

    # 기본 종목 목록: --ticker 미지정 시 com_list.csv 우선, 없으면 TARGETS
    if args.ticker:
        requested = set(args.ticker)
        # TARGETS + CSV 모두에서 검색
        all_known = {t["ticker"]: t for t in TARGETS}
        if COM_LIST_CSV.exists():
            for t in load_targets_from_csv(COM_LIST_CSV):
                all_known.setdefault(t["ticker"], t)
        targets = [all_known[tk] for tk in requested if tk in all_known]
        not_found = requested - set(all_known)
        if not_found:
            print(f"[ERROR] 등록되지 않은 종목: {', '.join(not_found)}")
            print(f"  TARGETS 종목: {', '.join(t['ticker'] for t in TARGETS)}")
            if COM_LIST_CSV.exists():
                print(f"  com_list.csv 에서도 찾을 수 없음")
            exit(1)
    elif COM_LIST_CSV.exists():
        targets = load_targets_from_csv(COM_LIST_CSV)
        print(f"com_list.csv 로드: {len(targets)}개 종목")
    else:
        targets = TARGETS
        print(f"TARGETS 사용 (com_list.csv 없음): {len(targets)}개 종목")

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

        debug_path = save_debug(target, research_result, analyst_result)
        print(f" 디버그 파일: {debug_path}")

        print(f"\n{'#'*60}")
        print(f"# {target['company_name']} ({target['ticker']}) — Writer")
        print(f"{'#'*60}")

        writer_result = run_writer(target, analyst_result)

        output_path  = writer_result.get("output_path", "")
        write_errors = writer_result.get("write_errors", [])
        print(f"\n Writer 완료: {output_path}")
        if write_errors:
            print(f"  [경고] 오류 섹션 {len(write_errors)}개: "
                  + ", ".join(str(e.get("order")) for e in write_errors))

    print("\n\n 완료 — 전체 파이프라인 종료")
    print("\nChromaDB 확인:")
    print("  python -c \"import chromadb; c=chromadb.PersistentClient('/Users/boon/report_db'); [print(col.name,':',col.count()) for col in c.list_collections()]\"")
    print("\n출력 파일 확인:")
    print("  ls /Users/boon/report_output/")
