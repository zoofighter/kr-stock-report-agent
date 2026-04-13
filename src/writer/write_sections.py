import time

from src.models.llm import get_llm
from src.researcher.rag_store import search
from src.state import WriterState

# 최신 동향 관련 키워드 (news 컬렉션 추가 트리거)
NEWS_KEYWORDS = {"동향", "시장", "최신", "트렌드", "전망", "outlook"}

# 리스크 관련 키워드 (issues 컬렉션 추가 트리거)
RISK_KEYWORDS = {"리스크", "위험", "우려", "하락", "경쟁", "규제", "제재"}


def _needs_news(plan: dict) -> bool:
    if plan.get("tone") == "전망적":
        return True
    title = plan.get("title", "")
    return any(kw in title for kw in NEWS_KEYWORDS)


def _needs_issues(plan: dict) -> bool:
    if plan.get("tone") == "경고적":
        return True
    title = plan.get("title", "")
    return any(kw in title for kw in RISK_KEYWORDS)


def _build_rag_context(plan: dict, ticker: str) -> str:
    """섹션 플랜 기반 RAG 검색 후 컨텍스트 문자열 반환."""
    parts = []

    # ① reports L0 — 정확한 수치 (rag_keywords 첫 번째로 검색)
    keywords = plan.get("rag_keywords", [plan.get("title", "")])
    query_l0 = " ".join(keywords[:2])
    l0_results = search("reports", query_l0, ticker, top_k=3, level=0)
    if l0_results:
        parts.append("--- 리포트 원문 (수치) ---")
        parts.extend(r["text"][:300] for r in l0_results)

    # ② reports L1 — 단락 요약 (두 번째 키워드로 검색)
    query_l1 = " ".join(keywords[1:3]) if len(keywords) > 1 else keywords[0]
    l1_results = search("reports", query_l1, ticker, top_k=2, level=1)
    if l1_results:
        parts.append("--- 리포트 요약 ---")
        parts.extend(r["text"][:300] for r in l1_results)

    # ③ reports L2 — 첫 번째 섹션에만 추가
    if plan.get("order") == 1:
        l2_results = search("reports", plan.get("title", ""), ticker, top_k=1, level=2)
        if l2_results:
            parts.append("--- 전체 요약 ---")
            parts.append(l2_results[0]["text"][:400])

    # ④ news — 전망적 또는 동향 섹션
    if _needs_news(plan):
        news_results = search("news", plan.get("title", ""), ticker, top_k=2)
        if news_results:
            parts.append("--- 최신 뉴스 ---")
            parts.extend(r["text"][:200] for r in news_results)

    # ⑤ issues — 경고적 또는 리스크 섹션
    if _needs_issues(plan):
        issue_results = search("issues", plan.get("title", ""), ticker, top_k=2)
        if issue_results:
            parts.append("--- 주요 이슈/리스크 ---")
            parts.extend(r["text"][:200] for r in issue_results)

    return "\n".join(parts)


def _build_prompt(plan: dict, rag_context: str,
                  global_context_seed: str, thesis_list: list) -> str:
    title        = plan.get("title", "")
    key_message  = plan.get("key_message", "")
    approx_len   = plan.get("approx_length", 500)
    tone         = plan.get("tone", "분석적")
    thesis_links = plan.get("thesis_link", [])
    data_points  = plan.get("required_data_points", [])

    # 연결 논지 텍스트
    linked = [
        f"[{t.get('type')}] {t.get('thesis')}"
        for i, t in enumerate(thesis_list, 1)
        if i in thesis_links
    ]
    linked_text = "\n".join(linked) if linked else "없음"

    dp_text = "\n".join(f"- {dp}" for dp in data_points) if data_points else "없음"

    return (
        f"[시스템 컨텍스트]\n{global_context_seed}\n\n"
        f"[이 섹션 작성 지침]\n"
        f"섹션 제목: {title}\n"
        f"핵심 메시지: {key_message}\n"
        f"예상 분량: {approx_len}자\n"
        f"어조: {tone}\n"
        f"연결 투자 논지:\n{linked_text}\n\n"
        f"[RAG 컨텍스트]\n{rag_context}\n\n"
        f"[필수 포함 항목]\n{dp_text}\n\n"
        "[작성 요령]\n"
        f"- 첫 문장을 다음 핵심 메시지로 시작하세요: \"{key_message}\"\n"
        "- 수치 인용 시 리포트 날짜를 함께 명시하세요\n"
        "- 순수 산문체로 작성하세요 (마크다운 기호, 헤더, 불릿 없이)\n"
        f"- 분량은 {approx_len}자 ±15% 이내로 작성하세요\n\n"
        "[출력]\n"
        "섹션 본문만 출력하세요. 제목, 헤더, 마크다운 기호는 제외합니다."
    )


def write_sections(state: WriterState) -> dict:
    """
    Writer 노드: write_sections
    section_plans를 순회하며 RAG 검색 + LLM 호출로 각 섹션 본문을 생성합니다.
    """
    ticker             = state["ticker"]
    company_name       = state["company_name"]
    section_plans      = state.get("section_plans", [])
    thesis_list        = state.get("thesis_list", [])
    global_context_seed = state.get("global_context_seed", "")

    print(f"[write_sections] {company_name} ({ticker}) — {len(section_plans)}개 섹션 작성 시작")

    llm = get_llm(temperature=0.3)

    written_sections = []
    total_start      = time.time()

    for plan in section_plans:
        order = plan.get("order", "?")
        title = plan.get("title", "")
        print(f"  섹션 {order}: {title}")

        t0 = time.time()
        rag_context = _build_rag_context(plan, ticker)
        prompt      = _build_prompt(plan, rag_context, global_context_seed, thesis_list)

        # 예외 발생 시 그대로 전파 — 파이프라인 중단
        content = llm.invoke(prompt).content.strip()
        elapsed = time.time() - t0

        if not content:
            raise ValueError(f"섹션 {order} '{title}' — LLM 응답이 비어 있습니다")

        written_sections.append({
            "order":   order,
            "title":   title,
            "content": content,
        })
        print(f"    완료 — {len(content)}자 / {elapsed:.1f}초")

    total_elapsed = time.time() - total_start
    print(f"[write_sections] 완료: {len(written_sections)}개 / 총 {total_elapsed:.1f}초")

    return {
        "written_sections": written_sections,
        "write_errors":     [],
    }
