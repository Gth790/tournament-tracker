import sqlite3
import threading
from datetime import datetime
import requests

DB_FILE = 'participants.db'

def fetch_participants(tid):
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

def update_tournament(tid, cur, conn, lock):
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

def update_all_tracked():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()
    lock = threading.Lock()
    tracked = cur.execute('SELECT tournament_id FROM tracked').fetchall()
    for (tid,) in tracked:
        try:
            update_tournament(tid, cur, conn, lock)
        except Exception as e:
            print(f"Error updating {tid}: {e}")
    conn.close()

if __name__ == '__main__':
    update_all_tracked()