# Naver 블로그 — 중요 투자 블로그 500개 리스트 구축 설계

작성일: 2026-04-14

---

## 1. 목표

Naver Blog API와 LangGraph를 사용해 **투자 분석 가치가 있는 블로그 500개** 리스트를 구축한다.

단순 랭킹이 아니라 **"이 파이프라인에서 참고할 만한 블로그"** 를 선별하는 것이 목적이다.  
선별된 블로그는 이후 뉴스 수집 시 우선 소스로 활용한다.

---

## 2. "중요 투자 블로그"의 정의

아래 조건을 모두 만족해야 리스트에 포함된다.

| 조건 | 기준 |
|------|------|
| **투자 전문성** | 본문에 수치(영업이익, PER, 목표주가 등) 또는 분석 키워드 포함 |
| **최신 활동** | 최근 90일 이내 포스팅 존재 |
| **최소 분량** | 포스팅 본문 평균 300자 이상 |
| **스팸 아님** | 광고·협찬·체험단 키워드 없음 |
| **개인 분석** | 단순 뉴스 복사가 아닌 자체 분석 포함 |

---

## 3. Naver Blog API 수집 가능 범위

| 파라미터 | 제한값 |
|---------|--------|
| `display` | 1회 호출당 최대 100건 |
| `start` | 최대 1,000 (페이지네이션) |
| 하루 호출 한도 | 25,000회 (무료) |

**500개 선별을 위한 수집 전략**:

```
쿼리 10개 × display 100 = 1,000건 (원시 수집)
  ↓ URL 중복 제거
유니크 포스팅: 약 600~800건
  ↓ 블로거 단위 집계
유니크 블로거: 약 300~500명
  ↓ 선별 조건 적용
최종 리스트: 목표 500개
```

수집 쿼리가 부족할 경우 쿼리를 15~20개로 늘려 원시 수집량을 확보한다.

---

## 4. 쿼리 생성 전략

LLM이 **투자 분석 관점 10개**를 커버하는 쿼리를 생성한다.

```
실적 분석     : "삼성전자 영업이익 실적 분석"
목표주가      : "삼성전자 목표주가 증권사 리포트"
밸류에이션    : "삼성전자 PER PBR 저평가 분석"
섹터 동향     : "반도체 AI 수요 전망 2026"
리스크        : "삼성전자 HBM 경쟁 리스크 분석"
경쟁사 비교   : "삼성전자 SK하이닉스 비교"
배당·주주환원 : "삼성전자 배당 자사주 소각"
매수 타이밍   : "삼성전자 매수 시점 분석"
뉴스 반응     : "삼성전자 실적 발표 투자 의견"
장기 전망     : "삼성전자 2027 장기 성장 전망"
```

---

## 5. LangGraph 구현 설계

### 5-1. State 정의

```python
class BlogListState(TypedDict):
    company_name:  str
    ticker:        str
    sector:        str
    queries:       list[str]      # LLM 생성 쿼리
    raw_posts:     list[dict]     # 수집된 원시 포스팅
    unique_posts:  list[dict]     # 중복 제거 후 포스팅
    blogger_map:   dict           # {blogger_url: 블로거 정보 + 포스팅 목록}
    blog_list:     list[dict]     # 최종 선별된 블로그 리스트
```

### 5-2. 그래프 구조

```
START
  ↓
generate_queries      LLM으로 10개 관점별 쿼리 생성
  ↓
collect_posts         Naver Blog API 수집 (쿼리별 100건)
  ↓
deduplicate           URL 기준 중복 포스팅 제거
  ↓
aggregate_bloggers    블로거 단위로 포스팅 집계
  ↓
filter_blogs          선별 조건 적용 → 중요 블로그 판별
  ↓
save_blog_list        CSV + ChromaDB 저장
  ↓
END
```

### 5-3. 핵심 노드

#### `generate_queries`

```python
def generate_queries(state: BlogListState) -> dict:
    prompt = f"""
{state['company_name']}({state['ticker']}) 투자 분석 블로그를
네이버에서 찾기 위한 검색 쿼리 10개를 생성하세요.

각 쿼리는 서로 다른 분석 관점을 커버해야 합니다:
실적·목표주가·밸류에이션·리스크·섹터동향·비교분석·배당·매수타이밍·뉴스반응·장기전망

JSON 배열로만 출력: ["쿼리1", "쿼리2", ...]
"""
    # LLM 호출 → JSON 파싱
    return {"queries": queries}
```

#### `collect_posts`

```python
def collect_posts(state: BlogListState) -> dict:
    all_posts = []
    for query in state["queries"]:
        items = naver_blog_search(query, display=100, sort="date")
        for item in items:
            item["query"] = query          # 어떤 쿼리에서 수집됐는지 태깅
        all_posts.extend(items)
        time.sleep(0.3)                    # API 과호출 방지
    return {"raw_posts": all_posts}
```

#### `aggregate_bloggers`

```python
def aggregate_bloggers(state: BlogListState) -> dict:
    blogger_map = {}
    for post in state["unique_posts"]:
        url  = post["blogger_url"]
        name = post["blogger_name"]
        if url not in blogger_map:
            blogger_map[url] = {
                "blogger_url":  url,
                "blogger_name": name,
                "posts":        [],
                "queries_hit":  set(),    # 몇 가지 쿼리에서 검색됐는지
            }
        blogger_map[url]["posts"].append(post)
        blogger_map[url]["queries_hit"].add(post["query"])
    return {"blogger_map": blogger_map}
```

#### `filter_blogs` — 선별 조건 적용

```python
INVEST_KEYWORDS = [
    "주가", "목표주가", "영업이익", "매출", "PER", "PBR", "ROE", "EPS",
    "실적", "배당", "밸류에이션", "매수", "매도", "리포트", "애널리스트",
    "포트폴리오", "수익률", "증권사", "투자의견", "재무제표"
]

SPAM_KEYWORDS = [
    "협찬", "광고", "유료광고", "체험단", "원고료", "소정의", "제품 제공"
]

def filter_blogs(state: BlogListState) -> dict:
    blog_list = []
    cutoff_90d = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")

    for url, data in state["blogger_map"].items():
        posts = data["posts"]

        # 조건 1: 최근 90일 이내 포스팅 존재
        recent = [p for p in posts if p.get("published_date", "") >= cutoff_90d]
        if not recent:
            continue

        # 조건 2: 스팸 필터
        text_all = " ".join(p.get("title", "") + p.get("summary", "") for p in posts)
        if any(kw in text_all for kw in SPAM_KEYWORDS):
            continue

        # 조건 3: 투자 키워드 포함
        invest_hit = sum(1 for kw in INVEST_KEYWORDS if kw in text_all)
        if invest_hit < 3:                 # 최소 3개 키워드 이상
            continue

        # 조건 4: 평균 본문 길이 300자 이상
        avg_len = sum(len(p.get("summary", "")) for p in posts) / len(posts)
        if avg_len < 300:
            continue

        # 통과 → 리스트에 추가
        blog_list.append({
            "blogger_url":    url,
            "blogger_name":   data["blogger_name"],
            "post_count":     len(posts),
            "recent_count":   len(recent),
            "queries_hit":    len(data["queries_hit"]),
            "invest_keywords": invest_hit,
            "avg_length":     int(avg_len),
            "latest_date":    max(p.get("published_date", "") for p in posts),
            "sample_titles":  [p["title"] for p in posts[:3]],
        })

    return {"blog_list": blog_list}
```

#### `save_blog_list`

```python
def save_blog_list(state: BlogListState) -> dict:
    blog_list = state["blog_list"]
    ticker    = state["ticker"]
    today     = datetime.today().strftime("%Y%m%d")

    # CSV 저장
    csv_path = f"report_output/{ticker}/{today}_blog_list.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "blogger_name", "blogger_url", "post_count",
            "recent_count", "queries_hit", "invest_keywords",
            "avg_length", "latest_date"
        ])
        writer.writeheader()
        writer.writerows(blog_list)

    # ChromaDB 저장 (bloggers 컬렉션)
    chunks = [{
        "id":   f"blogger_{b['blogger_url'].replace('/', '_')}",
        "text": f"{b['blogger_name']} — {', '.join(b['sample_titles'])}",
        "metadata": {
            "ticker":       ticker,
            "blogger_url":  b["blogger_url"],
            "blogger_name": b["blogger_name"],
            "post_count":   b["post_count"],
            "latest_date":  b["latest_date"],
        }
    } for b in blog_list]
    upsert_chunks("bloggers", chunks)

    print(f"중요 투자 블로그 선별: {len(blog_list)}개 → {csv_path}")
    return {}
```

---

## 6. 출력 형태

### CSV (blog_list.csv)

```csv
blogger_name,blogger_url,post_count,recent_count,queries_hit,invest_keywords,avg_length,latest_date
시그널 필터,blog.naver.com/flaneur_jy,12,8,6,14,420,2026-04-14
학습인,blog.naver.com/kwangpoong,9,7,5,11,380,2026-04-14
흑호의 주식인사이트,blog.naver.com/dividendtiger,7,5,4,9,350,2026-04-13
...
```

### ChromaDB (bloggers 컬렉션)

선별된 블로거를 저장해두면 이후 `fetch_news`에서 우선 검색 소스로 활용 가능하다.

---

## 7. 실현 가능성

| 항목 | 평가 | 비고 |
|------|------|------|
| 500개 블로그 선별 | ⚠️ 종목에 따라 다름 | 인기 종목(삼성전자)은 가능, 소형주는 어려울 수 있음 |
| API 비용 | ✅ 무료 | 하루 25,000 호출 |
| 수집 시간 | ✅ 30~60초 | 쿼리 10개 × 1회 호출 |
| 선별 정확도 | ✅ 높음 | 키워드 기반 필터라 명확 |
| 소형주 적용 | ⚠️ 어려움 | 검색 결과 자체가 적음 |

**종목별 예상 선별 수**:

| 종목 유형 | 원시 수집 | 선별 후 |
|----------|----------|--------|
| 대형주 (삼성전자, SK하이닉스) | 800~1,000건 | 300~500개 블로거 |
| 중형주 (NAVER, 현대차) | 400~600건 | 150~300개 블로거 |
| 소형주 | 100~300건 | 50~150개 블로거 |

→ **소형주는 단일 종목 쿼리만으론 500개 달성이 어려울 수 있음**  
→ 섹터 쿼리 추가 (예: "코스닥 바이오 투자 분석")로 보완 가능

---

## 8. 현재 파이프라인 통합 방안

### 독립 스크립트로 먼저 구현

```bash
python src/researcher/blog_list_builder.py --ticker 005930
```

### 이후 Researcher 그래프 통합

선별된 블로그 리스트를 `fetch_news`에서 우선 검색 소스로 활용:

```python
# fetch_news.py 개선안
# 기존: 모든 네이버 블로그 중 검색
# 개선: bloggers 컬렉션에서 검증된 블로거의 URL만 우선 크롤링
top_bloggers = search("bloggers", company_name, ticker, top_k=20)
for blogger_url in top_bloggers:
    crawl_latest_post(blogger_url)
```
