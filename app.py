import os
import time
import json
import csv
import io
from datetime import datetime
from collections import OrderedDict

from flask import Flask, render_template, Response, request
from flask_socketio import SocketIO, emit

# ==========================================
# 1. SERVER CONFIGURATION
# ==========================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key'
# cors_allowed_origins="*" allows phones on other networks to connect
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Database is optional for local testing; gracefully degraded if missing
NEON_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_cgnF9QEY0xBo@ep-winter-sky-aoist5rl-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

# ==========================================
# 2. DEFAULT QUESTIONS (Email Etiquette)
# ==========================================
DEFAULT_QUESTIONS = [
    {"id": 1, "type": "mcq", "question": "What is the main purpose of email etiquette?", "options": {"A": "To make emails longer", "B": "To communicate professionally and clearly", "C": "To use difficult words", "D": "To send more attachments"}, "correct": "B", "timeLimit": 20},
    {"id": 2, "type": "mcq", "question": "Which field contains the main recipient's email address?", "options": {"A": "CC", "B": "BCC", "C": "To", "D": "Subject"}, "correct": "C", "timeLimit": 20},
    {"id": 3, "type": "mcq", "question": "What is the purpose of CC in an email?", "options": {"A": "Hide recipients", "B": "Send a copy to additional people", "C": "Delete email", "D": "Add attachment"}, "correct": "B", "timeLimit": 20},
    {"id": 4, "type": "mcq", "question": "What does BCC mean?", "options": {"A": "Basic Carbon Copy", "B": "Blind Carbon Copy", "C": "Business Communication Copy", "D": "Backup Contact Copy"}, "correct": "B", "timeLimit": 20},
    {"id": 5, "type": "mcq", "question": "Which part of an email briefly explains the email purpose?", "options": {"A": "Greeting", "B": "Signature", "C": "Subject line", "D": "Attachment"}, "correct": "C", "timeLimit": 20},
    {"id": 6, "type": "mcq", "question": "Which is the most professional greeting?", "options": {"A": "Hey buddy", "B": "Hi bro", "C": "Dear Professor", "D": "Yo"}, "correct": "C", "timeLimit": 20},
    {"id": 7, "type": "mcq", "question": "What should you do before sending a professional email?", "options": {"A": "Use emojis everywhere", "B": "Check spelling and grammar", "C": "Write in capital letters", "D": "Leave the subject empty"}, "correct": "B", "timeLimit": 20},
    {"id": 8, "type": "mcq", "question": "Writing an email in ALL CAPITAL LETTERS usually represents:", "options": {"A": "Professional writing", "B": "Shouting or being rude", "C": "Formal greeting", "D": "Better communication"}, "correct": "B", "timeLimit": 20},
    {"id": 9, "type": "mcq", "question": "What is an attachment in an email?", "options": {"A": "A password", "B": "A file sent with the email", "C": "The recipient name", "D": "Email subject"}, "correct": "B", "timeLimit": 20},
    {"id": 10, "type": "mcq", "question": "Which is a common email mistake?", "options": {"A": "Clear subject line", "B": "Polite closing", "C": "Sending without proofreading", "D": "Professional signature"}, "correct": "C", "timeLimit": 20},
    {"id": 11, "type": "tf", "question": "Email etiquette helps maintain professional communication.", "options": {"True": "True", "False": "False"}, "correct": "True", "timeLimit": 15},
    {"id": 12, "type": "tf", "question": "The CC field is used to hide recipients from each other.", "options": {"True": "True", "False": "False"}, "correct": "False", "timeLimit": 15},
    {"id": 13, "type": "tf", "question": "A good email should have a clear subject line.", "options": {"True": "True", "False": "False"}, "correct": "True", "timeLimit": 15},
    {"id": 14, "type": "tf", "question": "Writing an email completely in capital letters is considered professional.", "options": {"True": "True", "False": "False"}, "correct": "False", "timeLimit": 15},
    {"id": 15, "type": "tf", "question": "BCC allows sending a copy of an email without showing the recipient list to others.", "options": {"True": "True", "False": "False"}, "correct": "True", "timeLimit": 15},
    {"id": 16, "type": "tf", "question": "It is okay to send a professional email without checking spelling and grammar.", "options": {"True": "True", "False": "False"}, "correct": "False", "timeLimit": 15},
    {"id": 17, "type": "tf", "question": "The 'To' field contains the main person who should receive the email.", "options": {"True": "True", "False": "False"}, "correct": "True", "timeLimit": 15},
    {"id": 18, "type": "tf", "question": "Attachments are used to send files like documents and images.", "options": {"True": "True", "False": "False"}, "correct": "True", "timeLimit": 15},
    {"id": 19, "type": "tf", "question": "Using slang words like 'Hey bro' is suitable when emailing a professor or company.", "options": {"True": "True", "False": "False"}, "correct": "False", "timeLimit": 15},
    {"id": 20, "type": "tf", "question": "A professional email should end with a polite closing and signature.", "options": {"True": "True", "False": "False"}, "correct": "True", "timeLimit": 15},
]

# ==========================================
# 3. IN-MEMORY STATE (RAM)
# ==========================================
quiz_state = {
    "questions": list(DEFAULT_QUESTIONS),
    "current_index": -1,            # -1 means lobby / no active question
    "active_question": None,        # question dict currently displayed
    "start_time": 0,                # epoch seconds when question started
    "answers_locked": set(),        # {(roll_no, question_id)} answered this question
    "students": OrderedDict(),      # {roll_no: {"name": str, "score": int, "answers": []}}
    "session_complete": False,
}

# ==========================================
# 4. DATABASE HELPER FUNCTIONS
# ==========================================
def get_db_connection():
    import psycopg2
    return psycopg2.connect(NEON_DB_URL)

def init_db():
    """Creates the results table if it doesn't exist yet."""
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
        print("✅ Neon Database Initialized Successfully!")
    except Exception as e:
        print(f"⚠️ Database initialization skipped: {e}")

init_db()

# ==========================================
# 5. CSV QUESTION LOADER
# ==========================================
CSV_COLUMNS = ['id', 'type', 'question', 'correct', 'timeLimit', 'A', 'B', 'C', 'D']

def parse_questions_csv(file_storage):
    """Parse uploaded CSV into the internal question format."""
    stream = io.StringIO(file_storage.stream.read().decode('utf-8'), newline=None)
    reader = csv.DictReader(stream)
    questions = []
    for row in reader:
        q_type = (row.get('type') or 'mcq').strip().lower()
        options = OrderedDict()
        if q_type == 'tf':
            options['True'] = 'True'
            options['False'] = 'False'
        else:
            for key in ['A', 'B', 'C', 'D']:
                val = (row.get(key) or '').strip()
                if val:
                    options[key] = val
        question = {
            'id': int(row['id']),
            'type': q_type,
            'question': row['question'].strip(),
            'options': options,
            'correct': row['correct'].strip(),
            'timeLimit': int(row.get('timeLimit') or 20),
        }
        questions.append(question)
    return questions

# ==========================================
# 6. HTTP ROUTES
# ==========================================
@app.route('/')
def student_view():
    return render_template('student.html')

@app.route('/admin')
def admin_view():
    return render_template('admin.html')

@app.route('/upload-csv', methods=['POST'])
def upload_csv():
    """Admin endpoint to replace current question set from CSV."""
    if 'questions_file' not in request.files:
        return {'success': False, 'error': 'No file provided'}, 400
    file = request.files['questions_file']
    if file.filename == '':
        return {'success': False, 'error': 'Empty filename'}, 400
    try:
        questions = parse_questions_csv(file)
        quiz_state['questions'] = questions
        quiz_state['current_index'] = -1
        quiz_state['active_question'] = None
        quiz_state['answers_locked'] = set()
        return {'success': True, 'count': len(questions)}
    except Exception as e:
        return {'success': False, 'error': str(e)}, 400

@app.route('/download-report')
def download_report():
    """Generates CSV report from the current session state."""
    questions = quiz_state['questions']
    students = quiz_state['students']

    def generate():
        output = io.StringIO()
        writer = csv.writer(output)

        header = ['Roll No', 'Name', 'Total Score']
        for q in questions:
            header.append(f"Q{q['id']}")
        writer.writerow(header)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for roll_no, data in students.items():
            answers_by_qid = {a['q_id']: a for a in data.get('answers', [])}
            row = [roll_no, data['name'], data['score']]
            for q in questions:
                ans = answers_by_qid.get(q['id'])
                if ans:
                    mark = '✓' if ans['correct'] else '✗'
                    row.append(f"{mark} {ans['points']}pts ({ans['time']}s)")
                else:
                    row.append('-')
            writer.writerow(row)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    filename = f"quiz_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        generate(),
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ==========================================
# 7. WEBSOCKET EVENTS
# ==========================================
@socketio.on('connect')
def handle_connect():
    # Send current state to the newly connected client
    emit('state_sync', {
        'connected_count': len(quiz_state['students']),
        'active_question': quiz_state['active_question'],
        'current_index': quiz_state['current_index'],
        'total': len(quiz_state['questions']),
        'session_complete': quiz_state['session_complete'],
    })

@socketio.on('join_game')
def handle_join(data):
    roll_no = str(data.get('roll_no', '')).strip().upper()
    name = str(data.get('name', '')).strip()

    if not roll_no or not name:
        emit('join_error', {'message': 'Roll No and Name are required'})
        return

    if roll_no not in quiz_state['students']:
        quiz_state['students'][roll_no] = {
            'name': name,
            'score': 0,
            'answers': []
        }
    else:
        # Update name if student rejoins
        quiz_state['students'][roll_no]['name'] = name

    print(f"Student Joined: {name} ({roll_no})")
    emit('joined', {'roll_no': roll_no, 'name': name})
    emit('update_lobby', {
        'count': len(quiz_state['students']),
        'students': list(quiz_state['students'].values())
    }, broadcast=True)

@socketio.on('admin_next_question')
def next_question():
    """Advance to the next question and broadcast it."""
    if quiz_state['session_complete']:
        emit('admin_error', {'message': 'Session already complete. End or reset the game.'})
        return

    quiz_state['current_index'] += 1
    if quiz_state['current_index'] >= len(quiz_state['questions']):
        emit('admin_error', {'message': 'No more questions. Use End Game.'})
        quiz_state['current_index'] -= 1
        return

    question = quiz_state['questions'][quiz_state['current_index']]
    quiz_state['active_question'] = question
    quiz_state['start_time'] = time.time()

    # Students receive question without the correct answer (prevent cheating)
    client_question = {k: v for k, v in question.items() if k != 'correct'}

    socketio.emit('receive_question', {
        'question': client_question,
        'index': quiz_state['current_index'] + 1,
        'total': len(quiz_state['questions'])
    })

    # Admin also gets the full question preview including correct answer
    socketio.emit('admin_question_preview', {
        'question': question,
        'index': quiz_state['current_index'] + 1,
        'total': len(quiz_state['questions'])
    })

    print(f"📢 Question {quiz_state['current_index'] + 1} sent: {question['question'][:50]}...")

@socketio.on('submit_answer')
def handle_answer(data):
    roll_no = str(data.get('roll_no', '')).strip().upper()
    choice = str(data.get('choice', '')).strip()

    if roll_no not in quiz_state['students']:
        emit('answer_feedback', {'error': 'Student not found'})
        return

    question = quiz_state['active_question']
    if not question:
        emit('answer_feedback', {'error': 'No active question'})
        return

    lock_key = (roll_no, question['id'])
    if lock_key in quiz_state['answers_locked']:
        emit('answer_feedback', {'error': 'Already answered'})
        return

    time_taken = time.time() - quiz_state['start_time']
    time_limit = question.get('timeLimit', 20)

    # Validate the choice exists
    if choice not in question['options']:
        emit('answer_feedback', {'error': 'Invalid choice'})
        return

    is_correct = (choice == str(question['correct']))
    points = 0
    if is_correct:
        # Linear decay: 1000 points at t=0, 0 points at timeLimit
        deduction_per_second = 1000 / time_limit
        points = max(0, int(1000 - (time_taken * deduction_per_second)))

    quiz_state['answers_locked'].add(lock_key)
    quiz_state['students'][roll_no]['score'] += points
    quiz_state['students'][roll_no]['answers'].append({
        'q_id': question['id'],
        'choice': choice,
        'correct': is_correct,
        'points': points,
        'time': round(time_taken, 2),
    })

    emit('answer_feedback', {
        'correct': is_correct,
        'points': points,
        'score': quiz_state['students'][roll_no]['score'],
        'correct_choice': str(question['correct']) if is_correct else None
    })

    # Auto-update leaderboard after every answer
    broadcast_leaderboard()

@socketio.on('admin_show_leaderboard')
def admin_show_leaderboard():
    broadcast_leaderboard()

def broadcast_leaderboard():
    sorted_board = sorted(
        quiz_state['students'].items(),
        key=lambda x: x[1]['score'],
        reverse=True
    )
    payload = [
        {'rank': i + 1, 'roll_no': r, 'name': d['name'], 'score': d['score']}
        for i, (r, d) in enumerate(sorted_board)
    ]
    socketio.emit('show_results', payload)

@socketio.on('admin_end_game')
def handle_end_game():
    """Save session results and notify all clients."""
    quiz_state['session_complete'] = True
    quiz_state['active_question'] = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for roll_no, data in quiz_state['students'].items():
            cur.execute('''
                INSERT INTO quiz_results (roll_no, name, total_score, answers_json)
                VALUES (%s, %s, %s, %s)
            ''', (roll_no, data['name'], data['score'], json.dumps(data.get('answers', []))))
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Session saved to Neon DB!")
    except Exception as e:
        print(f"⚠️ Could not save to database: {e}")

    emit('game_over', {
        'students': [
            {'roll_no': r, 'name': d['name'], 'score': d['score']}
            for r, d in quiz_state['students'].items()
        ]
    }, broadcast=True)

@socketio.on('admin_reset_game')
def handle_reset_game():
    """Clear RAM state for the next class while keeping the loaded question set."""
    quiz_state['current_index'] = -1
    quiz_state['active_question'] = None
    quiz_state['start_time'] = 0
    quiz_state['answers_locked'] = set()
    quiz_state['students'] = OrderedDict()
    quiz_state['session_complete'] = False
    emit('game_reset', broadcast=True)
    emit('update_lobby', {'count': 0, 'students': []}, broadcast=True)
    print("🔄 Game state reset")

# ==========================================
# 8. RUN THE SERVER
# ==========================================
if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', '5001'))
    socketio.run(app, debug=debug, host=host, port=port, allow_unsafe_werkzeug=True)
