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
🤖 *TERMUX CONTROLLER PRO* 🤖

*Features:*
• Execute shell commands
• Nano editor with web interface
• Process management
• Admin management
• File browser
• Session monitoring

*Quick Commands:*
/nano filename - Edit file
/stop - Stop current process
/status - Check system status
/admin - Admin panel
/sessions - Active sessions

*Use buttons below or type commands directly!*
"""
    bot.send_message(cid, welcome_msg, 
                     parse_mode="Markdown", 
                     reply_markup=main_menu_keyboard())

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    cid = m.chat.id
    
    if str(cid) != str(MAIN_ADMIN_ID):
        bot.send_message(cid, "❌ Only main admin can access this panel.")
        return
    
    bot.send_message(cid, "🔐 *ADMIN PANEL*", 
                     parse_mode="Markdown", 
                     reply_markup=admin_keyboard())

@bot.message_handler(commands=["status"])
def status_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    
    status_msg = f"""
📊 *SYSTEM STATUS* 📊

*Active Processes:* {len(processes)}
*Active Sessions:* {len(active_sessions)}
*Admins:* {len(admins)}
*Base Directory:* `{BASE_DIR}`

*Running Processes:*
"""
    
    for chat_id, (pid, fd, start_time, cmd) in processes.items():
        status_msg += f"\n👤 {chat_id}: `{cmd[:30]}...` ({start_time})"
    
    bot.send_message(cid, status_msg, parse_mode="Markdown")

@bot.message_handler(commands=["sessions"])
def sessions_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    
    sessions_msg = "🔄 *ACTIVE SESSIONS*\n"
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
    link = f"https://elite-vps-bot-try-hu7.onrender.com/edit/{sid}"
    
    # Send edit options
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✏️ Edit in Browser", url=link))
    markup.add(types.InlineKeyboardButton("📄 View Content", callback_data=f"view_{filename}"))
    
    bot.send_message(cid, f"📝 *EDIT FILE*\n\n*File:* `{filename}`\n*Path:* `{path}`", 
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
    <html>
    <head>
        <title>File Editor</title>
        <style>
            * { margin:0; padding:0; box-sizing:border-box; }
            body { 
                background: #0a0a0a; 
                color: #00ff00; 
                font-family: 'Courier New', monospace;
            }
            .header {
                background: #001a00;
                padding: 15px;
                border-bottom: 2px solid #00ff00;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .filename {
                font-size: 18px;
                font-weight: bold;
            }
            .container {
                padding: 20px;
            }
            textarea {
                width: 100%;
                height: 80vh;
                background: #000;
                color: #00ff00;
                border: 1px solid #008800;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 14px;
                resize: vertical;
                border-radius: 5px;
            }
            button {
                background: #008800;
                color: white;
                border: none;
                padding: 10px 30px;
                margin-top: 10px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
                transition: 0.3s;
            }
            button:hover {
                background: #00aa00;
                transform: scale(1.05);
            }
            .info {
                background: #001100;
                padding: 10px;
                border-radius: 5px;
                margin-bottom: 10px;
                border-left: 3px solid #00ff00;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="filename">📝 Editing: {{ file.split('/')[-1] }}</div>
            <div style="color:#aaa">Termux Controller Pro</div>
        </div>
        <div class="container">
            <div class="info">
                File: {{ file }}<br>
                Size: {{ code|length }} characters
            </div>
            <form method="post">
                <textarea name="code" placeholder="Start typing your code here...">{{ code }}</textarea>
                <button type="submit">💾 SAVE CHANGES</button>
            </form>
        </div>
    </body>
    </html>
    """, code=code, file=file)

# ================= START SERVER =================

@app.route('/')
def home():
    return """
    <html>
    <body style="background:#111;color:#0f0;text-align:center;padding:50px;">
    <h1>🤖 Termux Controller Pro</h1>
    <p>Server is running...</p>
    <p style="color:#888">Use Telegram bot to access features</p>
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
