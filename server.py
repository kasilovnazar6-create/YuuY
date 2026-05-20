import os
from flask import Flask, render_template_string, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# In-memory room database
rooms_data = {}

def get_allowed_name(room, requested_name, session_id):
    existing_names = [name.lower() for sid, name in room["users"].items() if sid != session_id]
    if not requested_name or requested_name.strip() == "":
        requested_name = "User"
    base_name = requested_name.strip()
    name = base_name
    counter = 1
    while name.lower() in existing_names:
        name = f"{base_name}_{counter}"
        counter += 1
    return name

@app.route('/')
def index():
    return render_template_string(HTML_CODE)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/create_room', methods=['POST'])
def create_room():
    data = request.json or {}
    port = int(data.get('port', 0))
    if port < 1 or port > 9999:
        return jsonify({"error": "Port must be between 1 and 9999"}), 400
    if port in rooms_data:
        return jsonify({"success": True})
    rooms_data[port] = {
        "users": {},
        "messages": [{"sender": "System", "type": "text", "text": f"Room on port {port} created!"}]
    }
    return jsonify({"success": True})

@app.route('/join_room', methods=['POST'])
def join_room():
    data = request.json or {}
    port = int(data.get('port', 0))
    session_id = data.get('session_id')
    requested_name = data.get('username', '').strip()
    
    if port not in rooms_data:
        return jsonify({"error": f"Room {port} hasn't been created yet!"}), 404
        
    room = rooms_data[port]
    if session_id not in room["users"] and len(room["users"]) >= 2:
        return jsonify({"error": f"Room {port} already has 2 participants!"}), 403
        
    final_name = get_allowed_name(room, requested_name, session_id)
    if session_id not in room["users"]:
        room["users"][session_id] = final_name
        room["messages"].append({"sender": "System", "type": "text", "text": f"{final_name} joined the room."})
    elif room["users"][session_id] != final_name:
        old_name = room["users"][session_id]
        room["users"][session_id] = final_name
        room["messages"].append({"sender": "System", "type": "text", "text": f"{old_name} changed to {final_name}."})
        
    return jsonify({"user": final_name, "messages": room["messages"], "active_users": list(room["users"].values())})

@app.route('/change_nickname', methods=['POST'])
def change_nickname():
    data = request.json or {}
    port = int(data.get('port', 0))
    session_id = data.get('session_id')
    new_name = data.get('username', '').strip()
    
    if port not in rooms_data or session_id not in rooms_data[port]["users"]:
        return jsonify({"error": "Room not found"}), 400
    room = rooms_data[port]
    existing_names = [name.lower() for sid, name in room["users"].items() if sid != session_id]
    if new_name.lower() in existing_names:
        return jsonify({"error": "This nickname is already taken!"}), 400
    if not new_name:
        return jsonify({"error": "Nickname is empty"}), 400

    old_name = room["users"][session_id]
    room["users"][session_id] = new_name
    room["messages"].append({"sender": "System", "type": "text", "text": f"{old_name} changed their name to {new_name}"})
    return jsonify({"success": True, "username": new_name})

@app.route('/get_messages/<int:port>', methods=['GET'])
def get_messages(port):
    if port in rooms_data:
        return jsonify({"messages": rooms_data[port]["messages"], "users": list(rooms_data[port]["users"].values())})
    return jsonify({"messages": [], "users": []})

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.json or {}
    port = int(data.get('port', 0))
    session_id = data.get('session_id')
    text = data.get('text')
    if port in rooms_data and session_id in rooms_data[port]["users"] and text:
        user = rooms_data[port]['users'][session_id]
        rooms_data[port]['messages'].append({"sender": user, "type": "text", "text": text})
        return jsonify({"success": True})
    return jsonify({"success": False}), 400

@app.route('/upload_file', methods=['POST'])
def upload_file():
    port = int(request.form.get('port', 0))
    session_id = request.form.get('session_id')
    if port not in rooms_data or session_id not in rooms_data[port]["users"]:
        return jsonify({"error": "Session error"}), 400
    if 'file' not in request.files:
        return jsonify({"error": "File not found"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    if file:
        filename = secure_filename(file.filename)
        unique_filename = f"{port}_{session_id[:4]}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        user = rooms_data[port]['users'][session_id]
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
        rooms_data[port]['messages'].append({
            "sender": user, "type": file_type, "filename": filename, "url": f"/uploads/{unique_filename}", "text": preview_content
        })
        return jsonify({"success": True})

HTML_CODE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>YuuY - 2-User Chat</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; }
        body { display: flex; height: 100vh; background: #0f172a; color: #e2e8f0; overflow: hidden; }
        .sidebar { width: 320px; background: #1e293b; display: flex; flex-direction: column; border-right: 1px solid #334155; }
        .sidebar-header { padding: 20px; font-size: 1.1rem; font-weight: bold; background: #0f172a; text-align: center; color: #38bdf8; }
        .setup-profile { padding: 15px; background: #1e293b; border-bottom: 1px solid #334155; display: flex; flex-direction: column; gap: 8px; }
        .setup-profile label { font-size: 0.8rem; color: #94a3b8; font-weight: bold; }
        .profile-input-zone { display: flex; gap: 8px; }
        .setup-profile input { flex: 1; padding: 8px 12px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: white; outline: none; }
        .setup-profile button { padding: 8px 12px; border: none; background: #10b981; color: white; font-weight: bold; border-radius: 6px; cursor: pointer; }
        .port-search { padding: 15px; display: flex; flex-direction: column; gap: 8px; background: #0f172a; margin: 10px; border-radius: 8px; }
        .port-search-row { display: flex; gap: 8px; }
        .port-search input { flex: 1; padding: 10px; border-radius: 6px; border: 1px solid #475569; background: #1e293b; color: white; outline: none; }
        .port-search button { padding: 10px 15px; border: none; background: #38bdf8; color: #0f172a; font-weight: bold; border-radius: 6px; cursor: pointer; }
        .port-list { flex: 1; overflow-y: auto; padding: 10px; }
        .port-item { padding: 14px; margin-bottom: 8px; background: #334155; border-radius: 8px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
        .port-item.active { background: #38bdf8; color: #0f172a; font-weight: bold; }
        .empty-list-text { text-align: center; color: #64748b; margin-top: 20px; font-size: 0.9rem; }
        .chat-container { flex: 1; display: flex; flex-direction: column; background: #0f172a; position: relative; }
        .chat-header { padding: 20px; background: #1e293b; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
        .chat-header h2 { color: #38bdf8; font-size: 1.2rem; }
        .room-users-info { font-size: 0.85rem; color: #94a3b8; background: #0f172a; padding: 6px 12px; border-radius: 20px; border: 1px solid #334155; }
        .messages-area { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; }
        .msg { max-width: 65%; padding: 12px 16px; border-radius: 12px; line-height: 1.45; display: flex; flex-direction: column; }
        .msg.system { background: #1e293b; color: #38bdf8; align-self: center; font-size: 0.85rem; text-align: center; border: 1px solid #334155; border-radius: 20px; padding: 6px 16px; }
        .msg.you { background: #38bdf8; color: #0f172a; align-self: flex-end; border-bottom-right-radius: 2px; }
        .msg.other { background: #1e293b; color: #e2e8f0; align-self: flex-start; border-bottom-left-radius: 2px; border: 1px solid #334155; }
        .msg-sender { font-size: 0.75rem; font-weight: bold; margin-bottom: 6px; opacity: 0.8; }
        .chat-image { max-width: 100%; max-height: 250px; border-radius: 8px; margin-top: 5px; }
        .chat-text-preview { background: #0f172a; color: #10b981; font-family: monospace; padding: 10px; border-radius: 6px; font-size: 0.85rem; margin-top: 6px; max-height: 150px; overflow-y: auto; }
        .file-link-btn { display: inline-flex; background: #475569; color: white; padding: 8px 12px; border-radius: 6px; text-decoration: none; font-size: 0.85rem; margin-top: 5px; font-weight: bold; }
        .msg.you .file-link-btn { background: #0f172a; color: #38bdf8; }
        .input-area { padding: 20px; background: #1e293b; display: flex; gap: 12px; border-top: 1px solid #334155; align-items: center; }
        .input-area input[type="text"] { flex: 1; padding: 14px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: white; outline: none; }
        .input-area button.send-btn { padding: 14px 24px; border: none; background: #38bdf8; color: #0f172a; font-weight: bold; border-radius: 8px; cursor: pointer; }
        .file-upload-label { padding: 13px; background: #475569; color: white; border-radius: 8px; cursor: pointer; }
        .file-upload-label input { display: none; }
        .no-room-overlay { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: #0f172a; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #64748b; z-index: 10; }
        .no-room-overlay h3 { color: #38bdf8; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">YuuY - 2-User Chat</div>
        <div class="setup-profile">
            <label>Your nickname:</label>
            <div class="profile-input-zone">
                <input type="text" id="usernameInput" value="User">
                <button onclick="updateNickname()">OK</button>
            </div>
        </div>
        <div class="port-search">
            <label>Create room (Port):</label>
            <div class="port-search-row">
                <input type="number" id="portInput" min="1" max="9999" placeholder="1-9999">
                <button onclick="createNewPortRoom()">Create</button>
            </div>
        </div>
        <div class="port-list" id="portList">
            <div class="empty-list-text" id="emptyListText">No open ports.</div>
        </div>
    </div>

    <div class="chat-container">
        <div class="no-room-overlay" id="noRoomOverlay">
            <h3>No room selected</h3>
            <p>Create a new port in the left panel.</p>
        </div>
        <div class="chat-header">
            <h2 id="currentPortTitle">Port: not selected</h2>
            <div class="room-users-info" id="roomUsersInfo">Participants: 0 / 2</div>
        </div>
        <div class="messages-area" id="messagesArea"></div>
        <div class="input-area">
            <label class="file-upload-label">
                📎 <input type="file" id="fileSelector" onchange="uploadSelectedFile(this)">
            </label>
            <input type="text" id="messageInput" placeholder="Message..." onkeypress="handleKeyPress(event)">
            <button class="send-btn" onclick="sendMessage()">--></button>
        </div>
    </div>

    <script>
        // Initialize session
        if(!localStorage.getItem('chat_session_id')) {
            localStorage.setItem('chat_session_id', 'usr_' + Math.random().toString(36).substr(2, 9));
        }
        const sessionId = localStorage.getItem('chat_session_id');

        // Check saved nickname in localStorage
        if(localStorage.getItem('chat_saved_username')) {
            document.getElementById('usernameInput').value = localStorage.getItem('chat_saved_username');
        }
        
        let currentPort = null;
        let myRoleName = document.getElementById('usernameInput').value;
        let localCreatedPorts = new Set();

        function createNewPortRoom() {
            const input = document.getElementById('portInput');
            const port = parseInt(input.value);
            if(!port || port < 1 || port > 9999) return alert("Invalid port");
            
            fetch('/create_room', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ port: port })
            })
            .then(res => res.json())
            .then(data => {
                localCreatedPorts.add(port);
                renderPortList();
                input.value = '';
                const items = document.querySelectorAll('.port-item');
                const target = Array.from(items).find(el => el.dataset.port == port);
                if(target) switchPort(port, target);
            });
        }

        function renderPortList() {
            const list = document.getElementById('portList');
            document.getElementById('emptyListText').style.display = localCreatedPorts.size === 0 ? "block" : "none";
            list.querySelectorAll('.port-item').forEach(item => item.remove());

            Array.from(localCreatedPorts).sort((a,b)=>a-b).forEach(port => {
                const div = document.createElement('div');
                div.className = `port-item ${currentPort === port ? 'active' : ''}`;
                div.dataset.port = port;
                div.onclick = function() { switchPort(port, this); };
                div.innerHTML = `<span>🚪 Port ${port}</span>`;
                list.appendChild(div);
            });
        }

        function switchPort(port, element) {
            currentPort = port;
            document.getElementById('noRoomOverlay').style.display = "none";
            document.querySelectorAll('.port-item').forEach(el => el.classList.remove('active'));
            if(element) element.classList.add('active');

            fetch('/join_room', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ port: port, session_id: sessionId, username: document.getElementById('usernameInput').value })
            })
            .then(res => {
                if(!res.ok) {
                    res.json().then(data => { alert(data.error); document.getElementById('noRoomOverlay').style.display = "flex"; currentPort = null; renderPortList(); });
                    throw new Error("Full");
                }
                return res.json();
            })
            .then(data => {
                myRoleName = data.user;
                document.getElementById('usernameInput').value = myRoleName;
                localStorage.setItem('chat_saved_username', myRoleName); // Save name on join
                document.getElementById('currentPortTitle').innerText = `Port: ${port}`;
                updateUsersHeaderInfo(data.active_users);
                renderMessages(data.messages);
            }).catch(e=>{});
        }

        function updateNickname() {
            const newName = document.getElementById('usernameInput').value.trim();
            if(!newName) return alert("Nickname is empty!");
            
            // Save locally anyway
            localStorage.setItem('chat_saved_username', newName);

            if(!currentPort) {
                alert("Nickname saved for future rooms!");
                return;
            }

            fetch('/change_nickname', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ port: currentPort, session_id: sessionId, username: newName })
            })
            .then(res => {
                if(!res.ok) { res.json().then(data => alert(data.error)); return; }
                return res.json();
            })
            .then(data => { 
                if(data) { 
                    myRoleName = data.username; 
                    localStorage.setItem('chat_saved_username', myRoleName);
                    alert("Nickname changed!"); 
                } 
            });
        }

        function updateUsersHeaderInfo(usersList) {
            document.getElementById('roomUsersInfo').innerText = `Participants (${usersList.length}/2): ${usersList.join(', ')}`;
        }

        function renderMessages(messages) {
            const area = document.getElementById('messagesArea');
            area.innerHTML = '';
            messages.forEach(msg => {
                const div = document.createElement('div');
                if(msg.sender === 'System') {
                    div.className = 'msg system';
                    div.innerText = msg.text;
                    area.appendChild(div);
                    return;
                }
                div.className = msg.sender === myRoleName ? 'msg you' : 'msg other';
                let html = `<div class="msg-sender">${msg.sender}</div>`;
                if(msg.type === 'text') html += `<div>${msg.text}</div>`;
                else if(msg.type === 'image') html += `<div>🖼️ Image: <b>${msg.filename}</b></div><a href="${msg.url}" target="_blank"><img src="${msg.url}" class="chat-image"></a>`;
                else if(msg.type === 'text_file') html += `<div>📄 Text: <b>${msg.filename}</b></div><div class="chat-text-preview">${escapeHtml(msg.text)}</div><a href="${msg.url}" class="file-link-btn" download>📥 Download</a>`;
                else html += `<div>📦 File: <b>${msg.filename}</b></div><a href="${msg.url}" class="file-link-btn" download>📥 Download</a>`;
                div.innerHTML = html;
                area.appendChild(div);
            });
            area.scrollTop = area.scrollHeight;
        }

        function uploadSelectedFile(input) {
            if(!currentPort || input.files.length === 0) return;
            const formData = new FormData();
            formData.append('file', input.files[0]); // FIXED: send specific file, not the list
            formData.append('port', currentPort);
            formData.append('session_id', sessionId);
            input.value = '';

            fetch('/upload_file', { method: 'POST', body: formData })
            .then(res => res.json()).then(data => { if(data.error) alert(data.error); });
        }

        function sendMessage() {
            const input = document.getElementById('messageInput');
            const text = input.value.trim();
            if(!text || !currentPort) return;
            fetch('/send_message', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ port: currentPort, session_id: sessionId, text: text })
            }).then(res => res.json()).then(data => { if(data.success) input.value = ''; });
        }

        setInterval(() => {
            if(currentPort) {
                fetch(`/get_messages/${currentPort}`).then(res => res.json())
                .then(data => { renderMessages(data.messages); updateUsersHeaderInfo(data.users); }).catch(e=>{});
            }
        }, 1000);

        function handleKeyPress(e) { if(e.key === 'Enter') sendMessage(); }
        function escapeHtml(text) { return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)