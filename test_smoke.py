"""Smoke tests for the quiz platform."""
import time
import socketio

BASE = 'http://localhost:5001'

admin = socketio.Client()
student = socketio.Client()

results = {}

@student.on('joined')
def on_joined(data):
    results['joined'] = data

@student.on('receive_question')
def on_question(data):
    results['question'] = data

@student.on('answer_feedback')
def on_feedback(data):
    results['feedback'] = data

@student.on('show_results')
def on_results(data):
    results['leaderboard'] = data

@student.on('game_over')
def on_over(data):
    results['game_over'] = data

@admin.on('receive_question')
def admin_on_question(data):
    results['admin_question'] = data

@admin.on('show_results')
def admin_on_results(data):
    results['admin_leaderboard'] = data

admin.connect(BASE)
student.connect(BASE)

try:
    student.emit('join_game', {'roll_no': '22CSEC01', 'name': 'Test Student'})
    time.sleep(0.5)
    assert results.get('joined'), 'Student did not receive joined event'
    print('✅ Student joined:', results['joined'])

    admin.emit('admin_next_question')
    time.sleep(0.5)
    assert results.get('question'), 'Student did not receive question'
    q = results['question']['question']
    print('✅ Question received:', q['question'][:40])

    # Submit first option (likely wrong) to test flow; correct handling is verified server side
    options = list(q['options'].keys())
    choice = options[0]
    student.emit('submit_answer', {'roll_no': '22CSEC01', 'choice': choice})
    time.sleep(0.5)
    assert results.get('feedback'), 'Student did not receive answer feedback'
    print('✅ Answer feedback:', results['feedback'])

    # Leaderboard should be emitted automatically
    assert results.get('leaderboard'), 'Leaderboard not emitted'
    print('✅ Leaderboard:', results['leaderboard'])

    admin.emit('admin_end_game')
    time.sleep(0.5)
    assert results.get('game_over'), 'Game over not received'
    print('✅ Game over:', results['game_over'])

    # HTTP endpoints
    import urllib.request
    student_html = urllib.request.urlopen(f'{BASE}/').read()
    assert b'Join Quiz Session' in student_html
    print('✅ Student page renders')

    admin_html = urllib.request.urlopen(f'{BASE}/admin').read()
    assert b'Admin Dashboard' in admin_html
    print('✅ Admin page renders')

    print('\n🎉 All smoke tests passed!')
finally:
    student.disconnect()
    admin.disconnect()
