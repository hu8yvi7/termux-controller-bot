# ================= ENHANCED TELEGRAM TERMUX CONTROLLER =================

import os
import pty
import threading
import uuid
import select
import json
import time
import signal
from datetime import datetime
from flask import Flask, request, render_template_string
import telebot
from telebot import types

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAIN_ADMIN_ID = int(os.environ.get("MAIN_ADMIN_ID")) # Main admin who can add/remove other admins
BASE_DIR = os.getcwd()
PORT = int(os.environ.get("PORT", 9090))
DATA_FILE = "bot_data.json"

# Initialize
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Data storage
edit_sessions = {}
processes = {}        # chat_id -> (pid, fd, start_time, cmd)
input_wait = {}       # chat_id -> fd
admins = set()        # Set of admin IDs
active_sessions = {}  # chat_id -> last_activity

# Load saved data
def load_data():
    global admins
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                admins = set(data.get('admins', []))
                admins.add(MAIN_ADMIN_ID)  # Ensure main admin is always in list
    except:
        admins = {MAIN_ADMIN_ID}

def save_data():
    try:
        data = {'admins': list(admins)}
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f)
    except:
        pass

load_data()

# ================= ENHANCED PTY RUNNER =================

def run_cmd(cmd, chat_id):
    def task():
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(BASE_DIR)
            os.execvp("bash", ["bash", "-c", cmd])
        else:
            start_time = datetime.now().strftime("%H:%M:%S")
            processes[chat_id] = (pid, fd, start_time, cmd)
            active_sessions[chat_id] = time.time()
            
            while True:
                r, _, _ = select.select([fd], [], [], 0.1)
                if fd in r:
                    try:
                        out = os.read(fd, 1024).decode(errors="ignore")
                    except OSError:
                        break
                    
                    if out:
                        # Truncate long output
                        display_out = out if len(out) < 2000 else out[:2000] + "\n... [OUTPUT TRUNCATED]"
                        bot.send_message(chat_id, f"```\n{display_out}\n```", parse_mode="Markdown")
                    
                    # Check if waiting for input
                    if out.strip().endswith(":"):
                        input_wait[chat_id] = fd
                
                # Check if process is still alive
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
                    
                time.sleep(0.1)
            
            # Cleanup after process ends
            if chat_id in processes:
                del processes[chat_id]
    
    threading.Thread(target=task, daemon=True).start()

# ================= ADMIN MANAGEMENT =================

def is_admin(chat_id):
    return str(chat_id) == str(MAIN_ADMIN_ID) or chat_id in admins

def admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Status", callback_data="status"),
        types.InlineKeyboardButton("🛑 Stop All", callback_data="stop_all"),
        types.InlineKeyboardButton("👥 Admin List", callback_data="admin_list"),
        types.InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
        types.InlineKeyboardButton("➖ Remove Admin", callback_data="remove_admin"),
        types.InlineKeyboardButton("📁 List Files", callback_data="list_files"),
        types.InlineKeyboardButton("🗑️ Clean Logs", callback_data="clean_logs")
    )
    return markup

def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        "📁 ls", "📂 pwd",
        "💿 df -h", "📊 top",
        "📝 nano", "🛑 stop",
        "📜 ps aux", "🗑️ clear",
        "🔄 ping 8.8.8.8", "🌐 ifconfig"
    )
    return markup

# ================= TELEGRAM HANDLERS =================

@bot.message_handler(commands=["start"])
def start(m):
    cid = m.chat.id
    
    if not is_admin(cid):
        bot.send_message(cid, "❌ You are not authorized to use this bot.")
        return
    
    welcome_msg = """
━━━━━━━━━━━━━━━━━━━━━━
        𝗧𝗘𝗥𝗠𝗨𝗫  𝗕𝗢𝗧
━━━━━━━━━━━━━━━━━━━━━━

📌 𝗙𝗲𝗮𝘁𝘂𝗿𝗲𝘀:
• 🖥️ 𝗘𝘅𝗲𝗰𝘂𝘁𝗲 𝘀𝗵𝗲𝗹𝗹 𝗰𝗼𝗺𝗺𝗮𝗻𝗱𝘀
• ✏️ 𝗡𝗮𝗻𝗼 𝗲𝗱𝗶𝘁𝗼𝗿 𝘄𝗶𝘁𝗵 𝘄𝗲𝗯 𝗶𝗻𝘁𝗲𝗿𝗳𝗮𝗰𝗲
• ⚙️ 𝗣𝗿𝗼𝗰𝗲𝘀𝘀 𝗺𝗮𝗻𝗮𝗴𝗲𝗺𝗲𝗻𝘁
• 👑 𝗔𝗱𝗺𝗶𝗻 𝗺𝗮𝗻𝗮𝗴𝗲𝗺𝗲𝗻𝘁
• 📂 𝗙𝗶𝗹𝗲 𝗯𝗿𝗼𝘄𝘀𝗲𝗿
• 📊 𝗦𝗲𝘀𝘀𝗶𝗼𝗻 𝗺𝗼𝗻𝗶𝘁𝗼𝗿𝗶𝗻𝗴

📌 𝗤𝘂𝗶𝗰𝗸 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀:
• /nano filename - 𝗘𝗱𝗶𝘁 𝗮 𝗳𝗶𝗹𝗲
• /stop - 𝗦𝘁𝗼𝗽 𝗰𝘂𝗿𝗿𝗲𝗻𝘁 𝗽𝗿𝗼𝗰𝗲𝘀𝘀
• /status - 𝗖𝗵𝗲𝗰𝗸 𝘀𝘆𝘀𝘁𝗲𝗺 𝘀𝘁𝗮𝘁𝘂𝘀
• /admin - 𝗢𝗽𝗲𝗻 𝗮𝗱𝗺𝗶𝗻 𝗽𝗮𝗻𝗲𝗹
• /sessions - 𝗩𝗶𝗲𝘄 𝗮𝗰𝘁𝗶𝘃𝗲 𝘀𝗲𝘀𝘀𝗶𝗼𝗻𝘀

💡 𝗧𝗶𝗽: 𝗨𝘀𝗲 𝗯𝘂𝘁𝘁𝗼𝗻𝘀 𝗯𝗲𝗹𝗼𝘄 𝗼𝗿 𝘁𝘆𝗽𝗲 𝗰𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗱𝗶𝗿𝗲𝗰𝘁𝗹𝘆!
━━━━━━━━━━━━━━━━━━━━━━
"""
    bot.send_message(cid, welcome_msg, 
                     parse_mode="Markdown", 
                     reply_markup=main_menu_keyboard())

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    cid = m.chat.id
    
    if str(cid) != str(MAIN_ADMIN_ID):
        bot.send_message(cid, "𝗢𝗻𝗹𝘆 𝗠𝗮𝗶𝗻 𝗔𝗱𝗺𝗶𝗻 𝗰𝗮𝗻 𝗮𝗰𝗰𝗲𝘀𝘀 𝘁𝗵𝗶𝘀 𝗽𝗮𝗻𝗲𝗹🕵️‍♀️")
        return
    
    bot.send_message(cid, "🔐 𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟*", 
                     parse_mode="Markdown", 
                     reply_markup=admin_keyboard())

@bot.message_handler(commands=["status"])
def status_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    
    status_msg = f"""
━━━━━━━━━━━━━━━━━━━━━━
📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗨𝗦 📊
━━━━━━━━━━━━━━━━━━━━━━

• 𝗔𝗰𝘁𝗶𝘃𝗲 𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗲𝘀: {len(processes)}
• 𝗔𝗰𝘁𝗶𝘃𝗲 𝗦𝗲𝘀𝘀𝗶𝗼𝗻𝘀: {len(active_sessions)}
• 𝗔𝗱𝗺𝗶𝗻𝘀: {len(admins)}
• 𝗕𝗮𝘀𝗲 𝗗𝗶𝗿𝗲𝗰𝘁𝗼𝗿𝘆: `{BASE_DIR}`

📌 𝗥𝘂𝗻𝗻𝗶𝗻𝗴 𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗲𝘀:
"""
    
    for chat_id, (pid, fd, start_time, cmd) in processes.items():
        status_msg += f"\n👤 {chat_id}: `{cmd[:30]}...` ({start_time})"
    
    bot.send_message(cid, status_msg, parse_mode="Markdown")

@bot.message_handler(commands=["sessions"])
def sessions_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    
    sessions_msg = "🔄 𝗔𝗖𝗧𝗜𝗩𝗘 𝗦𝗘𝗦𝗦𝗜𝗢𝗡𝗦\n"
    for chat_id, last_active in active_sessions.items():
        elapsed = int(time.time() - last_active)
        sessions_msg += f"\n👤 {chat_id}: {elapsed}s ago"
    
    bot.send_message(cid, sessions_msg, parse_mode="Markdown")

@bot.message_handler(commands=["stop"])
def stop_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    
    if cid in processes:
        pid, fd, start_time, cmd = processes[cid]
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
            os.kill(pid, signal.SIGKILL)
        except:
            pass
        
        if cid in processes:
            del processes[cid]
        if cid in input_wait:
            del input_wait[cid]
        
        bot.send_message(cid, "✅ Process stopped successfully!")
    else:
        bot.send_message(cid, "⚠️ No running process to stop.")

@bot.message_handler(commands=["nano"])
def nano_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    
    text = m.text.strip()
    if len(text.split()) < 2:
        bot.send_message(cid, "Usage: /nano filename")
        return
    
    filename = text.split(' ', 1)[1]
    path = os.path.join(BASE_DIR, filename)
    
    # Create file if it doesn't exist
    if not os.path.exists(path):
        try:
            open(path, 'w').close()
        except:
            bot.send_message(cid, f"❌ Cannot create file: {filename}")
            return
    
    # Create edit session
    sid = str(uuid.uuid4())
    edit_sessions[sid] = path
    
    # Create web interface URL
    link = f"https://rocky-termux-com.onrender.com/edit/{sid}"
    
    # Send edit options
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✏️𝗡𝗔𝗡𝗢 𝗘𝗗𝗜𝗧, url=link))
    markup.add(types.InlineKeyboardButton("📄 𝗩𝗜𝗘𝗪 𝗖𝗢𝗡𝗧𝗘𝗡𝗧", callback_data=f"view_{filename}"))
    
    bot.send_message(cid, f"📝 𝗘𝗗𝗜𝗧 𝗙𝗜𝗟𝗘\n\n*File:* `{filename}`\n*Path:* `{path}`", 
                     parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda m: True)
def shell(m):
    cid = m.chat.id
    text = m.text.strip()
    
    if not is_admin(cid):
        bot.send_message(cid, "❌ You are not authorized to use this bot.")
        return
    
    # Update session activity
    active_sessions[cid] = time.time()
    
    # Handle input response
    if cid in input_wait:
        fd = input_wait.pop(cid)
        os.write(fd, (text + "\n").encode())
        return
    
    # Handle quick commands from buttons
    if text == "📁 ls":
        text = "ls -la"
    elif text == "📂 pwd":
        text = "pwd"
    elif text == "💿 df -h":
        text = "df -h"
    elif text == "📊 top":
        text = "top -b -n 1 | head -20"
    elif text == "📜 ps aux":
        text = "ps aux | head -15"
    elif text == "🗑️ clear":
        bot.send_message(cid, "🗑️ Chat cleared (bot-side)")
        return
    elif text == "🛑 stop":
        stop_cmd(m)
        return
    elif text == "📝 nano":
        bot.send_message(cid, "Usage: /nano filename")
        return
    elif text == "🔄 ping 8.8.8.8":
        text = "ping -c 4 8.8.8.8"
    elif text == "🌐 ifconfig":
        text = "ifconfig || ip addr"
    
    # Stop any existing process for this chat
    if cid in processes:
        pid, fd, start_time, cmd = processes[cid]
        try:
            os.kill(pid, signal.SIGTERM)
        except:
            pass
        del processes[cid]
    
    # Run command
    bot.send_message(cid, f"```\n$ {text}\n```", parse_mode="Markdown")
    run_cmd(text, cid)

# ================= CALLBACK HANDLERS =================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    cid = call.message.chat.id
    
    if not is_admin(cid):
        bot.answer_callback_query(call.id, "❌ Not authorized!")
        return
    
    if call.data == "status":
        status_cmd(call.message)
        bot.answer_callback_query(call.id)
    
    elif call.data == "stop_all":
        if str(cid) != str(MAIN_ADMIN_ID):
            bot.answer_callback_query(call.id, "❌ Main admin only!")
            return
        
        stopped = 0
        for chat_id in list(processes.keys()):
            try:
                pid, fd, start_time, cmd = processes[chat_id]
                os.kill(pid, signal.SIGKILL)
                stopped += 1
            except:
                pass
        
        processes.clear()
        input_wait.clear()
        bot.answer_callback_query(call.id, f"✅ Stopped {stopped} processes")
        bot.send_message(cid, f"🛑 Stopped all {stopped} processes")
    
    elif call.data == "admin_list":
        admin_list = "\n".join([f"👤 {admin}" for admin in admins])
        bot.answer_callback_query(call.id)
        bot.send_message(cid, f"*ADMIN LIST:*\n{admin_list}", parse_mode="Markdown")
    
    elif call.data == "add_admin":
        msg = bot.send_message(cid, "Send the user ID to add as admin:")
        bot.register_next_step_handler(msg, add_admin_step)
    
    elif call.data == "remove_admin":
        msg = bot.send_message(cid, "Send the user ID to remove from admins:")
        bot.register_next_step_handler(msg, remove_admin_step)
    
    elif call.data == "list_files":
        try:
            files = os.listdir(BASE_DIR)
            file_list = "\n".join([f"📄 {f}" for f in files[:20]])
            if len(files) > 20:
                file_list += f"\n... and {len(files)-20} more"
            bot.answer_callback_query(call.id)
            bot.send_message(cid, f"*FILES IN {BASE_DIR}:*\n{file_list}", parse_mode="Markdown")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Error: {e}")
    
    elif call.data == "clean_logs":
        # Clean old sessions
        current_time = time.time()
        old_sessions = [sid for sid, last_active in list(active_sessions.items()) 
                       if current_time - last_active > 3600]
        for sid in old_sessions:
            active_sessions.pop(sid, None)
        
        bot.answer_callback_query(call.id, "✅ Cleaned old sessions")
    
    elif call.data.startswith("view_"):
        filename = call.data[5:]
        path = os.path.join(BASE_DIR, filename)
        try:
            with open(path, 'r') as f:
                content = f.read(1000)
            bot.send_message(cid, f"```\n{content}\n```", parse_mode="Markdown")
            bot.answer_callback_query(call.id)
        except:
            bot.answer_callback_query(call.id, "❌ Cannot read file")

def add_admin_step(m):
    cid = m.chat.id
    if str(cid) != str(MAIN_ADMIN_ID):
        return
    
    try:
        new_admin = int(m.text.strip())
        admins.add(new_admin)
        save_data()
        bot.send_message(cid, f"✅ Added admin: {new_admin}")
    except:
        bot.send_message(cid, "❌ Invalid user ID")

def remove_admin_step(m):
    cid = m.chat.id
    if str(cid) != str(MAIN_ADMIN_ID):
        return
    
    try:
        admin_id = int(m.text.strip())
        if admin_id != MAIN_ADMIN_ID and admin_id in admins:
            admins.remove(admin_id)
            save_data()
            bot.send_message(cid, f"✅ Removed admin: {admin_id}")
        else:
            bot.send_message(cid, "❌ Cannot remove main admin or admin not found")
    except:
        bot.send_message(cid, "❌ Invalid user ID")

# ================= ENHANCED EDITOR =================

@app.route("/edit/<sid>", methods=["GET", "POST"])
def edit(sid):
    if sid not in edit_sessions:
        return """
        <html>
        <body style="background:#111;color:#fff;padding:20px;">
        <h2>❌ Invalid or expired session</h2>
        </body>
        </html>
        """
    
    file = edit_sessions[sid]
    
    if request.method == "POST":
        try:
            with open(file, "w", encoding='utf-8') as f:
                f.write(request.form["code"])
            
            # Remove session after save
            edit_sessions.pop(sid, None)
            
            return """
            <html>
            <body style="background:#111;color:#0f0;padding:20px;text-align:center;">
            <h2>✅ File Saved Successfully!</h2>
            <p>You can close this window.</p>
            </body>
            </html>
            """
        except Exception as e:
            return f"""
            <html>
            <body style="background:#111;color:#f00;padding:20px;">
            <h2>❌ Error saving file: {e}</h2>
            </body>
            </html>
            """
    
    try:
        with open(file, "r", encoding='utf-8') as f:
            code = f.read()
    except:
        code = ""
    
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pro IDE | {{ file.split('/')[-1] }}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.23.0/ace.js"></script>
    <style>
        :root {
            --bg-dark: #0d1117;
            --accent: #58a6ff;
            --card-bg: #161b22;
            --border: #30363d;
        }

        body { 
            margin: 0; background: var(--bg-dark); 
            color: #c9d1d9; font-family: 'Segoe UI', sans-serif; 
        }

        .header {
            background: var(--card-bg);
            padding: 10px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
        }

        .file-info {
            font-size: 14px;
            padding: 8px 15px;
            background: #0d1117;
            border-radius: 6px;
            color: var(--accent);
            border: 1px solid var(--border);
        }

        /* Editor container must have height */
        #editor {
            width: 100%;
            height: calc(100vh - 140px);
            font-size: 16px;
        }

        .footer {
            padding: 15px 20px;
            background: var(--card-bg);
            border-top: 1px solid var(--border);
            display: flex;
            justify-content: flex-end;
        }

        .btn-save {
            background: #238636;
            color: white;
            border: none;
            padding: 10px 25px;
            border-radius: 6px;
            font-weight: bold;
            cursor: pointer;
            transition: 0.2s;
        }

        .btn-save:hover { background: #2ea043; }
    </style>
</head>
<body>

<div class="header">
    <div style="font-weight: bold; color: white;">
        <i class="fas fa-code" style="color:var(--accent)"></i> Nano Termux 
    </div>
    <div class="file-info">
        <i class="far fa-file"></i> {{ file }}
    </div>
</div>

<div id="editor">{{ code }}</div>

<form id="saveForm" method="post">
    <input type="hidden" name="code" id="hiddenCode">
    <div class="footer">
        <button type="button" onclick="saveData()" class="btn-save">
            <i class="fas fa-cloud-upload-alt"></i> SAVE CHANGES
        </button>
    </div>
</form>

<script>
    // Ace Editor Setup
    var editor = ace.edit("editor");
    editor.setTheme("ace/theme/one_dark"); // Premium Dark Theme
    
    // File Extension ke hisaab se mode set karna
    var filename = "{{ file }}";
    var ext = filename.split('.').pop().toLowerCase();
    
    if(ext === 'py') editor.session.setMode("ace/mode/python");
    else if(ext === 'js') editor.session.setMode("ace/mode/javascript");
    else if(ext === 'php') editor.session.setMode("ace/mode/php");
    else if(ext === 'html') editor.session.setMode("ace/mode/html");
    else if(ext === 'css') editor.session.setMode("ace/mode/css");
    else editor.session.setMode("ace/mode/text");

    // Editor Options
    editor.setOptions({
        enableBasicAutocompletion: true,
        enableLiveAutocompletion: true,
        showPrintMargin: false,
        useSoftTabs: true,
        tabSize: 4
    });

    // Save Function
    function saveData() {
        document.getElementById('hiddenCode').value = editor.getValue();
        document.getElementById('saveForm').submit();
    }
</script>

</body>
</html>
""", code=code, file=file)

# ================= START SERVER =================

@app.route('/')
def home():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Termux Pro | Active</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body { 
            background: #050505; 
            height: 100vh; 
            display: flex; 
            justify-content: center; 
            align-items: center; 
            font-family: 'Segoe UI', sans-serif;
            overflow: hidden;
        }

        /* Ambient Glow Background */
        .glow-bg {
            position: absolute;
            width: 300px;
            height: 300px;
            background: radial-gradient(circle, rgba(0, 212, 255, 0.2) 0%, rgba(0, 0, 0, 0) 70%);
            z-index: 1;
        }

        .container {
            position: relative;
            z-index: 10;
            text-align: center;
        }

        /* Central Bot Animation */
        .bot-wrapper {
            position: relative;
            width: 150px;
            height: 150px;
            margin: 0 auto 30px;
            display: flex;
            justify-content: center;
            align-items: center;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 50%;
            border: 1px solid rgba(0, 212, 255, 0.3);
            box-shadow: 0 0 30px rgba(0, 212, 255, 0.1);
        }

        .bot-icon {
            font-size: 70px;
            color: #00d4ff;
            filter: drop-shadow(0 0 15px #00d4ff);
            animation: float 3s ease-in-out infinite;
        }

        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-15px); }
        }

        /* Pulsing Rings */
        .ring {
            position: absolute;
            border: 2px solid #00d4ff;
            border-radius: 50%;
            opacity: 0;
            animation: pulse-ring 3s infinite;
        }

        @keyframes pulse-ring {
            0% { width: 150px; height: 150px; opacity: 0.5; }
            100% { width: 300px; height: 300px; opacity: 0; }
        }

        h1 {
            color: white;
            font-size: 28px;
            font-weight: 300;
            letter-spacing: 5px;
            margin-bottom: 10px;
            text-transform: uppercase;
        }

        .status-text {
            color: #00d4ff;
            font-size: 14px;
            font-weight: bold;
            letter-spacing: 2px;
            opacity: 0.8;
        }

        .btn-telegram {
            margin-top: 40px;
            display: inline-flex;
            align-items: center;
            gap: 12px;
            background: transparent;
            color: white;
            border: 1px solid #00d4ff;
            padding: 12px 30px;
            border-radius: 50px;
            text-decoration: none;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.4s;
            overflow: hidden;
            position: relative;
        }

        .btn-telegram:hover {
            background: #00d4ff;
            color: #000;
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.5);
        }
    </style>
</head>
<body>

    <div class="glow-bg"></div>
    
    <div class="container">
        <div class="bot-wrapper">
            <div class="ring"></div>
            <div class="ring" style="animation-delay: 1s;"></div>
            <i class="fas fa-robot bot-icon"></i>
        </div>

        <h1>TERMUX PRO</h1>
        <div class="status-text">SYSTEM ACTIVE • 100%</div>

        <p style="color: #666; margin-top: 20px; font-size: 13px; max-width: 300px; margin-left: auto; margin-right: auto;">
            Server is listening for remote commands via Telegram encrypted tunnel.
        </p>

        <a href="https://t.me/Reac4ron_bot_bot" class="btn-telegram">
            <i class="fab fa-telegram-plane"></i> OPEN TELEGRAM BOT
        </a>
    </div>

</body>
</html>
"""

if __name__ == "__main__":
    print("🤖 Starting Termux Controller Pro...")
    print(f"👑 Main Admin: {MAIN_ADMIN_ID}")
    print(f"📁 Base Directory: {BASE_DIR}")
    
    # Start Flask server
    threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0", 
            port=PORT, 
            debug=False, 
            use_reloader=False
        ), 
        daemon=True
    ).start()
    
    # Start bot
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        print(f"Bot error: {e}")
        # Retry after 5 seconds
        time.sleep(5)
        bot.infinity_polling()
