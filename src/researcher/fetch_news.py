import os
import time
import hashlib
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
import feedparser
from dotenv import load_dotenv

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
            pub = _parse_date(item.get("postdate", ""))
            results.append({
                "id":             _news_id(ticker, "naver_blog", item.get("link", ""), i),
                "title":          title,
                "url":            item.get("link", ""),
                "summary":        content,
                "source":         "naver_blog",
                "source_name":    "Naver블로그",
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


def fetch_news(state: ResearcherState) -> dict:
    """
    Researcher 노드: fetch_news
    4개 소스 병렬 수집 → 중복 제거 → ChromaDB news 저장
    """
    ticker       = state["ticker"]
    company_name = state["company_name"]
    query        = f"{company_name} 주가 실적"

    print(f"[fetch_news] {company_name} ({ticker}) 시작")

    # 4개 소스 수집
    naver_news = search_naver_news(query, ticker)
    naver_blog = search_naver_blog(query, ticker)
    google     = search_google_news(query, ticker)
    ddg        = search_ddg(query, ticker)

    print(f"  Naver뉴스={len(naver_news)} Google={len(google)} DDG={len(ddg)} 블로그={len(naver_blog)}")

    # 병합 + 중복 제거
    all_items = naver_news + google + ddg + naver_blog
    deduped   = deduplicate(all_items)

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
            },
        })

    saved = upsert_chunks("news", chunks)
    print(f"  news 저장: {saved}개")

    return {"news_chunks": chunks}
