import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import altair as alt

# --- 설정: 페이지 기본 세팅 ---
st.set_page_config(page_title="프라이빗 학습 관리", layout="wide")



# --- 수정된 구글 시트 연결 함수 (클라우드 호환용) ---
@st.cache_resource
def get_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # 1. 로컬 컴퓨터에 파일이 있는지 확인
    import os
    if os.path.exists("service_account.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    # 2. 파일이 없으면 스트림릿 클라우드의 'Secrets'에서 가져옴
    else:
        # st.secrets에 저장된 정보를 딕셔너리로 가져옴
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
    
    client = gspread.authorize(creds)
    return client


def get_data():
    client = get_connection()
    sh = client.open("Tutoring_DB") # 스프레드시트 이름
    return sh

# --- 기능: 데이터 로드 및 처리 ---
try:
    sh = get_data()
    # 각 시트 가져오기
    ws_students = sh.worksheet("Students")
    ws_logs = sh.worksheet("StudyLogs")
    ws_exams = sh.worksheet("Exams")
    ws_homework = sh.worksheet("Homework")
    ws_summaries = sh.worksheet("Summaries")
except Exception as e:
    st.error(f"구글 시트 연결 실패! JSON 파일이나 시트 이름을 확인하세요.\n에러: {e}")
    st.stop()

# --- 로그인 화면 ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['user_name'] = ""

if not st.session_state['logged_in']:
    st.title("🔐 학습 관리 시스템 로그인")
    input_pw = st.text_input("비밀번호를 입력하세요", type="password")
    if st.button("접속"):
        students = ws_students.get_all_records()
        user_found = False
        for student in students:
            # 엑셀의 비밀번호는 숫자일 수 있으므로 문자로 변환해서 비교
            if str(student['비밀번호']) == str(input_pw):
                st.session_state['logged_in'] = True
                st.session_state['user_name'] = student['이름']
                st.session_state['goals'] = student # 목표 시간 정보 저장
                user_found = True
                st.rerun()
        if not user_found:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop() # 로그인 전에는 아래 코드 실행 안 함

# ================= 메인 앱 시작 =================
user_name = st.session_state['user_name']
st.sidebar.title(f"👋 반가워요, {user_name} 학생!")
menu = st.sidebar.radio("메뉴 이동", ["📊 오늘의 학습 현황", "📝 과제 체크", "💯 영단어 테스트", "📅 주간/월간 리포트", "🗄️ 지난 기록 보관소"])

# --- 1. 오늘의 학습 현황 (입력 & 일간 그래프) ---
if menu == "📊 오늘의 학습 현황":
    st.title("⏱️ 오늘의 학습 기록")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("학습 시간 입력")
        with st.form("study_input"):
            date_val = st.date_input("날짜", datetime.now())
            subject_val = st.selectbox("과목", ["수학", "영어", "국어", "과학", "기타"])
            time_val = st.number_input("공부 시간 (분)", min_value=0, step=10)
            memo_val = st.text_input("한줄 메모 (선택)")
            
            if st.form_submit_button("기록 저장"):
                ws_logs.append_row([str(date_val), user_name, subject_val, time_val, memo_val])
                st.success("저장되었습니다! (새로고침 시 그래프 반영)")
                # st.rerun() # 자동 새로고침 (선택사항)

    with col2:
        st.subheader("오늘의 목표 달성률")
        # 목표 시간 가져오기 (요일별)
        weekday_map = {0: '월_목표', 1: '화_목표', 2: '수_목표', 3: '목_목표', 4: '금_목표', 5: '토_목표', 6: '일_목표'}
        today_goal_hours = st.session_state['goals'][weekday_map[date_val.weekday()]]
        today_goal_mins = today_goal_hours * 60
        
        # 오늘 공부한 데이터 가져오기
        all_logs = pd.DataFrame(ws_logs.get_all_records())
        if not all_logs.empty:
            # 날짜 필터링 (문자열 비교)
            today_logs = all_logs[(all_logs['이름'] == user_name) & (all_logs['날짜'] == str(date_val))]
            total_mins = today_logs['시간(분)'].sum()
        else:
            total_mins = 0
            today_logs = pd.DataFrame()

        # 달성률 계산
        progress = (total_mins / today_goal_mins) * 100 if today_goal_mins > 0 else 0
        
        st.metric(label=f"목표: {today_goal_hours}시간 ({today_goal_mins}분)", 
                  value=f"{total_mins}분 달성", 
                  delta=f"{progress:.1f}%")
        
        # 과목별 도넛 차트 (Q7 해결)
        if not today_logs.empty:
            chart = alt.Chart(today_logs).mark_arc(innerRadius=50).encode(
                theta=alt.Theta(field="시간(분)", type="quantitative"),
                color=alt.Color(field="과목", type="nominal"),
                tooltip=["과목", "시간(분)"]
            ).properties(title="과목별 비중")
            st.altair_chart(chart, use_container_width=True)

# --- 2. 과제 체크 ---
elif menu == "📝 과제 체크":
    st.title("숙제 했니? 👀")
    
    # 데이터 가져오기
    hw_data = ws_homework.get_all_records()
    df_hw = pd.DataFrame(hw_data)
    
    if not df_hw.empty:
        my_hw = df_hw[df_hw['이름'] == user_name]
        # 최근 7일치만 보여주거나, 완료 안 된 것만 보여주는 등 필터링 가능
        # 여기서는 전체 다 보여주고 체크박스로 관리
        
        for i, row in my_hw.iterrows():
            # 엑셀의 TRUE/FALSE 텍스트를 파이썬 boolean으로 변환
            is_done = str(row['완료여부']).upper() == 'TRUE'
            
            col_a, col_b, col_c = st.columns([1, 4, 1])
            col_a.write(row['날짜'])
            col_b.write(f"**{row['내용']}**")
            
            # 체크박스 상태가 바뀌면 엑셀 업데이트
            new_status = col_c.checkbox("완료", value=is_done, key=f"hw_{i}")
            
            if new_status != is_done:
                # 엑셀의 해당 행(row) 업데이트 (헤더가 1줄 있으므로 인덱스+2)
                # 실제 데이터 위치를 찾기 위해 원본 데이터에서의 인덱스를 추적해야 함 (간략화된 로직)
                # *주의: 실제 운영시 고유 ID를 쓰는 게 좋지만, 여기선 간단히 구현
                row_num = i + 2 # (0부터 시작하므로 +2) -> *정확하지 않을 수 있음(필터링 시)*
                # 정확한 행 번호를 찾기 위한 로직 (날짜와 내용으로 매칭)
                cell = ws_homework.find(row['내용'])
                if cell:
                    ws_homework.update_cell(cell.row, 4, str(new_status).upper())
                    st.toast("상태가 업데이트 되었습니다!")
                    # st.rerun()
    else:
        st.info("등록된 과제가 없습니다.")

# --- 3. 영단어 테스트 ---
elif menu == "💯 영단어 테스트":
    st.title("Voca Test")
    
    with st.form("exam_input"):
        st.write("시험 결과를 입력하세요.")
        e_date = st.date_input("시험 날짜", datetime.now())
        e_name = st.text_input("시험명 (예: Day 5)")
        e_total = st.number_input("총 문제 수", min_value=1)
        e_correct = st.number_input("맞은 개수", min_value=0)
        e_cut = st.number_input("통과 기준 점수(개수)", min_value=0)
        
        if st.form_submit_button("결과 제출"):
            ws_exams.append_row([str(e_date), user_name, e_name, e_total, e_correct, e_cut])
            st.success("입력 완료!")
            
    st.divider()
    st.subheader("최근 시험 결과")
    df_exam = pd.DataFrame(ws_exams.get_all_records())
    if not df_exam.empty:
        my_exams = df_exam[df_exam['이름'] == user_name].tail(5) # 최근 5개
        for _, row in my_exams.iterrows():
            pass_fail = "✅ 통과" if row['정답'] >= row['기준점수'] else "🚨 재시험"
            st.write(f"**[{row['날짜']}] {row['시험명']}** : {row['정답']}/{row['총문제']} ({pass_fail})")

# --- 4. 주간/월간 리포트 (그래프 기능 강화) ---
elif menu == "📅 주간/월간 리포트":
    st.title("📈 학습 분석 리포트")
    
    # 기간 선택
    period = st.selectbox("기간 선택", ["최근 7일", "이번 달"])
    
    all_logs = pd.DataFrame(ws_logs.get_all_records())
    if not all_logs.empty:
        df = all_logs[all_logs['이름'] == user_name].copy()
        df['날짜'] = pd.to_datetime(df['날짜'])
        
        if period == "최근 7일":
            start_date = pd.Timestamp(datetime.now().date() - timedelta(days=6))
            df = df[df['날짜'] >= start_date]
        else: # 이번 달
            today = datetime.now()
            start_date = pd.Timestamp(today.year, today.month, 1)
            df = df[df['날짜'] >= start_date]
            
        if not df.empty:
            # 1. 꺾은선 그래프 + 목표선 (Altair 활용)
            # 날짜별 총 시간 집계
            daily_sum = df.groupby('날짜')['시간(분)'].sum().reset_index()
            daily_sum['목표(분)'] = 420 # 기본 7시간(420분) 예시 (요일별 매핑은 복잡해지니 평균값 혹은 상수로 표시)
            
            # 메인 꺾은선 (내 공부시간)
            line = alt.Chart(daily_sum).mark_line(point=True, color='blue').encode(
                x=alt.X('날짜', axis=alt.Axis(format='%m-%d')),
                y='시간(분)',
                tooltip=['날짜', '시간(분)']
            )
            
            # 목표선 (빨간 점선)
            rule = alt.Chart(daily_sum).mark_rule(color='red', strokeDash=[5, 5]).encode(
                y='목표(분)',
                size=alt.value(2)
            )
            
            st.altair_chart(line + rule, use_container_width=True)
            
            # 2. 과목별 누적 시간 (Q7)
            st.subheader("과목별 투자 시간")
            subj_sum = df.groupby('과목')['시간(분)'].sum().reset_index()
            bar = alt.Chart(subj_sum).mark_bar().encode(
                x='과목',
                y='시간(분)',
                color='과목'
            )
            st.altair_chart(bar, use_container_width=True)
            
        else:
            st.warning("해당 기간의 데이터가 없습니다.")

# --- 5. 지난 기록 보관소 (아카이브) ---
elif menu == "🗄️ 지난 기록 보관소":
    st.title("🗄️ Archive")
    st.info("오래된 학습 기록을 조회합니다.")
    
    col1, col2 = st.columns(2)
    start_d = col1.date_input("시작일", datetime.now() - timedelta(days=30))
    end_d = col2.date_input("종료일", datetime.now())
    
    all_logs = pd.DataFrame(ws_logs.get_all_records())
    if not all_logs.empty:
        # 날짜 문자열 변환 및 필터링
        all_logs['날짜_dt'] = pd.to_datetime(all_logs['날짜'])
        mask = (all_logs['날짜_dt'].dt.date >= start_d) & (all_logs['날짜_dt'].dt.date <= end_d) & (all_logs['이름'] == user_name)
        
        filtered_df = all_logs.loc[mask].drop(columns=['날짜_dt'])
        st.dataframe(filtered_df, use_container_width=True)
