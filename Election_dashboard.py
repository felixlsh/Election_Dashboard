import streamlit as st
import time
import os
import pandas as pd
import altair as alt
import re
from datetime import datetime, timedelta, timezone
from github import Github
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# 1. 대시보드 기본 페이지 레이아웃 세팅
st.set_page_config(page_title="실시간 개표 추적 시스템", page_icon="📊", layout="wide")

st.title("📊 깃허브 연동 실시간 개표 방송 대시보드")
st.caption("대시보드가 60초마다 선관위 데이터를 추적하며, 역전 발생 시각화 및 정당별 로그 음영 레이아웃이 적용되어 있습니다.")

# ⏱️ 데이터 추적 주기 및 저장 파일 설정
FETCH_INTERVAL = 60
LOG_FILE = "election_gap_data.csv"

# 2. [로그 파일 복원 엔진] 기존 데이터 로드 및 신규 컬럼 대응 보정
if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
    try:
        df_history = pd.read_csv(LOG_FILE, encoding='utf-8')
        df_history['시간'] = df_history['시간'].astype(str)
        df_history['더불어민주당 합계'] = pd.to_numeric(df_history['더불어민주당 합계']).astype(int)
        df_history['국민의힘 오세훈'] = pd.to_numeric(df_history['국민의힘 오세훈']).astype(int)
        df_history['표차'] = pd.to_numeric(df_history['표차']).astype(int)
        # 하위 호환성 패치: 기존 파일에 개표율 컬럼이 없으면 자동 생성
        if '개표율' not in df_history.columns:
            df_history['개표율'] = '-'
    except Exception as e:
        st.error(f"⚠️ 로그 파일 로드 실패: {e}")
        df_history = pd.DataFrame(columns=['시간', '더불어민주당 합계', '국민의힘 오세훈', '표차', '우세정당', '변동폭', '개표율'])
else:
    df_history = pd.DataFrame(columns=['시간', '더불어민주당 합계', '국민의힘 오세훈', '표차', '우세정당', '변동폭', '개표율'])

# 🤖 클라우드 서버 전용 깃허브 원격 자동 푸시 함수
def auto_git_push(df):
    try:
        github_secrets = st.secrets["github.com"] if "github.com" in st.secrets else st.secrets["github"]
        token = github_secrets["token"]
        repo_name = github_secrets["repo"]
        
        g = Github(token)
        repo = g.get_repo(repo_name)
        
        try:
            contents = repo.get_contents(LOG_FILE)
            sha = contents.sha
            path = contents.path
        except Exception:
            sha = None
            path = LOG_FILE
            
        csv_text = df.to_csv(index=False, encoding='utf-8')
        
        if sha:
            repo.update_file(
                path=path,
                message=f"sys: {df.iloc[-1]['시간']} 개표율 {df.iloc[-1]['개표율']} 변동 자동 업데이트",
                content=csv_text,
                sha=sha,
                branch="main"
            )
        else:
            repo.create_file(
                path=path,
                message="sys: 최초 데이터 동기화 파일 생성",
                content=csv_text,
                branch="main"
            )
    except Exception as e:
        st.warning(f"⚠️ 깃허브 자동 백업 지연 (화면은 정상 가동 중): {e}")

# 선관위 크롤러 가동 엔진 (득표수 및 개표율 동시 스크래핑)
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
        return None, None, "0.0%"
    
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
        
        # ⏳ [개표율 추출] 페이지 내부에서 개표율 정보 레이블 서칭
        counting_rate = "0.0%"
        for element in soup.find_all(['div', 'p', 'span', 'td', 'h4', 'th']):
            text = element.get_text(strip=True)
            if "개표율" in text and ":" in text:
                match = re.search(r'개표율\s*:\s*([0-9.]+\s*%)', text)
                if match:
                    counting_rate = match.group(1).replace(" ", "")
                    break
        
        target_row = None
        for row in soup.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if cells and '합계' in cells[0].get_text(strip=True):
                target_row = cells
                break
        
        if target_row:
            votes_a = int(target_row[3].get_text(strip=True).replace(',', ''))
            votes_b = int(target_row[4].get_text(strip=True).replace(',', ''))
            return votes_a, votes_b, counting_rate
    except Exception as e:
        st.error(f"⚠️ 선관위 데이터 파싱 에러: {e}")
    finally:
        driver.quit()
    return None, None, "0.0%"

# 실시간 스크래핑 제어부
with st.spinner("선관위 중앙 데이터베이스 동기화 중..."):
    v_a, v_b, c_rate = fetch_current_votes()

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

    if should_accumulate:
        new_row = pd.DataFrame([{
            '시간': current_time,
            '더불어민주당 합계': int(v_a),
            '국민의힘 오세훈': int(v_b),
            '표차': int(current_gap),
            '우세정당': party_leader,
            '변동폭': live_delta,
            '개표율': c_rate
        }])
        
        df_history = pd.concat([df_history, new_row], ignore_index=True)
        df_history.to_csv(LOG_FILE, index=False, encoding='utf-8')
        auto_git_push(df_history)

# 3. 상단 4열 실시간 지표 보드 (Metric)
if v_a and v_b:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(label="🔹 더불어민주당 후보 합계", value=f"{v_a:,} 표")
    col2.metric(label="🔸 국민의힘 오세훈 후보", value=f"{v_b:,} 표")
    col3.metric(label=f"⚡ 현재 표차 ({party_leader} 리드)", value=f"{current_gap:,} 표", delta=live_delta)
    col4.metric(label="⏳ 선관위 공식 개표율", value=c_rate)
    st.divider()

# 4. 차트 레이어링 시각화 (역전 순간 포인트 하이라이트)
if not df_history.empty:
    st.subheader("📊 누적 표차 추이 그래프 (역전 시점 추적 뱃지 탑재)")
    
    # 베이스 막대 차트
    base_bar = alt.Chart(df_history).mark_bar(opacity=0.8, size=22).encode(
        x=alt.X('시간:N', title='조회 시간', sort=None),
        y=alt.Y('표차:Q', title='정당별 표차 격차 (표)', axis=alt.Axis(format=',d')), 
        color=alt.Color('우세정당:N', title='선두 정당',
                        scale=alt.Scale(
                            domain=['더불어민주당', '국민의힘', '동률'],
                            range=['#2457A6', '#E61E2B', '#888888']
                        )),
        tooltip=[
            alt.Tooltip('시간:N', title='시간'),
            alt.Tooltip('개표율:N', title='개표 진행률'),
            alt.Tooltip('더불어민주당 합계:Q', format=',d', title='더불어민주당 (표)'),
            alt.Tooltip('국민의힘 오세훈:Q', format=',d', title='국민의힘 오세훈 (표)'),
            alt.Tooltip('표차:Q', format=',d', title='현재 격차 (표)'),
            alt.Tooltip('변동폭:N', title='직전대비 변동폭')
        ]
    )
    
    # 🌟 [디자인 보완] 역전이 발생한 데이터 포인트만 필터링하여 상단에 🚨 표식을 매핑하는 레이어
    turnaround_annotation = alt.Chart(df_history).filter(
        alt.datum.변동폭 == '🔄 역전 발생!'
    ).mark_text(
        text='🚨 골든크로스 역전',
        dy=-15,
        fontSize=12,
        fontWeight='bold',
        color='#9900cc'
    ).encode(
        x='시간:N',
        y='표차:Q'
    )
    
    # 두 레이어를 병합하여 출력
    final_chart = alt.layer(base_bar, turnaround_annotation).properties(height=400)
    st.altair_chart(final_chart, width='stretch')
    
    # 5. [디자인 보완] 판다스 스타일러를 이용한 테이블 커스텀 음영 주입
    st.subheader(f"📋 전술 개표 누적 데이터 테이블 (총 {len(df_history)}개 분기점)")
    
    def apply_row_styles(row):
        """ 행의 상태에 따라 배경색 음영을 다르게 제어하는 스타일 함수 """
        if row['변동폭'] == '🔄 역전 발생!':
            # 👑 역전 발생 순간: 황금색 테두리 효과 및 굵은 글씨
            return ['background-color: #fff2cc; font-weight: bold; color: #7f6000; border: 1px solid #ffd966;'] * len(row)
        elif row['우세정당'] == '더불어민주당':
            # 민주당 우세: 파스텔 소프트 블루
            return ['background-color: #f2f7ff; color: #1c3d73;'] * len(row)
        elif row['우세정당'] == '국민의힘':
            # 국민의힘 우세: 파스텔 소프트 레드
            return ['background-color: #fff5f5; color: #8c2323;'] * len(row)
        return [''] * len(row)

    df_display = df_history[::-1].copy()
    
    # 스타일 함수 결합 및 천 단위 컴마 인쇄 결합
    styled_table = df_display.style.apply(apply_row_styles, axis=1).format({
        '더불어민주당 합계': '{:,}',
        '국민의힘 오세훈': '{:,}',
        '표차': '{:,}'
    })
    
    st.dataframe(styled_table, width='stretch', hide_index=True)
else:
    st.info("개표 로그 데이터를 연동 중입니다.")

st.write(f"🔄 **{FETCH_INTERVAL}초** 후 대시보드가 자동으로 업데이트됩니다.")
time.sleep(FETCH_INTERVAL)
st.rerun()