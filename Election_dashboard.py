import streamlit as st
import time
import os
import pandas as pd
import altair as alt
from datetime import datetime, timedelta, timezone
from github import Github
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# 1. 대시보드 기본 페이지 레이아웃 세팅
st.set_page_config(page_title="실시간 개표 표차 추적", page_icon="📊", layout="wide")

st.title("📊 실시간 개표 변동 추이 대시보드")
st.caption("Streamlit Community Cloud 환경에서 60초마다 선관위 데이터를 추적해 변동이 생긴 순간 그래프와 로그 테이블에 누적합니다.")

# ⏱️ 데이터 추적 주기 및 저장 파일 설정
FETCH_INTERVAL = 60
LOG_FILE = "election_gap_data.csv"

# 2. [로그 파일 복원 엔진] 켜지자마자 저장된 CSV가 있다면 판다스로 로드
if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
    try:
        df_history = pd.read_csv(LOG_FILE, encoding='utf-8')
        df_history['시간'] = df_history['시간'].astype(str)
        df_history['더불어민주당 합계'] = pd.to_numeric(df_history['더불어민주당 합계']).astype(int)
        df_history['국민의힘 오세훈'] = pd.to_numeric(df_history['국민의힘 오세훈']).astype(int)
        df_history['표차'] = pd.to_numeric(df_history['표차']).astype(int)
    except Exception as e:
        st.error(f"⚠️ 로그 파일 로드 실패: {e}")
        df_history = pd.DataFrame(columns=['시간', '더불어민주당 합계', '국민의힘 오세훈', '표차', '우세정당', '변동폭'])
else:
    df_history = pd.DataFrame(columns=['시간', '더불어민주당 합계', '국민의힘 오세훈', '표차', '우세정당', '변동폭'])

# 🤖 [핵심] 클라우드 서버가 직접 내 깃허브 저장소로 자동 커밋&푸시를 쏘는 함수
def auto_git_push(df):
    try:
        # Streamlit Secrets에 저장해 둔 토큰 및 레포지토리 정보 호출
        github_secrets = st.secrets["github.com"] if "github.com" in st.secrets else st.secrets["github"]
        token = github_secrets["token"]
        repo_name = github_secrets["repo"]
        
        # PyGithub을 통한 원격 서버 제어권 획득
        g = Github(token)
        repo = g.get_repo(repo_name)
        
        # 깃허브 원격지에 이미 올라가 있는 파일의 고유 식별자(SHA) 획득
        try:
            contents = repo.get_contents(LOG_FILE)
            sha = contents.sha
            path = contents.path
        except Exception:
            sha = None
            path = LOG_FILE
            
        # 메모리상의 최신 데이터프레임을 깨끗한 CSV 텍스트 스트링으로 가공
        csv_text = df.to_csv(index=False, encoding='utf-8')
        
        # 원격 저장소 파일 덮어쓰기 명령 (Push 일임)
        if sha:
            repo.update_file(
                path=path,
                message=f"sys: {df.iloc[-1]['시간']} 개표 변동 발생 - 원격 클라우드 자동 동기화 완료",
                content=csv_text,
                sha=sha,
                branch="main" # 내 메인 브랜치명이 master라면 master로 수정
            )
        else:
            repo.create_file(
                path=path,
                message="sys: 최초 데이터 동기화 파일 생성",
                content=csv_text,
                branch="main"
            )
    except Exception as e:
        st.warning(f"⚠️ 깃허브 원격 자동 저장 지연 (대시보드는 정상 가동 중): {e}")

# 선관위 크롤러 가동 엔진 (Headless 브라우저)
def fetch_current_votes():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')  
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        st.error(f"❌ 크롬 드라이버 초기화 실패: {e}")
        return None, None
    
    try:
        url = "https://info.nec.go.kr/main/showDocument.xhtml?electionId=0020260603&topMenuId=VC&secondMenuId=VCCP09"
        driver.get(url)
        
        wait = WebDriverWait(driver, 12)
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        if iframes:
            driver.switch_to.frame(iframes[0])

        driver.find_element(By.ID, "electionId3").click()
        time.sleep(2.0)
        
        city_code_elem = wait.until(EC.presence_of_element_located((By.ID, "cityCode")))
        Select(city_code_elem).select_by_value("1100")
        time.sleep(0.5)
        
        driver.find_element(By.CSS_SELECTOR, "#spanSubmit input[type='image']").click()
        time.sleep(5.0)
        
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        target_row = None
        for row in soup.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if cells and '합계' in cells[0].get_text(strip=True):
                target_row = cells
                break
        
        if target_row:
            votes_a = int(target_row[3].get_text(strip=True).replace(',', ''))
            votes_b = int(target_row[4].get_text(strip=True).replace(',', ''))
            return votes_a, votes_b
    except Exception as e:
        st.error(f"⚠️ 선관위 파싱 에러: {e}")
    finally:
        driver.quit()
    return None, None

# 실시간 크롤링 수행
with st.spinner("선관위 메인 전산망과 연동 제어 중..."):
    v_a, v_b = fetch_current_votes()

live_delta = "최초 측정"
party_leader = ""

if v_a and v_b:
    current_gap = abs(v_a - v_b)
    
    if v_a > v_b:
        party_leader = "더불어민주당"
    elif v_a < v_b:
        party_leader = "국민의힘"
    else:
        party_leader = "동률"
        
    # 🛠️ 타임존 패치: 해외 클라우드 서버 시간 대신 무조건 대한민국 표준시(KST) 인화
    KST = timezone(timedelta(hours=9))
    current_time = datetime.now(KST).strftime('%H:%M:%S')
    
    should_accumulate = False
    
    if len(df_history) == 0:
        live_delta = "최초 측정"
        should_accumulate = True
    else:
        prev_gap = int(df_history.iloc[-1]['표차'])
        prev_leader = str(df_history.iloc[-1]['우세정당'])
        
        gap_change = current_gap - prev_gap
        
        if party_leader != prev_leader and prev_leader != "동률" and party_leader != "동률":
            live_delta = "🔄 역전 발생!"
            should_accumulate = True
        else:
            if gap_change != 0:
                sign = "+" if gap_change > 0 else ""
                live_delta = f"{sign}{gap_change:,} 표"
                should_accumulate = True
            else:
                live_delta = "0 표 (변동없음)"
                should_accumulate = False

    # 변동 탐지 시 로컬 저장 및 원격 깃허브 동시 덮어쓰기 백업 발동
    if should_accumulate:
        new_row = pd.DataFrame([{
            '시간': current_time,
            '더불어민주당 합계': int(v_a),
            '국민의힘 오세훈': int(v_b),
            '표차': int(current_gap),
            '우세정당': party_leader,
            '변동폭': live_delta
        }])
        
        df_history = pd.concat([df_history, new_row], ignore_index=True)
        # 1. 임시 서버 로컬 디스크 안정 백업
        df_history.to_csv(LOG_FILE, index=False, encoding='utf-8')
        # 2. 내 깃허브 저장소로 원격 커밋 및 푸시 자동 대행
        auto_git_push(df_history)

# 3. 상단 킬러 메트릭스 렌더링
if v_a and v_b:
    col1, col2, col3 = st.columns(3)
    col1.metric(label="🔹 더불어민주당 후보 합계", value=f"{v_a:,} 표")
    col2.metric(label="🔸 국민의힘 오세훈 후보", value=f"{v_b:,} 표")
    col3.metric(label=f"⚡ 현재 표차 ({party_leader} 리드)", value=f"{current_gap:,} 표", delta=live_delta)
    st.divider()

# 4. 차트 및 데이터 테이블 드로잉 (2026 규격 준수)
if not df_history.empty:
    st.subheader("📊 누적 표차 추이 그래프 (정당 고유 색상 매핑)")
    
    color_chart = alt.Chart(df_history).mark_bar(opacity=0.85, size=25).encode(
        x=alt.X('시간:N', title='조회 시간', sort=None),
        y=alt.Y('표차:Q', title='합계 표차 격차 (표)', axis=alt.Axis(format=',d')), 
        color=alt.Color('우세정당:N', title='선두 정당',
                        scale=alt.Scale(
                            domain=['더불어민주당', '국민의힘', '동률'],
                            range=['#2457A6', '#E61E2B', '#888888']
                        )),
        tooltip=[
            alt.Tooltip('시간:N', title='조회 시간'),
            alt.Tooltip('더불어민주당 합계:Q', format=',d', title='더불어민주당 합계 (표)'),
            alt.Tooltip('국민의힘 오세훈:Q', format=',d', title='국민의힘 오세훈 (표)'),
            alt.Tooltip('표차:Q', format=',d', title='현재 격차 (표)'),
            alt.Tooltip('우세정당:N', title='리드 정당'),
            alt.Tooltip('변동폭:N', title='직전대비 변동폭')
        ]
    ).properties(height=400)
    
    st.altair_chart(color_chart, width='stretch')
    
    st.subheader(f"📋 전체 누적 개표 로그 기록 (총 {len(df_history)}개 변동 분기점 백업 완료)")
    
    df_display = df_history[::-1].copy()
    formatted_df = df_display.style.format({
        '더불어민주당 합계': '{:,}',
        '국민의힘 오세훈': '{:,}',
        '표차': '{:,}'
    })
    
    st.dataframe(formatted_df, width='stretch', hide_index=True)
else:
    st.info("개표 로그 데이터를 연동 중입니다.")

st.write(f"🔄 **{FETCH_INTERVAL}초** 후 대시보드가 자동으로 업데이트됩니다. (서버 리셋 프리)")
time.sleep(FETCH_INTERVAL)
st.rerun()