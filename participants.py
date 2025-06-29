import streamlit as st
import pandas as pd
import os
import csv
import threading
import sys
from datetime import datetime
from io import StringIO
from apscheduler.schedulers.background import BackgroundScheduler
from streamlit_autorefresh import st_autorefresh
from supabase import create_client, Client
import pytz

SUPABASE_URL = "https://zkszohjgstfkdjjklraq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inprc3pvaGpnc3Rma2RqamtscmFxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTExNzM4MjksImV4cCI6MjA2Njc0OTgyOX0.a7t29H0o8_fu3pK7OFvQ256-8HpAhsEVC4FuoLBDefY"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CSV_DIR = 'csv_exports'
os.makedirs(CSV_DIR, exist_ok=True)
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

def get_tracked():
    try:
        res = supabase.table("tracked").select("*").execute()
        return res.data or []
    except Exception as e:
        st.error(f"Supabase error: {e}")
        return []

def add_tournament(tid, tname, now):
    supabase.table("tracked").upsert({
        "tournament_id": tid,
        "last_run": now,
        "tournament_name": tname
    }).execute()

def remove_tournament(tid):
    supabase.table("tracked").delete().eq("tournament_id", tid).execute()
    # Do NOT delete from participants or changes anymore

def update_tournament(tid):
    stockholm = pytz.timezone('Europe/Stockholm')
    now = datetime.now(stockholm).strftime("%Y-%m-%d %H:%M:%S")
    entries = fetch_participants(tid)
    with lock:
        tracked = supabase.table("tracked").select("*").eq("tournament_id", tid).execute().data
        existing_name = tracked[0]["tournament_name"] if tracked else None
        add_tournament(tid, existing_name, now)
        participants = supabase.table("participants").select("participant_id, status").eq("tournament_id", tid).execute().data
        stored = {row["participant_id"]: row["status"] for row in participants} if participants else {}
        if not stored:
            for pid, name in entries:
                supabase.table("participants").upsert({
                    "tournament_id": tid,
                    "participant_id": pid,
                    "name": name,
                    "status": "active",
                    "joined_date": now,
                    "left_date": None
                }).execute()
            return
        for pid, name in entries:
            if pid not in stored:
                supabase.table("participants").upsert({
                    "tournament_id": tid,
                    "participant_id": pid,
                    "name": name,
                    "status": "active",
                    "joined_date": now,
                    "left_date": None
                }).execute()
                supabase.table("changes").insert({
                    "tournament_id": tid,
                    "participant_id": pid,
                    "change_type": "joined",
                    "change_date": now
                }).execute()
        for pid, status in stored.items():
            if status == 'active' and pid not in dict(entries):
                supabase.table("participants").update({
                    "status": "left",
                    "left_date": now
                }).eq("tournament_id", tid).eq("participant_id", pid).execute()
                supabase.table("changes").insert({
                    "tournament_id": tid,
                    "participant_id": pid,
                    "change_type": "left",
                    "change_date": now
                }).execute()

def export_csv(tid):
    rows = supabase.table("participants").select("participant_id,name,status,joined_date,left_date").eq("tournament_id", tid).execute().data
    output = StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID','Name','Status','Joined','Left'])
    for row in rows:
        writer.writerow([row['participant_id'], row['name'], row['status'], row['joined_date'] or '', row['left_date'] or ''])
    return output.getvalue()

def get_all_tournament_ids():
    # Get all unique tournament_ids from participants table
    res = supabase.table("participants").select("tournament_id").execute()
    ids = set(row['tournament_id'] for row in res.data) if res.data else set()
    # Also include currently tracked tournaments
    tracked = get_tracked()
    ids.update(row['tournament_id'] for row in tracked)
    return sorted(ids)

# Scheduler for hourly update
def update_all_tracked():
    tracked = get_tracked()
    for row in tracked:
        try:
            update_tournament(row['tournament_id'])
        except Exception as e:
            print(f"Error updating {row['tournament_id']}: {e}", file=sys.stderr)

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
df_tracked = pd.DataFrame(get_tracked())

# Build a mapping of tournament_id to tournament_name for all tournaments ever tracked
all_tids = get_all_tournament_ids()
# Get names for all_tids from tracked and participants tables
id_to_name = {}
for row in get_tracked():
    if row.get('tournament_id') and row.get('tournament_name'):
        id_to_name[row['tournament_id']] = row['tournament_name']
# Fallback: try to get names from participants table if not in tracked
def get_name_from_participants(tid):
    res = supabase.table("participants").select("name").eq("tournament_id", tid).limit(1).execute()
    if res.data and len(res.data) > 0:
        return res.data[0].get('name')
    return None
for tid in all_tids:
    if tid not in id_to_name:
        name = get_name_from_participants(tid)
        if name:
            id_to_name[tid] = name
# Build display options for dropdowns
def display_label(tid):
    name = id_to_name.get(tid)
    return f"{name} ({tid})" if name else str(tid)
remove_options = [''] + [display_label(tid) for tid in df_tracked['tournament_id'].tolist()] if not df_tracked.empty else ['']
remove_map = {display_label(tid): tid for tid in df_tracked['tournament_id'].tolist()} if not df_tracked.empty else {}
update_options = [''] + [display_label(tid) for tid in df_tracked['tournament_id'].tolist()] if not df_tracked.empty else ['']
update_map = {display_label(tid): tid for tid in df_tracked['tournament_id'].tolist()} if not df_tracked.empty else {}
csv_options = [''] + [display_label(tid) for tid in all_tids]
csv_map = {display_label(tid): tid for tid in all_tids}
show_options = [''] + [display_label(tid) for tid in all_tids]
show_map = {display_label(tid): tid for tid in all_tids}

st.subheader('Tracked Tournaments')
st.dataframe(df_tracked)

# Add tournament
with st.form('add_tournament'):
    tid = st.text_input('Tournament ID')
    tname = st.text_input('Tournament Name (optional)')
    submit = st.form_submit_button('Add & Initialize')
    if submit and tid:
        stockholm = pytz.timezone('Europe/Stockholm')
        now = datetime.now(stockholm).strftime("%Y-%m-%d %H:%M:%S")
        with lock:
            add_tournament(tid, tname or None, now)
        update_tournament(tid)
        st.success(f'Initialized {tid}')
        st.rerun()

# Remove tournament
remove_tid_label = st.selectbox('Stop tracking tournament', remove_options)
remove_tid = remove_map.get(remove_tid_label, '')
if remove_tid:
    if st.button('Remove selected tournament'):
        with lock:
            remove_tournament(remove_tid)
        st.success(f'Stopped tracking {remove_tid}')
        st.rerun()

# Manual update (only for currently tracked)
update_tid_label = st.selectbox('Manually update tournament', update_options)
update_tid = update_map.get(update_tid_label, '')
if update_tid:
    if st.button('Update selected tournament'):
        update_tournament(update_tid)
        st.success(f'Updated {update_tid}')
        st.rerun()

# Download CSV (for all ever tracked)
csv_tid_label = st.selectbox('Download CSV for tournament', csv_options)
csv_tid = csv_map.get(csv_tid_label, '')
if csv_tid:
    csv_data = export_csv(csv_tid)
    st.download_button(
        label=f"Download CSV for {csv_tid}",
        data=csv_data,
        file_name=f"{csv_tid}_participants.csv",
        mime='text/csv'
    )

# Show participants for selected tournament (for all ever tracked)
show_tid_label = st.selectbox('Show participants for tournament', show_options)
show_tid = show_map.get(show_tid_label, '')
if show_tid:
    df_part = pd.DataFrame(supabase.table("participants").select("*").eq("tournament_id", show_tid).execute().data)
    st.dataframe(df_part)

st.markdown('---')
st.markdown('© Guido Thyssen 2025 | Streamlit version')
