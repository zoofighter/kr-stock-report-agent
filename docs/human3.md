
해결 방안 3가지
방안 A — 순서 변경 (병렬성 포기)


START → collect_reports → extract_issues → fetch_news(이슈 키워드 사용) → END
장점: 이슈 키워드로 정확한 뉴스 수집
단점: 전체 처리 시간 증가 (순차 실행)
방안 B — 뉴스 2단계 수집 (현재 구조 유지)


START → collect_reports ──→ extract_issues → fetch_news_targeted → END
      └→ fetch_news_basic ──→
fetch_news_basic: 기존처럼 {company_name} 주가 실적 으로 기본 수집
fetch_news_targeted: extract_issues 후 이슈 키워드로 추가 수집 및 재랭킹
장점: 병렬성 유지 + 이슈 키워드 활용
단점: 노드 하나 추가
방안 C — L2 청크 키워드 활용 (구조 변경 최소)


START → collect_reports → fetch_news(L2 키워드) + extract_issues → END
collect_reports 완료 후 fetch_news 실행 (L2 요약에서 키워드 추출)
fetch_news 와 extract_issues 병렬 실행
이슈 대신 RAPTOR L2(전체 투자 논지 요약)에서 키워드를 뽑아 사용
장점: 이슈와 유사한 품질, 노드 추가 없음




전체 파이프라인

flowchart TD
    CLI["main.py\n--ticker\n--no-hitl\n--toc-retries"]

    CLI --> R
    CLI --> A
    CLI --> W

    subgraph R["① RESEARCHER GRAPH"]
        direction TB
        R1["collect_reports\nPDF → RAPTOR L0/L1/L2"]
        R2["fetch_news\n4개 소스 뉴스"]
        R3["extract_issues\n이슈 카테고리 추출"]
        R1 --> R3
        R2 --> R3
    end

    subgraph RAG["ChromaDB (RAG Store)"]
        DB1[(reports\nL0/L1/L2)]
        DB2[(news)]
        DB3[(issues)]
    end

    R3 --> RAG

    subgraph A["② ANALYST GRAPH"]
        direction TB
        A1["assess_data\n데이터 품질 점수"]
        A2["extract_thesis\n투자 thesis 추출"]
        A3["build_toc\nTOC 초안 생성\n(iteration++)"]
        A4{"_route_after_build\niteration ≥ max_retries?"}
        A5["review_toc\nLLM 자동 검토"]
        A6{"_route_review\napproved?"}
        A7["human_toc\n⚡ HITL INTERRUPT"]
        A8{"_route_human\nok / 변경?"}
        A9["plan_sections\n섹션 계획 + seed"]

        A1 --> A2 --> A3 --> A4
        A4 -- "No" --> A5
        A4 -- "Yes (skip)" --> A7
        A5 --> A6
        A6 -- "Yes" --> A7
        A6 -- "No" --> A3
        A7 --> A8
        A8 -- "승인" --> A9
        A8 -- "수정 요청" --> A3
    end

    RAG --> A

    subgraph W["③ WRITER GRAPH"]
        direction TB
        W1["write_sections\nRAG + LLM 섹션 작성"]
        W2["assemble_report\nMarkdown 조합"]
        W3["save_report\n파일 저장"]
        W1 --> W2 --> W3
    end

    A9 --> W
    RAG --> W

    W3 --> OUT["📄 report_output/{ticker}/\n{date}_{company}_report.md"]
데이터 플로우

flowchart LR
    RS["ResearcherState\n• report_chunks\n• news_chunks\n• issues"]
    AS["AnalystState\n• toc\n• thesis_list\n• section_plans\n• global_context_seed"]
    WS["WriterState\n• written_sections\n• report_markdown\n• output_path"]

    RS --> AS --> WS
Analyst 상세 제어 흐름

stateDiagram-v2
    [*] --> assess_data
    assess_data --> extract_thesis
    extract_thesis --> build_toc

    build_toc --> route_build: iteration++

    state route_build <<choice>>
    route_build --> review_toc: iteration < max_retries
    route_build --> human_toc: iteration ≥ max_retries\n(강제 통과)

    review_toc --> route_review

    state route_review <<choice>>
    route_review --> human_toc: approved = True
    route_review --> build_toc: approved = False\n(feedback 주입)

    human_toc --> route_human: ⚡ INTERRUPT\n(stdin 대기)

    state route_human <<choice>>
    route_human --> plan_sections: "ok" / "승인"
    route_human --> build_toc: 수정 요청\n(feedback 주입)

    plan_sections --> [*]
주요 설계 포인트:

RAPTOR: PDF 원문(L0) → 청크 요약(L1) → 전체 요약(L2) 계층적 색인
HITL 우회: --no-hitl 또는 --toc-retries 초과 시 자동 승인
RAG 조건부 트리거: 섹션 tone에 따라 news/issues 검색 추가
MemorySaver: 각 그래프가 독립적인 thread_id로 체크포인트 유지
