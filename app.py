# ==============================================
# Project: Tharmux Bot Pro - HF SPACE FIXED
# Owner: @rajfflive
# Admin: 8154922225
# Version: 7.0 - WEBHOOK ONLY (No Outgoing)
# ==============================================

import os
import sys
import time
import threading
import json
import uuid
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify
import logging

# ========== CONFIG ==========
BOT_TOKEN = "8062060822:AAF4JuXunJnoJNIWTYffvr-JuA0nDaz7adc"
MAIN_ADMIN_ID = 8154922225
PORT = int(os.environ.get("PORT", 7860))

BASE_DIR = os.getcwd()
USER_DATA_DIR = os.path.join(BASE_DIR, "user_data")
os.makedirs(USER_DATA_DIR, exist_ok=True)

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== INIT ==========
app = Flask(__name__)

# ========== DATA STRUCTURES ==========
edit_sessions = {}
processes = {}
user_stats = {}

# ========== HELPER FUNCTIONS ==========
def get_user_directory(user_id):
    path = os.path.join(USER_DATA_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

def is_admin(user_id):
    return str(user_id) == str(MAIN_ADMIN_ID)

def run_command(cmd, cwd):
    """Run command and return output"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, 
            timeout=60, cwd=cwd
        )
        output = result.stdout if result.stdout else result.stderr
        if not output:
            output = "✅ Command executed (no output)"
        return output[:4000]  # Telegram limit
    except subprocess.TimeoutExpired:
        return "⏰ Command timeout (60s)"
    except Exception as e:
        return f"❌ Error: {str(e)[:200]}"

def get_system_stats():
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        return f"📊 *System Stats*\nCPU: {cpu:.1f}%\nMemory: {mem:.1f}%\nDisk: {disk:.1f}%"
    except:
        return "📊 System stats unavailable"

def get_public_url():
    return f"https://rajfflive-termuxbot.hf.space"

# ========== WEBHOOK HANDLER ==========
@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """Handle incoming updates - NO OUTGOING REQUESTS"""
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return 'OK', 200
        
        msg = data['message']
        chat_id = msg['chat']['id']
        text = msg.get('text', '').strip()
        username = msg.get('from', {}).get('username', 'Unknown')
        
        logger.info(f"Message from {chat_id}: {text[:50]}")
        
        # Check authorization
        if not is_admin(chat_id):
            logger.warning(f"Unauthorized: {chat_id}")
            return 'OK', 200  # Silently ignore
        
        # Update stats
        user_stats[str(chat_id)] = user_stats.get(str(chat_id), 0) + 1
        
        # Process command
        response = process_command(chat_id, text)
        
        # Send response via Telegram API (this will still try but might fail)
        send_via_telegram(chat_id, response)
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'Error', 500

def process_command(chat_id, text):
    """Process command and return response text"""
    
    # Handle /start
    if text == '/start':
        return f"""
🚀 *Tharmux Bot Pro v7.0*
━━━━━━━━━━━━━━━━━━━━━
👑 Owner: @rajfflive
✅ Status: Online
📁 Your dir: `{get_user_directory(chat_id)}`
💡 *Commands:*
• Any Linux command
• /status - System stats
• /nano filename - Edit files
• /files - List your files
━━━━━━━━━━━━━━━━━━━━━
"""
    
    # Handle /status
    if text == '/status':
        return get_system_stats()
    
    # Handle /files
    if text == '/files':
        user_dir = get_user_directory(chat_id)
        try:
            files = os.listdir(user_dir)
            if not files:
                return "📁 Your directory is empty"
            file_list = "\n".join([f"• {f}" for f in files[:20]])
            return f"📁 *Your Files*\n{file_list}"
        except Exception as e:
            return f"❌ Error: {e}"
    
    # Handle /nano
    if text.startswith('/nano '):
        filename = text[6:].strip()
        safe_path = os.path.join(get_user_directory(chat_id), filename)
        sid = str(uuid.uuid4())
        edit_sessions[sid] = {"file": safe_path, "user_id": chat_id, "filename": filename}
        url = f"{get_public_url()}/edit/{sid}"
        return f"📝 *Edit File:* `{filename}`\n✏️ [Click here to edit]({url})"
    
    # Handle quick buttons (from keyboard)
    button_map = {
        "📁 ls -la": "ls -la",
        "📂 pwd": "pwd", 
        "💿 df -h": "df -h",
        "📊 system stats": None,
        "🔄 ping 8.8.8.8 -c 4": "ping -c 4 8.8.8.8",
        "🌐 ifconfig": "ifconfig 2>/dev/null || ip addr",
    }
    
    if text in button_map:
        if text == "📊 system stats":
            return get_system_stats()
        cmd = button_map[text]
        if cmd:
            output = run_command(cmd, get_user_directory(chat_id))
            return f"```\n$ {cmd}\n{output}\n```"
        return "✅ Done"
    
    # Default: run as shell command
    if text:
        output = run_command(text, get_user_directory(chat_id))
        return f"```\n$ {text}\n{output}\n```"
    
    return "Type a command or use /help"

def send_via_telegram(chat_id, text, parse_mode="Markdown"):
    """Try to send message - uses multiple methods"""
    if not text:
        return
    
    # Method 1: Direct HTTP (most reliable if egress works)
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # Try multiple endpoints
    endpoints = [
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        f"https://telegram-bot-api.herokuapp.com/bot{BOT_TOKEN}/sendMessage", 
        f"https://telegram-api.herokuapp.com/bot{BOT_TOKEN}/sendMessage",
    ]
    
    for endpoint in endpoints:
        try:
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': parse_mode
            }
            # Split long messages
            if len(text) > 4000:
                for i in range(0, len(text), 4000):
                    payload['text'] = text[i:i+4000]
                    requests.post(endpoint, json=payload, timeout=10)
                return
            else:
                resp = requests.post(endpoint, json=payload, timeout=10)
                if resp.status_code == 200:
                    logger.info(f"Message sent to {chat_id}")
                    return
        except Exception as e:
            logger.error(f"Send failed to {endpoint}: {e}")
            continue
    
    # If all fail, log it
    logger.error(f"Could not send message to {chat_id}: {text[:100]}")

# ========== EDIT ROUTE ==========
@app.route('/edit/<sid>', methods=['GET', 'POST'])
def edit_file(sid):
    if sid not in edit_sessions:
        return "❌ Session expired or invalid", 404
    
    sess = edit_sessions[sid]
    filepath = sess['file']
    filename = sess.get('filename', os.path.basename(filepath))
    
    if request.method == 'POST':
        content = request.form.get('code', '')
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return """
            <html>
            <head><title>Saved</title></head>
            <body style="background:#0d1117;color:#fff;text-align:center;padding:50px;">
            <h2>✅ File Saved!</h2>
            <p>You can close this window</p>
            <script>setTimeout(()=>window.close(),2000);</script>
            </body>
            </html>
            """
        except Exception as e:
            return f"❌ Error saving: {e}"
    
    # GET request - show editor
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except:
        content = ""
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Edit {filename}</title>
        <meta charset="utf-8">
        <style>
            body {{ margin:0; background:#0d1117; color:#c9d1d9; font-family:monospace; }}
            .header {{ background:#161b22; padding:10px 20px; border-bottom:1px solid #30363d; }}
            textarea {{ width:100%; height:calc(100vh - 100px); background:#0d1117; color:#c9d1d9; border:none; padding:20px; font-family:monospace; font-size:14px; }}
            button {{ background:#238636; color:white; border:none; padding:8px 24px; border-radius:6px; cursor:pointer; margin:10px; }}
            button:hover {{ background:#2ea043; }}
        </style>
    </head>
    <body>
        <div class="header">
            <strong>✏️ Editing: {filename}</strong>
        </div>
        <form method="post">
            <textarea name="code">{content}</textarea>
            <div style="text-align:center;">
                <button type="submit">💾 Save File</button>
            </div>
        </form>
    </body>
    </html>
    """

# ========== HEALTH ROUTES ==========
@app.route('/')
def home():
    return f"""
    <html>
    <head><title>Tharmux Bot</title></head>
    <body style="background:#0d1117;color:#fff;text-align:center;padding:50px;">
        <h1>🤖 Tharmux Bot Pro v7.0</h1>
        <p>Owner: @rajfflive</p>
        <p>Status: <span style="color:#3fb950;">✅ Running (Webhook Mode)</span></p>
        <p>Commands sent: {sum(user_stats.values())}</p>
        <hr>
        <p>Send <code>/start</code> to your bot on Telegram</p>
    </body>
    </html>
    """

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "owner": "@rajfflive",
        "version": "7.0",
        "mode": "webhook"
    })

# ========== MAIN ==========
if __name__ == "__main__":
    print("="*50)
    print("🤖 Tharmux Bot Pro v7.0 - HF SPACE FIXED")
    print(f"👑 Owner: @rajfflive | Admin ID: {MAIN_ADMIN_ID}")
    print(f"🔑 Token: {BOT_TOKEN[:15]}...")
    print("="*50)
    print("✅ Webhook mode - NO outgoing polling")
    print("✅ Bot will only respond to incoming webhooks")
    print("="*50)
    
    # Start Flask server
    app.run(host='0.0.0.0', port=PORT, debug=False)
