from datetime import datetime, timedelta

from src.state import AnalystState


def assess_data(state: AnalystState) -> dict:
    """
    Analyst 노드: assess_data
    수집된 데이터의 양·품질·최신성을 평가하고 경고를 생성한다.
    """
    report_chunks = state.get("report_chunks", [])
    news_chunks   = state.get("news_chunks", [])
    issues        = state.get("issues", [])

    # 리포트 수 추정 (L0 청크 기준)
    l0_chunks    = [c for c in report_chunks if c.get("metadata", {}).get("raptor_level") == 0]
    report_count = max(len(set(
        c["metadata"].get("source", "") for c in l0_chunks
    )), 1 if l0_chunks else 0)

    news_count  = len(news_chunks)
    issue_count = len(issues)

    # 최신 데이터 비율 (30일 이내)
    cutoff = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    recent_news = [n for n in news_chunks
                   if n.get("metadata", {}).get("published_date", "") >= cutoff]
    recent_ratio = round(len(recent_news) / max(news_count, 1) * 100)

    # 경고 생성
    warnings = []
    if report_count < 1:
        warnings.append("리포트 없음 — 보고서 근거 부족")
    if news_count < 5:
        warnings.append(f"뉴스 {news_count}개 — 최신 동향 반영 어려움")
    if issue_count < 3:
        warnings.append(f"이슈 {issue_count}개 — 핵심 분석 부족")
    if recent_ratio < 30:
        warnings.append(f"최신 뉴스 비율 {recent_ratio}% — 시의성 낮음")

    # 점수 (0~100)
    score = min(100, (
        min(report_count, 5) * 10 +
        min(news_count, 20) * 2 +
        min(issue_count, 10) * 3 +
        recent_ratio // 5
    ))

    assessment = {
        "score":          score,
        "warnings":       warnings,
        "report_count":   report_count,
        "news_count":     news_count,
        "issue_count":    issue_count,
        "recent_ratio":   recent_ratio,
    }

    print(f"[assess_data] 점수={score}/100 | 리포트={report_count} 뉴스={news_count} 이슈={issue_count}")
    if warnings:
        for w in warnings:
            print(f"  ⚠️  {w}")

    return {"data_assessment": assessment}
