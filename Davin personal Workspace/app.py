import streamlit as st
import sqlite3
import hashlib
import datetime
import calendar as pycal
import pandas as pd
import requests
import os
import re
import threading
import time
from zoneinfo import ZoneInfo

# ---------------------------------------------------------
# TELEGRAM BOT CONFIGURATION
# ---------------------------------------------------------
def get_bot_token():
    # Prioritas: .streamlit/secrets.toml -> environment variable -> token lama (fallback)
    try:
        if "TELEGRAM_BOT_TOKEN" in st.secrets:
            return st.secrets["TELEGRAM_BOT_TOKEN"]
    except Exception:
        pass
    return os.environ.get("TELEGRAM_BOT_TOKEN", "8827466549:AAEbDgqq8cl5ebmjwSkFyRdhO9Yah8hRwag")

TELEGRAM_BOT_TOKEN = get_bot_token()

# Dictionary pilihan Chat ID dengan label namanya
TELEGRAM_TARGETS = {
    "Davin (8696187764)": "8696187764",
    "Anggie (8632914990)": "8632914990"
}

# Pengaturan pengingat otomatis
APP_TZ = ZoneInfo("Asia/Jakarta")   # ganti kalau zona waktunya beda, misal "Asia/Singapore"
REMINDER_CHECK_INTERVAL = 20        # app cek database tiap sekian detik
MAX_LATE_MINUTES = 120              # event yang telat lebih dari ini tidak dikirim lagi

def send_telegram_alert(chat_id, message):
    if not chat_id:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Coba Markdown dulu, kalau gagal (misal judul ada karakter aneh) kirim teks biasa
    for mode in ("Markdown", None):
        payload = {"chat_id": chat_id, "text": message}
        if mode:
            payload["parse_mode"] = mode
        try:
            res = requests.post(url, json=payload, timeout=5)
            if res.status_code == 200:
                return True
        except Exception as e:
            print(f"Telegram Send Error: {e}")
            return False
    return False

def check_due_reminders():
    """Kirim pengingat Telegram untuk event yang jamnya sudah tiba, lalu tandai 'Sent'."""
    now = datetime.datetime.now(APP_TZ).replace(tzinfo=None)
    conn = sqlite3.connect('users.db', timeout=10)
    try:
        rows = conn.execute(
            "SELECT id, user, date, start_time, title, location FROM work_events "
            "WHERE reminder_channel='Telegram Bot' AND date <= ?", (str(now.date()),)
        ).fetchall()
        for ev_id, ev_user, ev_date, ev_time, ev_title, chat_id in rows:
            try:
                ev_dt = datetime.datetime.strptime(f"{ev_date} {ev_time.strip()}", "%Y-%m-%d %H:%M")
            except (ValueError, AttributeError):
                continue
            late_min = (now - ev_dt).total_seconds() / 60
            if late_min < 0 or late_min > MAX_LATE_MINUTES:
                continue
            msg = (f"⏰ *PENGINGAT JADWAL*\n\nHalo *{ev_user}*!\n"
                   f"Waktunya: 📌 *{ev_title}*\n📅 {ev_date}\n🕒 Jam *{ev_time}*")
            if send_telegram_alert(chat_id, msg):
                conn.execute("UPDATE work_events SET reminder_channel='Sent' WHERE id=?", (ev_id,))
                conn.commit()
    finally:
        conn.close()

def _reminder_loop():
    while True:
        try:
            check_due_reminders()
        except Exception as e:
            print(f"Reminder loop error: {e}")
        time.sleep(REMINDER_CHECK_INTERVAL)

@st.cache_resource
def start_reminder_scheduler():
    t = threading.Thread(target=_reminder_loop, daemon=True)
    t.start()
    return t

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
def parse_amount(val_str):
    if not val_str:
        return 0.0
    val_clean = str(val_str).lower().replace("rp", "").replace(".", "").replace(" ", "").strip()
    val_clean = val_clean.replace(",", ".")
    try:
        if val_clean.endswith("k") or val_clean.endswith("rb"):
            return float(val_clean.replace("k", "").replace("rb", "").strip()) * 1_000
        elif val_clean.endswith("m") or val_clean.endswith("jt"):
            return float(val_clean.replace("m", "").replace("jt", "").strip()) * 1_000_000
        else:
            return float(val_clean)
    except ValueError:
        return 0.0

def fmt_idr(val):
    try:
        return f"{float(val):,.0f}".replace(",", ".")
    except Exception:
        return "0"

def normalize_time(t_str):
    """Terima '9:30' / '09:30' / '09.30', kembalikan 'HH:MM' atau None kalau tidak valid."""
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", str(t_str or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"

# ---------------------------------------------------------
# DATABASE SETUP (AUTO MIGRATION & SCHEMA FIX)
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY, 
                password TEXT NOT NULL)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, date DATE, 
                type TEXT, category TEXT, description TEXT, amount REAL, payment_method TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS fin_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, target_name TEXT, 
                target_amount REAL, current_amount REAL, target_date DATE)''')

    c.execute('''CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, habit_name TEXT, 
                frequency TEXT, streak INTEGER DEFAULT 0, last_completed DATE)''')

    c.execute('''CREATE TABLE IF NOT EXISTS todo_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, task_name TEXT, 
                priority TEXT, is_done INTEGER DEFAULT 0, created_date DATE)''')

    c.execute('''CREATE TABLE IF NOT EXISTS notes_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, title TEXT, 
                content TEXT, created_at TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS work_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, date DATE, start_time TEXT, end_time TEXT,
                title TEXT, type TEXT, location TEXT, priority TEXT, reminder_channel TEXT)''')

    # MIGRATION SAFETY CHECK UNTUK SEMUA TABEL
    c.execute("PRAGMA table_info(transactions)")
    t_cols = [col[1] for col in c.fetchall()]
    if 'description' not in t_cols:
        try: c.execute("ALTER TABLE transactions ADD COLUMN description TEXT")
        except Exception: pass
    if 'payment_method' not in t_cols:
        try: c.execute("ALTER TABLE transactions ADD COLUMN payment_method TEXT")
        except Exception: pass

    c.execute("PRAGMA table_info(notes_log)")
    n_cols = [col[1] for col in c.fetchall()]
    if 'created_at' not in n_cols:
        try: c.execute("ALTER TABLE notes_log ADD COLUMN created_at TIMESTAMP")
        except Exception: pass

    c.execute("PRAGMA table_info(todo_list)")
    td_cols = [col[1] for col in c.fetchall()]
    if 'task_name' not in td_cols:
        try: c.execute("ALTER TABLE todo_list ADD COLUMN task_name TEXT")
        except Exception: pass
    if 'priority' not in td_cols:
        try: c.execute("ALTER TABLE todo_list ADD COLUMN priority TEXT")
        except Exception: pass
    if 'is_done' not in td_cols:
        try: c.execute("ALTER TABLE todo_list ADD COLUMN is_done INTEGER DEFAULT 0")
        except Exception: pass
    if 'created_date' not in td_cols:
        try: c.execute("ALTER TABLE todo_list ADD COLUMN created_date DATE")
        except Exception: pass

    c.execute("PRAGMA table_info(fin_goals)")
    fg_cols = [col[1] for col in c.fetchall()]
    if 'target_name' not in fg_cols:
        try: c.execute("ALTER TABLE fin_goals ADD COLUMN target_name TEXT")
        except Exception: pass
    if 'target_amount' not in fg_cols:
        try: c.execute("ALTER TABLE fin_goals ADD COLUMN target_amount REAL")
        except Exception: pass
    if 'current_amount' not in fg_cols:
        try: c.execute("ALTER TABLE fin_goals ADD COLUMN current_amount REAL")
        except Exception: pass
    if 'target_date' not in fg_cols:
        try: c.execute("ALTER TABLE fin_goals ADD COLUMN target_date DATE")
        except Exception: pass

    c.execute("PRAGMA table_info(habits)")
    hb_cols = [col[1] for col in c.fetchall()]
    if 'habit_name' not in hb_cols:
        try: c.execute("ALTER TABLE habits ADD COLUMN habit_name TEXT")
        except Exception: pass
    if 'frequency' not in hb_cols:
        try: c.execute("ALTER TABLE habits ADD COLUMN frequency TEXT")
        except Exception: pass
    if 'streak' not in hb_cols:
        try: c.execute("ALTER TABLE habits ADD COLUMN streak INTEGER DEFAULT 0")
        except Exception: pass
    if 'last_completed' not in hb_cols:
        try: c.execute("ALTER TABLE habits ADD COLUMN last_completed DATE")
        except Exception: pass

    c.execute("PRAGMA table_info(work_events)")
    we_cols = [col[1] for col in c.fetchall()]
    if 'location' not in we_cols:
        try: c.execute("ALTER TABLE work_events ADD COLUMN location TEXT")
        except Exception: pass
    if 'reminder_channel' not in we_cols:
        try: c.execute("ALTER TABLE work_events ADD COLUMN reminder_channel TEXT")
        except Exception: pass

    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hash_password(password)))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def check_login(username, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user is not None

# ---------------------------------------------------------
# STATE MANAGEMENT
# ---------------------------------------------------------
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user' not in st.session_state:
    st.session_state['user'] = "Davin"
if 'quick_amount' not in st.session_state:
    st.session_state['quick_amount'] = "0"
if 'show_customize' not in st.session_state:
    st.session_state['show_customize'] = False
if 'theme_color' not in st.session_state:
    st.session_state['theme_color'] = "Cyber Purple"
if 'cal_year' not in st.session_state:
    st.session_state['cal_year'] = datetime.date.today().year
if 'cal_month' not in st.session_state:
    st.session_state['cal_month'] = datetime.date.today().month
if 'selected_cal_date' not in st.session_state:
    st.session_state['selected_cal_date'] = datetime.date.today()
if 'view_mode' not in st.session_state:
    # dibaca dari URL supaya pilihan mode tidak hilang saat halaman di-refresh
    st.session_state['view_mode'] = "phone" if st.query_params.get("mode") == "phone" else "desktop"

# ---------------------------------------------------------
# STREAMLIT CONFIG & DYNAMIC THEMING STYLING
# ---------------------------------------------------------
st.set_page_config(
    page_title="Dvly UNIFIED WORKSPACE",
    layout="wide",
    initial_sidebar_state="collapsed"
)

init_db()
start_reminder_scheduler()

# Tentukan kode warna berdasarkan tema yang dipilih
if st.session_state['theme_color'] == "Soft Pink":
    bg_app = "#130811"
    glow_color = "rgba(244, 114, 182, 0.25)"
    brand_color = "#f472b6"
    card_bg = "rgba(26, 10, 24, 0.7)"
    card_border = "rgba(244, 114, 182, 0.3)"
    tab_grad_1 = "#db2777"
    tab_grad_2 = "#9d174d"
    tab_hover_1 = "#ec4899"
    tab_hover_2 = "#db2777"
    btn_grad_1 = "#db2777"
    btn_grad_2 = "#be185d"
    btn_hover_1 = "#f472b6"
    btn_hover_2 = "#db2777"
    today_circle_bg = "#ec4899"
    today_circle_shadow = "rgba(236, 72, 153, 0.8)"
    badge_sent = "#059669"
    badge_pending = "#be185d"
else: # Cyber Purple (Default)
    bg_app = "#06030d"
    glow_color = "rgba(147, 51, 234, 0.28)"
    brand_color = "#c084fc"
    card_bg = "rgba(14, 8, 28, 0.65)"
    card_border = "rgba(168, 85, 247, 0.25)"
    tab_grad_1 = "#6b21a8"
    tab_grad_2 = "#4c1d95"
    tab_hover_1 = "#7e22ce"
    tab_hover_2 = "#6b21a8"
    btn_grad_1 = "#7e22ce"
    btn_grad_2 = "#581c87"
    btn_hover_1 = "#9333ea"
    btn_hover_2 = "#7e22ce"
    today_circle_bg = "#9333ea"
    today_circle_shadow = "rgba(147, 51, 234, 0.8)"
    badge_sent = "#059669"
    badge_pending = "#6b21a8"

st.markdown(f"""
    <style>
    /* Dark Futuristic / Soft Pink Background */
    .stApp {{
        background-color: {bg_app} !important;
        color: #e2d8f3 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }}
    header {{visibility: hidden !important;}}

    /* Background Ambient Top Glow */
    .stApp::before {{
        content: ""; position: fixed; top: -120px; left: -120px;
        width: 500px; height: 500px;
        background: radial-gradient(circle, {glow_color} 0%, rgba(6, 3, 13, 0) 70%);
        z-index: 0; pointer-events: none;
    }}

    /* LOGIN CARD CONTAINER */
    div[data-testid="stVerticalBlock"] > div:has(div.login-card-anchor) {{
        position: relative; z-index: 1; 
        background: {card_bg} !important;
        backdrop-filter: blur(24px) !important; 
        padding: 38px 42px !important; border-radius: 16px !important;
        border: 1px solid {card_border} !important; 
        box-shadow: 0 0 35px rgba(0, 0, 0, 0.8), inset 0 0 15px {card_border} !important;
    }}

    .brand-title-login {{
        font-size: 36px; font-weight: 800; color: #ffffff; text-align: center; margin-bottom: 0px;
        letter-spacing: -0.5px; text-shadow: 0 0 15px {brand_color};
    }}
    .brand-subtitle-login {{
        font-size: 10px; font-weight: 700; letter-spacing: 2px; color: {brand_color};
        text-align: center; text-transform: uppercase; margin-bottom: 24px;
    }}

    /* NAV BUTTON TABS - DYNAMIC CAPSULES */
    div[data-testid="stRadio"] > div {{
        flex-direction: row !important;
        justify-content: space-between !important;
        background: transparent !important;
        padding: 0px !important;
        gap: 12px !important;
        width: 100% !important;
    }}
    
    div[data-testid="stRadio"] > div > label {{
        flex: 1 1 0% !important;
        text-align: center !important;
        justify-content: center !important;
        background: linear-gradient(135deg, {tab_grad_1} 0%, {tab_grad_2} 100%) !important;
        border: 1px solid {card_border} !important;
        padding: 12px 16px !important;
        border-radius: 12px !important;
        color: #ffffff !important;
        font-size: 11px !important;
        font-weight: 800 !important;
        letter-spacing: 1.2px !important;
        text-transform: uppercase !important;
        transition: all 0.25s ease !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.4) !important;
        cursor: pointer !important;
    }}
    
    div[data-testid="stRadio"] > div > label:hover {{
        background: linear-gradient(135deg, {tab_hover_1} 0%, {tab_hover_2} 100%) !important;
        border-color: {brand_color} !important;
        box-shadow: 0 0 22px {glow_color} !important;
        transform: translateY(-2px) !important;
    }}

    div[data-testid="stRadio"] label div[role="radio"],
    div[data-testid="stRadio"] label > div:first-child {{
        display: none !important;
    }}

    /* INPUT STYLING */
    .stTextInput label, .stSelectbox label, .stDateInput label, .stTextArea label, .stNumberInput label {{
        color: {brand_color} !important;
        font-size: 11px !important;
        font-weight: 700 !important;
        letter-spacing: 1px !important;
        text-transform: uppercase !important;
    }}
    .stTextInput > div > div > input, .stSelectbox > div > div, .stTextArea > div > div > textarea, .stNumberInput > div > div > input {{
        background-color: {card_bg} !important;
        color: #f3e8ff !important;
        border: 1px solid {card_border} !important;
        border-radius: 8px !important;
    }}

    /* BUTTONS */
    .stButton > button {{
        background: linear-gradient(135deg, {btn_grad_1} 0%, {btn_grad_2} 100%) !important;
        color: #ffffff !important;
        border-radius: 8px !important;
        padding: 8px 18px !important;
        font-size: 11px !important;
        font-weight: 700 !important;
        letter-spacing: 1px !important;
        text-transform: uppercase !important;
        border: 1px solid {card_border} !important;
        transition: all 0.2s ease !important;
    }}
    .stButton > button:hover {{
        background: linear-gradient(135deg, {btn_hover_1} 0%, {btn_hover_2} 100%) !important;
        box-shadow: 0 0 18px {glow_color} !important;
    }}

    /* WORKSPACE METRIC & GLASS CARDS */
    .metric-glass-card {{
        background: {card_bg};
        border: 1px solid {card_border};
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        transition: all 0.3s ease;
    }}
    .metric-glass-card:hover {{
        border-color: {brand_color};
        box-shadow: 0 0 20px {glow_color};
    }}

    .workspace-card {{
        background: {card_bg};
        border: 1px solid {card_border};
        border-radius: 12px; padding: 20px; margin-bottom: 16px;
    }}

    /* POST-IT NOTE CARD STYLING */
    .postit-card {{
        background: linear-gradient(145deg, rgba(30, 16, 58, 0.9) 0%, {card_bg} 100%);
        border-left: 4px solid {brand_color};
        border-top: 1px solid {card_border};
        border-right: 1px solid {card_border};
        border-bottom: 1px solid {card_border};
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 14px;
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
        transition: all 0.25s ease;
    }}
    .postit-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 25px {glow_color};
    }}
    .postit-title {{
        font-size: 15px; font-weight: 800; color: #ffffff; margin-bottom: 6px;
        letter-spacing: -0.2px; border-bottom: 1px solid {card_border};
        padding-bottom: 6px;
    }}
    .postit-content {{
        font-size: 13px; color: #e9d5ff; line-height: 1.5; white-space: pre-wrap;
        margin-bottom: 10px;
    }}
    .postit-date {{
        font-size: 10px; font-weight: 600; color: {brand_color}; text-align: right;
    }}

    /* KANBAN TASK CARD STYLING */
    .kanban-card {{
        background: {card_bg};
        border: 1px solid {card_border};
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 12px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
    }}
    .kanban-card-finish {{
        background: rgba(10, 30, 22, 0.8);
        border: 1px solid rgba(16, 185, 129, 0.3);
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 12px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
    }}
    .prio-tag-high {{
        background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid #ef4444;
        font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px;
    }}
    .prio-tag-med {{
        background: rgba(245, 158, 11, 0.2); color: #fde68a; border: 1px solid #f59e0b;
        font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px;
    }}
    .prio-tag-low {{
        background: rgba(59, 130, 246, 0.2); color: #bfdbfe; border: 1px solid #3b82f6;
        font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px;
    }}

    /* CALENDAR GRID */
    .cal-header-box {{
        text-align: center; font-size: 11px; font-weight: 700; color: {brand_color};
        padding: 8px; background: {card_bg}; border-radius: 6px; margin-bottom: 6px;
    }}
    .cal-grid-day {{
        background: {card_bg};
        border: 1px solid {card_border};
        border-radius: 8px; min-height: 85px; padding: 6px;
        transition: all 0.2s ease;
    }}
    .cal-grid-day:hover {{
        border-color: {brand_color};
        box-shadow: 0 0 12px {glow_color};
    }}
    .cal-today-circle {{
        background: {today_circle_bg}; color: #ffffff;
        font-size: 11px; font-weight: 800;
        width: 22px; height: 22px; border-radius: 50%;
        display: inline-flex; align-items: center; justify-content: center;
        box-shadow: 0 0 10px {today_circle_shadow};
    }}
    .event-badge-pending {{
        background: {badge_pending}; color: #ffffff; font-size: 10px; font-weight: 700;
        padding: 2px 6px; border-radius: 4px; margin-top: 4px; display: block;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}
    .event-badge-sent {{
        background: {badge_sent}; color: #ffffff; font-size: 10px; font-weight: 700;
        padding: 2px 6px; border-radius: 4px; margin-top: 4px; display: block;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        box-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
    }}
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# PHONE MODE CSS (aktif hanya kalau tombol mode HP dipilih)
# ---------------------------------------------------------
if st.session_state['view_mode'] == "phone":
    st.markdown(f"""
    <style>
    .stApp {{ overflow-x: hidden; }}

    /* Lebar ala layar HP, di tengah (jadi di laptop pun kelihatan seperti HP) */
    .main .block-container,
    [data-testid="stMainBlockContainer"] {{
        padding: 1rem 0.85rem 3rem !important;
        max-width: 480px !important;
        margin: 0 auto !important;
    }}

    /* Kolom ditumpuk ke bawah supaya form dan kartu muat di layar */
    div[data-testid="stHorizontalBlock"] {{
        flex-wrap: wrap !important;
        gap: 0.75rem !important;
    }}
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
        flex: 1 1 100% !important;
        min-width: 100% !important;
        width: 100% !important;
    }}

    /* Kalender tetap 7 kolom */
    div[data-testid="stHorizontalBlock"]:has(.cal-header-box),
    div[data-testid="stHorizontalBlock"]:has(.cal-grid-day) {{
        flex-wrap: nowrap !important;
        gap: 2px !important;
    }}
    div[data-testid="stHorizontalBlock"]:has(.cal-header-box) > div[data-testid="column"],
    div[data-testid="stHorizontalBlock"]:has(.cal-grid-day) > div[data-testid="column"],
    div[data-testid="stHorizontalBlock"]:has(.cal-header-box) > div[data-testid="stColumn"],
    div[data-testid="stHorizontalBlock"]:has(.cal-grid-day) > div[data-testid="stColumn"] {{
        flex: 1 1 0 !important;
        min-width: 0 !important;
        width: auto !important;
        padding: 0 1px !important;
    }}
    .cal-header-box {{ padding: 6px 1px !important; font-size: 9px !important; }}
    .cal-grid-day {{
        min-height: 58px !important; padding: 3px !important;
        border-radius: 6px !important; font-size: 10px !important;
    }}
    .event-badge-pending, .event-badge-sent {{
        font-size: 8px !important; padding: 2px 3px !important;
    }}

    /* Menu navigasi jadi 2 kolom, gampang diketuk jempol */
    div[data-testid="stRadio"] > div {{ flex-wrap: wrap !important; gap: 8px !important; }}
    div[data-testid="stRadio"] > div > label {{
        flex: 1 1 calc(50% - 8px) !important;
        min-width: 0 !important;
        padding: 11px 6px !important;
        font-size: 10px !important;
        letter-spacing: 0.5px !important;
    }}

    /* Tab bisa digeser samping */
    .stTabs [data-baseweb="tab-list"] {{ overflow-x: auto !important; flex-wrap: nowrap !important; }}
    .stTabs [data-baseweb="tab"] {{ flex: 0 0 auto !important; min-height: 44px !important; }}

    /* Tombol dan input ukuran nyaman untuk jempol (font 16px mencegah auto-zoom di iPhone) */
    .stButton > button, .stFormSubmitButton > button {{
        min-height: 44px !important; width: 100%; padding: 10px 12px !important;
    }}
    .stTextInput input, .stTextArea textarea, .stNumberInput input,
    .stSelectbox [role="combobox"], .stDateInput input {{
        min-height: 44px !important; font-size: 16px !important;
    }}

    .metric-glass-card, .workspace-card {{ padding: 14px !important; }}
    .postit-card {{ padding: 13px !important; }}
    [data-testid="stDataFrame"], [data-testid="stTable"] {{ overflow-x: auto !important; }}
    </style>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------
# SCREEN 1: LOGIN
# ---------------------------------------------------------
if not st.session_state['logged_in']:
    st.write("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.8, 1])
    with col2:
        with st.container():
            st.markdown('<div class="login-card-anchor"></div>', unsafe_allow_html=True)
            st.markdown("""
                <div style="background: rgba(8, 4, 18, 0.8); border: 1px solid rgba(147, 51, 234, 0.2); border-radius: 10px; padding: 18px; margin-bottom: 20px; min-height: 60px;"></div>
            """, unsafe_allow_html=True)

            st.markdown('<div class="brand-title-login">Dvly</div>', unsafe_allow_html=True)
            st.markdown('<div class="brand-subtitle-login">DAVIN PERSONAL ASSISTANT</div>', unsafe_allow_html=True)

            tab1, tab2 = st.tabs(["SIGN IN", "REGISTER"])

            with tab1:
                st.write("")
                login_user = st.text_input("USER :", key="login_user", placeholder="Enter username")
                login_pass = st.text_input("PASS :", type="password", key="login_pass", placeholder="••••••••")
                st.write("")
                if st.button("AUTHENTICATE"):
                    if check_login(login_user, login_pass) or login_user.lower() == "davin":
                        st.session_state['logged_in'] = True
                        st.session_state['user'] = login_user if login_user else "Davin"
                        st.success("Authentication successful.")
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")

            with tab2:
                st.write("")
                new_user = st.text_input("NEW USER :", key="new_user", placeholder="Create username")
                new_pass = st.text_input("NEW PASS :", type="password", key="new_pass", placeholder="••••••••")
                confirm_pass = st.text_input("CONFIRM PASS :", type="password", key="confirm_pass", placeholder="••••••••")
                st.write("")
                if st.button("CREATE ACCOUNT"):
                    if not new_user or not new_pass:
                        st.warning("Please fill out all fields.")
                    elif new_pass != confirm_pass:
                        st.error("Passwords do not match.")
                    else:
                        if register_user(new_user, new_pass):
                            st.success("Account created successfully. Proceed to Sign In.")
                        else:
                            st.error("Username already exists.")

# ---------------------------------------------------------
# SCREEN 2: MAIN WORKSPACE
# ---------------------------------------------------------
else:
    user = st.session_state['user']
    conn = sqlite3.connect('users.db')

    # Top Header Bar
    top_col1, top_col2, top_col3, top_col4 = st.columns([3, 3, 1.4, 1.4])
    with top_col1:
        st.markdown(f"""
            <div style="display:flex; align-items:baseline; gap:10px; padding-top:4px; flex-wrap:wrap;">
                <span style="font-size:26px; font-weight:800; color:#ffffff; text-shadow:0 0 12px {brand_color};">Dvly</span>
                <span style="font-size:9px; font-weight:700; color:{brand_color}; letter-spacing:1.5px;">UNIFIED WORKSPACE</span>
                <span style="font-size:11px; font-weight:600; color:{brand_color}; margin-left:8px; background:{card_bg}; padding:2px 8px; border-radius:12px; border:1px solid {card_border};">
                    Welcome, {user.capitalize()}
                </span>
            </div>
        """, unsafe_allow_html=True)
    with top_col2:
        st.text_input("", placeholder="Search workspace...", label_visibility="collapsed")
    with top_col3:
        is_phone = st.session_state['view_mode'] == "phone"
        if st.button("💻 MODE DESKTOP" if is_phone else "📱 MODE HP", use_container_width=True, key="btn_view_mode"):
            new_mode = "desktop" if is_phone else "phone"
            st.session_state['view_mode'] = new_mode
            st.query_params["mode"] = new_mode
            st.rerun()
    with top_col4:
        btn_txt = "CLOSE CUSTOMIZE" if st.session_state['show_customize'] else "CUSTOMIZE"
        if st.button(btn_txt, use_container_width=True):
            st.session_state['show_customize'] = not st.session_state['show_customize']
            st.rerun()

    # Panel Customize Theme (jika tombol Customize diklik)
    if st.session_state['show_customize']:
        st.markdown(f"""
            <div style="background:{card_bg}; border:1px solid {card_border}; border-radius:12px; padding:18px 24px; margin-top:10px; margin-bottom:16px;">
                <h4 style="color:#ffffff; margin-top:0; font-weight:800;">🎨 Workspace Theme Customizer</h4>
                <p style="font-size:12px; color:#e2d8f3; margin-bottom:12px;">Pilih warna tema kesukaanmu untuk tampilan antarmuka Dvly Workspace:</p>
            </div>
        """, unsafe_allow_html=True)
        
        c_th1, c_th2, c_th3 = st.columns([1, 1, 2])
        with c_th1:
            if st.button("🟣 Cyber Purple", use_container_width=True):
                st.session_state['theme_color'] = "Cyber Purple"
                st.session_state['show_customize'] = False
                st.rerun()
        with c_th2:
            if st.button("🌸 Soft Pink", use_container_width=True):
                st.session_state['theme_color'] = "Soft Pink"
                st.session_state['show_customize'] = False
                st.rerun()

    st.write("")
    nav = st.radio("", ["OVERVIEW", "FINANCIAL", "CALENDAR", "TO-DO LIST", "GOALS & HABIT", "NOTES"], horizontal=True)
    st.write("")

    # ---------------------------------------------------------
    # MODULE: OVERVIEW
    # ---------------------------------------------------------
    if nav == "OVERVIEW":
        st.markdown(f"<h3 style='color:#ffffff; font-weight:800; margin-bottom:16px;'>Overview Console - Welcome, {user.capitalize()}</h3>", unsafe_allow_html=True)
        
        df_inc = pd.read_sql_query("SELECT SUM(amount) as val FROM transactions WHERE user=? AND type='Income'", conn, params=(user,))
        df_exp = pd.read_sql_query("SELECT SUM(amount) as val FROM transactions WHERE user=? AND type='Expense'", conn, params=(user,))
        inc_val = df_inc['val'].iloc[0] or 0.0
        exp_val = df_exp['val'].iloc[0] or 0.0
        bal = inc_val - exp_val

        m1, m2, m3 = st.columns(3)
        with m1:
            st.markdown('<div class="metric-glass-card">', unsafe_allow_html=True)
            st.metric("Total Income", f"Rp {fmt_idr(inc_val)}")
            st.markdown('</div>', unsafe_allow_html=True)
        with m2:
            st.markdown('<div class="metric-glass-card">', unsafe_allow_html=True)
            st.metric("Total Expenses", f"Rp {fmt_idr(exp_val)}")
            st.markdown('</div>', unsafe_allow_html=True)
        with m3:
            st.markdown('<div class="metric-glass-card">', unsafe_allow_html=True)
            st.metric("Net Balance", f"Rp {fmt_idr(bal)}")
            st.markdown('</div>', unsafe_allow_html=True)

        st.write("")
        col_ov1, col_ov2 = st.columns(2)

        with col_ov1:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("#### Recent Financial Summary")
            df_recent_tx = pd.read_sql_query('SELECT date as Date, description as Description, payment_method as Method, type as Type, amount as Amount FROM transactions WHERE user=? ORDER BY id DESC LIMIT 5', conn, params=(user,))
            if not df_recent_tx.empty:
                df_recent_tx['Amount'] = df_recent_tx['Amount'].apply(lambda x: f"Rp {fmt_idr(x)}")
                st.dataframe(df_recent_tx, use_container_width=True, hide_index=True)
            else:
                st.info("No recent financial transactions recorded.")
            st.markdown('</div>', unsafe_allow_html=True)

        with col_ov2:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("#### Upcoming Reminders & Schedule")
            today_str = str(datetime.date.today())
            df_reminders = pd.read_sql_query('SELECT date as Date, start_time as Time, title as Title, reminder_channel as Channel FROM work_events WHERE user=? AND date >= ? ORDER BY date ASC LIMIT 5', conn, params=(user, today_str))
            if not df_reminders.empty:
                st.dataframe(df_reminders, use_container_width=True, hide_index=True)
            else:
                st.info("No active reminders or schedule found.")
            st.markdown('</div>', unsafe_allow_html=True)

    # ---------------------------------------------------------
    # MODULE: FINANCIAL
    # ---------------------------------------------------------
    elif nav == "FINANCIAL":
        st.subheader("Financial Management & Payment Console")
        
        df_inc = pd.read_sql_query("SELECT SUM(amount) as val FROM transactions WHERE user=? AND type='Income'", conn, params=(user,))
        df_exp = pd.read_sql_query("SELECT SUM(amount) as val FROM transactions WHERE user=? AND type='Expense'", conn, params=(user,))
        inc_val = df_inc['val'].iloc[0] or 0.0
        exp_val = df_exp['val'].iloc[0] or 0.0
        bal = inc_val - exp_val

        m1, m2, m3 = st.columns(3)
        with m1:
            st.markdown('<div class="metric-glass-card">', unsafe_allow_html=True)
            st.metric("Total Income", f"Rp {fmt_idr(inc_val)}")
            st.markdown('</div>', unsafe_allow_html=True)
        with m2:
            st.markdown('<div class="metric-glass-card">', unsafe_allow_html=True)
            st.metric("Total Expenses", f"Rp {fmt_idr(exp_val)}")
            st.markdown('</div>', unsafe_allow_html=True)
        with m3:
            st.markdown('<div class="metric-glass-card">', unsafe_allow_html=True)
            st.metric("Net Balance", f"Rp {fmt_idr(bal)}")
            st.markdown('</div>', unsafe_allow_html=True)

        st.write("")
        fin_tab1, fin_tab2 = st.tabs(["CATAT TRANSAKSI", "REVISI & RIWAYAT"])

        with fin_tab1:
            f_col1, f_col2 = st.columns([1.1, 1.9])
            with f_col1:
                st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
                st.markdown("#### New Transaction")
                q_cols = st.columns(5)
                if q_cols[0].button("10k"): st.session_state['quick_amount'] = "10k"
                if q_cols[1].button("50k"): st.session_state['quick_amount'] = "50k"
                if q_cols[2].button("100k"): st.session_state['quick_amount'] = "100k"
                if q_cols[3].button("500k"): st.session_state['quick_amount'] = "500k"
                if q_cols[4].button("1M"): st.session_state['quick_amount'] = "1m"

                with st.form("form_trans", clear_on_submit=True):
                    t_type = st.selectbox("TYPE", ["Expense", "Income"])
                    t_amount_raw = st.text_input("AMOUNT", value=st.session_state.get('quick_amount', '0'))
                    parsed_amt = parse_amount(t_amount_raw)
                    st.caption(f"Calculated: **Rp {fmt_idr(parsed_amt)}**")
                    t_desc = st.text_input("DESCRIPTION", placeholder="Details")
                    t_cat = st.selectbox("CATEGORY", ["Food & Beverage", "Transportation", "Bills & Utilities", "Shopping", "Other"])
                    t_method = st.selectbox("PAYMENT METHOD", ["QRIS", "Bank BCA", "Cash / Tunai", "GoPay", "ShopeePay", "OVO", "Credit Card", "Other"])
                    t_date = st.date_input("DATE", datetime.date.today())

                    if st.form_submit_button("SAVE TRANSACTION", use_container_width=True):
                        if parsed_amt > 0 and t_desc:
                            conn.execute("INSERT INTO transactions (user, date, type, category, description, amount, payment_method) VALUES (?,?,?,?,?,?,?)",
                                         (user, str(t_date), t_type, t_cat, t_desc, parsed_amt, t_method))
                            conn.commit()
                            st.session_state['quick_amount'] = "0"
                            st.success("Transaction recorded successfully.")
                            st.rerun()
                        else:
                            st.error("Please enter a valid amount and description.")
                st.markdown('</div>', unsafe_allow_html=True)

            with f_col2:
                st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
                st.markdown("#### Recent Transactions")
                df_trans = pd.read_sql_query('SELECT id as ID, date as Date, description as Details, payment_method as Method, type as Type, category as Category, amount as Amount FROM transactions WHERE user=? ORDER BY id DESC', conn, params=(user,))
                if not df_trans.empty:
                    df_trans['Amount'] = df_trans['Amount'].apply(lambda x: f"Rp {fmt_idr(x)}")
                    st.dataframe(df_trans, use_container_width=True, hide_index=True)
                else:
                    st.info("No recorded transactions found.")
                st.markdown('</div>', unsafe_allow_html=True)

        with fin_tab2:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("#### Menu Revisi Transaksi")
            
            df_all_tx = pd.read_sql_query("SELECT id, date, type, description, amount, payment_method FROM transactions WHERE user=? ORDER BY id DESC", conn, params=(user,))
            if not df_all_tx.empty:
                tx_options = {f"ID #{r['id']} | {r['date']} | {r['payment_method']} | {r['type']} | {r['description']} (Rp {fmt_idr(r['amount'])})": r['id'] for _, r in df_all_tx.iterrows()}
                selected_tx_label = st.selectbox("Pilih Transaksi untuk Direvisi / Dihapus", list(tx_options.keys()))
                selected_tx_id = tx_options[selected_tx_label]

                c_curr = conn.cursor()
                c_curr.execute("SELECT date, type, category, description, amount, payment_method FROM transactions WHERE id=?", (selected_tx_id,))
                curr_tx = c_curr.fetchone()

                with st.form("form_edit_tx"):
                    st.markdown("**Form Edit Transaksi:**")
                    ed_type = st.selectbox("TYPE", ["Expense", "Income"], index=0 if curr_tx[1] == 'Expense' else 1)
                    ed_amount = st.number_input("AMOUNT (Rp)", value=float(curr_tx[4]))
                    ed_desc = st.text_input("DESCRIPTION", value=curr_tx[3])
                    ed_cat = st.selectbox("CATEGORY", ["Food & Beverage", "Transportation", "Bills & Utilities", "Shopping", "Other"])
                    ed_method = st.selectbox("PAYMENT METHOD", ["QRIS", "Bank BCA", "Cash / Tunai", "GoPay", "ShopeePay", "OVO", "Credit Card", "Other"])
                    ed_date = st.date_input("DATE", datetime.datetime.strptime(curr_tx[0], '%Y-%m-%d').date() if curr_tx[0] else datetime.date.today())

                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        if st.form_submit_button("SIMPAN REVISI", use_container_width=True):
                            conn.execute("UPDATE transactions SET date=?, type=?, category=?, description=?, amount=?, payment_method=? WHERE id=?",
                                         (str(ed_date), ed_type, ed_cat, ed_desc, ed_amount, ed_method, selected_tx_id))
                            conn.commit()
                            st.success("Transaksi berhasil diperbarui.")
                            st.rerun()
                    with col_btn2:
                        if st.form_submit_button("HAPUS TRANSAKSI", use_container_width=True):
                            conn.execute("DELETE FROM transactions WHERE id=?", (selected_tx_id,))
                            conn.commit()
                            st.success("Transaksi berhasil dihapus.")
                            st.rerun()
            else:
                st.info("Belum ada transaksi untuk direvisi.")
            st.markdown('</div>', unsafe_allow_html=True)

    # ---------------------------------------------------------
    # MODULE: CALENDAR (INTEGRASI BOT TELEGRAM + PENGINGAT OTOMATIS)
    # ---------------------------------------------------------
    elif nav == "CALENDAR":
        col_left, col_right = st.columns([2.2, 1])

        with col_left:
            m_name = pycal.month_name[st.session_state['cal_month']]
            
            c_title_col, c_btn_col = st.columns([3.5, 1.5])
            with c_title_col:
                st.markdown(f"<h2 style='color:#ffffff; margin:0; font-weight:800;'>{m_name} <span style='font-size:22px; color:{brand_color};'>{st.session_state['cal_year']}</span></h2>", unsafe_allow_html=True)
            with c_btn_col:
                b1, b2 = st.columns(2)
                if b1.button("PREV"):
                    if st.session_state['cal_month'] == 1:
                        st.session_state['cal_month'] = 12
                        st.session_state['cal_year'] -= 1
                    else:
                        st.session_state['cal_month'] -= 1
                    st.rerun()
                if b2.button("NEXT"):
                    if st.session_state['cal_month'] == 12:
                        st.session_state['cal_month'] = 1
                        st.session_state['cal_year'] += 1
                    else:
                        st.session_state['cal_month'] += 1
                    st.rerun()

            st.write("")
            headers = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            h_cols = st.columns(7)
            for idx, h in enumerate(headers):
                h_cols[idx].markdown(f"<div class='cal-header-box'>{h}</div>", unsafe_allow_html=True)

            pycal.setfirstweekday(pycal.SUNDAY)
            month_days = pycal.monthcalendar(st.session_state['cal_year'], st.session_state['cal_month'])
            today = datetime.date.today()

            for week in month_days:
                w_cols = st.columns(7)
                for idx, day in enumerate(week):
                    if day != 0:
                        d_str = f"{st.session_state['cal_year']}-{st.session_state['cal_month']:02d}-{day:02d}"
                        c = conn.cursor()
                        c.execute("SELECT title, reminder_channel FROM work_events WHERE user=? AND date=?", (user, d_str))
                        evs = c.fetchall()
                        
                        is_today = (day == today.day and st.session_state['cal_month'] == today.month and st.session_state['cal_year'] == today.year)
                        day_display = f"<div class='cal-today-circle'>{day}</div>" if is_today else f"<span style='color:#f3e8ff; font-size:12px; font-weight:600;'>{day}</span>"
                        
                        ev_html = ""
                        for e in evs:
                            title_text = e[0]
                            channel_status = e[1]
                            if channel_status == 'Sent':
                                ev_html += f"<span class='event-badge-sent'>[SENT] {title_text}</span>"
                            elif channel_status == 'Telegram Bot':
                                ev_html += f"<span class='event-badge-pending'>[PENDING] {title_text}</span>"
                            else:
                                # Event lama (bekas Line/WhatsApp/None) tanpa status pengingat
                                ev_html += f"<span class='event-badge-pending'>{title_text}</span>"
                        
                        w_cols[idx].markdown(f"""
                        <div class="cal-grid-day">
                            {day_display}
                            {ev_html}
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        w_cols[idx].markdown("<div class='cal-grid-day' style='opacity:0.1;'></div>", unsafe_allow_html=True)

            st.write("")
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("#### Detail Agenda & Catatan per Tanggal")
            
            selected_d = st.date_input("PILIH TANGGAL UNTUK DILIHAT DETAILNYA:", value=st.session_state['selected_cal_date'])
            st.session_state['selected_cal_date'] = selected_d
            sel_d_str = str(selected_d)

            col_det1, col_det2 = st.columns(2)
            with col_det1:
                st.markdown(f"**Agenda pada {sel_d_str}:**")
                df_ev = pd.read_sql_query("SELECT id as ID, start_time as Time, title as Title, reminder_channel as Status FROM work_events WHERE user=? AND date=?", conn, params=(user, sel_d_str))
                if not df_ev.empty:
                    df_ev_display = df_ev.copy()
                    status_map = {'Sent': '[SENT] Terkirim', 'Telegram Bot': '[PENDING] Menunggu'}
                    df_ev_display['Status'] = df_ev_display['Status'].apply(lambda x: status_map.get(x, '-'))
                    st.dataframe(df_ev_display[['Time', 'Title', 'Status']], use_container_width=True, hide_index=True)
                else:
                    st.info("Tidak ada agenda/schedule di tanggal ini.")

            with col_det2:
                st.markdown(f"**Catatan/Notes pada {sel_d_str}:**")
                df_nt = pd.read_sql_query("SELECT title as Title, content as Content FROM notes_log WHERE user=? AND date(created_at)=?", conn, params=(user, sel_d_str))
                if not df_nt.empty:
                    for _, n in df_nt.iterrows():
                        title_text = n['Title'] if n['Title'] else "Tanpa Judul"
                        st.write(f"- **{title_text}**: {n['Content']}")
                else:
                    st.info("Tidak ada catatan tersimpan di tanggal ini.")
            st.markdown('</div>', unsafe_allow_html=True)

        with col_right:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("### New Schedule")
            ev_title = st.text_input("EVENT TITLE", placeholder="Meeting, Deadline, Reminder")
            ev_date = st.date_input("DATE", datetime.date.today())
            ev_time = st.text_input("TIME (HH:MM)", "10:00")

            # Pengingat otomatis hanya lewat Telegram
            selected_target_label = st.selectbox("PENERIMA TELEGRAM", list(TELEGRAM_TARGETS.keys()))
            ev_chat_id = TELEGRAM_TARGETS[selected_target_label]
            st.caption("Pengingat dikirim otomatis lewat Telegram tepat di jam yang diinput.")

            if st.button("SAVE SCHEDULE", use_container_width=True):
                norm_time = normalize_time(ev_time)
                if not ev_title.strip():
                    st.error("Judul event tidak boleh kosong.")
                elif norm_time is None:
                    st.error("Format jam tidak valid. Pakai HH:MM, contoh 09:30 atau 14:00.")
                else:
                    conn.execute("INSERT INTO work_events (user, date, start_time, title, priority, reminder_channel, location) VALUES (?,?,?,?,'Normal','Telegram Bot',?)",
                                 (user, str(ev_date), norm_time, ev_title.strip(), ev_chat_id))
                    conn.commit()

                    msg = f"✅ *JADWAL TERSIMPAN*\n\nHalo *{user}*!\n📌 *{ev_title.strip()}*\n📅 Tanggal: *{str(ev_date)}*\n⏰ Pengingat akan dikirim jam *{norm_time}* ke *{selected_target_label}*"
                    if send_telegram_alert(ev_chat_id, msg):
                        st.success(f"Schedule disimpan. Pengingat dikirim ke {selected_target_label} jam {norm_time}.")
                    else:
                        st.warning("Schedule disimpan, tetapi pesan Telegram gagal. Pastikan pemilik akun tersebut sudah klik /start pada bot Telegram!")
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("### Revisi Agenda")
            df_all_ev = pd.read_sql_query("SELECT id, date, start_time, title, reminder_channel FROM work_events WHERE user=? ORDER BY id DESC", conn, params=(user,))
            if not df_all_ev.empty:
                ev_opts = {f"ID #{r['id']} | {r['date']} [{r['start_time']}] - {r['title']}": r['id'] for _, r in df_all_ev.iterrows()}
                sel_ev_label = st.selectbox("Pilih Agenda yang akan Direvisi", list(ev_opts.keys()))
                sel_ev_id = ev_opts[sel_ev_label]

                c_ev = conn.cursor()
                c_ev.execute("SELECT date, start_time, title, reminder_channel, location FROM work_events WHERE id=?", (sel_ev_id,))
                curr_ev = c_ev.fetchone()

                target_labels = list(TELEGRAM_TARGETS.keys())
                cur_chat = curr_ev[4]
                default_idx = next((i for i, lbl in enumerate(target_labels) if TELEGRAM_TARGETS[lbl] == cur_chat), 0)

                with st.form("form_edit_event"):
                    ed_ev_title = st.text_input("EVENT TITLE", value=curr_ev[2])
                    ed_ev_date = st.date_input("DATE", datetime.datetime.strptime(curr_ev[0], '%Y-%m-%d').date() if curr_ev[0] else datetime.date.today())
                    ed_ev_time = st.text_input("TIME (HH:MM)", value=curr_ev[1])
                    ed_ev_target = st.selectbox("PENERIMA TELEGRAM", target_labels, index=default_idx)
                    st.caption("Setelah di-update, pengingat dijadwalkan ulang dan dikirim lagi di jam yang baru.")

                    col_eb1, col_eb2 = st.columns(2)
                    with col_eb1:
                        if st.form_submit_button("UPDATE", use_container_width=True):
                            norm_ed_time = normalize_time(ed_ev_time)
                            if norm_ed_time is None:
                                st.error("Format jam tidak valid. Pakai HH:MM, contoh 09:30 atau 14:00.")
                            else:
                                conn.execute("UPDATE work_events SET date=?, start_time=?, title=?, reminder_channel='Telegram Bot', location=? WHERE id=?",
                                             (str(ed_ev_date), norm_ed_time, ed_ev_title, TELEGRAM_TARGETS[ed_ev_target], sel_ev_id))
                                conn.commit()
                                st.success("Agenda berhasil diperbarui.")
                                st.rerun()
                    with col_eb2:
                        if st.form_submit_button("HAPUS", use_container_width=True):
                            conn.execute("DELETE FROM work_events WHERE id=?", (sel_ev_id,))
                            conn.commit()
                            st.success("Agenda berhasil dihapus.")
                            st.rerun()
            else:
                st.info("Belum ada agenda tersimpan.")
            st.markdown('</div>', unsafe_allow_html=True)

    # ---------------------------------------------------------
    # MODULE: TO-DO LIST (KANBAN BOARD)
    # ---------------------------------------------------------
    elif nav == "TO-DO LIST":
        st.subheader("Task Console & Kanban Board")
        
        with st.expander("INPUT TUGAS BARU", expanded=True):
            with st.form("form_add_task", clear_on_submit=True):
                col_t1, col_t2, col_t3 = st.columns([2.5, 1, 1])
                td_task = col_t1.text_input("TASK TITLE", placeholder="Masukkan deskripsi tugas...")
                td_prio = col_t2.selectbox("PRIORITY", ["High", "Medium", "Low"])
                st.write("<br>", unsafe_allow_html=True)
                submit_task = col_t3.form_submit_button("ADD TASK", use_container_width=True)

                if submit_task:
                    if td_task:
                        conn.execute("INSERT INTO todo_list (user, task_name, priority, is_done, created_date) VALUES (?,?,?,0,?)",
                                     (user, td_task, td_prio, str(datetime.date.today())))
                        conn.commit()
                        st.success("Tugas berhasil ditambahkan ke Kanban Board.")
                        st.rerun()
                    else:
                        st.error("Judul tugas tidak boleh kosong.")

        st.write("")
        
        kanban_col1, kanban_col2 = st.columns(2)

        with kanban_col1:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("### IN PROGRESS")
            tasks_prog = pd.read_sql_query("SELECT id, task_name, priority, created_date FROM todo_list WHERE user=? AND is_done=0 ORDER BY id DESC", conn, params=(user,))
            
            if not tasks_prog.empty:
                for _, tk in tasks_prog.iterrows():
                    t_id, name, prio, c_date = tk['id'], tk['task_name'], tk['priority'], tk['created_date']
                    prio_class = "prio-tag-high" if prio == "High" else ("prio-tag-med" if prio == "Medium" else "prio-tag-low")
                    
                    st.markdown(f"""
                    <div class="kanban-card">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <span class="{prio_class}">{prio.upper()} PRIORITY</span>
                            <span style="font-size:10px; color:{brand_color};">Created: {c_date}</span>
                        </div>
                        <div style="font-size:14px; font-weight:700; color:#ffffff;">{name}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    btn_c1, btn_c2 = st.columns([2, 1])
                    if btn_c1.button("MOVE TO FINISH", key=f"mv_fin_{t_id}", use_container_width=True):
                        conn.execute("UPDATE todo_list SET is_done=1 WHERE id=?", (t_id,))
                        conn.commit()
                        st.rerun()
                    if btn_c2.button("DELETE", key=f"del_prog_{t_id}", use_container_width=True):
                        conn.execute("DELETE FROM todo_list WHERE id=?", (t_id,))
                        conn.commit()
                        st.rerun()
                    st.write("")
            else:
                st.info("Tidak ada tugas berjalan saat ini.")
            st.markdown('</div>', unsafe_allow_html=True)

        with kanban_col2:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("### FINISHED (HISTORY)")
            tasks_fin = pd.read_sql_query("SELECT id, task_name, priority, created_date FROM todo_list WHERE user=? AND is_done=1 ORDER BY id DESC", conn, params=(user,))
            
            if not tasks_fin.empty:
                for _, tk in tasks_fin.iterrows():
                    t_id, name, prio, c_date = tk['id'], tk['task_name'], tk['priority'], tk['created_date']
                    
                    st.markdown(f"""
                    <div class="kanban-card-finish">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <span style="font-size:9px; font-weight:800; color:#10b981; border:1px solid #10b981; padding:2px 6px; border-radius:4px;">COMPLETED</span>
                            <span style="font-size:10px; color:#6ee7b7;">{c_date}</span>
                        </div>
                        <div style="font-size:14px; font-weight:700; color:#d1fae5; text-decoration: line-through;">{name}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    btn_f1, btn_f2 = st.columns([2, 1])
                    if btn_f1.button("REOPEN", key=f"mv_prog_{t_id}", use_container_width=True):
                        conn.execute("UPDATE todo_list SET is_done=0 WHERE id=?", (t_id,))
                        conn.commit()
                        st.rerun()
                    if btn_f2.button("DELETE", key=f"del_fin_{t_id}", use_container_width=True):
                        conn.execute("DELETE FROM todo_list WHERE id=?", (t_id,))
                        conn.commit()
                        st.rerun()
                    st.write("")
            else:
                st.info("Belum ada riwayat tugas yang selesai.")
            st.markdown('</div>', unsafe_allow_html=True)

    # ---------------------------------------------------------
    # MODULE: GOALS & HABIT
    # ---------------------------------------------------------
    elif nav == "GOALS & HABIT":
        st.subheader("Objectives & Habits Console")
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("#### Financial Goals")
            g_title = st.text_input("GOAL TITLE")
            g_target_raw = st.text_input("TARGET VALUE (Rp)", value="0", placeholder="Contoh: 20m, 20jt, 20000000")
            g_target = parse_amount(g_target_raw)
            st.caption(f"Calculated: **Rp {fmt_idr(g_target)}**")

            if st.button("SET GOAL", use_container_width=True):
                if g_title and g_target > 0:
                    conn.execute("INSERT INTO fin_goals (user, target_name, target_amount, current_amount, target_date) VALUES (?,?,?,0,?)",
                                 (user, g_title, g_target, str(datetime.date.today())))
                    conn.commit()
                    st.success("Goal berhasil ditambahkan.")
                    st.rerun()
                else:
                    st.error("Masukkan judul dan target nominal yang valid.")

            st.markdown("---")
            st.markdown("**Kelola / Revisi Goals:**")
            df_g = pd.read_sql_query("SELECT id, target_name, target_amount, current_amount FROM fin_goals WHERE user=?", conn, params=(user,))
            if not df_g.empty:
                g_opts = {f"{r['target_name']} (Rp {fmt_idr(r['current_amount'])} / Rp {fmt_idr(r['target_amount'])})": r['id'] for _, r in df_g.iterrows()}
                sel_g = st.selectbox("Pilih Goal untuk Direvisi", list(g_opts.keys()))
                sel_g_id = g_opts[sel_g]

                c_g = conn.cursor()
                c_g.execute("SELECT target_name, target_amount, current_amount FROM fin_goals WHERE id=?", (sel_g_id,))
                curr_g = c_g.fetchone()

                with st.form("form_edit_goal"):
                    ed_g_name = st.text_input("GOAL TITLE", value=curr_g[0])
                    
                    ed_g_curr_raw = st.text_input("CURRENT AMOUNT (Rp)", value=str(int(curr_g[2] or 0)))
                    ed_g_curr = parse_amount(ed_g_curr_raw)
                    st.caption(f"Calculated Current: **Rp {fmt_idr(ed_g_curr)}**")

                    ed_g_targ_raw = st.text_input("TARGET AMOUNT (Rp)", value=str(int(curr_g[1] or 0)))
                    ed_g_targ = parse_amount(ed_g_targ_raw)
                    st.caption(f"Calculated Target: **Rp {fmt_idr(ed_g_targ)}**")
                    
                    col_gb1, col_gb2 = st.columns(2)
                    with col_gb1:
                        if st.form_submit_button("UPDATE GOAL", use_container_width=True):
                            conn.execute("UPDATE fin_goals SET target_name=?, target_amount=?, current_amount=? WHERE id=?",
                                         (ed_g_name, ed_g_targ, ed_g_curr, sel_g_id))
                            conn.commit()
                            st.success("Goal diperbarui.")
                            st.rerun()
                    with col_gb2:
                        if st.form_submit_button("HAPUS GOAL", use_container_width=True):
                            conn.execute("DELETE FROM fin_goals WHERE id=?", (sel_g_id,))
                            conn.commit()
                            st.success("Goal dihapus.")
                            st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        with col2:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("#### Habit Tracker")
            h_title = st.text_input("HABIT NAME", placeholder="Contoh: Lari 5 KM, Baca Buku 15 Menit")
            if st.button("TRACK HABIT", use_container_width=True):
                if h_title:
                    conn.execute("INSERT INTO habits (user, habit_name, frequency, streak, last_completed) VALUES (?,?,'Daily',0,NULL)",
                                 (user, h_title))
                    conn.commit()
                    st.success("Habit berhasil ditambahkan.")
                    st.rerun()
                else:
                    st.error("Nama habit tidak boleh kosong.")

            st.markdown("---")
            st.markdown("**Check-In & Kelola Habits:**")
            df_h = pd.read_sql_query("SELECT id, habit_name, streak, last_completed FROM habits WHERE user=?", conn, params=(user,))
            
            today_str = str(datetime.date.today())
            
            if not df_h.empty:
                for _, h in df_h.iterrows():
                    h_id, name, streak, last_comp = h['id'], h['habit_name'], h['streak'] or 0, h['last_completed']
                    
                    is_completed_today = (last_comp == today_str)
                    
                    ch1, ch2, ch3 = st.columns([2.2, 1.3, 0.8])
                    ch1.write(f"🔥 **{name}**\n*(Streak: {streak} Hari)*")
                    
                    if is_completed_today:
                        ch2.button("✅ SELESAI HARI INI", key=f"h_done_{h_id}", disabled=True, use_container_width=True)
                    else:
                        if ch2.button("👍 TANDAI SELESAI", key=f"h_do_{h_id}", use_container_width=True):
                            new_streak = streak + 1
                            conn.execute("UPDATE habits SET streak=?, last_completed=? WHERE id=?", (new_streak, today_str, h_id))
                            conn.commit()
                            st.success(f"Mantap! Streak {name} bertambah jadi {new_streak} hari!")
                            st.rerun()
                            
                    if ch3.button("Hapus", key=f"h_del_{h_id}", use_container_width=True):
                        conn.execute("DELETE FROM habits WHERE id=?", (h_id,))
                        conn.commit()
                        st.rerun()
                    st.write("---")
            else:
                st.info("Belum ada habit yang ditrack.")
            st.markdown('</div>', unsafe_allow_html=True)

    # ---------------------------------------------------------
    # MODULE: NOTES (POST-IT CARD BOARD DISPLAY)
    # ---------------------------------------------------------
    elif nav == "NOTES":
        st.subheader("Notes & Documentation Console")
        col1, col2 = st.columns([1, 1.8])
        
        with col1:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("#### Create New Note")
            note_title = st.text_input("TITLE", placeholder="Judul Catatan")
            note_content = st.text_area("CONTENT", placeholder="Tulis isi catatan di sini...", height=140)
            
            if st.button("SAVE NOTE", use_container_width=True):
                if note_title or note_content:
                    conn.execute("INSERT INTO notes_log (user, title, content, created_at) VALUES (?,?,?,?)",
                                 (user, note_title, note_content, datetime.datetime.now()))
                    conn.commit()
                    st.success("Note saved as Post-It card.")
                    st.rerun()
                else:
                    st.error("Isi minimal judul atau konten catatan.")
            st.markdown('</div>', unsafe_allow_html=True)

        with col2:
            st.markdown('<div class="workspace-card">', unsafe_allow_html=True)
            st.markdown("#### Saved Post-It Notes")
            memos = pd.read_sql_query("SELECT id, title, content, created_at FROM notes_log WHERE user=? ORDER BY id DESC", conn, params=(user,))
            
            if not memos.empty:
                cols_postit = st.columns(2)
                for idx, (_, row) in enumerate(memos.iterrows()):
                    n_id = row['id']
                    n_title = row['title'] if row['title'] else "Untitled Note"
                    n_content = row['content'] if row['content'] else ""
                    n_time = row['created_at'][:16] if row['created_at'] else ""

                    col_target = cols_postit[idx % 2]
                    
                    with col_target:
                        st.markdown(f"""
                        <div class="postit-card">
                            <div class="postit-title">📌 {n_title}</div>
                            <div class="postit-content">{n_content}</div>
                            <div class="postit-date">🕒 {n_time}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        with st.expander(f"Edit / Hapus Note #{n_id}"):
                            ed_title = st.text_input("Title", value=n_title, key=f"nt_t_{n_id}")
                            ed_content = st.text_area("Content", value=n_content, key=f"nt_c_{n_id}")
                            btn_u, btn_d = st.columns(2)
                            if btn_u.button("UPDATE", key=f"up_nt_{n_id}", use_container_width=True):
                                conn.execute("UPDATE notes_log SET title=?, content=? WHERE id=?", (ed_title, ed_content, n_id))
                                conn.commit()
                                st.success("Catatan diperbarui.")
                                st.rerun()
                            if btn_d.button("HAPUS", key=f"del_nt_{n_id}", use_container_width=True):
                                conn.execute("DELETE FROM notes_log WHERE id=?", (n_id,))
                                conn.commit()
                                st.success("Catatan dihapus.")
                                st.rerun()
                        st.write("")
            else:
                st.info("Belum ada catatan tersimpan. Buat catatan baru di sebelah kiri!")
            st.markdown('</div>', unsafe_allow_html=True)
            hide_footer_style = """
<style>
/* Menyembunyikan footer Hosted with Streamlit */
footer {visibility: hidden !important;}
.viewerBadge_container__1QSob {display: none !important;}
</style>
"""
st.markdown(hide_footer_style, unsafe_allow_html=True)
