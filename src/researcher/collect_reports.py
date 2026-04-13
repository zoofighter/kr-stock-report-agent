"""
collect_reports.py — PDF 리포트 수집 및 RAPTOR 계층 청킹

역할:
  - REPORT_DIR 하위 폴더에서 종목별 PDF 파일을 읽어 텍스트를 추출한다.
  - 추출된 텍스트를 3단계 RAPTOR 계층으로 변환해 ChromaDB(reports 컬렉션)에 저장한다.

RAPTOR 계층:
  L0 (원문 청크) : 800자 단위로 분할한 원문. 수치·사실 인용에 사용.
  L1 (중간 요약) : L0 청크 5개를 묶어 LLM이 3~5문장으로 요약. 논거 검색에 사용.
  L2 (전체 요약) : 모든 L1 요약을 종합한 2~3문장 투자 논지. thesis 추출에 사용.

처리 흐름:
  PDF 파일 → extract_text_without_tables() → make_chunks() (L0)
           → build_raptor() (L1, L2) → upsert_chunks() → ChromaDB 저장
"""

import re
import hashlib
from pathlib import Path
from datetime import datetime

import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.models.llm import get_small_llm
from src.researcher.rag_store import upsert_chunks, count_by_ticker
from src.state import ResearcherState, REPORT_DIR, COMPANY_KEYWORDS

CHUNK_SIZE    = 800   # L0 청크 최대 글자 수
CHUNK_OVERLAP = 100   # 청크 간 중복 글자 수 (문맥 연속성 유지)
CLUSTER_SIZE  = 5     # L1 요약 단위: L0 청크 몇 개씩 묶을지


def extract_date_from_filename(filename: str) -> str:
    """
    파일명에서 리포트 발행일을 추출한다.
    파일명 패턴: YY.MM.DD_종목명_증권사_...
    예: 26.04.08_삼성전자_키움증권_너무 좋아도 걱정.pdf → 2026-04-08
    날짜 패턴이 없으면 오늘 날짜를 반환한다.
    """
    match = re.search(r'(\d{2})\.(\d{2})\.(\d{2})', filename)
    if match:
        yy, mm, dd = match.group(1), match.group(2), match.group(3)
        return f"20{yy}-{mm}-{dd}"
    return datetime.today().strftime("%Y-%m-%d")


def extract_text_without_tables(pdf_path: str) -> list[dict]:
    """
    PDF 페이지에서 텍스트를 추출하되, 표(table) 영역은 제외한다.
    표 데이터는 수식·숫자 나열이 많아 LLM 컨텍스트 품질을 떨어뜨리므로 필터링한다.

    반환: [{"text": str, "page": int}, ...]  (빈 페이지 제외)
    """
    pages_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            # 표 bbox 목록 추출
            table_bboxes = [t.bbox for t in page.find_tables()]

            if table_bboxes:
                # 표 영역에 속하는 문자 객체 제거
                filtered = page.filter(
                    lambda obj: not any(
                        obj.get("x0", 0) >= bbox[0]
                        and obj.get("x1", 0) <= bbox[2]
                        and obj.get("top", 0) >= bbox[1]
                        and obj.get("bottom", 0) <= bbox[3]
                        for bbox in table_bboxes
                    )
                )
                text = filtered.extract_text() or ""
            else:
                text = page.extract_text() or ""

            text = text.strip()
            if text:
                pages_data.append({"text": text, "page": page_num})

    return pages_data


def load_reports(ticker: str) -> list[dict]:
    """
    REPORT_DIR/{회사명}/ 폴더에서 해당 종목의 PDF 파일을 모두 읽는다.
    COMPANY_KEYWORDS로 ticker → 폴더명을 매핑한다.

    반환: [{"text", "source", "published_date", "page", "ticker"}, ...]
    """
    company_keyword = COMPANY_KEYWORDS[ticker]
    company_dir = Path(REPORT_DIR) / company_keyword
    raw_docs = []

    if not company_dir.exists():
        print(f"  [WARN] 폴더 없음: {company_dir}")
        return []

    matched = sorted(company_dir.glob("*.pdf"))
    print(f"  [{company_keyword}] 매칭 파일: {len(matched)}개")

    for pdf_path in matched:
        try:
            pub_date = extract_date_from_filename(pdf_path.name)
            pages = extract_text_without_tables(str(pdf_path))

            for page_data in pages:
                raw_docs.append({
                    "text":           page_data["text"],
                    "source":         pdf_path.name,
                    "published_date": pub_date,
                    "page":           page_data["page"],
                    "ticker":         ticker,
                })
        except Exception as e:
            print(f"  [WARN] {pdf_path.name} 파싱 실패: {e}")

    return raw_docs


def make_chunks(raw_docs: list[dict], ticker: str) -> list[dict]:
    """
    Level 0 청크 생성: 페이지 텍스트를 CHUNK_SIZE(800자) 단위로 분할한다.
    id는 source·page·위치·내용 앞 20자의 MD5 해시로 생성해 중복 삽입을 방지한다.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " "],
    )
    chunks = []
    for doc in raw_docs:
        parts = splitter.split_text(doc["text"])
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            chunk_id = hashlib.md5(
                f"{doc['source']}_{doc['page']}_{i}_{part[:20]}".encode()
            ).hexdigest()[:16]

            chunks.append({
                "id":   f"l0_{ticker}_{chunk_id}",
                "text": part,
                "metadata": {
                    "ticker":             ticker,
                    "source":             doc["source"],
                    "published_date":     doc["published_date"],
                    "page":               doc["page"],
                    "raptor_level":       0,
                    "source_reliability": 1.0,
                },
            })
    return chunks


def summarize_cluster(texts: list[str], llm) -> str:
    """
    L0 청크 CLUSTER_SIZE개를 하나로 묶어 LLM으로 중간 요약(Level 1)을 생성한다.
    핵심 수치(영업이익, 목표주가, 성장률 등)를 반드시 포함하도록 프롬프트에 명시한다.
    """
    joined = "\n\n".join(texts)
    prompt = (
        "다음 증권사 리포트 내용을 3~5문장으로 요약하세요.\n"
        "핵심 수치(영업이익, 목표주가, 성장률 등)를 반드시 포함하세요.\n\n"
        f"[내용]\n{joined}\n\n요약:"
    )
    return llm.invoke(prompt).content.strip()


def summarize_all(level1_texts: list[str], llm) -> str:
    """
    모든 L1 요약을 종합해 리포트 전체의 투자 논지를 2~3문장으로 압축한다 (Level 2).
    extract_thesis 노드에서 thesis 추출의 최상위 컨텍스트로 사용된다.
    """
    joined = "\n\n".join(level1_texts)
    prompt = (
        "다음 리포트 요약들을 종합하여 전체 투자 논지를 2~3문장으로 작성하세요.\n\n"
        f"[요약 목록]\n{joined}\n\n전체 요약:"
    )
    return llm.invoke(prompt).content.strip()


def build_raptor(chunks: list[dict], ticker: str) -> tuple[list[dict], list[dict]]:
    """
    L0 청크로부터 RAPTOR L1/L2 계층을 생성한다.

    L1: L0 청크를 CLUSTER_SIZE(5)개씩 그룹화 → LLM 중간 요약
        published_date = 그룹 내 L0 청크의 최신 날짜
        child_ids = 하위 L0 청크 id 목록 (추적용)

    L2: 모든 L1 요약을 한 번 더 요약한 단일 청크 (리포트 전체 논지)
        published_date = 오늘 날짜 (생성 시점)

    반환: (level1_chunks, level2_chunks)
    """
    llm = get_small_llm()
    level1_chunks, level1_texts = [], []

    l0_texts = [c["text"] for c in chunks]
    for i in range(0, len(l0_texts), CLUSTER_SIZE):
        cluster = l0_texts[i: i + CLUSTER_SIZE]
        if not cluster:
            continue

        summary = summarize_cluster(cluster, llm)
        child_ids = [chunks[j]["id"] for j in range(i, min(i + CLUSTER_SIZE, len(chunks)))]

        # L1의 published_date = 하위 L0 청크 중 가장 최신 날짜
        latest_date = max(
            chunks[j]["metadata"]["published_date"]
            for j in range(i, min(i + CLUSTER_SIZE, len(chunks)))
        )

        # 클러스터 내 L0 청크들의 source 목록 (중복 제거, 순서 유지)
        sources_in_cluster = list(dict.fromkeys(
            chunks[j]["metadata"].get("source", "unknown")
            for j in range(i, min(i + CLUSTER_SIZE, len(chunks)))
        ))
        # 클러스터가 단일 소스면 그대로, 여러 소스에 걸치면 대표 소스(첫 번째) 사용
        representative_source = sources_in_cluster[0]

        level1_chunks.append({
            "id":   f"l1_{ticker}_{i:05d}",
            "text": summary,
            "metadata": {
                "ticker":             ticker,
                "raptor_level":       1,
                "child_ids":          str(child_ids),
                "source":             representative_source,
                "source_reliability": 1.0,
                "published_date":     latest_date,
            },
        })
        level1_texts.append(summary)

    level2_chunks = []
    if level1_texts:
        top_summary = summarize_all(level1_texts, llm)
        level2_chunks.append({
            "id":   f"l2_{ticker}_top",
            "text": top_summary,
            "metadata": {
                "ticker":             ticker,
                "raptor_level":       2,
                "child_ids":          str([c["id"] for c in level1_chunks]),
                "source_reliability": 1.0,
                "published_date":     datetime.today().strftime("%Y-%m-%d"),
            },
        })

    return level1_chunks, level2_chunks


def collect_reports(state: ResearcherState) -> dict:
    """
    Researcher 그래프 노드: collect_reports

    처리 순서:
      1. ChromaDB에 해당 ticker 청크가 이미 있으면 재처리 없이 캐시에서 반환 (멱등성)
      2. PDF 로드 → L0 청크 생성 → RAPTOR L1/L2 생성 → ChromaDB 저장

    반환 키:
      report_chunks : L0 + L1 + L2 전체 청크 (애널리스트·라이터가 RAG로 검색)
      raptor_chunks : report_chunks와 동일 (상태 호환용 별칭)
      report_date   : L0 청크 중 가장 최신 published_date (리포트 기준일)
      raw_texts     : 원본 페이지 텍스트 (캐시 히트 시 빈 리스트)
      parse_errors  : PDF 파싱 실패 파일 목록
    """
    ticker       = state["ticker"]
    company_name = state["company_name"]
    print(f"[collect_reports] {company_name} ({ticker}) 시작")

    # 이미 처리된 종목이면 ChromaDB에서 불러와 스킵
    existing_count = count_by_ticker("reports", ticker)
    if existing_count > 0:
        print(f"  이미 처리됨 ({existing_count}개 청크) — 스킵")
        from src.researcher.rag_store import get_collection
        col = get_collection("reports")
        rows = col.get(where={"ticker": {"$eq": ticker}}, include=["documents", "metadatas"])
        cached_chunks = [
            {"id": id_, "text": doc, "metadata": meta}
            for id_, doc, meta in zip(rows["ids"], rows["documents"], rows["metadatas"])
        ]
        latest_date = max(
            (c["metadata"].get("published_date", "") for c in cached_chunks if c["metadata"].get("raptor_level") == 0),
            default=""
        )
        return {
            "report_chunks": cached_chunks,
            "raptor_chunks": cached_chunks,
            "report_date":   latest_date,
            "raw_texts":     [],
            "parse_errors":  [],
        }

    raw_docs = load_reports(ticker)
    if not raw_docs:
        print(f"  [WARN] {ticker}: 리포트 파일 없음")
        return {"parse_errors": [f"{ticker}: 리포트 없음"], "report_chunks": [],
                "raptor_chunks": [], "raw_texts": [], "report_date": ""}

    # Level 0
    l0_chunks = make_chunks(raw_docs, ticker)
    print(f"  Level 0 청크: {len(l0_chunks)}개")

    # RAPTOR Level 1/2
    l1_chunks, l2_chunks = build_raptor(l0_chunks, ticker)
    print(f"  Level 1 요약: {len(l1_chunks)}개 / Level 2 요약: {len(l2_chunks)}개")

    all_chunks = l0_chunks + l1_chunks + l2_chunks

    # ChromaDB 저장
    saved = upsert_chunks("reports", all_chunks)
    print(f"  RAG 저장 완료: {saved}개 → {state['ticker']} @ /Users/boon/report_db")

    # 가장 최신 리포트 날짜
    latest_date = max(c["metadata"]["published_date"] for c in l0_chunks)

    return {
        "report_chunks": all_chunks,
        "raptor_chunks": all_chunks,
        "report_date":   latest_date,
        "raw_texts":     raw_docs,
        "parse_errors":  [],
    }
