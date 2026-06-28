# Quiz Platform Usage Guide

A real-time, Kahoot-style multiplayer quiz platform built with Flask-SocketIO.

## Quick Start

1. **Install dependencies**
   ```bash
   python3 -m pip install -r requirements.txt
   ```

2. **Start the server**
   ```bash
   python3 app.py
   ```
   The server binds to `0.0.0.0` and runs on `http://localhost:5001` by default so it is reachable from Windows browsers when running inside WSL.

3. **Open the views**
   - Student (mobile): `http://localhost:5001`
   - Admin (desktop): `http://localhost:5001/admin`

   If you prefer a different port, set `FLASK_PORT`:
   ```bash
   FLASK_PORT=8080 python3 app.py
   ```

## Admin Dashboard

1. **Load questions**
   - By default the 20 Email Etiquette questions are already loaded.
   - To load your own set, click **Choose File** under *Question Data*, select a CSV file in the format below, then click **Load CSV**.

2. **Start the game**
   - Click **Next Question** to broadcast the first question to all connected students.
   - Click it again to move through the question set one at a time.

3. **During the game**
   - The *Connected Students* counter shows how many players are in the session.
   - The *Current Question* preview shows the question, options, and the correct answer (admin only).
   - The *Live Leaderboard* updates automatically every time a student answers.
   - You can click **Show Leaderboard** at any time to force an update.

4. **Finish the game**
   - Click **End Game & Save to DB** to save all scores and answers to the Neon PostgreSQL database and notify students that the session is over.
   - Click **Download CSV Report** to export a CSV with Roll No, Name, Total Score, and a detailed answer matrix for every question.

5. **Reset**
   - Click **Reset Game** to clear scores and students for the next class while keeping the currently loaded question set.

## Student Flow

1. **Lobby**
   - Enter your **Roll No** and **Full Name**.
   - Tap **Join Session**.

2. **Waiting**
   - You will see a loading spinner and the message *"Waiting for Admin to start..."*.
   - Your current score is shown (starts at 0).

3. **Answer**
   - When the admin sends a question, read it and tap one of the four options before the timer runs out.
   - Once you tap an option, the buttons are locked and you will see your result.

4. **Final screen**
   - After the admin ends the game, your final score is displayed with *"Session Complete"*.

## CSV Question Format

The platform expects a CSV with these columns:

```csv
id,type,question,correct,timeLimit,A,B,C,D
```

| Column | Description |
|--------|-------------|
| `id` | Unique question number |
| `type` | `mcq` for multiple-choice or `tf` for True/False |
| `question` | The question text |
| `correct` | The correct option key (`A`, `B`, `C`, `D`, `True`, or `False`) |
| `timeLimit` | Time allowed in seconds (e.g., `20`) |
| `A`, `B`, `C`, `D` | Option labels. For True/False questions use `True` and `False` in `A` and `B`, and leave `C` and `D` empty. |

### Example rows

```csv
id,type,question,correct,timeLimit,A,B,C,D
1,mcq,What is the main purpose of email etiquette?,B,20,To make emails longer,To communicate professionally and clearly,To use difficult words,To send more attachments
11,tf,Email etiquette helps maintain professional communication.,True,15,True,False,,
```

A ready-made file with the default 20 questions is included as `questions.csv`.

## Scoring

- Correct answers start at 1000 points.
- Points decrease linearly over the question time limit.
- Wrong or late answers receive 0 points.

## Environment Variables

- `DATABASE_URL` — PostgreSQL connection string. If not set, the app falls back to the bundled Neon URL and skips database operations if the connection fails.
- `FLASK_DEBUG=true` — Enables Flask debug mode (not recommended for live sessions).

## Production Deployment

For production, run with Gunicorn and the `eventlet` worker:

```bash
gunicorn -k eventlet -w 1 app:app
```

Make sure `eventlet` is installed.

## Troubleshooting

- **Port already in use**: Stop any other process on port 5000, or set a different port in `app.py`.
- **Students cannot connect**: Check that phones are on the same network and use the host computer's local IP address instead of `localhost`.
- **CSV upload fails**: Ensure the CSV header exactly matches `id,type,question,correct,timeLimit,A,B,C,D` and is saved as UTF-8.
