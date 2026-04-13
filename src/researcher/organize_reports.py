import os
import shutil
from datetime import datetime

def parse_filename(filename):
    """
    파일명에서 날짜, 회사명을 추출합니다.
    예: 26.04.07_아모레퍼시픽_교보증권_1Q26 Preview_ 국내 수익성과 COSRX 반등.pdf
    """
    name_without_ext, ext = os.path.splitext(filename)
    parts = name_without_ext.split('_')
    
    # 2개 이상의 _로 구분된 부분(날짜, 회사명)이 있는지 확인
    if len(parts) >= 2:
        date_str = parts[0].strip()
        company_name = parts[1].strip()
        
        # date_str: YY.MM.DD -> YYYYMMDD
        try:
            date_obj = datetime.strptime(date_str, "%y.%m.%d")
            formatted_date = date_obj.strftime("%Y%m%d")
            return formatted_date, company_name
        except ValueError:
            # 날짜 형식이 맞지 않을 경우 패스
            return None, None
    return None, None

def organize_reports(source_dir, target_dir, target_companies, start_date):
    """
    지정된 폴더에서 조건에 맞는 보고서 파일들을 회사별 폴더로 카피하는 함수
    
    :param source_dir: 소스 폴더 경로 ('/Users/boon/report_source')
    :param target_dir: 복사될 타겟 폴더 경로 ('/Users/boon/report')
    :param target_companies: 추출할 회사명 리스트 (예: ['아모레퍼시픽', '삼성전자'])
    :param start_date: 검색 기준 시작 날짜 (YYYYMMDD 포맷, 예: '20260101')
    """
    
    if not os.path.exists(source_dir):
        print(f"오류: 소스 디렉토리 '{source_dir}' 가 존재하지 않습니다.")
        return
        
    start_date_int = int(start_date)
    copied_count = 0
    skipped_count = 0
    
    for filename in os.listdir(source_dir):
        source_path = os.path.join(source_dir, filename)
        
        # 디렉토리는 건너뛰고 파일만 처리
        if not os.path.isfile(source_path):
            continue
            
        file_date, company = parse_filename(filename)
        
        if file_date and company:
            # 1. 날짜 확인: 기준일자(start_date) 이후에 작성된 파일인지
            if int(file_date) >= start_date_int:
                # 2. 회사명 확인: 지정된 회사명 리스트에 정확히 일치하는지
                if company in target_companies:
                    
                    # 대상 디렉토리에 '회사명'으로 폴더 생성
                    company_dir = os.path.join(target_dir, company)
                    os.makedirs(company_dir, exist_ok=True)
                    
                    target_path = os.path.join(company_dir, filename)
                    
                    try:
                        shutil.copy2(source_path, target_path)
                        print(f"[*] 파일 복사 성공: {filename} -> {company} 폴더")
                        copied_count += 1
                    except Exception as e:
                        print(f"[!] 복사 실패: {filename} (사유: {str(e)})")
                else:
                    skipped_count += 1
            else:
                skipped_count += 1
        else:
            # 파일명 규칙에 맞지 않는 파일 (건너뜀)
            skipped_count += 1
            
    print(f"\n작업 완료! 복사된 파일 수: {copied_count} 개, 건너뛴 파일 수: {skipped_count} 개")

if __name__ == "__main__":
    # --- 설정 부분 ---
    SOURCE_DIRECTORY = "/Users/boon/report_source"
    TARGET_DIRECTORY = "/Users/boon/report"
    
    # 추출하고자 하는 회사명을 리스트 형태로 명시해 줍니다.
    COMPANIES_TO_BE_EXTRACTED = [
        "NAVER",
        "카카오",
        "현대차",
        "SK하이닉스" 
        #"삼성전자"
        # 필요한 회사명을 더 추가하세요.
    ] 
    
    # 이 날짜(YYYYMMDD) 이후에 작성된 보고서만 가져옵니다.
    START_DATE_CONDITION = "20260101"
    
    # 실행
    print(f"보고서 정리를 시작합니다. (기준 날짜: {START_DATE_CONDITION} 이후)")
    organize_reports(
        source_dir=SOURCE_DIRECTORY,
        target_dir=TARGET_DIRECTORY,
        target_companies=COMPANIES_TO_BE_EXTRACTED,
        start_date=START_DATE_CONDITION
    )
