import os
import time
import json
import csv
import io
import eventlet
# Crucial for Linux/WSL to prevent WebSockets from freezing
eventlet.monkey_patch()

from collections import OrderedDict
from datetime import datetime
from flask import Flask, render_template, Response, request
from flask_socketio import SocketIO, emit

# ==========================================
# 1. SERVER CONFIGURATION
# ==========================================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'super-secret-key')
# Forcing eventlet guarantees the real-time sockets won't hang
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

NEON_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_cgnF9QEY0xBo@ep-winter-sky-aoist5rl-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

# ==========================================
# 2. IN-MEMORY STATE (RAM)
# ==========================================
quiz_state = {
    "questions": [],
    "current_index": -1,
    "active_question": None,
    "start_time": 0,
    "answers_locked": set(),
    "students": OrderedDict(),
    "session_complete": False,
}

# ==========================================
# 3. DATABASE LOGIC
# ==========================================
def get_db_connection():
    import psycopg2
    return psycopg2.connect(NEON_DB_URL)

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS quiz_results (
                id SERIAL PRIMARY KEY,
                roll_no VARCHAR(20) NOT NULL,
                name VARCHAR(100) NOT NULL,
                total_score INT NOT NULL,
                answers_json TEXT NOT NULL,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Neon DB Connected & Ready")
    except Exception as e:
        print(f"⚠️ DB Skipped (Will run in RAM only): {e}")

init_db()


# ==========================================
# 5. HTTP ROUTES
# ==========================================
@app.route('/')
def student_view():
    return render_template("student.html")


@app.route('/admin')
def admin_view():
    return render_template("admin.html")

@app.route('/ping')
def ping():
    return "<h1>Server is successfully running!</h1>"


@app.route('/upload-csv', methods=['POST'])
def upload_csv():
    file = request.files.get('file')
    if not file: return {'success': False, 'error': 'No file'}, 400
    try:
        stream = io.StringIO(file.read().decode('utf-8'), newline=None)
        reader = csv.DictReader(stream)
        questions = []
        for row in reader:
            # Detect options based on type
            if row['type'] == 'mcq':
                options = {k: row[k] for k in ['A','B','C','D'] if row.get(k)}
            else: # tf type
                options = {'A': 'True', 'B': 'False'}
            
            q = {
                'id': int(row['id']),
                'question': row['question'].strip(),
                'options': options,
                'correct': row['correct'].strip().upper(), # Normalize to Upper
                'timeLimit': int(row.get('timeLimit', 20))
            }
            questions.append(q)
        quiz_state['questions'] = questions
        quiz_state['current_index'] = -1
        return {'success': True, 'count': len(questions)}
    except Exception as e:
        return {'success': False, 'error': str(e)}

@app.route('/download-report')
def download_report():
    def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        headers = ['Roll No', 'Name', 'Total Score'] + [f"Q{q['id']}" for q in quiz_state['questions']]
        writer.writerow(headers)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for rno, data in quiz_state['students'].items():
            ans_map = {a['q_id']: a for a in data.get('answers', [])}
            row = [rno, data['name'], data['score']]
            for q in quiz_state['questions']:
                a = ans_map.get(q['id'])
                row.append(f"{a['points']}pts" if a and a['correct'] else "0pts")
            writer.writerow(row)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return Response(
        generate(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment; filename=results.csv"}
    )

# ==========================================
# 6. WEBSOCKET LOGIC
# ==========================================
@socketio.on('join_game')
def handle_join(data):
    rno, name = data['roll_no'], data['name']
    
    # If they are already in the list, just update their status
    if rno in quiz_state['students']:
        print(f"Student {rno} re-joined.")
    else:
        quiz_state['students'][rno] = {'name': name, 'score': 0, 'answers': []}
    
    emit('update_lobby', {'count': len(quiz_state['students'])}, broadcast=True)
    
    # If the game is currently active, push the current question to them immediately!
    if quiz_state['active_question']:
        q = quiz_state['active_question']
        client_q = {k: v for k, v in q.items() if k != 'correct'}
        emit('receive_question', {
            'question': client_q, 
            'index': quiz_state['current_index'] + 1, 
            'total': len(quiz_state['questions'])
        })


@socketio.on('admin_next_question')
def next_question():
    if quiz_state['session_complete']:
        return

    quiz_state['current_index'] += 1
    if quiz_state['current_index'] >= len(quiz_state['questions']):
        return

    q = quiz_state['questions'][quiz_state['current_index']]
    quiz_state['active_question'] = q
    quiz_state['start_time'] = time.time()

    client_q = {k: v for k, v in q.items() if k != 'correct'}
    socketio.emit('receive_question', {
        'question': client_q,
        'index': quiz_state['current_index'] + 1,
        'total': len(quiz_state['questions'])
    })

    # ⏱️ Start the Auto-Advance Timer (Time Limit + 3 seconds for students to read scores)
    socketio.start_background_task(auto_advance, quiz_state['current_index'], q.get('timeLimit', 20))


def auto_advance(target_index, time_limit):
    """Waits in the background, then pushes the next question automatically."""
    eventlet.sleep(time_limit + 3)

    # Check if the game is still active and we haven't already skipped ahead
    if quiz_state['current_index'] == target_index and not quiz_state['session_complete']:
        if quiz_state['current_index'] + 1 >= len(quiz_state['questions']):
            end_game()  # Auto-terminate and save if it was the last question
        else:
            next_question()  # Deploy the next question automatically


@socketio.on('submit_answer')
def handle_answer(data):
    # 1. Extract and Validate
    rno = data.get('roll_no')
    choice = str(data.get('choice', '')).strip().upper()
    q = quiz_state.get('active_question')
    
    if not rno or not q or (rno, q['id']) in quiz_state['answers_locked']:
        return

    # 2. Lock the answer to prevent double-submissions
    quiz_state['answers_locked'].add((rno, q['id']))
    
    # 3. Normalize Correct Answer
    # We strip and upper the CSV value
    correct_ans = str(q['correct']).strip().upper()
    
    # Map TF labels to A/B if the CSV uses words instead of keys
    if correct_ans == 'TRUE': correct_ans = 'A'
    if correct_ans == 'FALSE': correct_ans = 'B'
    
    # 4. Scoring Logic
    time_taken = time.time() - quiz_state['start_time']
    is_correct = (choice == correct_ans)
    
    # Award points: 1000 max, decaying by speed
    # We give 0 if they were too slow (time_taken > timeLimit)
    time_limit = q.get('timeLimit', 20)
    if time_taken > time_limit:
        pts = 0
    else:
        pts = int(1000 - (time_taken * (1000 / time_limit))) if is_correct else 0
    
    # 5. Update State
    if rno in quiz_state['students']:
        quiz_state['students'][rno]['score'] += pts
        quiz_state['students'][rno]['answers'].append({
            'q_id': q['id'], 
            'correct': is_correct, 
            'points': pts
        })
    
    # 6. Push Feedback
    # This specifically targets the student who just answered
    emit('answer_feedback', {
        'correct': is_correct, 
        'points': pts, 
        'score': quiz_state['students'][rno]['score'] if rno in quiz_state['students'] else 0
    })
    
    # Optional: Update Admin Leaderboard in real-time
    admin_show_leaderboard()

@socketio.on('admin_show_leaderboard')
def admin_show_leaderboard():
    board = sorted(quiz_state['students'].items(), key=lambda x: x[1]['score'], reverse=True)
    payload = [{'rank': i + 1, 'roll_no': r, 'name': d['name'], 'score': d['score']} for i, (r, d) in enumerate(board)]
    socketio.emit('show_results', payload)


@socketio.on('admin_end_game')
def end_game():
    quiz_state['session_complete'] = True  # Locks the game to prevent auto-advancing
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for rno, d in quiz_state['students'].items():
            cur.execute(
                'INSERT INTO quiz_results (roll_no, name, total_score, answers_json) VALUES (%s, %s, %s, %s)',
                (rno, d['name'], d['score'], json.dumps(d['answers']))
            )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("DB Save Error:", e)

    # 🏆 Broadcast the Final Leaderboard to ALL Students
    board = sorted(quiz_state['students'].items(), key=lambda x: x[1]['score'], reverse=True)
    payload = [{'rank': i + 1, 'roll_no': r, 'name': d['name'], 'score': d['score']} for i, (r, d) in enumerate(board)]
    socketio.emit('game_over', {'leaderboard': payload})


if __name__ == '__main__':
    # Binds directly to the exact port. Access via http://127.0.0.1:5002
    socketio.run(app, host='0.0.0.0', port=5002, debug=False)
