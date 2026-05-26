import os
import sqlite3
import json
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template_string, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

DB_PATH = 'chat_database.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  sender TEXT NOT NULL,
                  type TEXT NOT NULL,
                  text TEXT,
                  filename TEXT,
                  url TEXT,
                  timestamp TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (session_id TEXT PRIMARY KEY,
                  username TEXT NOT NULL,
                  last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                  is_online INTEGER DEFAULT 0)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)')
    conn.commit()
    conn.close()

def clean_old_messages():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        c.execute('SELECT url FROM messages WHERE timestamp < ? AND url IS NOT NULL', (cutoff_date,))
        for (url,) in c.fetchall():
            if url:
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], url.replace('/uploads/', ''))
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except:
                        pass
        c.execute('DELETE FROM messages WHERE timestamp < ?', (cutoff_date,))
        conn.commit()
        conn.close()
    except:
        pass

def add_message(sender, msg_type, text="", filename="", url=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO messages (sender, type, text, filename, url, timestamp) VALUES (?,?,?,?,?,?)',
              (sender, msg_type, text, filename, url, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

def get_all_messages():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT sender, type, text, filename, url FROM messages ORDER BY id ASC')
    messages = [{"sender": r[0], "type": r[1], "text": r[2] or "", "filename": r[3] or "", "url": r[4] or ""} for r in c.fetchall()]
    conn.close()
    return messages

def update_user_online(session_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (session_id, username, last_seen, is_online) VALUES (?,?,?,1)',
              (session_id, username, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

def set_user_offline(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET is_online=0, last_seen=? WHERE session_id=?',
              (datetime.now(timezone.utc).isoformat(), session_id))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username, is_online FROM users ORDER BY is_online DESC, username ASC')
    users = [{"username": r[0], "is_online": bool(r[1])} for r in c.fetchall()]
    conn.close()
    return users

def get_username(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username FROM users WHERE session_id=?', (session_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None

def is_username_taken(username, exclude_session_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if exclude_session_id:
        c.execute('SELECT COUNT(*) FROM users WHERE LOWER(username)=LOWER(?) AND session_id!=?', (username, exclude_session_id))
    else:
        c.execute('SELECT COUNT(*) FROM users WHERE LOWER(username)=LOWER(?)', (username,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

def get_allowed_name(requested_name, session_id):
    if not requested_name or not requested_name.strip():
        requested_name = "User"
    base_name = requested_name.strip()
    name = base_name
    
    # Check if THIS session already has this name
    current_name = get_username(session_id)
    if current_name and current_name.lower() == name.lower():
        return current_name  # Return existing name if it's the same session
    
    if is_username_taken(name, session_id):
        counter = 1
        while is_username_taken(f"{base_name}_{counter}", session_id):
            counter += 1
        name = f"{base_name}_{counter}"
    return name

init_db()

# При запуске сервера устанавливаем всех пользователей оффлайн
conn = sqlite3.connect(DB_PATH)
conn.execute('UPDATE users SET is_online=0')
conn.commit()
conn.close()

clean_old_messages()

if len(get_all_messages()) == 0:
    add_message("System", "text", "Welcome to YuuY Chat!")

@app.route('/')
def index():
    return render_template_string(HTML_CODE)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/join_chat', methods=['POST'])
def join_chat():
    data = request.json or {}
    session_id = data.get('session_id')
    requested_name = data.get('username', '').strip()
    
    # Try to get saved name for this session
    saved_name = get_username(session_id)
    if saved_name and (not requested_name or requested_name == "User"):
        requested_name = saved_name
    
    old_name = get_username(session_id)
    final_name = get_allowed_name(requested_name, session_id)
    update_user_online(session_id, final_name)
    
    if old_name is None:
        add_message("System", "text", f"{final_name} joined the chat.")
    elif old_name != final_name:
        add_message("System", "text", f"{old_name} → {final_name}")
    
    return jsonify({"user": final_name, "messages": get_all_messages(), "active_users": get_all_users()})

@app.route('/change_nickname', methods=['POST'])
def change_nickname():
    data = request.json or {}
    session_id = data.get('session_id')
    new_name = data.get('username', '').strip()
    current_name = get_username(session_id)
    
    if not current_name:
        return jsonify({"error": "User not found"}), 400
    if not new_name:
        return jsonify({"error": "Nickname is empty"}), 400
    if is_username_taken(new_name, session_id):
        return jsonify({"error": "Nickname taken!"}), 400
    
    update_user_online(session_id, new_name)
    add_message("System", "text", f"{current_name} → {new_name}")
    return jsonify({"success": True, "username": new_name})

@app.route('/get_messages', methods=['GET'])
def get_messages():
    return jsonify({"messages": get_all_messages(), "users": get_all_users()})

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.json or {}
    session_id = data.get('session_id')
    text = data.get('text')
    user = get_username(session_id)
    if user and text:
        add_message(user, "text", text)
        return jsonify({"success": True})
    return jsonify({"success": False}), 400

@app.route('/upload_file', methods=['POST'])
def upload_file():
    session_id = request.form.get('session_id')
    user = get_username(session_id)
    if not user:
        return jsonify({"error": "Session error"}), 400
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_filename = f"{timestamp}_{session_id[:8]}_{filename}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(file_path)
    
    ext = filename.split('.')[-1].lower()
    file_type = "file"
    if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
        file_type = "image"
    elif ext in ['txt', 'log', 'py', 'json', 'md']:
        file_type = "text_file"
    
    preview = ""
    if file_type == "text_file":
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                preview = f.read(1000)
        except:
            preview = "Preview error."
    
    add_message(user, file_type, preview, filename, f"/uploads/{unique_filename}")
    return jsonify({"success": True})

@app.route('/logout', methods=['POST'])
def logout():
    data = request.json or {}
    session_id = data.get('session_id')
    if session_id:
        set_user_offline(session_id)
    return jsonify({"success": True})

SOUND_FILE = os.path.join(UPLOAD_FOLDER, 'notification.wav')
if not os.path.exists(SOUND_FILE):
    import struct, wave
    with wave.open(SOUND_FILE, 'w') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        samples = [int(32767 * (1 - i/6615) * (0.5 * __import__('math').sin(2*__import__('math').pi*800*i/44100))) for i in range(6615)]
        wav.writeframes(struct.pack('<' + 'h'*len(samples), *samples))

@app.route('/notification.wav')
def notification_sound():
    return send_from_directory(UPLOAD_FOLDER, 'notification.wav')

HTML_CODE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>YuuY Chat</title>
    <style>
        :root {
            --bg-primary: #0d0a1a;
            --bg-secondary: #1a1333;
            --bg-tertiary: #231b42;
            --accent: #a78bfa;
            --accent-light: #c4b5fd;
            --accent-dark: #7c3aed;
            --text-primary: #f5f3ff;
            --text-secondary: #a5a0c0;
            --border: #2d2452;
            --success: #6ee7b7;
            --danger: #fca5a5;
            --msg-you: #8b5cf6;
            --msg-other: #2d2452;
            --input-bg: #1a1333;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg-primary); 
            color: var(--text-primary); 
            height: 100vh; 
            height: 100dvh;
            overflow: hidden;
            -webkit-tap-highlight-color: transparent;
        }
        
        .app-container {
            display: flex;
            height: 100%;
            position: relative;
        }
        
        .chat-section {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
            background: var(--bg-primary);
        }
        
        .chat-header {
            padding: 14px 18px;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
            backdrop-filter: blur(10px);
        }
        .chat-header h1 {
            font-size: 1.15rem;
            background: linear-gradient(135deg, var(--accent), #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 700;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .online-count-badge {
            background: var(--bg-tertiary);
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            color: var(--accent-light);
            border: 1px solid var(--border);
            white-space: nowrap;
            flex-shrink: 0;
            margin-left: 8px;
        }
        .menu-btn {
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            color: var(--accent);
            font-size: 1.2rem;
            cursor: pointer;
            padding: 6px 10px;
            border-radius: 10px;
            flex-shrink: 0;
            transition: all 0.2s;
        }
        .menu-btn:hover { background: var(--accent); color: white; }
        
        .messages-container {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            -webkit-overflow-scrolling: touch;
            background: linear-gradient(180deg, var(--bg-primary) 0%, #0f0c24 100%);
        }
        .messages-container::-webkit-scrollbar { width: 4px; }
        .messages-container::-webkit-scrollbar-track { background: transparent; }
        .messages-container::-webkit-scrollbar-thumb { background: var(--border); border-radius: 10px; }
        
        .msg {
            max-width: 80%;
            padding: 10px 14px;
            border-radius: 18px;
            line-height: 1.45;
            font-size: 0.9rem;
            word-wrap: break-word;
            position: relative;
        }
        .msg.new-msg { animation: slideIn 0.35s cubic-bezier(0.16, 1, 0.3, 1); }
        @keyframes slideIn { from { opacity: 0; transform: translateY(12px) scale(0.95); } to { opacity: 1; transform: translateY(0) scale(1); } }
        
        .msg.system {
            background: var(--bg-secondary);
            color: var(--accent-light);
            align-self: center;
            font-size: 0.75rem;
            text-align: center;
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 6px 14px;
            max-width: 90%;
        }
        .msg.you {
            background: linear-gradient(135deg, var(--msg-you), #7c3aed);
            color: white;
            align-self: flex-end;
            border-bottom-right-radius: 6px;
            box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
        }
        .msg.other {
            background: var(--msg-other);
            color: var(--text-primary);
            align-self: flex-start;
            border-bottom-left-radius: 6px;
            border: 1px solid var(--border);
        }
        .msg-sender {
            font-size: 0.7rem;
            font-weight: 700;
            margin-bottom: 4px;
            opacity: 0.8;
            color: var(--accent-light);
        }
        .msg.you .msg-sender { color: rgba(255,255,255,0.8); }
        .chat-image {
            max-width: 100%;
            max-height: 220px;
            border-radius: 10px;
            margin-top: 8px;
        }
        .chat-text-preview {
            background: var(--bg-primary);
            color: var(--success);
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            padding: 10px;
            border-radius: 8px;
            font-size: 0.8rem;
            margin-top: 6px;
            max-height: 130px;
            overflow-y: auto;
            white-space: pre-wrap;
            border: 1px solid var(--border);
        }
        .file-link-btn {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: var(--bg-tertiary);
            color: var(--accent-light);
            padding: 6px 12px;
            border-radius: 8px;
            text-decoration: none;
            font-size: 0.8rem;
            margin-top: 6px;
            font-weight: 600;
            transition: all 0.2s;
            border: 1px solid var(--border);
        }
        .file-link-btn:hover { background: var(--accent); color: white; border-color: var(--accent); }
        .msg.you .file-link-btn { background: rgba(255,255,255,0.15); color: white; border-color: rgba(255,255,255,0.2); }
        .msg.you .file-link-btn:hover { background: rgba(255,255,255,0.25); }
        
        .input-bar {
            padding: 12px 14px;
            background: var(--bg-secondary);
            border-top: 1px solid var(--border);
            display: flex;
            gap: 8px;
            align-items: center;
            flex-shrink: 0;
        }
        .input-bar input[type="text"] {
            flex: 1;
            padding: 11px 16px;
            border-radius: 24px;
            border: 1px solid var(--border);
            background: var(--input-bg);
            color: var(--text-primary);
            font-size: 0.9rem;
            outline: none;
            min-width: 0;
            transition: all 0.2s;
        }
        .input-bar input[type="text"]:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.15);
        }
        .input-bar input[type="text"]::placeholder { color: #5a5570; }
        .send-btn {
            width: 42px;
            height: 42px;
            border: none;
            background: linear-gradient(135deg, var(--accent), var(--accent-dark));
            color: white;
            font-weight: bold;
            border-radius: 50%;
            cursor: pointer;
            font-size: 1.1rem;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
            box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
        }
        .send-btn:hover { transform: scale(1.05); box-shadow: 0 4px 15px rgba(139, 92, 246, 0.5); }
        .send-btn:active { transform: scale(0.95); }
        .file-btn {
            width: 42px;
            height: 42px;
            background: var(--bg-tertiary);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 1.1rem;
            flex-shrink: 0;
            transition: all 0.2s;
            border: 1px solid var(--border);
        }
        .file-btn:hover { background: var(--border); }
        .file-btn input { display: none; }
        
        .sidebar {
            position: fixed;
            top: 0;
            right: -320px;
            bottom: 0;
            width: 290px;
            max-width: 85vw;
            background: var(--bg-secondary);
            border-left: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            z-index: 60;
            transition: right 0.35s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: -4px 0 20px rgba(0,0,0,0.3);
        }
        .sidebar.open { right: 0; }
        .sidebar::-webkit-scrollbar { width: 4px; }
        .sidebar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 10px; }
        
        .nickname-section {
            padding: 18px 14px;
            border-bottom: 1px solid var(--border);
        }
        .nickname-section label {
            font-size: 0.7rem;
            color: var(--text-secondary);
            font-weight: 700;
            display: block;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
        }
        .nickname-row {
            display: flex;
            gap: 8px;
        }
        .nickname-row input {
            flex: 1;
            padding: 9px 12px;
            border-radius: 10px;
            border: 1px solid var(--border);
            background: var(--input-bg);
            color: var(--text-primary);
            font-size: 0.85rem;
            outline: none;
            min-width: 0;
            transition: all 0.2s;
        }
        .nickname-row input:focus { border-color: var(--accent); }
        .nickname-row button {
            padding: 9px 16px;
            border: none;
            background: linear-gradient(135deg, var(--accent), var(--accent-dark));
            color: white;
            font-weight: 700;
            border-radius: 10px;
            font-size: 0.85rem;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s;
        }
        .nickname-row button:hover { opacity: 0.9; transform: translateY(-1px); }
        
        .users-section {
            flex: 1;
            overflow-y: auto;
            padding: 14px;
        }
        .users-section h3 {
            color: var(--text-secondary);
            font-size: 0.7rem;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            font-weight: 700;
        }
        .user-item {
            padding: 9px 12px;
            margin-bottom: 4px;
            background: var(--bg-tertiary);
            border-radius: 10px;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 10px;
            transition: all 0.2s;
        }
        .user-item:hover { background: #2a2050; }
        .user-item.offline {
            opacity: 0.45;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
            box-shadow: 0 0 8px currentColor;
        }
        .status-dot.online { background: var(--success); box-shadow: 0 0 10px rgba(110, 231, 183, 0.5); }
        .status-dot.offline { background: #4a4560; box-shadow: none; }
        .user-name {
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .you-tag {
            color: var(--accent-light);
            font-size: 0.7rem;
            font-weight: 600;
            margin-left: 4px;
        }
        .sidebar-close {
            position: absolute;
            top: 12px;
            left: 12px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            width: 32px;
            height: 32px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 0.9rem;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2;
            transition: all 0.2s;
        }
        .sidebar-close:hover { background: var(--accent); color: white; border-color: var(--accent); }
        
        .overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(13, 10, 26, 0.8);
            backdrop-filter: blur(4px);
            z-index: 50;
        }
        .overlay.open { display: block; }
        
        .connecting-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: var(--bg-primary);
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            z-index: 100;
        }
        .connecting-overlay h2 {
            font-size: 2rem;
            background: linear-gradient(135deg, var(--accent), #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }
        .spinner {
            width: 40px; height: 40px;
            border: 3px solid var(--border);
            border-top: 3px solid var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-top: 20px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        @media (min-width: 768px) {
            .sidebar {
                position: static;
                width: 270px;
                border-left: none;
                border-right: 1px solid var(--border);
                flex-shrink: 0;
                box-shadow: none;
            }
            .sidebar-close { display: none; }
            .overlay { display: none !important; }
            .menu-btn { display: none; }
        }
    </style>
</head>
<body>
    <div class="connecting-overlay" id="connecting">
        <h2>YuuY</h2>
        <p style="color:var(--text-secondary)">Connecting...</p>
        <div class="spinner"></div>
    </div>
    
    <div class="app-container">
        <div class="chat-section">
            <div class="chat-header">
                <h1>✦ YuuY Chat</h1>
                <span class="online-count-badge" id="onlineCount">0 online</span>
                <button class="menu-btn" onclick="toggleSidebar()">👥</button>
            </div>
            <div class="messages-container" id="messagesArea"></div>
            <div class="input-bar">
                <label class="file-btn">
                    📎 <input type="file" id="fileSelector" onchange="uploadFile(this)" accept="*/*">
                </label>
                <input type="text" id="messageInput" placeholder="Write a message..." onkeypress="if(event.key==='Enter')sendMessage()" autocomplete="off">
                <button class="send-btn" onclick="sendMessage()">➤</button>
            </div>
        </div>
        
        <div class="sidebar" id="sidebar">
            <button class="sidebar-close" onclick="toggleSidebar()">✕</button>
            <div class="nickname-section">
                <label>Nickname</label>
                <div class="nickname-row">
                    <input type="text" id="usernameInput" value="User" autocomplete="off" placeholder="Your name">
                    <button onclick="updateNickname()">Save</button>
                </div>
            </div>
            <div class="users-section">
                <h3>Members</h3>
                <div id="usersList"></div>
            </div>
        </div>
    </div>
    
    <div class="overlay" id="overlay" onclick="toggleSidebar()"></div>

    <script>
        // Get or create session ID
        if(!localStorage.getItem('chat_sid')) {
            localStorage.setItem('chat_sid', 'u_' + Math.random().toString(36).substr(2, 9));
        }
        const sid = localStorage.getItem('chat_sid');
        
        // Get saved nickname
        let myName = localStorage.getItem('chat_name') || 'User';
        document.getElementById('usernameInput').value = myName;
        
        let lastMsgCount = 0;
        let unread = 0;
        let focused = true;
        let audio = null;
        let userScrolled = false;
        let scrollTimeout = null;
        
        function initAudio() {
            audio = new Audio('/notification.wav');
            audio.volume = 0.3;
        }
        
        window.addEventListener('focus', () => { focused = true; unread = 0; document.title = 'YuuY Chat'; });
        window.addEventListener('blur', () => { focused = false; });
        
        window.addEventListener('beforeunload', () => {
            fetch('/logout', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({session_id: sid}),
                keepalive: true
            });
        });
        
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                fetch('/logout', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({session_id: sid}),
                    keepalive: true
                });
            } else {
                fetch('/join_chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({session_id: sid, username: myName})
                });
            }
        });
        
        function playSound() {
            if(!audio) initAudio();
            if(audio) { audio.currentTime = 0; audio.play().catch(()=>{}); }
        }
        
        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('open');
            document.getElementById('overlay').classList.toggle('open');
        }
        
        function joinChat() {
            fetch('/join_chat', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({session_id:sid, username:myName})
            })
            .then(r=>r.json())
            .then(d=>{
                myName = d.user;
                document.getElementById('usernameInput').value = myName;
                localStorage.setItem('chat_name', myName);
                document.getElementById('connecting').style.display = 'none';
                updateUsers(d.active_users);
                renderMessages(d.messages, true);
                lastMsgCount = d.messages.length;
                document.getElementById('messageInput').focus();
                initAudio();
                // Scroll to bottom on initial load
                const area = document.getElementById('messagesArea');
                area.scrollTop = area.scrollHeight;
            })
            .catch(()=>{
                document.getElementById('connecting').innerHTML = '<h2>Error</h2><p style="color:var(--text-secondary)">Refresh page</p>';
            });
        }
        
        function updateNickname() {
            const name = document.getElementById('usernameInput').value.trim();
            if(!name) return alert('Empty nickname!');
            if(name === myName) return;
            
            fetch('/change_nickname', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({session_id:sid, username:name})
            })
            .then(r=>r.ok ? r.json() : r.json().then(d=>{throw new Error(d.error)}))
            .then(d=>{ 
                myName = d.username; 
                localStorage.setItem('chat_name', myName);
                document.getElementById('usernameInput').value = myName;
            })
            .catch(e=>{ alert(e.message); document.getElementById('usernameInput').value = myName; });
        }
        
        function updateUsers(users) {
            const online = users.filter(u=>u.is_online).length;
            document.getElementById('onlineCount').textContent = online + ' online';
            document.getElementById('usersList').innerHTML = users.map(u=>
                `<div class="user-item ${!u.is_online?'offline':''}">
                    <span class="status-dot ${u.is_online?'online':'offline'}"></span>
                    <span class="user-name">${esc(u.username)}</span>
                    ${u.username===myName?'<span class="you-tag">you</span>':''}
                </div>`
            ).join('');
        }
        
        function renderMessages(msgs, initial=false) {
            const area = document.getElementById('messagesArea');
            
            // Check if user manually scrolled up
            const atBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 80;
            
            // Track user scrolling
            if (!initial && !atBottom) {
                userScrolled = true;
                if (scrollTimeout) clearTimeout(scrollTimeout);
                scrollTimeout = setTimeout(() => { userScrolled = false; }, 3000);
            }
            
            const hasNew = msgs.length > lastMsgCount && lastMsgCount > 0;
            
            // Only update DOM if messages changed
            if (!hasNew && !initial) return;
            
            area.innerHTML = '';
            msgs.forEach((m, i) => {
                const div = document.createElement('div');
                const isNew = !initial && hasNew && i >= lastMsgCount;
                
                if(m.sender === 'System') {
                    div.className = 'msg system' + (isNew?' new-msg':'');
                    div.textContent = m.text;
                } else {
                    div.className = (m.sender===myName?'msg you':'msg other') + (isNew?' new-msg':'');
                    let h = `<div class="msg-sender">${esc(m.sender)}</div>`;
                    if(m.type==='text') h += `<div>${linkify(esc(m.text))}</div>`;
                    else if(m.type==='image') h += `<div>🖼️ <b>${esc(m.filename)}</b></div><a href="${m.url}" target="_blank"><img src="${m.url}" class="chat-image" loading="lazy"></a>`;
                    else if(m.type==='text_file') h += `<div>📄 <b>${esc(m.filename)}</b></div><div class="chat-text-preview">${esc(m.text)}</div><a href="${m.url}" class="file-link-btn" download>📥 Download</a>`;
                    else h += `<div>📦 <b>${esc(m.filename)}</b></div><a href="${m.url}" class="file-link-btn" download>📥 Download</a>`;
                    div.innerHTML = h;
                }
                area.appendChild(div);
            });
            
            if(hasNew) {
                const newMsgs = msgs.slice(lastMsgCount);
                const hasOthers = newMsgs.some(m=>m.sender!=='System' && m.sender!==myName);
                
                if (hasOthers) {
                    if(!focused) {
                        unread += newMsgs.filter(m=>m.sender!=='System' && m.sender!==myName).length;
                        document.title = '('+unread+') YuuY Chat';
                    }
                    playSound();
                }
            }
            
            lastMsgCount = msgs.length;
            
            // Only auto-scroll if user hasn't scrolled up manually
            if (!userScrolled && (atBottom || initial || (hasNew && !userScrolled))) {
                area.scrollTop = area.scrollHeight;
            }
        }
        
        // Listen for scroll events
        document.getElementById('messagesArea').addEventListener('scroll', function() {
            const area = this;
            const atBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 80;
            if (atBottom) {
                userScrolled = false;
            }
        });
        
        function linkify(t) {
            return t.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" style="color:inherit;text-decoration:underline">$1</a>');
        }
        
        function uploadFile(input) {
            if(!input.files.length) return;
            const f = input.files[0];
            if(f.size > 16*1024*1024) { alert('File too large! Max 16MB'); input.value=''; return; }
            const fd = new FormData();
            fd.append('file', f);
            fd.append('session_id', sid);
            input.value = '';
            fetch('/upload_file', {method:'POST', body:fd}).then(r=>r.json()).then(d=>{if(d.error)alert(d.error)});
        }
        
        function sendMessage() {
            const inp = document.getElementById('messageInput');
            const text = inp.value.trim();
            if(!text) return;
            fetch('/send_message', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({session_id:sid, text:text})
            }).then(r=>r.json()).then(d=>{if(d.success){inp.value='';inp.focus();}});
        }
        
        setInterval(()=>{
            fetch('/get_messages').then(r=>r.json()).then(d=>{
                renderMessages(d.messages);
                updateUsers(d.users);
            }).catch(()=>{});
        }, 1000);
        
        function esc(t) { const d=document.createElement('div'); d.textContent=t; return d.innerHTML; }
        
        joinChat();
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
