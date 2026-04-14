import json

from src.models.llm import get_small_llm
from src.researcher.rag_store import upsert_chunks
from src.state import ResearcherState


CATEGORIES = ["growth", "risk", "catalyst", "quality"]


def extract_from_report(
    content: str,
    ticker: str,
    company_name: str,
    source: str,
    pub_date: str,
    llm,
) -> list[dict]:
    """리포트 1개 내용 → 카테고리별 핵심 이슈 JSON 생성"""
    prompt = (
        f"당신은 증권사 리포트를 분석하는 투자 리서치 전문가입니다.\n"
        f"아래 {company_name}({ticker}) 리포트를 읽고 "
        f"투자 판단에 중요한 핵심 이슈를 카테고리별로 추출하세요.\n\n"
        f"[리포트 내용]\n{content}\n\n"
        "카테고리:\n"
        "- growth: 수치 기반 성장 동력 (매출, 이익, 점유율 등 수치 포함)\n"
        "- risk: 하방 리스크, 불확실성, 경쟁 위협\n"
        "- catalyst: 단기 주가 촉매, 이벤트, 출시 일정, 실적 발표\n"
        "- quality: 질적 경쟁력 요소 (기술 우위, 고객 관계, 경영 전략 변화, 산업 구조 변화)\n\n"
        "조건:\n"
        "- 각 카테고리 최대 3개\n"
        "- detail에 수치나 구체적 근거 반드시 포함\n"
        "- importance: 1=가장 중요, 2=중요, 3=보통 (반드시 1~3 정수만 사용)\n\n"
        "출력 형식 (JSON 배열만, 다른 텍스트 없이):\n"
        '[\n'
        '  {"category": "growth", "issue": "주력 제품 매출 성장",\n'
        '   "detail": "전년 대비 매출 +XX% 전망, 시장점유율 XX% 확대", "importance": 1},\n'
        '  {"category": "risk", "issue": "원가 상승 압박",\n'
        '   "detail": "원재료 가격 XX% 상승, 영업이익률 XX%p 하락 우려", "importance": 2},\n'
        '  {"category": "catalyst", "issue": "신제품 출시 일정",\n'
        '   "detail": "XX분기 신모델 출시, 초기 수주 XX억원 확보", "importance": 1}\n'
        ']'
    )

    response = llm.invoke(prompt).content.strip()

    try:
        start = response.find("[")
        end   = response.rfind("]") + 1
        issues = json.loads(response[start:end])
    except Exception:
        return []

    # source, pub_date 주입 및 카테고리 검증
    valid = []
    for item in issues:
        if item.get("category") not in CATEGORIES:
            continue
        item["source"]         = source
        item["published_date"] = pub_date
        valid.append(item)

    return valid


def merge_issues(
    all_issues: list[dict],
    ticker: str,
    company_name: str,
    llm,
) -> list[dict]:
    """여러 리포트 이슈 → 중복 제거 + 중요도 순 통합"""
    if not all_issues:
        return []

    issues_json = json.dumps(all_issues, ensure_ascii=False, indent=2)

    prompt = (
        f"아래는 {company_name}({ticker})에 대한 여러 리포트에서 추출한 이슈 목록입니다.\n"
        "중복을 제거하고 중요도 순으로 통합 정리하세요.\n\n"
        "규칙:\n"
        "- 같은 의미의 이슈는 하나로 합칠 것\n"
        "- 수치가 다를 경우 가장 최신 리포트 기준 수치 사용\n"
        "- 카테고리별 최대 5개로 제한\n"
        "- source 필드는 원본 그대로 유지\n\n"
        f"[이슈 목록]\n{issues_json}\n\n"
        "출력 형식 (JSON 배열만, 다른 텍스트 없이):\n"
        '[\n'
        '  {"category": "...", "issue": "...", "detail": "...", '
        '"importance": 1, "source": "...", "published_date": "..."},\n'
        '  ...\n'
        ']'
    )

    response = llm.invoke(prompt).content.strip()

    try:
        start = response.find("[")
        end   = response.rfind("]") + 1
        merged = json.loads(response[start:end])
    except Exception:
        # 통합 실패 시 원본 그대로 반환
        merged = all_issues

    return merged


def extract_issues(state: ResearcherState) -> dict:
    """
    Researcher 노드: extract_issues
    1. 소스 파일별로 L1 청크 그룹화
    2. 리포트별 이슈 추출 (LLM)
    3. 전체 이슈 통합 및 중복 제거 (LLM)
    4. ChromaDB issues 컬렉션 저장
    """
    ticker        = state["ticker"]
    company_name  = state["company_name"]
    report_chunks = state["report_chunks"]

    print(f"[extract_issues] {company_name} ({ticker}) 시작")

    llm = get_small_llm()

    # L1 청크 소스별 그룹화 (없으면 L0 사용)
    l1_chunks = [c for c in report_chunks if c["metadata"].get("raptor_level") == 1]
    if not l1_chunks:
        l1_chunks = [c for c in report_chunks if c["metadata"].get("raptor_level") == 0][:15]

    by_source: dict[str, list] = {}
    for c in l1_chunks:
        src = c["metadata"].get("source", "unknown")
        by_source.setdefault(src, []).append(c)

    if not by_source:
        print("  [WARN] 청크 없음 — 이슈 추출 건너뜀")
        return {"issues": []}

    # 리포트별 이슈 추출
    all_issues: list[dict] = []
    for source, chunks in by_source.items():
        content  = "\n\n".join(c["text"] for c in chunks[:5])
        pub_date = chunks[0]["metadata"].get("published_date", "")

        issues = extract_from_report(content, ticker, company_name, source, pub_date, llm)
        all_issues.extend(issues)
        print(f"  [{source[:40]}] 이슈 {len(issues)}개 추출")

    # 전체 통합 (리포트 2개 이상일 때만)
    if len(by_source) > 1:
        merged = merge_issues(all_issues, ticker, company_name, llm)
        print(f"  통합 후: {len(merged)}개")
    else:
        merged = all_issues

    # ChromaDB 저장
    chunks_to_save = []
    # 카테고리별 중요도 카운터
    cat_counter: dict[str, int] = {}
    for item in merged:
        cat = item.get("category", "growth")
        cat_counter[cat] = cat_counter.get(cat, 0) + 1
        imp = int(item.get("importance", cat_counter[cat]))

        # ID는 cat_counter(순번) 기반으로 생성 — importance 중복 시 ID 충돌 방지
        issue_id = f"issue_{ticker}_{cat}_{cat_counter[cat]:02d}"
        text     = f"{item.get('issue', '')} — {item.get('detail', '')}"

        chunks_to_save.append({
            "id":   issue_id,
            "text": text,
            "metadata": {
                "ticker":         ticker,
                "category":       cat,
                "issue":          item.get("issue", ""),
                "detail":         item.get("detail", ""),
                "importance":     imp,
                "source":         item.get("source", ""),
                "published_date": item.get("published_date", state.get("report_date", "")),
            },
        })

    saved = upsert_chunks("issues", chunks_to_save)
    print(f"  issues 저장: {saved}개")

    return {"issues": merged}
