import streamlit as st
import os
import pandas as pd
import altair as alt

# 1. 대시보드 페이지 기본 세팅
st.set_page_config(page_title="선거 개표 최종 분석 결과", page_icon="📊", layout="wide")

st.title("🏁 선거 개표 최종 분석 결과 대시보드")
st.caption("개표가 완료됨에 따라 실시간 자동 추적을 종료하고, 축적된 데이터를 바탕으로 한 정적 분석 모드로 가동 중입니다.")

LOG_FILE = "election_gap_data.csv"

# 2. [데이터 로드 엔진] 저장된 최종 CSV 파일을 안전하게 읽어옵니다.
if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
    try:
        df_history = pd.read_csv(LOG_FILE, encoding='utf-8')
        df_history['시간'] = df_history['시간'].astype(str)
        df_history['더불어민주당 합계'] = pd.to_numeric(df_history['더불어민주당 합계']).astype(int)
        df_history['국민의힘 오세훈'] = pd.to_numeric(df_history['국민의힘 오세훈']).astype(int)
        df_history['표차'] = pd.to_numeric(df_history['표차']).astype(int)
        if '개표율' not in df_history.columns:
            df_history['개표율'] = '100.0%'
    except Exception as e:
        st.error(f"⚠️ 로그 파일 로드 실패: {e}")
        df_history = pd.DataFrame(columns=['시간', '더불어민주당 합계', '국민의힘 오세훈', '표차', '우세정당', '변동폭', '개표율'])
else:
    df_history = pd.DataFrame(columns=['시간', '더불어민주당 합계', '국민의힘 오세훈', '표차', '우세정당', '변동폭', '개표율'])

# 3. 메인 시각화 및 데이터 출력
if not df_history.empty:
    # 데이터프레임의 가장 마지막 행(최종 확정 데이터) 추출
    final_row = df_history.iloc[-1]
    v_a = final_row['더불어민주당 합계']
    v_b = final_row['국민의힘 오세훈']
    current_gap = final_row['표차']
    party_leader = final_row['우세정당']
    live_delta = final_row['변동폭']
    c_rate = final_row['개표율']

    # 상단 최종 확정 스코어보드
    st.subheader("🏆 최종 개표 결과 마감")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(label="🔹 더불어민주당 후보 최종 합계", value=f"{v_a:,} 표")
    col2.metric(label="🔸 국민의힘 오세훈 후보 최종", value=f"{v_b:,} 표")
    col3.metric(label=f"🏁 최종 리드 정당 ({party_leader})", value=f"{current_gap:,} 표", delta=live_delta)
    col4.metric(label="⏳ 개표 마감 진행률", value=c_rate)
    st.divider()

    # 차트 레이어링 시각화 (역전 순간 뱃지 포함)
    st.subheader("📊 전체 개표 추이 및 드라마틱 역전 지점 시각화")
    
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
            alt.Tooltip('개표율:N', title='당시 개표율'),
            alt.Tooltip('더불어민주당 합계:Q', format=',d', title='더불어민주당 (표)'),
            alt.Tooltip('국민의힘 오세훈:Q', format=',d', title='국민의힘 오세훈 (표)'),
            alt.Tooltip('표차:Q', format=',d', title='격차 (표)'),
            alt.Tooltip('변동폭:N', title='직전대비 변동폭')
        ]
    )
    
    # 🛠️ [버그 수정 완료] 판다스에서 역전 데이터만 안전하게 필터링한 뒤 Altair에 전달합니다.
    df_turnaround = df_history[df_history['변동폭'] == '🔄 역전 발생!']
    
    turnaround_annotation = alt.Chart(df_turnaround).mark_text(
        text='🚨 골든크로스 역전',
        dy=-15,
        fontSize=12,
        fontWeight='bold',
        color='#9900cc'
    ).encode(
        x='시간:N',
        y='표차:Q'
    )
    
    final_chart = alt.layer(base_bar, turnaround_annotation).properties(height=400)
    st.altair_chart(final_chart, width='stretch')
    
    # 판다스 스타일러를 이용한 테이블 커스텀 음영 주입
    st.subheader(f"📋 전술 개표 히스토리 로그 테이블 (총 {len(df_history)}개 변동 기록)")
    
    def apply_row_styles(row):
        if row['변동폭'] == '🔄 역전 발생!':
            return ['background-color: #fff2cc; font-weight: bold; color: #7f6000; border: 1px solid #ffd966;'] * len(row)
        elif row['우세정당'] == '더불어민주당':
            return ['background-color: #f2f7ff; color: #1c3d73;'] * len(row)
        elif row['우세정당'] == '국민의힘':
            return ['background-color: #fff5f5; color: #8c2323;'] * len(row)
        return [''] * len(row)

    # 최신 순으로 정렬하여 뷰어 렌더링
    df_display = df_history[::-1].copy()
    styled_table = df_display.style.apply(apply_row_styles, axis=1).format({
        '더불어민주당 합계': '{:,}',
        '국민의힘 오세훈': '{:,}',
        '표차': '{:,}'
    })
    
    st.dataframe(styled_table, width='stretch', hide_index=True)
else:
    st.info("시각화할 개표 로그 데이터가 존재하지 않습니다. 'election_gap_data.csv' 파일을 확인해 주세요.")