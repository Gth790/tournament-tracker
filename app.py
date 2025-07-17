from flask import Flask, render_template, request, redirect, url_for, jsonify
import pandas as pd
import os
import csv
import threading
from datetime import datetime
from supabase import create_client, Client
import pytz
import requests

app = Flask(__name__)

SUPABASE_URL = "https://zkszohjgstfkdjjklraq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inprc3pvaGpnc3Rma2RqamtscmFxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTExNzM4MjksImV4cCI6MjA2Njc0OTgyOX0.a7t29H0o8_fu3pK7OFvQ256-8HpAhsEVC4FuoLBDefY"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CSV_DIR = 'csv_exports'
os.makedirs(CSV_DIR, exist_ok=True)
lock = threading.Lock()

# Fetch participants from API
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

def get_tracked():
    try:
        res = supabase.table("tracked").select("*").execute()
        return res.data
    except Exception as e:
        print(f"Supabase error: {e}")
        return []

def initialize_tournament(tid, tname=None):
    try:
        participants = fetch_participants(tid)
        if not participants:
            return False, "No participants found"
        
        # Add to tracked tournaments
        supabase.table("tracked").upsert({
            "tournament_id": tid,
            "tournament_name": tname or f"Tournament {tid}",
            "last_updated": datetime.now().isoformat()
        }).execute()
        
        # Add participants
        for pid, name in participants:
            supabase.table("participants").upsert({
                "tournament_id": tid,
                "player_id": pid,
                "player_name": name,
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat()
            }).execute()
        
        return True, f"Initialized {len(participants)} participants"
    except Exception as e:
        return False, str(e)

def update_tournament(tid):
    try:
        current_participants = fetch_participants(tid)
        if not current_participants:
            return False, "No participants found"
        
        # Get existing participants
        existing = supabase.table("participants").select("*").eq("tournament_id", tid).execute()
        existing_ids = {p['player_id'] for p in existing.data}
        
        new_count = 0
        for pid, name in current_participants:
            if pid not in existing_ids:
                supabase.table("participants").insert({
                    "tournament_id": tid,
                    "player_id": pid,
                    "player_name": name,
                    "first_seen": datetime.now().isoformat(),
                    "last_seen": datetime.now().isoformat()
                }).execute()
                new_count += 1
            else:
                # Update last_seen
                supabase.table("participants").update({
                    "last_seen": datetime.now().isoformat()
                }).eq("tournament_id", tid).eq("player_id", pid).execute()
        
        # Update tournament last_updated
        supabase.table("tracked").update({
            "last_updated": datetime.now().isoformat()
        }).eq("tournament_id", tid).execute()
        
        return True, f"Updated: {new_count} new participants"
    except Exception as e:
        return False, str(e)

def remove_tournament(tid):
    try:
        supabase.table("participants").delete().eq("tournament_id", tid).execute()
        supabase.table("tracked").delete().eq("tournament_id", tid).execute()
        return True, "Tournament removed"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    tracked = get_tracked()
    return render_template('index.html', tracked=tracked)

@app.route('/tournament/<tid>')
def tournament_detail(tid):
    try:
        # Get tournament info
        tournament = supabase.table("tracked").select("*").eq("tournament_id", tid).execute()
        if not tournament.data:
            return "Tournament not found", 404
        
        # Get participants
        participants = supabase.table("participants").select("*").eq("tournament_id", tid).execute()
        
        return render_template('tournament.html', 
                             tournament=tournament.data[0], 
                             participants=participants.data)
    except Exception as e:
        return f"Error: {e}", 500

@app.route('/add_tournament', methods=['POST'])
def add_tournament():
    tid = request.form.get('tournament_id')
    tname = request.form.get('tournament_name', '')
    
    if not tid:
        return redirect(url_for('index'))
    
    success, message = initialize_tournament(tid, tname)
    return redirect(url_for('index'))

@app.route('/update_tournament/<tid>', methods=['POST'])
def update_tournament_route(tid):
    success, message = update_tournament(tid)
    return redirect(url_for('index'))

@app.route('/remove_tournament/<tid>', methods=['POST'])
def remove_tournament_route(tid):
    success, message = remove_tournament(tid)
    return redirect(url_for('index'))

@app.route('/api/tournaments')
def api_tournaments():
    tracked = get_tracked()
    return jsonify(tracked)

@app.route('/api/tournament/<tid>/participants')
def api_tournament_participants(tid):
    try:
        participants = supabase.table("participants").select("*").eq("tournament_id", tid).execute()
        return jsonify(participants.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)
