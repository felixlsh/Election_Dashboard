import streamlit as st
import time
import os
import pandas as pd
import altair as alt
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# 1. 페이지 레이아웃 세팅
st.set_page_config(page_title="실시간 개표 표차 추적", page_icon="📊", layout="wide")

st.title("📊 파일 연동 실시간 개표 대시보드")
st.caption("새로고침을 하더라도 로그 파일에서 데이터를 역추적해 그래프와 히스토리를 완벽히 복원합니다.")

# ⏱️ 새로고침 주기 (60초 = 1분)
FETCH_INTERVAL = 60
LOG_FILE = "election_gap_data.csv"

# 2. [로그 파일 복원 엔진] 에러 발생 시 숨기지 않고 출력하도록 개선
if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
    try:
        df_history = pd.read_csv(LOG_FILE, encoding='utf-8')
        df_history['시간'] = df_history['시간'].astype(str)
        df_history['더불어민주당 합계'] = pd.to_numeric(df_history['더불어민주당 합계']).astype(int)
        df_history['국민의힘 오세훈'] = pd.to_numeric(df_history['국민의힘 오세훈']).astype(int)
        df_history['표차'] = pd.to_numeric(df_history['표차']).astype(int)
    except Exception as e:
        # 어디서 파일 에러가 났는지 브라우저 화면에 직접 띄워 추적을 돕습니다.
        st.error(f"⚠️ 기존 로그 파일 로드 중 오류 발생: {e}")
        st.warning("로그 파일 내부 서식이 고르지 않습니다. 아래 시스템이 수집 즉시 정정 및 자동 복구를 시도합니다.")
        df_history = pd.DataFrame(columns=['시간', '더불어민주당 합계', '국민의힘 오세훈', '표차', '우세정당', '변동폭'])
else:
    df_history = pd.DataFrame(columns=['시간', '더불어민주당 합계', '국민의힘 오세훈', '표차', '우세정당', '변동폭'])

# 셀레니움 크롤링 (클라우드/로컬 공용 최적화)
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
        st.error(f"⚠️ 데이터 파싱 실패: {e}")
    finally:
        driver.quit()
    return None, None

# 실시간 크롤링 수행
with st.spinner("선관위 서버 동기화 및 텍스트 파일 데이터 대조 중..."):
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
        
    current_time = time.strftime('%H:%M:%S')
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

    # 3. [🔥 핵심 변경] mode='a'를 폐기하고, 병합 후 파일 전체를 새로 고쳐 쓰는 완전 안전한 방식으로 수정
    if should_accumulate:
        new_row = pd.DataFrame([{
            '시간': current_time,
            '더불어민주당 합계': int(v_a),
            '국민의힘 오세훈': int(v_b),
            '표차': int(current_gap),
            '우세정당': party_leader,
            '변동폭': live_delta
        }])
        
        # 메모리 위에서 깔끔하게 결합을 끝낸 뒤
        df_history = pd.concat([df_history, new_row], ignore_index=True)
        # 규격화된 파일 서식으로 매번 완전히 깔끔하게 덮어써서 줄바꿈 깨짐을 원천 봉쇄합니다.
        df_history.to_csv(LOG_FILE, index=False, encoding='utf-8')

# 4. 화면 UI 출력 (상단 매트릭스 지표)
if v_a and v_b:
    col1, col2, col3 = st.columns(3)
    col1.metric(label="🔹 더불어민주당 후보 합계", value=f"{v_a:,} 표")
    col2.metric(label="🔸 국민의힘 오세훈 후보", value=f"{v_b:,} 표")
    col3.metric(label=f"⚡ 현재 표차 ({party_leader} 리드)", value=f"{current_gap:,} 표", delta=live_delta)
    st.divider()

# 5. 시각화 렌더링 영역
if not df_history.empty:
    st.subheader("📊 누적 표차 추이 그래프 (정당 고유 색상 배치)")
    
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
    
    st.subheader(f"📋 전체 누적 개표 로그 기록 (총 {len(df_history)}개 변동 시점 저장됨)")
    
    df_display = df_history[::-1].copy()
    formatted_df = df_display.style.format({
        '더불어민주당 합계': '{:,}',
        '국민의힘 오세훈': '{:,}',
        '표차': '{:,}'
    })
    
    st.dataframe(formatted_df, width='stretch', hide_index=True)
else:
    st.info("개표 로그 파일이 비어있거나 생성 중입니다.")

st.write(f"🔄 **{FETCH_INTERVAL}초** 후 대시보드가 자동으로 업데이트됩니다.")
time.sleep(FETCH_INTERVAL)
st.rerun()