"""
organize_reports.py — 날짜 기준으로 보고서를 회사별 폴더에 자동 정리

사용법:
  python src/researcher/organize_reports.py          # 기본 (START_DATE 이후 전체)
  python src/researcher/organize_reports.py 20260401 # 특정 날짜 이후만

동작:
  1. source_dir 에서 START_DATE 이후 PDF 파일을 스캔
  2. 파일명에서 회사명을 자동 추출 (회사명 목록 사전 등록 불필요)
  3. target_dir/{회사명}/ 폴더로 복사
  4. 정리된 회사명 목록을 target_dir/organized_companies.txt 에 저장

파일명 규칙: YY.MM.DD_회사명_증권사_제목.pdf
"""

import os
import sys
import csv
import shutil
from datetime import datetime
from collections import defaultdict

# main.py 와 같은 위치 (프로젝트 루트)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


SOURCE_DIR = "/Users/boon/report_source"
TARGET_DIR = "/Users/boon/report"


def parse_filename(filename: str) -> tuple[str | None, str | None]:
    """
    파일명에서 (날짜 YYYYMMDD, 회사명) 추출.
    예: 26.04.09_NAVER_SK증권_커머스가 하드캐리.pdf → ("20260409", "NAVER")
    패턴 불일치 시 (None, None) 반환.
    """
    name, ext = os.path.splitext(filename)
    if ext.lower() != ".pdf":
        return None, None

    parts = name.split("_")
    if len(parts) < 2:
        return None, None

    date_str     = parts[0].strip()
    company_name = parts[1].strip()

    try:
        date_obj = datetime.strptime(date_str, "%y.%m.%d")
        return date_obj.strftime("%Y%m%d"), company_name
    except ValueError:
        return None, None


def organize_reports(source_dir: str, target_dir: str, start_date: str) -> dict[str, list]:
    """
    start_date 이후 PDF를 자동으로 회사별 폴더에 복사한다.
    회사명은 파일명에서 자동 추출 — 사전 등록 불필요.

    반환: {회사명: [복사된 파일명, ...]}
    """
    if not os.path.exists(source_dir):
        print(f"[오류] 소스 디렉토리 없음: {source_dir}")
        return {}

    start_int   = int(start_date)
    result      = defaultdict(list)  # {회사명: [파일명]}
    skip_count  = 0

    files = sorted(os.listdir(source_dir))
    print(f"  전체 파일: {len(files)}개 스캔 중 (기준일: {start_date} 이후)")

    for filename in files:
        source_path = os.path.join(source_dir, filename)
        if not os.path.isfile(source_path):
            continue

        file_date, company = parse_filename(filename)

        if not file_date or not company:
            skip_count += 1
            continue

        if int(file_date) < start_int:
            skip_count += 1
            continue

        # 회사별 폴더 생성 후 복사
        company_dir = os.path.join(target_dir, company)
        os.makedirs(company_dir, exist_ok=True)
        target_path = os.path.join(company_dir, filename)

        try:
            shutil.copy2(source_path, target_path)
            result[company].append(filename)
            print(f"  [복사] {filename[:60]}")
        except Exception as e:
            print(f"  [실패] {filename}: {e}")

    print(f"\n  스킵: {skip_count}개 (날짜 미달 또는 파일명 규칙 불일치)")
    return dict(result)


def save_company_list(result: dict[str, list], target_dir: str, start_date: str) -> tuple[str, str]:
    """
    정리된 회사명과 파일 목록을 텍스트 + CSV 두 파일로 저장한다.
    - target_dir/organized_companies.txt  : 상세 목록 + TARGETS 스니펫
    - PROJECT_ROOT/organized_companies.csv: company_name, file_count (main.py 위치)
    """
    out_path = os.path.join(target_dir, "organized_companies.txt")
    today    = datetime.today().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"보고서 정리 결과",
        f"실행일시: {today}",
        f"기준날짜: {start_date} 이후",
        f"정리 회사 수: {len(result)}개",
        "=" * 50,
        "",
    ]

    for company in sorted(result.keys()):
        files = sorted(result[company])
        lines.append(f"[ {company} ]  ({len(files)}개)")
        for f in files:
            lines.append(f"  - {f}")
        lines.append("")

    # TARGETS 등록용 코드 스니펫
    lines += [
        "=" * 50,
        "# main.py TARGETS 등록 참고",
        "# COMPANY_KEYWORDS (state.py) 에도 추가 필요",
        "",
        "TARGETS = [",
    ]
    for company in sorted(result.keys()):
        lines.append(f'    {{"company_name": "{company}", "ticker": "??????", "sector": "??????"}},')
    lines.append("]")

    content = "\n".join(lines)
    os.makedirs(target_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    return out_path


def save_company_csv(result: dict[str, list], out_dir: str) -> str:
    """
    회사별 파일 수를 CSV로 저장한다.
    저장 경로: out_dir/organized_companies.csv
    컬럼: company_name, file_count
    """
    out_path = os.path.join(out_dir, "organized_companies.csv")
    rows = sorted(
        [{"company_name": company, "file_count": len(files)}
         for company, files in result.items()],
        key=lambda r: r["company_name"],
    )

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "file_count"])
        writer.writeheader()
        writer.writerows(rows)

    return out_path


if __name__ == "__main__":
    # 날짜 인수: python organize_reports.py 20260401
    # 미입력 시 기본값 사용
    if len(sys.argv) >= 2:
        START_DATE = sys.argv[1].strip()
        # YYYYMMDD 형식 검증
        try:
            datetime.strptime(START_DATE, "%Y%m%d")
        except ValueError:
            print(f"[오류] 날짜 형식 오류: {START_DATE}  (올바른 형식: YYYYMMDD, 예: 20260401)")
            sys.exit(1)
    else:
        START_DATE = "20260101"   # 기본값

    print(f"\n보고서 정리 시작")
    print(f"  소스: {SOURCE_DIR}")
    print(f"  대상: {TARGET_DIR}")
    print(f"  기준: {START_DATE} 이후\n")

    result = organize_reports(SOURCE_DIR, TARGET_DIR, START_DATE)

    if result:
        txt_path = save_company_list(result, TARGET_DIR, START_DATE)
        csv_path = save_company_csv(result, PROJECT_ROOT)
        total = sum(len(v) for v in result.values())
        print(f"\n완료!")
        print(f"  복사 파일: {total}개")
        print(f"  회사 수  : {len(result)}개 → {sorted(result.keys())}")
        print(f"  목록 저장: {txt_path}")
        print(f"  CSV 저장 : {csv_path}")
    else:
        print("\n복사된 파일이 없습니다.")
