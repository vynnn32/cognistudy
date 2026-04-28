import streamlit as st
import os
import base64

# --- 1. SYSTEM CONFIGURATION ---
st.set_page_config(
    page_title="CogniStudy | Secure Login", 
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
    }}

    * {{ font-family: 'Plus Jakarta Sans', sans-serif; }}

    html, body, [data-testid="stAppViewContainer"] {{
        overflow: hidden !important;
        height: 100vh !important;
    }}
    [data-testid="block-container"] {{ padding: 0px !important; }}
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
        padding-top: 0px; 
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

    .title-main {{
        font-size: 52px;
        font-weight: 800;
        color: white;
        text-align: center;
        margin-top: 10px !important; 
        margin-bottom: 0px;
        letter-spacing: -2px;
    }}
    
    .title-sub {{
        font-size: 32px;
        font-weight: 600;
        color: white;
        text-align: center;
        margin-top: 5px;
        margin-bottom: 40px;
    }}

    [data-testid="stTextInput"] > div [data-baseweb="input"] {{
        background-color: var(--input-bg) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 10px !important;
        height: 44px;
    }}
    .stTextInput input {{
        background-color: transparent !important;
        color: white !important;
        border: none !important;
    }}

    [data-testid="stTextInputPasswordVisibility"] {{
        color: white !important;
        background: transparent !important;
        transform: scale(0.85);
    }}

    [data-testid="column"]:nth-of-type(2) {{
        padding-right: 0px !important;
        display: flex;
        justify-content: flex-end;
    }}

    div.stButton > button {{
        background: linear-gradient(90deg, #FF6B35, #F97316) !important;
        color: white !important;
        border: none !important;
        padding: 10px 45px !important;
        border-radius: 50px !important;
        font-weight: 700 !important;
        font-size: 14px !important;
        margin-top: -3px;
        box-shadow: 0 4px 15px rgba(255, 107, 53, 0.3);
        white-space: nowrap !important;
        width: auto !important;
        min-width: 140px;
        position: relative !important;
        left: 22px !important; 
    }}

    /* Footer clickable text (text-only buttons) */
    .footer-link {{
        color: white !important;
        font-size: 11px !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        cursor: pointer;
        transition: color 0.3s ease;
        display: block;
        text-decoration: none;
    }}
    .footer-link.signup {{
        margin-top: -1px;
    }}
    .footer-link:hover {{
        color: var(--primary-orange) !important;
    }}
    .footer-link#forgot_pw {{
        margin-top: -10px;
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
    st.markdown('<div style="height: 50px;"></div>', unsafe_allow_html=True)
    
    st.markdown('<h1 class="title-main">CogniStudy</h1>', unsafe_allow_html=True)
    st.markdown('<h2 class="title-sub">Sign in</h2>', unsafe_allow_html=True)
    
    st.markdown('<p style="font-size:14px; font-weight:500;">Fullname</p>', unsafe_allow_html=True)
    st.text_input("fn", label_visibility="collapsed", key="v17_fn")
    
    st.markdown('<p style="font-size:14px; font-weight:500; margin-top:10px;">Password</p>', unsafe_allow_html=True)
    st.text_input("pw", type="password", label_visibility="collapsed", key="v17_pw")
    
    # Footer Row
    c1, c2 = st.columns([1.5, 1])
    with c1:
        st.markdown(
            """
            <p class="footer-link" id="forgot_pw">Forgot password</p>
            <p class="footer-link signup" id="sign_up">Don't have an account? Sign up</p>
            """,
            unsafe_allow_html=True
        )

    with c2:
        if st.button("Sign in"):
            st.toast("Neural interface connected.")

# --- 4. Handle text clicks using session state ---
if "clicked" not in st.session_state:
    st.session_state.clicked = None

# JS to Python click detection
st.write("""
<script>
const forgot = document.getElementById('forgot_pw');
const signup = document.getElementById('sign_up');

forgot.onclick = () => { window.parent.postMessage({clicked: 'forgot_pw'}, '*'); };
signup.onclick = () => { window.parent.postMessage({clicked: 'sign_up'}, '*'); };
</script>
""", unsafe_allow_html=True)