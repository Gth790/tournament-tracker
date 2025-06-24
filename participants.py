import streamlit as st
import pandas as pd
import sqlite3
import os
import csv
import threading
import sys
from datetime import datetime
from io import StringIO
from apscheduler.schedulers.background import BackgroundScheduler
from streamlit_autorefresh import st_autorefresh

DB_FILE = 'participants.db'
CSV_DIR = 'csv_exports'
os.makedirs(CSV_DIR, exist_ok=True)

# Database initialization
def init_db(drop=False):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    if drop:
        cur.execute('DROP TABLE IF EXISTS participants')
        cur.execute('DROP TABLE IF EXISTS changes')
        cur.execute('DROP TABLE IF EXISTS tracked')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            tournament_id TEXT,
            participant_id TEXT,
            name TEXT,
            status TEXT,
            joined_date TEXT,
            left_date TEXT,
            PRIMARY KEY (tournament_id, participant_id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id TEXT,
            participant_id TEXT,
            change_type TEXT,
            change_date TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS tracked (
            tournament_id TEXT PRIMARY KEY,
            last_run TEXT,
            tournament_name TEXT
        )
    ''')
    try:
        cur.execute('ALTER TABLE tracked ADD COLUMN tournament_name TEXT')
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn, cur

conn, cur = init_db()
lock = threading.Lock()

# Fetch participants from API
def fetch_participants(tid):
    import requests
    url = f'https://api.cuescore.com/tournament/?id={tid}&participants=Participants+list'
    try:
        resp = requests.get(url, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict):
            entries = data.get('Participants list') or data.get('participants') or []
        else:
            entries = []
        result = []
        for p in entries:
            if not isinstance(p, dict):
                continue
            pid = p.get('playerId') or p.get('PlayerId') or p.get('id')
            name = p.get('name')
            if pid and name:
                result.append((str(pid), name))
        return result
    except Exception:
        return []

# Update tournament data
def update_tournament(tid):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entries = fetch_participants(tid)
    with lock:
        cur.execute('SELECT tournament_name FROM tracked WHERE tournament_id=?', (tid,))
        existing = cur.fetchone()
        existing_name = existing[0] if existing else None
        cur.execute('REPLACE INTO tracked (tournament_id, last_run, tournament_name) VALUES (?,?,?)',
                    (tid, now, existing_name))
        cur.execute('SELECT COUNT(*) FROM participants WHERE tournament_id=?', (tid,))
        count = cur.fetchone()[0]
        if count == 0:
            for pid, name in entries:
                cur.execute(
                    'INSERT INTO participants (tournament_id,participant_id,name,status,joined_date,left_date) VALUES (?,?,?,?,?,?)',
                    (tid, pid, name, 'active', now, None)
                )
            conn.commit()
            return
        cur.execute('SELECT participant_id, status FROM participants WHERE tournament_id=?', (tid,))
        stored = {row[0]: row[1] for row in cur.fetchall()}
        for pid, name in entries:
            if pid not in stored:
                cur.execute(
                    'INSERT INTO participants (tournament_id,participant_id,name,status,joined_date,left_date) VALUES (?,?,?,?,?,?)',
                    (tid, pid, name, 'active', now, None)
                )
                cur.execute(
                    'INSERT INTO changes (tournament_id,participant_id,change_type,change_date) VALUES (?,?,?,?)',
                    (tid, pid, 'joined', now)
                )
        for pid, status in stored.items():
            if status == 'active' and pid not in dict(entries):
                cur.execute(
                    'UPDATE participants SET status=?, left_date=? WHERE tournament_id=? AND participant_id=?',
                    ('left', now, tid, pid)
                )
                cur.execute(
                    'INSERT INTO changes (tournament_id,participant_id,change_type,change_date) VALUES (?,?,?,?)',
                    (tid, pid, 'left', now)
                )
        conn.commit()

# Export CSV
def export_csv(tid):
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    rows = cur.execute(
        'SELECT participant_id,name,status,joined_date,left_date FROM participants WHERE tournament_id=?',
        (tid,)
    ).fetchall()
    output = StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID','Name','Status','Joined','Left'])
    for pid,name,status,j,l in rows:
        writer.writerow([pid, name, status, j or '', l or ''])
    return output.getvalue()

# Scheduler for hourly update
def update_all_tracked():
    tracked = cur.execute('SELECT tournament_id FROM tracked').fetchall()
    for (tid,) in tracked:
        try:
            update_tournament(tid)
        except Exception as e:
            print(f"Error updating {tid}: {e}", file=sys.stderr)

# Start scheduler in background
def start_scheduler():
    sched = BackgroundScheduler()
    sched.add_job(update_all_tracked, 'interval', hours=1, id='job_hourly')
    sched.start()
    return sched

if 'scheduler_started' not in st.session_state:
    start_scheduler()
    st.session_state['scheduler_started'] = True

st.title('Tournament Tracker (Streamlit)')
st_autorefresh(interval=60*60*1000, key="autorefresh")  # hourly refresh

# Show tracked tournaments
df_tracked = pd.read_sql('SELECT tournament_id, tournament_name, last_run FROM tracked', conn)
st.subheader('Tracked Tournaments')
st.dataframe(df_tracked)

# Add tournament
with st.form('add_tournament'):
    tid = st.text_input('Tournament ID')
    tname = st.text_input('Tournament Name (optional)')
    submit = st.form_submit_button('Add & Initialize')
    if submit and tid:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with lock:
            cur.execute('REPLACE INTO tracked (tournament_id, last_run, tournament_name) VALUES (?,?,?)',
                        (tid, now, tname or None))
            conn.commit()
        update_tournament(tid)
        st.success(f'Initialized {tid}')
        st.rerun()

# Remove tournament
remove_tid = st.selectbox('Stop tracking tournament', [''] + df_tracked['tournament_id'].tolist())
if remove_tid:
    if st.button('Remove selected tournament'):
        with lock:
            cur.execute('DELETE FROM tracked WHERE tournament_id=?', (remove_tid,))
            conn.commit()
        st.success(f'Stopped tracking {remove_tid}')
        st.rerun()

# Manual update
update_tid = st.selectbox('Manually update tournament', [''] + df_tracked['tournament_id'].tolist())
if update_tid:
    if st.button('Update selected tournament'):
        update_tournament(update_tid)
        st.success(f'Updated {update_tid}')
        st.rerun()

# Download CSV
csv_tid = st.selectbox('Download CSV for tournament', [''] + df_tracked['tournament_id'].tolist())
if csv_tid:
    csv_data = export_csv(csv_tid)
    st.download_button(
        label=f"Download CSV for {csv_tid}",
        data=csv_data,
        file_name=f"{csv_tid}_participants.csv",
        mime='text/csv'
    )

# Show participants for selected tournament
show_tid = st.selectbox('Show participants for tournament', [''] + df_tracked['tournament_id'].tolist())
if show_tid:
    df_part = pd.read_sql('SELECT * FROM participants WHERE tournament_id=?', conn, params=(show_tid,))
    st.dataframe(df_part)

st.markdown('---')
st.markdown('© Guido Thyssen 2025 | Streamlit version')
