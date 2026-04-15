from flask import Flask, request, jsonify
from flask_cors import CORS
import csv
import os
import sys
import json
import threading
import subprocess
from flask import Flask, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

llm_process = None
llm_thread = None

@app.route('/feedback', methods=['POST'])
def feedback():
    data = request.get_json(force=True)
    rating = data.get('rating', '')
    recommend = data.get('recommend', '')
    feedback_text = data.get('feedback', '')
    # Save to CSV (use absolute path)
    feedback_file = os.path.join(os.path.dirname(__file__), 'data', 'feedback.csv')
    file_exists = os.path.isfile(feedback_file)
    try:
        with open(feedback_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['rating', 'recommend', 'feedback'])
            writer.writerow([rating, recommend, feedback_text])
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


def start_llm():
    global llm_process
    llm_process = subprocess.Popen(
        [sys.executable, "llm.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    return llm_process


def read_llm_stdout():
    while True:
        if llm_process is None:
            break
        line = llm_process.stdout.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            socketio.emit("message", data)
        except Exception as e:
            socketio.emit("message", {
                "type": "debug",
                "content": f"[LLM Output Parse Error] {line}"
            })



def stop_llm():
    global llm_process
    if llm_process is not None:
        try:
            llm_process.terminate()
        except Exception:
            pass
        llm_process = None

@socketio.on("connect")
def handle_connect():
    global llm_process, llm_thread
    stop_llm()
    start_llm()
    llm_thread = threading.Thread(target=read_llm_stdout, daemon=True)
    llm_thread.start()
    emit("message", {"type": "system", "content": "Connected to backend."})


@socketio.on("user_message")
def handle_user_message(data):
    if llm_process and llm_process.stdin:
        try:
            llm_process.stdin.write(data + "\n")
            llm_process.stdin.flush()
        except Exception as e:
            emit("message", {"type": "debug", "content": f"[LLM Input Error] {str(e)}"})
    else:
        emit("message", {"type": "debug", "content": "LLM process not running."})


if __name__ == "__main__":
    # Use allow_unsafe_werkzeug for dev, so Flask routes work with SocketIO
    socketio.run(app, host="0.0.0.0", port=8080, allow_unsafe_werkzeug=True)


    @socketio.on("restart_chat")
    def handle_restart_chat():
        global llm_process, llm_thread
        start_llm()
        llm_thread = threading.Thread(target=read_llm_stdout, daemon=True)
        llm_thread.start()
        emit("message", {"type": "system", "content": "Chat restarted."})
