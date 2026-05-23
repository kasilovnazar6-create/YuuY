import os
import sqlite3
import json
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template_string, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Database setup
DB_PATH = 'chat_database.db'

# Delete old database to fix schema issues
if os.path.exists(DB_PATH):
    try:
        os.remove(DB_PATH)
        print("Old database removed. Starting fresh.")
    except:
        pass

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
    
    c.execute('''CREATE INDEX IF NOT EXISTS idx_timestamp 
                 ON messages(timestamp)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_username 
                 ON users(username)''')
    
    conn.commit()
    conn.close()

def clean_old_messages():
    """Remove messages older than 30 days"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        
        c.execute('SELECT url FROM messages WHERE timestamp < ? AND url IS NOT NULL', (cutoff_date,))
        old_files = c.fetchall()
        
        for (url,) in old_files:
            if url:
                filename = url.replace('/uploads/', '')
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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
    timestamp = datetime.now(timezone.utc).isoformat()
    c.execute('''INSERT INTO messages (sender, type, text, filename, url, timestamp)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (sender, msg_type, text, filename, url, timestamp))
    conn.commit()
    conn.close()

def get_all_messages():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT sender, type, text, filename, url 
                 FROM messages 
                 ORDER BY id ASC''')
    messages = []
    for row in c.fetchall():
        msg = {
            "sender": row[0],
            "type": row[1],
            "text": row[2] if row[2] else "",
            "filename": row[3] if row[3] else "",
            "url": row[4] if row[4] else ""
        }
        messages.append(msg)
    conn.close()
    return messages

def update_user(session_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    last_seen = datetime.now(timezone.utc).isoformat()
    c.execute('''INSERT OR REPLACE INTO users (session_id, username, last_seen, is_online)
                 VALUES (?, ?, ?, 1)''', (session_id, username, last_seen))
    conn.commit()
    conn.close()

def set_user_offline(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    last_seen = datetime.now(timezone.utc).isoformat()
    c.execute('UPDATE users SET is_online = 0, last_seen = ? WHERE session_id = ?', 
              (last_seen, session_id))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username, is_online FROM users ORDER BY is_online DESC, username ASC')
    users = [{"username": row[0], "is_online": bool(row[1])} for row in c.fetchall()]
    conn.close()
    return users

def get_username(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username FROM users WHERE session_id = ?', (session_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def is_username_taken(username, exclude_session_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if exclude_session_id:
        c.execute('SELECT COUNT(*) FROM users WHERE LOWER(username) = LOWER(?) AND session_id != ?', 
                 (username, exclude_session_id))
    else:
        c.execute('SELECT COUNT(*) FROM users WHERE LOWER(username) = LOWER(?)', (username,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

def get_allowed_name(requested_name, session_id):
    if not requested_name or requested_name.strip() == "":
        requested_name = "User"
    base_name = requested_name.strip()
    name = base_name
    
    if is_username_taken(name, session_id):
        counter = 1
        while is_username_taken(f"{base_name}_{counter}", session_id):
            counter += 1
        name = f"{base_name}_{counter}"
    
    return name

# Initialize database
init_db()
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute('UPDATE users SET is_online = 0')
conn.commit()
conn.close()
clean_old_messages()

if len(get_all_messages()) == 0:
    add_message("System", "text", "Welcome to YuuY Chat! Messages are saved for 30 days.")

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
    
    old_name = get_username(session_id)
    final_name = get_allowed_name(requested_name, session_id)
    update_user(session_id, final_name)
    
    if old_name is None:
        add_message("System", "text", f"{final_name} joined the chat.")
    elif old_name != final_name:
        add_message("System", "text", f"{old_name} changed their name to {final_name}.")
    else:
        add_message("System", "text", f"{final_name} is back online.")
    
    messages = get_all_messages()
    users = get_all_users()
    
    return jsonify({"user": final_name, "messages": messages, "active_users": users})

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
        return jsonify({"error": "This nickname is already taken!"}), 400
    
    update_user(session_id, new_name)
    add_message("System", "text", f"{current_name} changed their name to {new_name}")
    
    return jsonify({"success": True, "username": new_name})

@app.route('/get_messages', methods=['GET'])
def get_messages():
    messages = get_all_messages()
    users = get_all_users()
    return jsonify({"messages": messages, "users": users})

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.json or {}
    session_id = data.get('session_id')
    text = data.get('text')
    
    user = get_username(session_id)
    if user and text:
        add_message(user, "text", text)
        return jsonify({"success": True, "sender": user})
    return jsonify({"success": False}), 400

@app.route('/upload_file', methods=['POST'])
def upload_file():
    session_id = request.form.get('session_id')
    user = get_username(session_id)
    
    if not user:
        return jsonify({"error": "Session error"}), 400
    if 'file' not in request.files:
        return jsonify({"error": "File not found"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if file:
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
        
        preview_content = ""
        if file_type == "text_file":
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    preview_content = f.read(1000)
            except Exception:
                preview_content = "Preview read error."
        
        add_message(user, file_type, preview_content, filename, f"/uploads/{unique_filename}")
        return jsonify({"success": True})

@app.route('/logout', methods=['POST'])
def logout():
    data = request.json or {}
    session_id = data.get('session_id')
    if session_id:
        username = get_username(session_id)
        if username:
            set_user_offline(session_id)
            add_message("System", "text", f"{username} went offline.")
    return jsonify({"success": True})

# Create notification sound file
SOUND_FILE = os.path.join(UPLOAD_FOLDER, 'notification.wav')
if not os.path.exists(SOUND_FILE):
    # Generate a simple WAV file for notification
    import struct
    import wave
    
    sample_rate = 44100
    duration = 0.15
    frequency = 800
    
    with wave.open(SOUND_FILE, 'w') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        
        samples = []
        for i in range(int(sample_rate * duration)):
            t = i / sample_rate
            # Fade out
            amplitude = 32767 * (1 - i / (sample_rate * duration))
            sample = int(amplitude * (0.5 * __import__('math').sin(2 * __import__('math').pi * frequency * t)))
            samples.append(sample)
        
        wav.writeframes(struct.pack('<' + 'h' * len(samples), *samples))

@app.route('/notification.wav')
def notification_sound():
    return send_from_directory(UPLOAD_FOLDER, 'notification.wav')

HTML_CODE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>YuuY - Global Chat</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; }
        body { display: flex; height: 100vh; background: #0f172a; color: #e2e8f0; overflow: hidden; }
        .sidebar { width: 280px; background: #1e293b; display: flex; flex-direction: column; border-right: 1px solid #334155; }
        .sidebar-header { padding: 20px; font-size: 1.3rem; font-weight: bold; background: #0f172a; text-align: center; color: #38bdf8; }
        .setup-profile { padding: 15px; background: #1e293b; border-bottom: 1px solid #334155; display: flex; flex-direction: column; gap: 8px; }
        .setup-profile label { font-size: 0.8rem; color: #94a3b8; font-weight: bold; }
        .profile-input-zone { display: flex; gap: 8px; }
        .setup-profile input { flex: 1; padding: 8px 12px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: white; outline: none; }
        .setup-profile button { padding: 8px 12px; border: none; background: #10b981; color: white; font-weight: bold; border-radius: 6px; cursor: pointer; }
        .online-users { flex: 1; overflow-y: auto; padding: 15px; }
        .online-users h3 { color: #94a3b8; font-size: 0.85rem; margin-bottom: 10px; }
        .user-item { padding: 8px 12px; margin-bottom: 4px; background: #334155; border-radius: 6px; font-size: 0.9rem; display: flex; align-items: center; gap: 8px; }
        .user-item .online-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .user-item .online-dot.online { background: #10b981; }
        .user-item .online-dot.offline { background: #64748b; }
        .user-item.offline-user { opacity: 0.6; }
        .info-box { padding: 10px; margin: 10px; background: #0f172a; border-radius: 8px; font-size: 0.8rem; color: #64748b; text-align: center; }
        .chat-container { flex: 1; display: flex; flex-direction: column; background: #0f172a; }
        .chat-header { padding: 20px; background: #1e293b; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
        .chat-header h2 { color: #38bdf8; font-size: 1.2rem; }
        .online-count { font-size: 0.85rem; color: #94a3b8; background: #0f172a; padding: 6px 12px; border-radius: 20px; border: 1px solid #334155; }
        .messages-area { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; }
        .msg { max-width: 65%; padding: 12px 16px; border-radius: 12px; line-height: 1.45; display: flex; flex-direction: column; }
        .msg.new-message { animation: fadeIn 0.3s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .msg.system { background: #1e293b; color: #38bdf8; align-self: center; font-size: 0.85rem; text-align: center; border: 1px solid #334155; border-radius: 20px; padding: 6px 16px; max-width: 80%; }
        .msg.you { background: #38bdf8; color: #0f172a; align-self: flex-end; border-bottom-right-radius: 2px; }
        .msg.other { background: #1e293b; color: #e2e8f0; align-self: flex-start; border-bottom-left-radius: 2px; border: 1px solid #334155; }
        .msg-sender { font-size: 0.75rem; font-weight: bold; margin-bottom: 6px; opacity: 0.8; }
        .chat-image { max-width: 100%; max-height: 250px; border-radius: 8px; margin-top: 5px; }
        .chat-text-preview { background: #0f172a; color: #10b981; font-family: monospace; padding: 10px; border-radius: 6px; font-size: 0.85rem; margin-top: 6px; max-height: 150px; overflow-y: auto; white-space: pre-wrap; }
        .file-link-btn { display: inline-flex; background: #475569; color: white; padding: 8px 12px; border-radius: 6px; text-decoration: none; font-size: 0.85rem; margin-top: 5px; font-weight: bold; align-items: center; gap: 4px; }
        .msg.you .file-link-btn { background: #0f172a; color: #38bdf8; }
        .input-area { padding: 20px; background: #1e293b; display: flex; gap: 12px; border-top: 1px solid #334155; align-items: center; }
        .input-area input[type="text"] { flex: 1; padding: 14px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: white; outline: none; }
        .input-area button.send-btn { padding: 14px 24px; border: none; background: #38bdf8; color: #0f172a; font-weight: bold; border-radius: 8px; cursor: pointer; }
        .file-upload-label { padding: 13px; background: #475569; color: white; border-radius: 8px; cursor: pointer; transition: background 0.2s; }
        .file-upload-label:hover { background: #5a6a82; }
        .file-upload-label input { display: none; }
        .connecting-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: #0f172a; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #64748b; z-index: 100; }
        .connecting-overlay h3 { color: #38bdf8; margin-bottom: 10px; font-size: 2rem; }
        .connecting-overlay .spinner { width: 40px; height: 40px; border: 3px solid #334155; border-top: 3px solid #38bdf8; border-radius: 50%; animation: spin 1s linear infinite; margin-top: 20px; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="connecting-overlay" id="connectingOverlay">
        <h3>YuuY</h3>
        <p>Connecting to chat...</p>
        <div class="spinner"></div>
    </div>
    
    <div class="sidebar">
        <div class="sidebar-header">💬 YuuY Chat</div>
        <div class="setup-profile">
            <label>Your nickname:</label>
            <div class="profile-input-zone">
                <input type="text" id="usernameInput" value="User" autocomplete="off">
                <button onclick="updateNickname()">OK</button>
            </div>
        </div>
        <div class="online-users">
            <h3>👥 Users</h3>
            <div id="onlineUsersList"></div>
        </div>
        <div class="info-box">
            💾 Messages persist for 30 days
        </div>
    </div>

    <div class="chat-container">
        <div class="chat-header">
            <h2>🌐 Global Chat</h2>
            <div class="online-count" id="onlineCount">Users online: 0</div>
        </div>
        <div class="messages-area" id="messagesArea"></div>
        <div class="input-area">
            <label class="file-upload-label">
                📎 <input type="file" id="fileSelector" onchange="uploadSelectedFile(this)">
            </label>
            <input type="text" id="messageInput" placeholder="Type a message..." onkeypress="handleKeyPress(event)" autocomplete="off">
            <button class="send-btn" onclick="sendMessage()">Send</button>
        </div>
    </div>

    <script>
        if(!localStorage.getItem('chat_session_id')) {
            localStorage.setItem('chat_session_id', 'usr_' + Math.random().toString(36).substr(2, 9));
        }
        const sessionId = localStorage.getItem('chat_session_id');
        
        let myRoleName = localStorage.getItem('chat_saved_username') || 'User';
        document.getElementById('usernameInput').value = myRoleName;
        
        let lastMessageCount = 0;
        let unreadCount = 0;
        let windowFocused = true;
        let notificationAudio = null;
        
        // Load notification sound
        function initAudio() {
            notificationAudio = new Audio('/notification.wav');
            notificationAudio.volume = 0.3;
            notificationAudio.preload = 'auto';
        }
        
        window.addEventListener('focus', () => {
            windowFocused = true;
            unreadCount = 0;
            document.title = 'YuuY - Global Chat';
        });
        
        window.addEventListener('blur', () => {
            windowFocused = false;
        });
        
        window.addEventListener('beforeunload', () => {
            try {
                navigator.sendBeacon('/logout', JSON.stringify({ session_id: sessionId }));
            } catch(e) {}
        });
        
        function playNotificationSound() {
            if (!notificationAudio) {
                initAudio();
            }
            if (notificationAudio) {
                notificationAudio.currentTime = 0;
                notificationAudio.play().catch(() => {});
            }
        }
        
        function joinChat() {
            fetch('/join_chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ session_id: sessionId, username: myRoleName })
            })
            .then(res => res.json())
            .then(data => {
                myRoleName = data.user;
                document.getElementById('usernameInput').value = myRoleName;
                localStorage.setItem('chat_saved_username', myRoleName);
                document.getElementById('connectingOverlay').style.display = 'none';
                updateOnlineUsers(data.active_users);
                renderMessages(data.messages, true);
                lastMessageCount = data.messages.length;
                document.getElementById('messageInput').focus();
                initAudio();
            })
            .catch(err => {
                console.error('Failed to join chat:', err);
                document.getElementById('connectingOverlay').innerHTML = '<h3>Connection Error</h3><p>Please refresh the page</p>';
            });
        }

        function updateNickname() {
            const newName = document.getElementById('usernameInput').value.trim();
            if(!newName) return alert("Nickname is empty!");
            if(newName === myRoleName) return;
            
            fetch('/change_nickname', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ session_id: sessionId, username: newName })
            })
            .then(res => {
                if(!res.ok) { 
                    res.json().then(data => {
                        alert(data.error);
                        document.getElementById('usernameInput').value = myRoleName;
                    }); 
                    return; 
                }
                return res.json();
            })
            .then(data => { 
                if(data && data.success) { 
                    myRoleName = data.username; 
                    localStorage.setItem('chat_saved_username', myRoleName);
                } 
            });
        }

        function updateOnlineUsers(usersList) {
            const onlineUsers = usersList.filter(u => u.is_online).length;
            document.getElementById('onlineCount').innerText = 'Users online: ' + onlineUsers;
            const list = document.getElementById('onlineUsersList');
            list.innerHTML = usersList.map(user => 
                `<div class="user-item ${!user.is_online ? 'offline-user' : ''}">
                    <span class="online-dot ${user.is_online ? 'online' : 'offline'}"></span>
                    ${escapeHtml(user.username)}${user.username === myRoleName ? ' (you)' : ''}
                    ${!user.is_online ? ' <span style="font-size:0.7rem;color:#64748b">(offline)</span>' : ''}
                </div>`
            ).join('');
        }

        function renderMessages(messages, isInitialLoad = false) {
            const area = document.getElementById('messagesArea');
            const wasScrolledToBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 50;
            
            // Check for new messages
            const hasNewMessages = messages.length > lastMessageCount && lastMessageCount > 0;
            const newMessageIds = hasNewMessages ? messages.slice(lastMessageCount) : [];
            
            area.innerHTML = '';
            messages.forEach((msg, index) => {
                const div = document.createElement('div');
                const isNew = !isInitialLoad && hasNewMessages && index >= lastMessageCount;
                
                if(msg.sender === 'System') {
                    div.className = 'msg system' + (isNew ? ' new-message' : '');
                    div.innerText = msg.text;
                    area.appendChild(div);
                    return;
                }
                div.className = (msg.sender === myRoleName ? 'msg you' : 'msg other') + (isNew ? ' new-message' : '');
                let html = `<div class="msg-sender">${escapeHtml(msg.sender)}</div>`;
                if(msg.type === 'text') {
                    html += `<div>${formatMessage(escapeHtml(msg.text))}</div>`;
                } else if(msg.type === 'image') {
                    html += `<div>🖼️ Image: <b>${escapeHtml(msg.filename)}</b></div><a href="${msg.url}" target="_blank"><img src="${msg.url}" class="chat-image" loading="lazy"></a>`;
                } else if(msg.type === 'text_file') {
                    html += `<div>📄 Text file: <b>${escapeHtml(msg.filename)}</b></div><div class="chat-text-preview">${escapeHtml(msg.text)}</div><a href="${msg.url}" class="file-link-btn" download>📥 Download</a>`;
                } else {
                    html += `<div>📦 File: <b>${escapeHtml(msg.filename)}</b></div><a href="${msg.url}" class="file-link-btn" download>📥 Download</a>`;
                }
                div.innerHTML = html;
                area.appendChild(div);
            });
            
            // Handle new messages
            if (hasNewMessages) {
                const hasNewMessageFromOthers = newMessageIds.some(msg => msg.sender !== 'System' && msg.sender !== myRoleName);
                
                if (hasNewMessageFromOthers) {
                    if (!windowFocused) {
                        unreadCount += newMessageIds.filter(msg => msg.sender !== 'System' && msg.sender !== myRoleName).length;
                        document.title = '(' + unreadCount + ') YuuY - Global Chat';
                    }
                    playNotificationSound();
                }
            }
            
            lastMessageCount = messages.length;
            
            // Scroll to bottom
            if (wasScrolledToBottom || hasNewMessages) {
                area.scrollTop = area.scrollHeight;
            }
        }
        
        function formatMessage(text) {
            const urlRegex = /(https?:\/\/[^\s<]+)/g;
            return text.replace(urlRegex, '<a href="$1" target="_blank" style="color: inherit; text-decoration: underline;">$1</a>');
        }

        function uploadSelectedFile(input) {
            if(input.files.length === 0) return;
            const file = input.files[0];
            if(file.size > 16 * 1024 * 1024) {
                alert("File is too large! Maximum size is 16 MB.");
                input.value = '';
                return;
            }
            
            const formData = new FormData();
            formData.append('file', file);
            formData.append('session_id', sessionId);
            input.value = '';

            fetch('/upload_file', { method: 'POST', body: formData })
            .then(res => res.json())
            .then(data => { if(data.error) alert(data.error); });
        }

        function sendMessage() {
            const input = document.getElementById('messageInput');
            const text = input.value.trim();
            if(!text) return;
            
            fetch('/send_message', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ session_id: sessionId, text: text })
            }).then(res => res.json())
            .then(data => { 
                if(data.success) {
                    input.value = '';
                    input.focus();
                }
            });
        }

        setInterval(() => {
            fetch('/get_messages').then(res => res.json())
            .then(data => { 
                renderMessages(data.messages); 
                updateOnlineUsers(data.users); 
            }).catch(e => {});
        }, 1000);

        function handleKeyPress(e) { 
            if(e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage(); 
            }
        }
        
        function escapeHtml(text) { 
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        joinChat();
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
