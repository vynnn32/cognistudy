import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

# --- 1. SYSTEM CONFIGURATION ---
st.set_page_config(
    page_title="CogniStudy | Scholar Workspace", 
    page_icon="🧠", 
    layout="wide",
    initial_sidebar_state="expanded" 
)

# --- 2. SESSION STATE ---
if "current_page" not in st.session_state:
    st.session_state.current_page = "Overview"

# --- 3. THE UNIFIED OBSIDIAN ELITE CSS ---
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

    .stApp {
        background: radial-gradient(circle at 0% 100%, #1e293b, #020617);
        color: var(--text-white);
    }

    /* HARDWARE OVERLAY ENGINE */
    #brightness-layer {
        position: fixed;
        top: 0; left: 0; width: 100vw; height: 100vh;
        background: black;
        pointer-events: none;
        z-index: 9999999;
    }

    #eye-protection-layer {
        position: fixed;
        top: 0; left: 0; width: 100vw; height: 100vh;
        background: #ff9100;
        pointer-events: none;
        z-index: 9999998;
    }

    header[data-testid="stHeader"] { background-color: rgba(0,0,0,0) !important; border: none !important; }
    .stDeployButton { display: none !important; }
    #MainMenu { visibility: hidden !important; }
    footer { visibility: hidden !important; }

    [data-testid="stSidebarCollapsedControl"] {
        background-color: var(--sidebar-navy) !important;
        color: var(--primary-orange) !important;
        border: 1px solid var(--border-glass) !important;
        border-radius: 0 10px 10px 0 !important;
        top: 10px !important;
    }

    [data-testid="stSidebar"] {
        background-color: var(--sidebar-navy) !important;
        border-right: 1px solid var(--border-glass);
    }

    .user-identity {
        background: linear-gradient(135deg, #FF6B35 0%, #F97316 100%);
        padding: 20px; border-radius: 20px; margin-bottom: 25px;
        box-shadow: 0 10px 20px rgba(255, 107, 53, 0.2);
    }

    div.stButton > button {
        background-color: transparent;
        color: #94A3B8;
        border: 1px solid #334155;
        padding: 10px 15px;
        border-radius: 12px;
        font-weight: 600;
        width: 100%;
        text-align: left;
        transition: 0.2s;
    }
    div.stButton > button:hover {
        border-color: var(--primary-orange);
        color: white;
        background-color: rgba(255, 107, 53, 0.05);
    }

    .bento-card {
        background: var(--card-slate);
        backdrop-filter: blur(15px);
        border: 1px solid var(--border-glass);
        border-radius: 24px;
        padding: 24px;
        transition: 0.3s ease-in-out;
    }

    .m-bar-bg { height: 8px; background: rgba(255, 255, 255, 0.05); border-radius: 10px; margin-top: 15px; }
    .m-bar-fill { height: 100%; background: linear-gradient(90deg, #FF6B35, #F97316); border-radius: 10px; box-shadow: 0 0 15px rgba(255, 107, 53, 0.4); }

    .logout-box > div > button {
        background: linear-gradient(90deg, #FF6B35, #F97316) !important;
        color: white !important;
        border: none !important;
        font-weight: 800 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 4. SIDEBAR NAVIGATION & SYSTEM MODES ---
with st.sidebar:
    st.markdown("<h1 style='color:white; font-size:24px; letter-spacing:-1px;'>Cogni<span style='color:#FF6B35'>Study</span></h1>", unsafe_allow_html=True)
    
    st.markdown("""
        <div class="user-identity">
            <div style="display:flex; align-items:center; gap:12px;">
                <div style="background:white; width:40px; height:40px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-weight:800; color:#FF6B35;">VS</div>
                <div>
                    <div style="color:white; font-size:14px; font-weight:700;">Vynn Sanchez</div>
                    <div style="color:rgba(255,255,255,0.8); font-size:10px; font-weight:800; letter-spacing:1px;">MASTER SCHOLAR</div>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if st.button("🏠 System Overview"):
        st.session_state.current_page = "Overview"
    if st.button("📚 Knowledge Base"):
        st.session_state.current_page = "Library"
    if st.button("🎯 Mastery Analytics"):
        st.session_state.current_page = "Analytics"
    
    st.write("###")
    st.markdown("<p style='font-size:11px; color:#94A3B8; font-weight:700; margin-bottom:10px; letter-spacing:1px;'>SYSTEM</p>", unsafe_allow_html=True)
    
    # WORKING BRIGHTNESS SLIDER
    # We use a slider to control the opacity of the black fixed div
    brightness = st.slider("Adjust Brightness", 10, 100, 100)
    
    # WORKING EYE PROTECTION TOGGLE
    # We use a toggle to control the display of the amber fixed div
    eye_prot = st.toggle("Eye Protection Mode")
    
    # Dynamic Overlay Logic
    b_opacity = (100 - brightness) / 100 * 0.8  # Caps at 80% darkness for safety
    e_display = "block" if eye_prot else "none"
    e_opacity = 0.15 if eye_prot else 0

    st.markdown(f"""
        <div id="brightness-layer" style="opacity: {b_opacity};"></div>
        <div id="eye-protection-layer" style="display: {e_display}; opacity: {e_opacity};"></div>
    """, unsafe_allow_html=True)
    
    st.write("###")
    st.markdown('<div class="logout-box">', unsafe_allow_html=True)
    if st.button("🚪 LOG OUT"):
        st.toast("Ending session...")
    st.markdown('</div>', unsafe_allow_html=True)

# --- 5. DYNAMIC PAGE CONTENT ---
if st.session_state.current_page == "Overview":
    now = datetime.now()
    greeting = "Good Evening" if now.hour > 18 else "Good Day"
    head_col1, head_col2 = st.columns([3, 1])
    with head_col1:
        st.markdown(f"<h1 style='color:white; font-size:42px; font-weight:800; margin-bottom:0;'>{greeting}, Vynn.</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color:#94A3B8; font-size:18px;'>Your neural processing is 12% faster today.</p>", unsafe_allow_html=True)
    with head_col2:
        st.write("##")
        st.markdown('<div style="text-align:right;"><span style="color:#2DD4BF; border:1px solid rgba(45,212,191,0.3); background:rgba(45,212,191,0.1); padding:4px 12px; border-radius:50px; font-size:11px; font-weight:800;">● SYSTEM OPERATIONAL</span></div>', unsafe_allow_html=True)

    st.write("##")
    col_engine, col_radar = st.columns([1.8, 1])
    with col_engine:
        st.markdown('<div class="bento-card" style="height:100%;"><div style="border: 2px dashed rgba(255,107,53,0.3); border-radius: 20px; padding: 60px 20px; text-align: center;"><h1 style="color:white; font-weight:800; margin-bottom:5px;">Neural Engine</h1><p style="color:#94A3B8; font-size:14px;">Drop your modules for autonomous synthesis.</p></div>', unsafe_allow_html=True)
        file = st.file_uploader("Internal_Upload", type="pdf", label_visibility="collapsed")
        if file:
            st.info(f"File Ready: {file.name}")
            if st.button("🚀 EXECUTE SYNTHESIS"): st.toast("Processing...")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_radar:
        st.markdown('<div class="bento-card"><p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0; letter-spacing:1px;">GLOBAL RANK</p><h1 style="margin:0; font-size:38px; font-weight:800; color:white;">#1,204</h1><div class="m-bar-bg"><div class="m-bar-fill" style="width: 75%;"></div></div><p style="color:#FF6B35; font-size:11px; font-weight:800; margin-top:5px;">TOP 5% OF CYBERNAUTS</p></div><div style="margin-top:20px;"></div>', unsafe_allow_html=True)
        st.markdown("<div class='bento-card'>", unsafe_allow_html=True)
        st.markdown("<p style='color:white; font-weight:800; font-size:13px; margin-top:0; letter-spacing:1px;'>SUBJECT MASTERY</p>", unsafe_allow_html=True)
        mastery_data = pd.DataFrame({'Subject': ['Math', 'Bio', 'Hist', 'Eng'], 'Level': [85, 92, 65, 78]})
        fig = px.line_polar(mastery_data, r='Level', theta='Subject', line_close=True)
        fig.update_traces(fill='toself', line_color='#FF6B35', fillcolor='rgba(255, 107, 53, 0.4)')
        fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='white', size=11), polar=dict(bgcolor='rgba(0,0,0,0)', radialaxis=dict(visible=False, range=[0, 100])), margin=dict(l=50, r=50, t=40, b=40), height=280)
        st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})
        st.markdown("</div>", unsafe_allow_html=True)

    st.write("##"); st.markdown("<h3 style='font-weight:800; color:white;'>Intelligence Feed</h3>", unsafe_allow_html=True)
    f1, f2, f3 = st.columns(3)
    with f1: st.markdown('<div class="bento-card"><small style="color:#2DD4BF; font-weight:800; letter-spacing:1px;">INSIGHT</small><p style="margin-top:10px; font-size:14px; color:white;">Focus on <b>Cell Division</b> today.</p></div>', unsafe_allow_html=True)
    with f2: st.markdown('<div class="bento-card"><small style="color:#FF6B35; font-weight:800; letter-spacing:1px;">REMINDER</small><p style="margin-top:10px; font-size:14px; color:white;"><b>Math Exam</b> in 2 days.</p></div>', unsafe_allow_html=True)
    with f3: st.markdown('<div class="bento-card"><small style="color:#94A3B8; font-weight:800; letter-spacing:1px;">COMMUNITY</small><p style="margin-top:10px; font-size:14px; color:white;">3 classmates studying History now.</p></div>', unsafe_allow_html=True)

elif st.session_state.current_page == "Library":
    st.markdown("<h1 style='color:white; font-size:42px; font-weight:800;'>Knowledge Base</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color:#94A3B8; font-size:18px;'>Access and manage your synthesized modules.</p>", unsafe_allow_html=True)
    st.write("##"); st.markdown('<div class="bento-card">', unsafe_allow_html=True)
    lib_data = pd.DataFrame({'File Name': ['Bio_U1.pdf', 'Algebra.pdf'], 'Subject': ['Science', 'Math'], 'Date': ['2026-04-01', '2026-03-28']})
    st.dataframe(lib_data, width="stretch"); st.markdown('</div>', unsafe_allow_html=True)

elif st.session_state.current_page == "Analytics":
    st.markdown("<h1 style='color:white; font-size:42px; font-weight:800;'>Mastery Analytics</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color:#94A3B8; font-size:18px;'>Visualizing your academic growth curve.</p>", unsafe_allow_html=True)
    st.write("##"); st.markdown('<div class="bento-card">', unsafe_allow_html=True)
    chart_data = pd.DataFrame({'Subject': ['Math', 'Bio', 'Hist', 'Eng'], 'Progress': [85, 92, 65, 78]})
    st.plotly_chart(px.bar(chart_data, x='Subject', y='Progress', color_discrete_sequence=['#FF6B35']).update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='white'), width="stretch")
    st.markdown('</div>', unsafe_allow_html=True)