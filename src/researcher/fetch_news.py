import json
import os
import time
import hashlib
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
import feedparser
from dotenv import load_dotenv

from src.models.llm import get_small_llm
from src.researcher.rag_store import upsert_chunks
from src.state import ResearcherState, COMPANY_KEYWORDS

load_dotenv()

NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

SPAM_KEYWORDS = ["협찬", "광고", "유료광고", "제품 제공", "리뷰 이벤트",
                 "무료체험", "체험단", "원고료", "소정의"]

SOURCE_RELIABILITY = {
    "naver_news": 0.85,
    "google_news": 0.80,
    "ddg":        0.75,
    "naver_blog": 0.50,
}


def _naver_headers() -> dict:
    return {
        "X-Naver-Client-Id":     NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }


def _parse_date(date_str: str) -> str:
    """다양한 날짜 형식 → YYYY-MM-DD"""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y%m%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return datetime.today().strftime("%Y-%m-%d")


def _news_id(ticker: str, source: str, url: str, idx: int) -> str:
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    date = datetime.today().strftime("%Y%m%d")
    return f"news_{ticker}_{date}_{source}_{h}"


def search_naver_news(query: str, ticker: str) -> list[dict]:
    """Naver 뉴스 API"""
    if not NAVER_CLIENT_ID:
        return []
    try:
        url = "https://openapi.naver.com/v1/search/news.json"
        params = {"query": query, "display": 20, "sort": "date"}
        resp = requests.get(url, headers=_naver_headers(), params=params, timeout=5)
        items = resp.json().get("items", [])
        results = []
        for i, item in enumerate(items):
            pub = _parse_date(item.get("pubDate", ""))
            results.append({
                "id":             _news_id(ticker, "naver_news", item.get("originallink", item.get("link", "")), i),
                "title":          item.get("title", "").replace("<b>", "").replace("</b>", ""),
                "url":            item.get("originallink") or item.get("link", ""),
                "summary":        item.get("description", "").replace("<b>", "").replace("</b>", ""),
                "source":         "naver_news",
                "source_name":    "Naver뉴스",
                "published_date": pub,
                "ticker":         ticker,
                "reliability":    SOURCE_RELIABILITY["naver_news"],
            })
        return results
    except Exception as e:
        print(f"  [WARN] Naver 뉴스 수집 실패: {e}")
        return []


def search_naver_blog(query: str, ticker: str) -> list[dict]:
    """Naver 블로그 API"""
    if not NAVER_CLIENT_ID:
        return []
    try:
        url = "https://openapi.naver.com/v1/search/blog.json"
        params = {"query": query, "display": 10, "sort": "date"}
        resp = requests.get(url, headers=_naver_headers(), params=params, timeout=5)
        items = resp.json().get("items", [])
        results = []
        for i, item in enumerate(items):
            title   = item.get("title", "").replace("<b>", "").replace("</b>", "")
            content = item.get("description", "").replace("<b>", "").replace("</b>", "")
            if len(content) < 100:
                continue
            if any(kw in title + content for kw in SPAM_KEYWORDS):
                continue
            pub          = _parse_date(item.get("postdate", ""))
            blogger_name = item.get("bloggername", "").strip() or "Naver블로그"
            blogger_url  = item.get("bloggerlink", "").strip()
            results.append({
                "id":             _news_id(ticker, "naver_blog", item.get("link", ""), i),
                "title":          title,
                "url":            item.get("link", ""),
                "summary":        content,
                "source":         "naver_blog",
                "source_name":    f"Naver블로그({blogger_name})",
                "blogger_name":   blogger_name,
                "blogger_url":    blogger_url,
                "published_date": pub,
                "ticker":         ticker,
                "reliability":    SOURCE_RELIABILITY["naver_blog"],
            })
        return results
    except Exception as e:
        print(f"  [WARN] Naver 블로그 수집 실패: {e}")
        return []


def search_google_news(query: str, ticker: str) -> list[dict]:
    """Google News RSS (API 키 불필요)"""
    try:
        encoded = quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(rss_url)
        results = []
        for i, entry in enumerate(feed.entries[:20]):
            pub = _parse_date(entry.get("published", ""))
            results.append({
                "id":             _news_id(ticker, "google_news", entry.get("link", ""), i),
                "title":          entry.get("title", ""),
                "url":            entry.get("link", ""),
                "summary":        entry.get("summary", "")[:300],
                "source":         "google_news",
                "source_name":    entry.get("source", {}).get("title", "Google뉴스"),
                "published_date": pub,
                "ticker":         ticker,
                "reliability":    SOURCE_RELIABILITY["google_news"],
            })
        return results
    except Exception as e:
        print(f"  [WARN] Google 뉴스 수집 실패: {e}")
        return []


def search_ddg(query: str, ticker: str) -> list[dict]:
    """DuckDuckGo 뉴스"""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            items = list(ddgs.news(
                keywords=query,
                region="kr-ko",
                safesearch="off",
                timelimit="m",
                max_results=15,
            ))
        time.sleep(0.5)
        for i, item in enumerate(items):
            pub = _parse_date(item.get("date", ""))
            results.append({
                "id":             _news_id(ticker, "ddg", item.get("url", ""), i),
                "title":          item.get("title", ""),
                "url":            item.get("url", ""),
                "summary":        item.get("body", "")[:300],
                "source":         "ddg",
                "source_name":    item.get("source", "DuckDuckGo"),
                "published_date": pub,
                "ticker":         ticker,
                "reliability":    SOURCE_RELIABILITY["ddg"],
            })
        return results
    except Exception as e:
        print(f"  [WARN] DDG 수집 실패: {e}")
        return []


def deduplicate(items: list[dict]) -> list[dict]:
    """URL 기준 중복 제거. 신뢰도 높은 소스 우선 보존."""
    seen, result = set(), []
    # 신뢰도 높은 순서로 정렬 후 중복 제거
    items.sort(key=lambda x: x.get("reliability", 0), reverse=True)
    for item in items:
        url = item.get("url", "").split("?")[0].lower()
        if url and url not in seen:
            seen.add(url)
            result.append(item)
    return result


def _blog_queries_from_l2(l2_text: str, company_name: str, ticker: str, sector: str, llm) -> list[str]:
    """
    RAPTOR L2 요약에서 블로그 전용 검색어 3개를 생성한다.
    뉴스 쿼리와 달리 개인 투자자 시각(주가 전망, 재무 분석, 투자 의견)에 특화.
    파싱 실패 시 기본 쿼리로 폴백.
    """
    prompt = (
        f"다음은 {company_name}({ticker}, {sector}) 리포트의 전체 요약입니다.\n"
        "이 내용을 바탕으로 네이버 블로그 검색에 사용할 한국어 검색어 3개를 JSON 배열로만 출력하세요.\n"
        "블로그는 개인 투자자가 작성하므로, 아래 관점을 각각 커버해야 합니다:\n"
        "- 주가 전망 및 목표주가 분석\n"
        "- 재무제표·실적 분석 (영업이익, 매출, 밸류에이션)\n"
        "- 투자 의견·리스크 및 매수·매도 근거\n\n"
        f"[리포트 요약]\n{l2_text}\n\n"
        '["검색어1", "검색어2", "검색어3"]'
    )
    try:
        raw = llm.invoke(prompt).content.strip()
        start, end = raw.find("["), raw.rfind("]") + 1
        queries = json.loads(raw[start:end])
        if isinstance(queries, list) and queries:
            return queries
    except Exception:
        pass
    return [f"{company_name} 주가 전망 분석"]  # 폴백


def _queries_from_l2(l2_text: str, company_name: str, ticker: str, sector: str, llm) -> list[str]:
    """
    RAPTOR L2 전체 요약 텍스트에서 뉴스 검색어 4개를 추출한다.
    실적 / 시장동향 / 리스크 / 촉매 관점을 각각 커버하도록 LLM에 요청.
    파싱 실패 시 기본 쿼리로 폴백.
    """
    prompt = (
        f"다음은 {company_name}({ticker}, {sector}) 리포트의 전체 요약입니다.\n"
        "이 내용을 바탕으로 최신 뉴스 검색에 사용할 한국어 검색어 4개를 JSON 배열로만 출력하세요.\n"
        "각 검색어는 아래 관점을 하나씩 커버해야 합니다: 실적·매출, 시장·섹터 동향, 리스크·경쟁, 단기 촉매 이벤트.\n\n"
        f"[리포트 요약]\n{l2_text}\n\n"
        '["검색어1", "검색어2", "검색어3", "검색어4"]'
    )
    try:
        raw = llm.invoke(prompt).content.strip()
        start, end = raw.find("["), raw.rfind("]") + 1
        queries = json.loads(raw[start:end])
        if isinstance(queries, list) and queries:
            return queries
    except Exception:
        pass
    return [f"{company_name} 주가 실적"]  # 폴백


def fetch_news(state: ResearcherState) -> dict:
    """
    Researcher 노드: fetch_news  (collect_reports 완료 후 실행)

    L2 청크(전체 투자 논지 요약)가 있으면 LLM으로 관점별 검색어 4개를 생성하고
    각 쿼리로 4개 소스를 수집한다. L2가 없으면 기본 쿼리로 폴백.
    수집 후 중복 제거 → 90일 필터 → ChromaDB news 저장.
    """
    ticker       = state["ticker"]
    company_name = state["company_name"]
    sector       = state["sector"]

    print(f"[fetch_news] {company_name} ({ticker}) 시작")

    # L2 청크에서 검색어 생성
    l2_chunks = [
        c for c in state.get("report_chunks", [])
        if c.get("metadata", {}).get("raptor_level") == 2
    ]
    if l2_chunks:
        llm     = get_small_llm()
        queries = _queries_from_l2(l2_chunks[0]["text"], company_name, ticker, sector, llm)
        print(f"  L2 기반 쿼리: {queries}")
    else:
        queries = [f"{company_name} 주가 실적"]
        print(f"  L2 없음 — 기본 쿼리 사용: {queries}")

    # 블로그 전용 쿼리 생성 (개인 투자자 시각: 주가전망·재무분석·투자의견)
    if l2_chunks:
        blog_queries = _blog_queries_from_l2(l2_chunks[0]["text"], company_name, ticker, sector, llm)
        print(f"  블로그 쿼리: {blog_queries}")
    else:
        blog_queries = [f"{company_name} 주가 전망 분석"]

    # 뉴스/구글/DDG: L2 기반 쿼리 4개, 블로그: 전용 쿼리 3개
    all_items = []
    for query in queries:
        all_items += search_naver_news(query, ticker)
        all_items += search_google_news(query, ticker)
        all_items += search_ddg(query, ticker)
    for query in blog_queries:
        all_items += search_naver_blog(query, ticker)

    naver_news_count = sum(1 for i in all_items if i.get("source") == "naver_news")
    google_count     = sum(1 for i in all_items if i.get("source") == "google_news")
    ddg_count        = sum(1 for i in all_items if i.get("source") == "ddg")
    blog_count       = sum(1 for i in all_items if i.get("source") == "naver_blog")
    print(f"  수집(중복 전): Naver뉴스={naver_news_count} Google={google_count} DDG={ddg_count} 블로그={blog_count}")

    # 중복 제거
    deduped = deduplicate(all_items)

    # 최신 90일 이내만 유지
    cutoff = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    deduped = [i for i in deduped if i.get("published_date", "9999") >= cutoff]

    print(f"  중복 제거 후: {len(deduped)}개")

    # ChromaDB 저장
    collected_date = datetime.today().strftime("%Y-%m-%d")
    chunks = []
    for item in deduped:
        text = f"{item['title']} — {item['summary']}"
        chunks.append({
            "id":   item["id"],
            "text": text,
            "metadata": {
                "ticker":           ticker,
                "source":           item["source"],
                "source_name":      item["source_name"],
                "url":              item["url"],
                "title":            item["title"],
                "published_date":   item["published_date"],
                "collected_date":   collected_date,
                "reliability":      item["reliability"],
                # 블로그 전용 필드 (naver_blog 소스만 값 있음, 나머지는 빈 문자열)
                "blogger_name":     item.get("blogger_name", ""),
                "blogger_url":      item.get("blogger_url", ""),
            },
        })

    saved = upsert_chunks("news", chunks)
    print(f"  news 저장: {saved}개")

    return {"news_chunks": chunks}
