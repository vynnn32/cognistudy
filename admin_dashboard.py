import streamlit as st
import pandas as pd
import plotly.express as px
import os
from datetime import datetime

# --- 1. SYSTEM CONFIGURATION ---
st.set_page_config(
    page_title="CogniStudy | Admin Control Center", 
    page_icon="🛠️", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- PERSISTENT STORAGE & TELEMETRY LOGIC ---
CONFIG_FILE = "api_key.txt"
USAGE_FILE = "usage_logs.csv"

def save_key_permanently(key):
    with open(CONFIG_FILE, "w") as f:
        f.write(key)

def load_key_permanently():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return f.read().strip()
    return ""

def get_actual_usage():
    # Define the strict week structure
    days_of_week = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Check if file exists and has correct columns
    if os.path.exists(USAGE_FILE):
        try:
            df = pd.read_csv(USAGE_FILE)
            if 'Day' not in df.columns:
                raise ValueError("Old file format")
            # Group and sort by the week order
            usage = df.groupby('Day')['Tokens'].sum().reindex(days_of_week, fill_value=0).reset_index()
            return usage
        except:
            # If file is corrupted or old, reset it
            return pd.DataFrame({'Day': days_of_week, 'Tokens': [0]*7})
    else:
        # Create fresh file with 0 usage
        df = pd.DataFrame({'Day': days_of_week, 'Tokens': [0]*7})
        df.to_csv(USAGE_FILE, index=False)
        return df

# Initialize System Memory
if "admin_nav" not in st.session_state:
    st.session_state.admin_nav = "System Overview"

if "saved_api_key" not in st.session_state:
    st.session_state.saved_api_key = load_key_permanently()

# --- 2. THE UNIFIED OBSIDIAN ELITE CSS ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');
    :root {
        --primary-orange: #FF6B35;
        --bg-obsidian: #020617;
        --sidebar-navy: #112240;
        --card-slate: rgba(30, 41, 59, 0.4);
        --text-white: #F8FAFC;
        --border-glass: rgba(255, 255, 255, 0.08);
    }
    * { font-family: 'Plus Jakarta Sans', sans-serif; }
    .stApp { background: radial-gradient(circle at 0% 100%, #1e293b, #020617); color: var(--text-white); }
    header[data-testid="stHeader"] { background-color: rgba(0,0,0,0) !important; border: none !important; }
    .stDeployButton { display: none !important; } #MainMenu { visibility: hidden !important; } footer { visibility: hidden !important; }
    [data-testid="stSidebarCollapsedControl"] {
        background-color: var(--sidebar-navy) !important;
        color: var(--primary-orange) !important;
        border: 1px solid var(--border-glass) !important;
        border-radius: 0 10px 10px 0 !important;
        top: 10px !important;
    }
    [data-testid="stSidebar"] { background-color: var(--sidebar-navy) !important; border-right: 1px solid var(--border-glass); }
    .admin-identity { background: linear-gradient(135deg, #FF6B35 0%, #F97316 100%); padding: 20px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 20px rgba(255, 107, 53, 0.2); }
    .admin-card { background: var(--card-slate); backdrop-filter: blur(15px); border: 1px solid var(--border-glass); border-radius: 24px; padding: 24px; transition: 0.3s ease-in-out; }
    div.stButton > button { background-color: transparent; color: #94A3B8; border: 1px solid #334155; padding: 10px 15px; border-radius: 12px; font-weight: 600; width: 100%; text-align: left; transition: 0.2s; }
    div.stButton > button:hover { border-color: var(--primary-orange); color: white; background-color: rgba(255, 107, 53, 0.05); }
    .status-badge { color: #2DD4BF; font-weight: 800; font-size: 11px; border: 1px solid rgba(45, 212, 191, 0.3); background: rgba(45, 212, 191, 0.1); padding: 4px 12px; border-radius: 50px; letter-spacing: 1px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. SIDEBAR NAVIGATION ---
with st.sidebar:
    st.markdown("<h1 style='color:white; font-size:24px; letter-spacing:-1px;'>Cogni<span style='color:#FF6B35'>Admin</span></h1>", unsafe_allow_html=True)
    st.markdown("""<div class="admin-identity"><div style="display:flex; align-items:center; gap:12px;"><div style="background:white; width:40px; height:40px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-weight:800; color:#FF6B35;">AD</div><div><div style="color:white; font-size:14px; font-weight:700;">CyberNauts Dev</div><div style="color:rgba(255,255,255,0.8); font-size:10px; font-weight:800; letter-spacing:1px;">ROOT ACCESS</div></div></div></div>""", unsafe_allow_html=True)
    if st.button("📈 System Overview"): st.session_state.admin_nav = "System Overview"
    if st.button("👥 User Database"): st.session_state.admin_nav = "User Database"
    if st.button("🔑 API Settings"): st.session_state.admin_nav = "API Settings"
    if st.button("📜 Audit Logs"): st.session_state.admin_nav = "Audit Logs"
    st.write("###")
    if st.button("🚪 EXIT TO USER APP"): st.toast("Switching view...")

# --- 4. MAIN CONTROL CENTER ROUTING ---
head_col1, head_col2 = st.columns([3, 1])
with head_col1:
    st.markdown(f"<h1 style='color:white; font-size:42px; font-weight:800; margin-bottom:0;'>{st.session_state.admin_nav}</h1>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:#94A3B8; font-size:18px;'>Orchestrating the CogniStudy Neural Core.</p>", unsafe_allow_html=True)
with head_col2:
    st.write("##")
    status_text = "● SYSTEM OPERATIONAL" if st.session_state.saved_api_key else "● ACTION REQUIRED"
    status_color = "#2DD4BF" if st.session_state.saved_api_key else "#FF6B35"
    st.markdown(f"<div style='text-align:right;'><span class='status-badge' style='color:{status_color}; border-color:{status_color};'>{status_text}</span></div>", unsafe_allow_html=True)

st.write("##")

# PAGE: SYSTEM OVERVIEW
if st.session_state.admin_nav == "System Overview":
    # FETCH ACTUAL DATA
    usage_data = get_actual_usage()
    total_tokens = usage_data['Tokens'].sum()
    estimated_cost = (total_tokens / 1000000) * 0.075 
    
    m1, m2, m3, m4 = st.columns(4)
    with m1: st.markdown('<div class="admin-card"><small style="color:#94A3B8;">ACTIVE USERS</small><h2 style="color:white; margin:0;">1,402</h2></div>', unsafe_allow_html=True)
    with m2: st.markdown(f'<div class="admin-card"><small style="color:#94A3B8;">FILES PROCESSED</small><h2 style="color:white; margin:0;">{int(total_tokens/2000)}</h2></div>', unsafe_allow_html=True)
    with m3: st.markdown(f'<div class="admin-card"><small style="color:#94A3B8;">API COST (MTD)</small><h2 style="color:#FF6B35; margin:0;">${estimated_cost:.5f}</h2></div>', unsafe_allow_html=True)
    with m4: st.markdown('<div class="admin-card"><small style="color:#94A3B8;">TOKEN LIMIT</small><h2 style="color:white; margin:0;">1.2M</h2></div>', unsafe_allow_html=True)
    
    st.write("##"); st.markdown('<div class="admin-card">', unsafe_allow_html=True)
    st.subheader("📊 API Token Consumption (Live Feed)")
    
    # Render Bar Chart with Fixed Order
    fig = px.bar(usage_data, x='Day', y='Tokens')
    fig.update_traces(marker_color='#FF6B35', marker_line_color='#FF6B35', marker_line_width=1.5, opacity=0.8)
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='white', margin=dict(l=0, r=0, t=20, b=0), height=300)
    st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})
    st.markdown('</div>', unsafe_allow_html=True)

# PAGE: USER DATABASE
elif st.session_state.admin_nav == "User Database":
    st.markdown('<div class="admin-card">', unsafe_allow_html=True)
    st.subheader("👥 Registered Scholars")
    user_registry = pd.DataFrame({'Name': ['Vynn Sanchez', 'Juan Dela Cruz'], 'Email': ['vynn@gmail.com', 'juan@dev.ph'], 'Status': ['Premium', 'Free']})
    st.dataframe(user_registry, width="stretch")
    st.markdown('</div>', unsafe_allow_html=True)

# PAGE: API SETTINGS
elif st.session_state.admin_nav == "API Settings":
    col_brain, col_prompt = st.columns([1, 1.2])
    with col_brain:
        st.markdown('<div class="admin-card" style="height:100%;">', unsafe_allow_html=True)
        st.subheader("🤖 Neural Engine Config")
        api_input = st.text_input("Enter API Key", value=st.session_state.saved_api_key, type="password", key="api_key_field")
        if st.button("💾 SAVE CONFIG"):
            if api_input:
                save_key_permanently(api_input)
                st.session_state.saved_api_key = api_input
                st.success("Key Secured.")
        st.markdown('</div>', unsafe_allow_html=True)
    with col_prompt:
        st.markdown('<div class="admin-card" style="height:100%;">', unsafe_allow_html=True)
        st.subheader("📝 Master System Prompt")
        st.text_area("Instructions", "You are the CogniStudy Neural Engine...", height=210)
        st.markdown('</div>', unsafe_allow_html=True)

# PAGE: AUDIT LOGS
elif st.session_state.admin_nav == "Audit Logs":
    st.markdown('<div class="admin-card">', unsafe_allow_html=True)
    st.subheader("📜 System Audit Trail")
    st.write("No critical events recorded yet.")
    st.markdown('</div>', unsafe_allow_html=True)