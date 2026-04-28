import streamlit as st
import os
import base64

# --- 1. SYSTEM CONFIGURATION ---
st.set_page_config(
    page_title="CogniStudy | Sign Up", 
    page_icon="🧠", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# Function to handle logo professionally
def get_base64(bin_file):
    if os.path.exists(bin_file):
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    return ""

# --- 2. PIXEL-PERFECT CSS ---
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');

:root {{
    --primary-orange: #FF6B35;
    --glow-navy: #1e293b;
    --bg-obsidian: #020617;
    --input-bg: rgba(38, 50, 69, 0.6);
    --green-box-nudge: 60px; 
    --text-vertical-nudge: -5px; 
    --title-horizontal-nudge: 8px; 
}}

* {{ font-family: 'Plus Jakarta Sans', sans-serif; }}

html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"], .stApp {{
    overflow: hidden !important;
    height: 100vh !important;
    width: 100vw !important;
}}
[data-testid="block-container"] {{ padding: 0px !important; overflow: hidden !important; }}
header, footer, .stDeployButton {{ display: none !important; }}

.stApp {{
    background: radial-gradient(circle at 0% 100%, var(--glow-navy) 0%, var(--bg-obsidian) 100%);
}}

.header-zone {{
    width: 100%;
    height: 50px; 
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}}
.logo-img {{
    width: 70px; 
    margin-bottom: 2px;
    transform: translateY(-58px); 
}}
.brand-tag {{
    font-size: 10px;
    color: white;
    letter-spacing: 4px;
    font-weight: 500;
    text-transform: uppercase;
    transform: translateY(-58px);
}}

.orange-line-divider {{
    width: 100vw;
    height: 2px;
    background-color: var(--primary-orange);
    position: relative;
    left: 50%;
    right: 50%;
    margin-left: -50vw;
    margin-right: -50vw;
}}

.green-box-container {{ margin-top: var(--green-box-nudge) !important; }}

.title-main {{ 
    font-size: 52px; 
    font-weight: 800; 
    color: white; 
    text-align: center; 
    margin: 0px !important; 
    letter-spacing: -2px;
    transform: translateX(var(--title-horizontal-nudge));
}}

.title-sub {{ 
    font-size: 32px; 
    font-weight: 600; 
    color: white; 
    text-align: center; 
    margin: 0px 0px 20px 0px; 
    transform: translateX(var(--title-horizontal-nudge));
}}

[data-testid="stTextInput"] > div [data-baseweb="input"] {{
    background-color: var(--input-bg) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 10px !important;
    height: 42px;
}}

div.stButton > button {{
    background: linear-gradient(90deg, #FF6B35, #F97316) !important;
    color: white !important;
    border: none !important;
    padding: 10px 45px !important;
    border-radius: 50px !important;
    font-weight: 700 !important;
    font-size: 14px !important;
    box-shadow: 0 4px 15px rgba(255, 107, 53, 0.3);
    width: auto !important;
    min-width: 140px;
    position: relative !important;
    left: 22px !important; 
    margin-top: -5px;
}}

/* --- TEXT-ONLY CLICKABLE LINK --- */
.footer-text-nudge {{
    transform: translateY(var(--text-vertical-nudge)) !important;
    position: relative;
    z-index: 99;
}}

.footer-link {{
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 11px;
    color: #94A3B8;
    text-decoration: none;
    cursor: pointer;
    display: block;
    text-align: left;
    transition: color 0.3s;
}}

.footer-link:hover {{
    color: #FF6B35;
}}
</style>
""", unsafe_allow_html=True)

# --- 3. UI CONSTRUCTION ---
logo_b64 = get_base64("cnlogo.png")
st.markdown(f"""
<div class="header-zone">
    <img src="data:image/png;base64,{logo_b64}" class="logo-img">
    <div class="brand-tag">CyberNauts</div>
</div>
<div class="orange-line-divider"></div>
""", unsafe_allow_html=True)

_, center_col, _ = st.columns([1.5, 1, 1.5])

with center_col:
    st.markdown('<div class="green-box-container">', unsafe_allow_html=True)
    st.markdown('<h1 class="title-main">CogniStudy</h1>', unsafe_allow_html=True)
    st.markdown('<h2 class="title-sub">Sign up</h2>', unsafe_allow_html=True)
    
    # Inputs
    st.markdown('<p style="font-size:14px; font-weight:500; margin-bottom: 5px;">Fullname</p>', unsafe_allow_html=True)
    st.text_input("su_fn_label", label_visibility="collapsed", key="su_fn")
    
    st.markdown('<p style="font-size:14px; font-weight:500; margin-top:8px; margin-bottom: 5px;">Email</p>', unsafe_allow_html=True)
    st.text_input("su_em_label", label_visibility="collapsed", key="su_em")
    
    st.markdown('<p style="font-size:14px; font-weight:500; margin-top:8px; margin-bottom: 5px;">Password</p>', unsafe_allow_html=True)
    st.text_input("su_pw_label", type="password", label_visibility="collapsed", key="su_pw")
    
    st.markdown('<p style="font-size:14px; font-weight:500; margin-top:8px; margin-bottom: 5px;">Confirm Password</p>', unsafe_allow_html=True)
    st.text_input("su_cp_label", type="password", label_visibility="collapsed", key="su_cp")
    
    # Footer Area
    c1, c2 = st.columns([1.6, 1])
    with c1:
        st.markdown("""
        <div class="footer-text-nudge">
            <p class="footer-link" id="sign_in_text">Already have an account? Sign in</p>
        </div>
        <script>
        const signInText = document.getElementById('sign_in_text');
        signInText.onclick = () => { window.parent.postMessage({clicked: 'sign_in'}, '*'); };
        </script>
        """, unsafe_allow_html=True)
        
    with c2:
        if st.button("Sign up"):
            st.toast("Redirecting...")

    st.markdown('</div>', unsafe_allow_html=True)