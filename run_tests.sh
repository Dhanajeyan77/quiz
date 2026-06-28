#!/bin/bash
set -e
cd /mnt/c/quiz
pkill -f "python3 app.py" 2>/dev/null || true
sleep 1
rm -f server.log
python3 -u app.py > server.log 2>&1 &
SERVER_PID=$!
sleep 4
echo "SERVER_PID=$SERVER_PID"
if ps -p $SERVER_PID > /dev/null 2>&1; then echo "ALIVE=yes"; else echo "ALIVE=no"; fi
curl -sf http://localhost:5001/ > /dev/null && echo "SERVER_UP=yes" || echo "SERVER_UP=no"
python3 -u test_full.py
TEST_RC=$?
echo "TEST_RC=$TEST_RC"
kill $SERVER_PID 2>/dev/null || true
exit $TEST_RC
