"""Full integration tests for the quiz platform."""
import time
import socketio
import urllib.request
import io
import csv

BASE = 'http://localhost:5001'

admin = socketio.Client()
student = socketio.Client()
student2 = socketio.Client()

results = {}

events = [
    ('joined', 'joined'),
    ('receive_question', 'question'),
    ('answer_feedback', 'feedback'),
    ('show_results', 'leaderboard'),
    ('game_over', 'game_over'),
]
for ev, key in events:
    student.on(ev, lambda data, k=key: results.update({k: data}))
    student2.on(ev, lambda data, k=key + '2': results.update({k: data}))

admin.on('admin_question_preview', lambda data: results.update({'admin_question': data}))
admin.on('show_results', lambda data: results.update({'admin_leaderboard': data}))

admin.connect(BASE)
student.connect(BASE)
student2.connect(BASE)

# Reset game before tests
admin.emit('admin_reset_game')
time.sleep(0.3)

try:
    # Test join
    student.emit('join_game', {'roll_no': 'R001', 'name': 'Alice'})
    student2.emit('join_game', {'roll_no': 'R002', 'name': 'Bob'})
    time.sleep(0.3)
    assert results.get('joined'), 'Alice did not join'
    print('✅ Two students joined')

    # Test question flow
    admin.emit('admin_next_question')
    time.sleep(0.3)
    q = results['question']['question']
    admin_q = results['admin_question']['question']
    correct = admin_q['correct']
    print('✅ Question sent:', q['question'][:40], f'(correct={correct})')

    # Alice answers correctly quickly
    student.emit('submit_answer', {'roll_no': 'R001', 'choice': correct})
    time.sleep(0.1)
    fb = results['feedback']
    assert fb['correct'] is True, 'Correct answer should be marked correct'
    assert fb['points'] > 0, 'Correct answer should earn points'
    alice_score = fb['score']
    print(f'✅ Alice correct: +{fb["points"]} points (score={alice_score})')

    # Bob answers incorrectly
    wrong = [k for k in q['options'] if k != correct][0]
    student2.emit('submit_answer', {'roll_no': 'R002', 'choice': wrong})
    time.sleep(0.1)
    fb2 = results['feedback2']
    assert fb2['correct'] is False, 'Wrong answer should be incorrect'
    assert fb2['points'] == 0, 'Wrong answer should earn 0 points'
    print('✅ Bob wrong: 0 points')

    # Leaderboard ranking
    lb = results['leaderboard']
    assert lb[0]['roll_no'] == 'R001' and lb[1]['roll_no'] == 'R002'
    print('✅ Leaderboard sorted correctly')

    # End game and save
    results.pop('game_over', None)
    admin.emit('admin_end_game')
    deadline = time.time() + 5.0
    while time.time() < deadline and 'game_over' not in results:
        time.sleep(0.1)
    assert results.get('game_over'), 'game_over event not received'
    print('✅ Game over emitted')

    # Test report download
    report = urllib.request.urlopen(f'{BASE}/download-report').read().decode('utf-8')
    rows = list(csv.reader(io.StringIO(report)))
    assert rows[0][:3] == ['Roll No', 'Name', 'Total Score']
    assert any(row[0] == 'R001' for row in rows[1:]), 'Report missing Alice'
    print(f'✅ CSV report generated with {len(rows)} rows')

    # Test CSV upload
    sample_csv = io.BytesIO(b'id,type,question,correct,timeLimit,A,B,C,D\n100,mcq,Test question?,A,10,Opt A,Opt B,Opt C,Opt D\n101,tf,Is this true?,True,5,True,False,,'.replace(b'\n', b'\r\n'))
    import requests
    res = requests.post(f'{BASE}/upload-csv', files={'questions_file': ('test.csv', sample_csv, 'text/csv')})
    assert res.json()['success'] and res.json()['count'] == 2, 'CSV upload failed'
    print('✅ CSV upload works')

    # After upload, next question should be from CSV
    admin.emit('admin_reset_game')
    time.sleep(0.5)
    admin.emit('admin_next_question')
    time.sleep(0.5)
    assert results['question']['question']['id'] == 100, 'Uploaded question not used'
    print('✅ Uploaded questions are active')

    print('\n🎉 Full integration tests passed!')
finally:
    student.disconnect()
    student2.disconnect()
    admin.disconnect()
