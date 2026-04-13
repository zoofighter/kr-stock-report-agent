from src.models.llm import INFERENCE_MODEL
from src.state import WriterState


def assemble_report(state: WriterState) -> dict:
    """
    Writer 노드: assemble_report
    written_sections를 마크다운 형식으로 조립합니다.
    구조: 헤더 → 목차 → 섹션 본문 → 핵심 논지 요약 → 푸터
    """
    company_name        = state["company_name"]
    ticker              = state["ticker"]
    sector              = state.get("sector", "")
    today               = state["today"]
    report_date         = state.get("report_date", "")
    toc                 = state.get("toc", [])
    thesis_list         = state.get("thesis_list", [])
    global_context_seed = state.get("global_context_seed", "")
    written_sections    = state.get("written_sections", [])

    print(f"[assemble_report] {company_name} ({ticker}) 조립 중...")

    # global_context_seed 첫 줄 (요약 문장)
    seed_first_line = global_context_seed.split("\n")[0] if global_context_seed else ""

    # ── 헤더 ──────────────────────────────────────────────
    lines = [
        f"# {company_name}({ticker}) 투자 분석 보고서",
        "",
        f"> **{seed_first_line}**",
        "",
        f"**작성일**: {today}  |  **기준 리포트**: {report_date}  |  **섹터**: {sector}",
        "",
        "---",
        "",
    ]

    # ── 목차 ──────────────────────────────────────────────
    lines.append("## 목차")
    lines.append("")
    for s in sorted(toc, key=lambda x: x.get("order", 0)):
        lines.append(f"{s.get('order')}. {s.get('title')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 섹션 본문 ─────────────────────────────────────────
    # order 기준 정렬, 누락 섹션은 placeholder
    written_map = {s["order"]: s for s in written_sections}

    for toc_item in sorted(toc, key=lambda x: x.get("order", 0)):
        order = toc_item.get("order")
        title = toc_item.get("title", "")
        section = written_map.get(order)

        lines.append(f"## {order}. {title}")
        lines.append("")

        if section:
            lines.append(section["content"])
        else:
            lines.append("*[작성 실패 — 데이터 부족으로 해당 섹션을 생성하지 못했습니다.]*")

        lines.append("")
        lines.append("---")
        lines.append("")

    # ── 핵심 투자 논지 요약 ───────────────────────────────
    if thesis_list:
        lines.append("## 핵심 투자 논지 요약")
        lines.append("")
        lines.append("| 구분 | 논지 | 근거 |")
        lines.append("|------|------|------|")
        for t in thesis_list:
            t_type     = t.get("type", "")
            thesis     = t.get("thesis", "").replace("|", "\\|")
            evidence   = t.get("evidence", "").replace("|", "\\|")[:60]
            lines.append(f"| {t_type} | {thesis} | {evidence} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── 푸터 ──────────────────────────────────────────────
    lines.append(
        f"*본 보고서는 AI 기반 자동 분석 시스템에 의해 생성되었습니다.*  "
    )
    lines.append(
        f"*생성일시: {today} | 모델: Ollama/{INFERENCE_MODEL}*"
    )

    report_markdown = "\n".join(lines)

    print(f"  마크다운 완성: {len(report_markdown):,}자")

    return {"report_markdown": report_markdown}
