# ==============================================
# Project: Tharmux Bot Pro
# Author: Pp
# Telegram: @ROCKY_BHAI787
# Version: 5.0
# Description:
#   Advanced Telegram remote shell & file editor bot
#   with system monitoring and multi-user support
# ==============================================

import os
import pty
import threading
import uuid
import select
import json
import time
import signal
import psutil
import subprocess
from datetime import datetime, timedelta
from flask import Flask, request, render_template_string, jsonify
import telebot
from telebot import types
import traceback
import logging
import re
import zipfile as _zipfile
import tarfile as _tarfile
from logging.handlers import RotatingFileHandler

# ========== CONFIGURATION ==========
BOT_TOKEN = "8062060822:AAHrr45bjcCHxR2-LG_BpVsIhjJcJ3ryDaQ"
MAIN_ADMIN_ID = 8154922225
PORT = int(os.environ.get("PORT", 10000))
BASE_DIR = os.getcwd()
DATA_FILE = "bot_data.json"
USER_DATA_DIR = os.path.join(BASE_DIR, "user_data")
LOG_FILE = "bot.log"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB
BACKUP_COUNT = 3

# Create directories
os.makedirs(USER_DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

# ========== LOGGING SETUP ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            os.path.join(BASE_DIR, "logs", LOG_FILE),
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

print("🔧 Configuration loaded:")
print(f"   PORT: {PORT}")
print(f"   BOT_TOKEN present: {'Yes' if BOT_TOKEN != '8062060822:AAHrr45bjcCHxR2-LG_BpVsIhjJcJ3ryDaQ' else 'No'}")
print(f"   MAIN_ADMIN_ID: {MAIN_ADMIN_ID}")
print(f"   USER_DATA_DIR: {USER_DATA_DIR}")

# ========== INITIALIZE BOT ==========
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== DATA STRUCTURES ==========
edit_sessions = {}
processes = {}
input_wait = {}
active_sessions = {}
admins = set()
user_stats = {}  # Track user usage stats
system_alerts = []  # Store system alerts
MAX_ALERTS = 50
authorized_users = set()  # All users who can use basic features

# ========== HELPER FUNCTIONS ==========
def get_user_directory(user_id):
    """Get or create user's private directory"""
    user_dir = os.path.join(USER_DATA_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def is_admin(user_id):
    """Check if user is admin"""
    return str(user_id) == str(MAIN_ADMIN_ID) or user_id in admins

def is_authorized(user_id):
    """Check if user is authorized (ONLY ADMINS)"""
    return is_admin(user_id)  # 🔥 SIRF YAHI LINE CHANGE KARNA HAI

def sanitize_path(user_id, path):
    """Ensure path is within user's directory and prevent path traversal"""
    user_dir = get_user_directory(user_id)
    
    if not os.path.isabs(path):
        clean_path = os.path.join(user_dir, path)
    else:
        clean_path = path
    
    clean_path = os.path.normpath(clean_path)
    
    if not clean_path.startswith(os.path.abspath(user_dir)):
        return None
    
    return clean_path

def get_user_dict(user_id, dict_obj):
    """Get user-specific dictionary, create if not exists"""
    if user_id not in dict_obj:
        dict_obj[user_id] = {}
    return dict_obj[user_id]

def generate_session_id():
    """Generate unique session ID for each command"""
    return str(uuid.uuid4())

def get_system_stats():
    """Get system statistics with progress bars"""
    try:
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_bars = int(cpu_percent / 10)
        cpu_bar = "▒" * cpu_bars + "░" * (10 - cpu_bars)
        
        # Memory usage
        memory = psutil.virtual_memory()
        mem_percent = memory.percent
        mem_bars = int(mem_percent / 10)
        mem_bar = "▒" * mem_bars + "░" * (10 - mem_bars)
        
        # Disk usage
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_bars = int(disk_percent / 10)
        disk_bar = "▒" * disk_bars + "░" * (10 - disk_bars)
        
        # Additional stats
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        uptime_str = str(uptime).split('.')[0]
        
        processes_count = len(psutil.pids())
        
        return {
            'cpu': cpu_percent,
            'cpu_bar': cpu_bar,
            'memory': mem_percent,
            'memory_bar': mem_bar,
            'disk': disk_percent,
            'disk_bar': disk_bar,
            'uptime': uptime_str,
            'processes': processes_count,
            'boot_time': boot_time.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        return {
            'cpu': 0,
            'cpu_bar': "░" * 10,
            'memory': 0,
            'memory_bar': "░" * 10,
            'disk': 0,
            'disk_bar': "░" * 10,
            'uptime': "N/A",
            'processes': 0,
            'boot_time': "N/A"
        }

def add_system_alert(alert_type, message):
    """Add system alert"""
    system_alerts.append({
        'type': alert_type,
        'message': message,
        'time': datetime.now().strftime("%H:%M:%S")
    })
    if len(system_alerts) > MAX_ALERTS:
        system_alerts.pop(0)

# ══════════════════════════════════════════════════
# 📦 DEPENDENCY AUTO-INSTALLER
# ══════════════════════════════════════════════════
def auto_install_deps(file_path, chat_id):
    """File ke imports scan karke missing packages install karo"""
    try:
        with open(file_path, 'r', errors='ignore') as f:
            content = f.read()
        imports = re.findall(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE)
        stdlib = {
            'os','sys','re','json','time','math','random','threading','subprocess',
            'datetime','collections','itertools','functools','pathlib','io','abc',
            'typing','logging','hashlib','base64','uuid','signal','select','shutil',
            'glob','zipfile','socket','struct','copy','enum','traceback','warnings',
            'pty','psutil','flask','telebot','secrets','hmac','http','urllib'
        }
        to_install = [m for m in set(imports) if m.lower() not in stdlib]
        if not to_install:
            return True, "Sab dependencies already available hain!"
        results = []
        for pkg in to_install:
            try:
                r = subprocess.run(
                    ['pip', 'install', pkg, '--quiet', '--break-system-packages'],
                    capture_output=True, text=True, timeout=30
                )
                results.append(f"{'✅' if r.returncode == 0 else '⚠️'} {pkg}")
            except Exception as e:
                results.append(f"❌ {pkg}: {str(e)[:40]}")
        return True, "\n".join(results)
    except Exception as e:
        return False, str(e)

# ══════════════════════════════════════════════════
# 🌐 CLOUDFLARED TUNNEL
# ══════════════════════════════════════════════════
_cf_process = None
_cf_url = None

def start_cloudflared(port=5000):
    global _cf_process, _cf_url
    try:
        _cf_process = subprocess.Popen(
            ['cloudflared', 'tunnel', '--url', f'http://localhost:{port}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        # URL aane ka wait karo (max 15 seconds)
        import re as _re
        start = time.time()
        while time.time() - start < 15:
            line = _cf_process.stdout.readline()
            if not line:
                break
            # Cloudflared URL is iss format mein aata hai
            match = _re.search(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com', line)
            if match:
                _cf_url = match.group(0)
                return True, _cf_url
        return False, "URL nahi mila — cloudflared installed hai? `pkg install cloudflared`"
    except FileNotFoundError:
        return False, "cloudflared not found!\nTermux mein install karo:\n`pkg install cloudflared`"
    except Exception as e:
        return False, str(e)

def stop_cloudflared():
    global _cf_process, _cf_url
    if _cf_process:
        _cf_process.terminate()
        _cf_process = None
        _cf_url = None
        return True
    return False

# ══════════════════════════════════════════════════
# 📦 ZIP FILE MANAGER
# ══════════════════════════════════════════════════
MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10 MB

def zip_files(file_paths, output_name, user_id):
    """Multiple files ya folder ko zip karo"""
    try:
        user_dir = get_user_directory(user_id)
        out_path = os.path.join(user_dir, output_name if output_name.endswith('.zip') else output_name + '.zip')
        with _zipfile.ZipFile(out_path, 'w', _zipfile.ZIP_DEFLATED) as zf:
            for fp in file_paths:
                if os.path.isdir(fp):
                    for root, dirs, files in os.walk(fp):
                        for f in files:
                            full = os.path.join(root, f)
                            arcname = os.path.relpath(full, os.path.dirname(fp))
                            zf.write(full, arcname)
                elif os.path.isfile(fp):
                    zf.write(fp, os.path.basename(fp))
        size = os.path.getsize(out_path)
        return True, out_path, size
    except Exception as e:
        return False, str(e), 0

def unzip_file(zip_path, extract_to):
    """ZIP file extract karo"""
    try:
        with _zipfile.ZipFile(zip_path, 'r') as zf:
            members = zf.namelist()
            zf.extractall(extract_to)
        return True, members
    except Exception as e:
        return False, str(e)

def zip_info(zip_path):
    """ZIP file ka content list karo"""
    try:
        with _zipfile.ZipFile(zip_path, 'r') as zf:
            infos = []
            for info in zf.infolist():
                infos.append({
                    'name': info.filename,
                    'size': info.file_size,
                    'compressed': info.compress_size,
                    'is_dir': info.filename.endswith('/')
                })
        return True, infos
    except Exception as e:
        return False, str(e)

def add_to_zip(zip_path, file_path):
    """Existing ZIP mein file add karo"""
    try:
        with _zipfile.ZipFile(zip_path, 'a', _zipfile.ZIP_DEFLATED) as zf:
            zf.write(file_path, os.path.basename(file_path))
        return True, os.path.basename(file_path)
    except Exception as e:
        return False, str(e)

def extract_single_from_zip(zip_path, member_name, extract_to):
    """ZIP se sirf ek file extract karo"""
    try:
        with _zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extract(member_name, extract_to)
        return True, os.path.join(extract_to, member_name)
    except Exception as e:
        return False, str(e)

# ══════════════════════════════════════════════════
# 🔗 NETWORK TOOLS
# ══════════════════════════════════════════════════
def get_public_ip():
    try:
        r = subprocess.run(['curl', '-s', 'https://api.ipify.org'], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except:
        return "N/A"

def port_check(host, port):
    """Koi port open hai ya nahi check karo"""
    import socket
    try:
        s = socket.create_connection((host, int(port)), timeout=3)
        s.close()
        return True
    except:
        return False

# ══════════════════════════════════════════════════
# ⏱️ UPTIME TRACKER
# ══════════════════════════════════════════════════
BOT_START_TIME = datetime.now()

def get_bot_uptime():
    delta = datetime.now() - BOT_START_TIME
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"

def get_public_base_url():
    if os.environ.get("BASE_URL"):
        return os.environ.get("BASE_URL").rstrip("/")
    if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        return f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}"
    if os.environ.get("RAILWAY_STATIC_URL"):
        return f"https://{os.environ.get('RAILWAY_STATIC_URL')}"
    if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        return f"https://{os.environ.get('RAILWAY_PUBLIC_DOMAIN')}"
    if os.environ.get("HEROKU_APP_NAME"):
        return f"https://{os.environ.get('HEROKU_APP_NAME')}.herokuapp.com"
    if os.environ.get("KOYEB_PUBLIC_DOMAIN"):
        return f"https://{os.environ.get('KOYEB_PUBLIC_DOMAIN')}"
    for key in ["PUBLIC_URL", "APP_URL", "HOST_URL", "DOMAIN"]:
        val = os.environ.get(key)
        if val:
            return val.rstrip("/")
    return f"http://localhost:{PORT}"

def load_data():
    """Load bot data from file"""
    global admins, user_stats, authorized_users
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                admins = set(data.get('admins', []))
                user_stats = data.get('user_stats', {})
                authorized_users = set(data.get('authorized_users', []))
        admins.add(MAIN_ADMIN_ID)
        logger.info(f"Data loaded. Admins: {len(admins)}, Authorized users: {len(authorized_users)}")
    except Exception as e:
        logger.error(f"⚠️ Load data failed: {e}")
        admins = {MAIN_ADMIN_ID}
        user_stats = {}
        authorized_users = set()

def save_data():
    """Save bot data to file"""
    try:
        data = {
            'admins': list(admins),
            'user_stats': user_stats,
            'authorized_users': list(authorized_users)
        }
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info("Data saved successfully")
    except Exception as e:
        logger.error(f"⚠️ Save data failed: {e}")

def update_user_stats(user_id, username):
    """Update user statistics"""
    user_id_str = str(user_id)
    if user_id_str not in user_stats:
        user_stats[user_id_str] = {
            'commands': 0,
            'first_seen': datetime.now().isoformat(),
            'username': username,
            'user_id': user_id
        }
    user_stats[user_id_str]['commands'] += 1
    user_stats[user_id_str]['last_seen'] = datetime.now().isoformat()
    user_stats[user_id_str]['username'] = username
    save_data()

def run_cmd(cmd, user_id, chat_id, session_id):
    """Run command in isolated PTY for specific user"""
    def task():
        try:
            proc_dict = get_user_dict(user_id, processes)
            sess_dict = get_user_dict(user_id, active_sessions)
            input_dict = get_user_dict(user_id, input_wait)
            
            user_dir = get_user_directory(user_id)
            
            pid, fd = pty.fork()
            if pid == 0:
                # Child process
                os.chdir(user_dir)
                # Use bash -c to execute the command
                os.execvp("bash", ["bash", "-c", cmd])
            else:
                # Parent process
                start_time = datetime.now().strftime("%H:%M:%S")
                proc_dict[session_id] = (pid, fd, start_time, cmd)
                sess_dict[session_id] = time.time()

                try:
                    while True:
                        rlist, _, _ = select.select([fd], [], [], 0.1)
                        if fd in rlist:
                            try:
                                out = os.read(fd, 1024).decode(errors="ignore")
                            except OSError:
                                break

                            if out:
                                # Split long output into chunks
                                for i in range(0, len(out), 3500):
                                    chunk = out[i:i+3500]
                                    try:
                                        bot.send_message(chat_id, f"```\n{chunk}\n```", parse_mode="Markdown")
                                    except Exception as e:
                                        logger.error(f"Error sending message: {e}")

                            if out.strip().endswith(":"):
                                input_dict[session_id] = fd

                        # Check if process is still alive
                        try:
                            os.kill(pid, 0)
                        except OSError:
                            break

                        time.sleep(0.1)
                except Exception as e:
                    logger.error(f"Error in command execution: {e}")
                finally:
                    # Cleanup
                    if session_id in proc_dict:
                        del proc_dict[session_id]
                    if session_id in input_dict:
                        del input_dict[session_id]
                    if session_id in sess_dict:
                        del sess_dict[session_id]
                    
                    try:
                        os.close(fd)
                    except:
                        pass
        except Exception as e:
            logger.error(f"Fatal error in run_cmd: {e}")
            try:
                bot.send_message(chat_id, f"❌ Error executing command: {str(e)[:200]}")
            except:
                pass

    threading.Thread(target=task, daemon=True).start()

# ========== KEYBOARDS ==========
def main_menu_keyboard(is_admin_user=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    # Basic commands for all users
    buttons = [
        "📁 ls -la", "📂 pwd",
        "💿 df -h", "📊 system stats",
        "📝 nano", "🛑 stop",
        "🗑️ clear", "📁 my files",
        "ℹ️ my info", "📜 ps aux | head -20",
        "🌐 ifconfig", "🔄 ping 8.8.8.8 -c 4",
        "📤 upload zip", "🌐 public url"
    ]
    
    # Add admin-only buttons if user is admin
    if is_admin_user:
        buttons.extend(["👑 admin panel", "📈 performance"])
    
    markup.add(*buttons)
    return markup

def admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 System Status", callback_data="status"),
        types.InlineKeyboardButton("🛑 Stop All", callback_data="stop_all"),
        types.InlineKeyboardButton("👥 Admin List", callback_data="admin_list"),
        types.InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
        types.InlineKeyboardButton("➖ Remove Admin", callback_data="remove_admin"),
        types.InlineKeyboardButton("📁 Browse Files", callback_data="list_files"),
        types.InlineKeyboardButton("🗑️ Clean Logs", callback_data="clean_logs"),
        types.InlineKeyboardButton("📊 User Stats", callback_data="user_stats"),
        types.InlineKeyboardButton("⚠️ System Alerts", callback_data="system_alerts"),
        types.InlineKeyboardButton("📈 Performance", callback_data="performance"),
        types.InlineKeyboardButton("👥 Authorize User", callback_data="authorize_user"),
        types.InlineKeyboardButton("🚫 Deauthorize User", callback_data="deauthorize_user"),
        types.InlineKeyboardButton("📤 ZIP Upload Guide", callback_data="zip_guide"),
        types.InlineKeyboardButton("🌐 Public URL", callback_data="public_url")
    )
    return markup

# ========== AUTO RESTART FUNCTION (SIRF BOT.PY KE LIYE) ==========
def run_bot_py_with_monitor(cmd, user_id, chat_id):
    """Run bot.py with auto restart - 30 min baad aur crash pe"""
    def task():
        while True:
            try:
                proc_dict = get_user_dict(user_id, processes)
                sess_dict = get_user_dict(user_id, active_sessions)
                input_dict = get_user_dict(user_id, input_wait)
                
                user_dir = get_user_directory(user_id)
                
                pid, fd = pty.fork()
                if pid == 0:
                    os.chdir(user_dir)
                    os.execvp("bash", ["bash", "-c", cmd])
                else:
                    session_id = generate_session_id()
                    start_time = datetime.now()
                    proc_dict[session_id] = (pid, fd, start_time, cmd)
                    sess_dict[session_id] = time.time()
                    
                    auto_restart = False
                    thirty_min_msg_sent = False

                    try:
                        while True:
                            current_time = datetime.now()
                            
                            # 30 min complete? Auto restart ON
                            if not auto_restart:
                                elapsed = current_time - start_time
                                if elapsed.total_seconds() >= 1800 and not thirty_min_msg_sent:  # 30 minutes
                                    auto_restart = True
                                    thirty_min_msg_sent = True
                                    bot.send_message(chat_id, f"✅ *30 min complete!*\n🔄 Auto restart ENABLED - ab crash hoga toh restart hoga!", parse_mode="Markdown")
                            
                            rlist, _, _ = select.select([fd], [], [], 0.1)
                            if fd in rlist:
                                try:
                                    out = os.read(fd, 1024).decode(errors="ignore")
                                except OSError:
                                    break

                                if out:
                                    for i in range(0, len(out), 3500):
                                        chunk = out[i:i+3500]
                                        try:
                                            bot.send_message(chat_id, f"```\n{chunk}\n```", parse_mode="Markdown")
                                        except:
                                            pass

                            # Check if process crashed
                            try:
                                os.kill(pid, 0)
                            except OSError:
                                if auto_restart:
                                    bot.send_message(chat_id, f"⚠️ *bot.py Crashed!*\n🔄 Restarting in 3 seconds...", parse_mode="Markdown")
                                    break
                                else:
                                    bot.send_message(chat_id, f"❌ *bot.py Crashed!*\n(30 min complete nahi hua - auto restart disabled)", parse_mode="Markdown")
                                    return

                            time.sleep(0.1)
                    except Exception as e:
                        logger.error(f"Error in command execution: {e}")
                    finally:
                        if session_id in proc_dict:
                            del proc_dict[session_id]
                        if session_id in input_dict:
                            del input_dict[session_id]
                        if session_id in sess_dict:
                            del sess_dict[session_id]
                        try:
                            os.close(fd)
                        except:
                            pass
                    
                    if auto_restart:
                        time.sleep(3)
                    else:
                        return
                    
            except Exception as e:
                logger.error(f"Fatal error in run_bot_py_with_monitor: {e}")
                time.sleep(3)

    threading.Thread(target=task, daemon=True).start()

# ========== MESSAGE HANDLERS ==========
@bot.message_handler(commands=["start"])
def start(m):
    cid = m.chat.id
    username = m.from_user.username or "Unknown"
    first_name = m.from_user.first_name or "User"
    
    # 🔥 SIRF ADMINS 🔥
    if not is_admin(cid):
        bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗
╰━━━━━━━━━━━━━━━✦
""")
        logger.warning(f"UNAUTHORIZED ACCESS: User {cid} (@{username}) tried /start")
        return

    authorized_users.add(cid)
    update_user_stats(cid, username)
    
    # Get system stats
    stats = get_system_stats()
    
    welcome_msg = f"""
         𝗧𝗛𝗔𝗥𝗠𝗨𝗫 𝗕𝗢𝗧 v5
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

👋 Hello Admin, {first_name}!

──────────────────
📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗨𝗦
──────────────────
🖥️  CPU    : {stats['cpu_bar']}  {stats['cpu']:.1f}%
💾  Memory : {stats['memory_bar']}  {stats['memory']:.1f}%
💿  Disk   : {stats['disk_bar']}  {stats['disk']:.1f}%

━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 𝗔𝗩𝗔𝗜𝗟𝗔𝗕𝗟𝗘 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦:
• Type any Linux command directly
• Use buttons below for quick commands
• /nano filename - Edit files in browser
• /help - Show help
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
"""
    bot.send_message(cid, welcome_msg, 
                     parse_mode="Markdown", 
                     reply_markup=main_menu_keyboard(True))
    
    logger.info(f"Admin {cid} ({username}) started the bot")

@bot.message_handler(commands=["help"])
def help_cmd(m):
    cid = m.chat.id
    
    # 🔥 SIRF ADMINS 🔥
    if not is_admin(cid):
        bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗
╰━━━━━━━━━━━━━━━✦
""")
        logger.warning(f"UNAUTHORIZED ACCESS: User {cid} tried /help")
        return
    
    help_msg = """
    📚 𝗛𝗘𝗟𝗣 & 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬


        🖥️ 𝗕𝗔𝗦𝗜𝗖 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦
━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 𝚃𝚈𝙿𝙴 𝙰𝙽𝚈 𝙻𝙸𝙽𝚄𝚇 𝙲𝙾𝙼𝙼𝙰𝙽𝙳 𝙳𝙸𝚁𝙴𝙲𝚃𝙻𝚈
• 𝚄𝚂𝙴 𝙱𝚄𝚃𝚃𝙾𝙽𝚂 𝙵𝙾𝚁 𝚀𝚄𝙸𝙲𝙺 𝙲𝙾𝙼𝙼𝙰𝙽𝙳𝚂
• /start - 𝚁𝙴𝚂𝚃𝙰𝚁𝚃 𝙱𝙾𝚃
• /help - 𝚂𝙷𝙾𝚆 𝚃𝙷𝙸𝚂 𝙷𝙴𝙻𝙿

━━━━━━━━━━━━━━━━━━━━━━━━━━━
          📝 𝗙𝗜𝗟𝗘 𝗘𝗗𝗜𝗧𝗜𝗡𝗚
━━━━━━━━━━━━━━━━━━━━━━━━━━━
• /nano <filename> - 𝙴𝙳𝙸𝚃 𝙵𝙸𝙻𝙴𝚂 𝙸𝙽 𝙱𝚁𝙾𝚆𝚂𝙴𝚁
• 𝚅𝙸𝙴𝚆 𝙵𝙸𝙻𝙴𝚂 𝙸𝙽 𝚈𝙾𝚄𝚁 𝙿𝚁𝙸𝚅𝙰𝚃𝙴 𝙳𝙸𝚁𝙴𝙲𝚃𝙾𝚁𝚈
• 𝚂𝙰𝚅𝙴 𝙲𝙷𝙰𝙽𝙶𝙴𝚂 𝙵𝚁𝙾𝙼 𝚆𝙴𝙱 𝙸𝙽𝚃𝙴𝚁𝙵𝙰𝙲𝙴

━━━━━━━━━━━━━━━━━━━━━━━━━━━
         🔄 𝗔𝗨𝗧𝗢 𝗥𝗘𝗦𝗧𝗔𝗥𝗧
━━━━━━━━━━━━━━━━━━━━━━━━━━━
• /autorestart on - 𝙴𝙽𝙰𝙱𝙻𝙴 auto restart
• /autorestart off - 𝙳𝙸𝚂𝙰𝙱𝙻𝙴 auto restart
• /autorestart status - 𝙲𝙷𝙴𝙲𝙺 status

━━━━━━━━━━━━━━━━━━━━━━━━━━━
         📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗜𝗡𝗙𝗢
━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 𝚂𝚈𝚂𝚃𝙴𝙼 𝚂𝚃𝙰𝚃𝚂 - 𝚅𝙸𝙴𝚆 𝚂𝚈𝚂𝚃𝙴𝙼 𝚂𝚃𝙰𝚃𝚄𝚂
• 𝙼𝚈 𝙵𝙸𝙻𝙴𝚂 - 𝙻𝙸𝚂𝚃 𝚈𝙾𝚄𝚁 𝙵𝙸𝙻𝙴𝚂
• 𝙼𝚈 𝙸𝙽𝙵𝙾 - 𝚈𝙾𝚄𝚁 𝚄𝚂𝙴𝚁 𝙸𝙽𝙵𝙾
┏━━━━━━━━━━━━━━━━━━━━━━━━┓
        👑 ADMIN COMMANDS
┗━━━━━━━━━━━━━━━━━━━━━━━━┛
• /admin - 𝙾𝙿𝙴𝙽 𝙰𝙳𝙼𝙸𝙽 𝙿𝙰𝙽𝙴𝙻
• /status - 𝙳𝙴𝚃𝙰𝙸𝙻𝙴𝙳 𝚂𝚈𝚂𝚃𝙴𝙼 𝚂𝚃𝙰𝚃𝚄𝚂
• /sessions - 𝚅𝙸𝙴𝚆 𝙰𝙲𝚃𝙸𝚅𝙴 𝚂𝙴𝚂𝚂𝙸𝙾𝙽𝚂

▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
"""
    bot.send_message(cid, help_msg, parse_mode="Markdown")

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    cid = m.chat.id
    
    # 🔥 SIRF ADMINS 🔥
    if not is_admin(cid):
        bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗
╰━━━━━━━━━━━━━━━✦
""")
        logger.warning(f"UNAUTHORIZED ACCESS: User {cid} tried /admin")
        return
    
    bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🔐 𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟
╰━━━━━━━━━━━━━━━✦
""", parse_mode="Markdown", reply_markup=admin_keyboard())

@bot.message_handler(commands=["status"])
def status_cmd(m):
    cid = m.chat.id
    
    # 🔥 SIRF ADMINS 🔥
    if not is_admin(cid):
        bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗
╰━━━━━━━━━━━━━━━✦
""")
        logger.warning(f"UNAUTHORIZED ACCESS: User {cid} tried /status")
        return
    
    stats = get_system_stats()
    
    total_processes = sum(len(procs) for procs in processes.values())
    total_sessions = sum(len(sess) for sess in active_sessions.values())
    total_users = len(set(active_sessions.keys()) | set(processes.keys()))
    
    status_msg = f"""
 📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗨𝗦 𝗥𝗘𝗣𝗢𝗥𝗧 📊
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🖥️ 𝗛𝗔𝗥𝗗𝗪𝗔𝗥𝗘 𝗠𝗢𝗡𝗜𝗧𝗢𝗥
──────────────────
𝗖𝗣𝗨    : {stats['cpu_bar']}  {stats['cpu']:.1f}%
𝗠𝗘𝗠𝗢𝗥𝗬 : {stats['memory_bar']}  {stats['memory']:.1f}%
𝗗𝗜𝗦𝗞   : {stats['disk_bar']}  {stats['disk']:.1f}%

 [ ⏱️] 𝗨𝗣𝗧𝗜𝗠𝗘        : {stats['uptime']}
 [🔄] 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗘𝗦     : {stats['processes']}
 [🚀] 𝗕𝗢𝗢𝗧 𝗧𝗜𝗠𝗘      : {stats['boot_time']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
👥 𝗨𝗦𝗘𝗥 𝗦𝗧𝗔𝗧𝗜𝗦𝗧𝗜𝗖𝗦
──────────────────
• 𝗧𝗢𝗧𝗔𝗟 𝗔𝗗𝗠𝗜𝗡𝗦        : {len(admins)}
• 𝗔𝗖𝗧𝗜𝗩𝗘 𝗨𝗦𝗘𝗥𝗦        : {total_users}
• 𝗔𝗖𝗧𝗜𝗩𝗘 𝗦𝗘𝗦𝗦𝗜𝗢𝗡𝗦     : {total_sessions}
• 𝗥𝗨𝗡𝗡𝗜𝗡𝗚 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗘𝗦   : `{total_processes}`

▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
"""
    bot.send_message(cid, status_msg, parse_mode="Markdown")

@bot.message_handler(commands=["sessions"])
def sessions_cmd(m):
    cid = m.chat.id
    
    # 🔥 SIRF ADMINS 🔥
    if not is_admin(cid):
        bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗
╰━━━━━━━━━━━━━━━✦
""")
        logger.warning(f"UNAUTHORIZED ACCESS: User {cid} tried /sessions")
        return
    
    sessions_msg = "🔄 *ACTIVE SESSIONS*\n\n"
    has_sessions = False
    
    for user_id, sess_dict in active_sessions.items():
        if sess_dict:
            has_sessions = True
            sessions_msg += f"👤 User {user_id}:\n"
            for session_id, last_active in sess_dict.items():
                elapsed = int(time.time() - last_active)
                sessions_msg += f"  • `{session_id[:8]}`: {elapsed}s ago\n"
    
    if not has_sessions:
        sessions_msg += "📭 No active sessions"
    
    bot.send_message(cid, sessions_msg, parse_mode="Markdown")

# ========== STOP COMMAND FIXED ==========
@bot.message_handler(commands=["stop"])
def stop_cmd(m):
    cid = m.chat.id
    text = m.text.strip()
    
    # 🔥 SIRF ADMINS 🔥
    if not is_admin(cid):
        bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗
╰━━━━━━━━━━━━━━━✦
""")
        logger.warning(f"UNAUTHORIZED ACCESS: User {cid} tried /stop")
        return
    
    # Agar "/stop bot.py" type kiya hai
    if len(text.split()) > 1 and "bot.py" in text:
        # Sirf bot.py band karo
        proc_dict = get_user_dict(cid, processes)
        input_dict = get_user_dict(cid, input_wait)
        sess_dict = get_user_dict(cid, active_sessions)
        
        stopped = 0
        for session_id in list(proc_dict.keys()):
            pid, fd, _, cmd = proc_dict[session_id]
            if "bot.py" in cmd:
                try:
                    os.kill(pid, signal.SIGKILL)
                    stopped += 1
                    if session_id in proc_dict:
                        del proc_dict[session_id]
                    if session_id in input_dict:
                        del input_dict[session_id]
                    if session_id in sess_dict:
                        del sess_dict[session_id]
                    bot.send_message(cid, "✅ *bot.py Stopped*\nAuto restart disabled!", parse_mode="Markdown")
                except:
                    pass
        
        if stopped == 0:
            bot.send_message(cid, "❌ bot.py is not running!", parse_mode="Markdown")
    
    else:
        # Button se aaya hai - SABHI FILES BAND KARO
        proc_dict = get_user_dict(cid, processes)
        input_dict = get_user_dict(cid, input_wait)
        sess_dict = get_user_dict(cid, active_sessions)
        
        stopped = 0
        for session_id in list(proc_dict.keys()):
            try:
                pid, fd, _, _ = proc_dict[session_id]
                os.kill(pid, signal.SIGKILL)
                stopped += 1
            except:
                pass
            
            if session_id in proc_dict:
                del proc_dict[session_id]
            if session_id in input_dict:
                del input_dict[session_id]
            if session_id in sess_dict:
                del sess_dict[session_id]
        
        if stopped > 0:
            bot.send_message(cid, f"✅ Stopped {stopped} processes!")
            add_system_alert("INFO", f"Admin {cid} stopped {stopped} processes")
        else:
            bot.send_message(cid, "⚠️ No running processes.")

@bot.message_handler(commands=["nano"])
def nano_cmd(m):
    cid = m.chat.id
    
    # 🔥 SIRF ADMINS 🔥
    if not is_admin(cid):
        bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗
╰━━━━━━━━━━━━━━━✦
""")
        logger.warning(f"UNAUTHORIZED ACCESS: User {cid} tried /nano")
        return

    args = m.text.strip().split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(cid, "📝 *Usage:* `/nano <filename>`\nExample: `/nano script.py`", parse_mode="Markdown")
        return

    filename = args[1].strip()
    safe_path = sanitize_path(cid, filename)

    if not safe_path:
        bot.send_message(cid, "❌ Invalid filename or path traversal attempt!")
        return

    try:
        if not os.path.exists(safe_path):
            open(safe_path, 'w').close()
            bot.send_message(cid, f"✅ Created new file: `{filename}`", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(cid, f"❌ Error creating file: {e}")
        return
    
    sid = str(uuid.uuid4())

    edit_sessions[sid] = {
        "file": safe_path,
        "user_id": cid,
        "timestamp": time.time(),
        "filename": filename
    }

    # Clean old sessions
    current_time = time.time()
    for sess_id in list(edit_sessions.keys()):
        if current_time - edit_sessions[sess_id].get('timestamp', 0) > 3600:
            edit_sessions.pop(sess_id, None)

    BASE_URL = os.environ.get("BASE_URL", f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:10000')}")
    link = f"{BASE_URL}/edit/{sid}"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✏️ Edit in Browser", url=link),
        types.InlineKeyboardButton("📄 View Content", callback_data=f"view_{filename}"),
        types.InlineKeyboardButton("📁 Browse Directory", callback_data=f"browse_{os.path.dirname(filename) or '.'}")
    )

    bot.send_message(
        cid,
        f"📝 *EDIT FILE*\n\n"
        f"📄 *File:* `{filename}`\n"
        f"📁 *Path:* `{safe_path}`\n"
        f"📊 *Size:* {os.path.getsize(safe_path)} bytes\n"
        f"⏱️ *Modified:* {datetime.fromtimestamp(os.path.getmtime(safe_path)).strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.message_handler(commands=["autorestart"])
def autorestart_cmd(m):
    cid = m.chat.id
    
    # 🔥 SIRF ADMINS 🔥
    if not is_admin(cid):
        bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗
╰━━━━━━━━━━━━━━━✦
""")
        return
    
    args = m.text.strip().split()
    if len(args) < 2:
        bot.send_message(cid, "📝 *Usage:*\n`/autorestart on` - Enable\n`/autorestart off` - Disable\n`/autorestart status` - Check status", parse_mode="Markdown")
        return
    
    cmd = args[1].lower()
    
    # Initialize auto_restart setting if not exists
    if str(cid) not in user_stats:
        user_stats[str(cid)] = {}
    if 'auto_restart' not in user_stats[str(cid)]:
        user_stats[str(cid)]['auto_restart'] = False
    
    if cmd == "on":
        user_stats[str(cid)]['auto_restart'] = True
        save_data()
        bot.send_message(cid, "✅ *Auto Restart ENABLE!", parse_mode="Markdown")
    elif cmd == "off":
        user_stats[str(cid)]['auto_restart'] = False
        save_data()
        bot.send_message(cid, "❌ *Auto Restart DISABLED*", parse_mode="Markdown")
    elif cmd == "status":
        status = "✅ ON" if user_stats[str(cid)]['auto_restart'] else "❌ OFF"
        bot.send_message(cid, f"🔄 *Auto Restart Status:* {status}", parse_mode="Markdown")
    else:
        bot.send_message(cid, "❌ Invalid option! Use `on`, `off`, or `status`", parse_mode="Markdown")

# ══════════════════════════════════════════════════
# 📤 ZIP UPLOAD HANDLER (Telegram se ZIP bhejo)
# ══════════════════════════════════════════════════
@bot.message_handler(content_types=['document'])
def handle_document(m):
    cid = m.chat.id
    if not is_admin(cid):
        bot.send_message(cid, "╭━━━━━━━━━━━━━━━✦\n│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗\n╰━━━━━━━━━━━━━━━✦")
        return

    doc = m.document
    file_name = doc.file_name or "uploaded_file"

    # Sirf ZIP files accept karo
    if not file_name.lower().endswith('.zip'):
        bot.send_message(cid, "❌ Sirf `.zip` files upload karo!\n📦 Example: `myproject.zip`", parse_mode="Markdown")
        return

    # Size check — 10 MB max
    if doc.file_size > MAX_ZIP_SIZE:
        size_mb = doc.file_size / (1024 * 1024)
        bot.send_message(cid, f"❌ *File too large!*\n📦 Size: `{size_mb:.1f} MB`\n⚠️ Max allowed: `10 MB`", parse_mode="Markdown")
        return

    msg = bot.send_message(cid, f"📥 *ZIP Upload Ho Raha Hai...*\n📦 `{file_name}`\n📊 Size: `{doc.file_size / 1024:.1f} KB`", parse_mode="Markdown")

    try:
        user_dir = get_user_directory(cid)
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)

        zip_save_path = os.path.join(user_dir, file_name)
        with open(zip_save_path, 'wb') as f:
            f.write(downloaded)

        # ZIP contents list karo
        ok, members = unzip_file(zip_save_path, user_dir)

        if ok:
            member_list = "\n".join([f"  📄 `{m_}`" for m_ in members[:15]])
            extra = f"\n  ...aur {len(members) - 15} files" if len(members) > 15 else ""

            public_url = get_public_base_url()

            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📁 Files Dekho", callback_data="list_files"),
                types.InlineKeyboardButton("🌐 Public URL", url=public_url)
            )

            bot.edit_message_text(
                f"✅ *ZIP Extract Ho Gaya!*\n\n"
                f"📦 File: `{file_name}`\n"
                f"📂 Extract Path: `{user_dir}`\n"
                f"🗂️ Total Files: `{len(members)}`\n\n"
                f"*Files:*\n{member_list}{extra}\n\n"
                f"🌐 *Public URL:* `{public_url}`",
                cid, msg.message_id,
                parse_mode="Markdown",
                reply_markup=markup
            )
            add_system_alert("INFO", f"User {cid} uploaded ZIP: {file_name} ({len(members)} files)")
        else:
            bot.edit_message_text(f"⚠️ ZIP save hua lekin extract nahi hua:\n`{members}`", cid, msg.message_id, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"ZIP upload error: {e}")
        bot.edit_message_text(f"❌ Upload/Extract Error:\n`{str(e)[:200]}`", cid, msg.message_id, parse_mode="Markdown")


# ══════════════════════════════════════════════════
# 🌐 NGROK COMMAND
# ══════════════════════════════════════════════════
@bot.message_handler(commands=["cf", "cloudflared", "tunnel"])
def cf_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        bot.send_message(cid, "╭━━━━━━━━━━━━━━━✦\n│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗\n╰━━━━━━━━━━━━━━━✦")
        return
    args = m.text.strip().split()
    sub = args[1].lower() if len(args) > 1 else "status"

    if sub == "start":
        port = int(args[2]) if len(args) > 2 else 5000
        msg = bot.send_message(cid, f"🌐 *Cloudflared tunnel start ho raha hai...*\n⏳ Port: `{port}`\n_Thoda wait karo (10-15 sec)..._", parse_mode="Markdown")
        ok, result = start_cloudflared(port)
        if ok:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🌐 URL Kholo", url=result))
            bot.edit_message_text(
                f"✅ *Cloudflared Active!*\n\n"
                f"🔗 `{result}`\n\n"
                f"📋 Copy karke share karo!\n"
                f"🛑 Band karne ke liye: `/cf stop`",
                cid, msg.message_id,
                parse_mode="Markdown",
                reply_markup=markup
            )
            add_system_alert("INFO", f"Cloudflared started: {result}")
        else:
            bot.edit_message_text(
                f"❌ *Cloudflared Failed!*\n\n`{result}`",
                cid, msg.message_id,
                parse_mode="Markdown"
            )
    elif sub == "stop":
        ok = stop_cloudflared()
        bot.send_message(cid, "✅ *Cloudflared stopped!*" if ok else "❌ Cloudflared chal nahi raha tha.", parse_mode="Markdown")
    else:
        url = _cf_url or "Not running"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("▶️ Start (port 5000)", callback_data="cf_start_5000"),
            types.InlineKeyboardButton("🛑 Stop", callback_data="cf_stop")
        )
        bot.send_message(
            cid,
            f"🌐 *Cloudflared Status*\n\n"
            f"🔗 URL: `{url}`\n\n"
            f"`/cf start` — Port 5000 pe start\n"
            f"`/cf start 8080` — Custom port\n"
            f"`/cf stop` — Band karo",
            parse_mode="Markdown",
            reply_markup=markup
        )


# ══════════════════════════════════════════════════
# 📦 /INSTALL COMMAND (dependency installer)
# ══════════════════════════════════════════════════
@bot.message_handler(commands=["install"])
def install_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    args = m.text.strip().split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(cid, "📦 *Usage:* `/install <package>` ya `/install <file.py>`\nExample: `/install requests`", parse_mode="Markdown")
        return
    pkg = args[1].strip()
    # Agar .py file hai toh auto deps install karo
    if pkg.endswith('.py'):
        safe_path = sanitize_path(cid, pkg)
        if not safe_path or not os.path.exists(safe_path):
            bot.send_message(cid, f"❌ File not found: `{pkg}`", parse_mode="Markdown")
            return
        msg = bot.send_message(cid, f"🔍 Scanning `{pkg}` for dependencies...", parse_mode="Markdown")
        ok, result = auto_install_deps(safe_path, cid)
        bot.edit_message_text(f"📦 *Dependency Install Result:*\n\n{result}", cid, msg.message_id, parse_mode="Markdown")
    else:
        msg = bot.send_message(cid, f"📦 Installing `{pkg}`...", parse_mode="Markdown")
        try:
            r = subprocess.run(
                ['pip', 'install', pkg, '--break-system-packages'],
                capture_output=True, text=True, timeout=60
            )
            result = r.stdout[-1500:] if r.stdout else r.stderr[-1500:]
            status = "✅ Installed!" if r.returncode == 0 else "❌ Failed!"
            bot.edit_message_text(f"{status}\n```\n{result}\n```", cid, msg.message_id, parse_mode="Markdown")
        except Exception as e:
            bot.edit_message_text(f"❌ Error: `{e}`", cid, msg.message_id, parse_mode="Markdown")


@bot.message_handler(func=lambda m: True)
def handle_all_messages(m):
    """Handle ALL messages - text, buttons, everything"""
    cid = m.chat.id
    text = m.text.strip() if m.text else ""
    username = m.from_user.username or "Unknown"
    
    # 🔥 SIRF ADMINS 🔥
    if not is_admin(cid):
        access_denied_msg = """
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗥𝗘𝗦𝗧𝗥𝗜𝗖𝗧𝗘𝗗
╰━━━━━━━━━━━━━━━✦

🔒 ᴛʜɪs ʙᴏᴛ ɪs ᴍᴀᴅᴇ ғᴏʀ ᴀᴅᴍɪɴs ᴏɴʟʏ.

⚠️ ɪғ ʏᴏᴜ ᴡᴀɴᴛ ᴀᴄᴄᴇss  
📩 ᴘʟᴇᴀsᴇ ᴅᴍ ᴛʜᴇ ᴏᴡɴᴇʀ:

👤 @Felix_bhai

━━━━━━━━━━━━━━━━━━
🤖 ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ
━━━━━━━━━━━━━━━━━━
"""
        bot.send_message(cid, access_denied_msg)
        logger.warning(f"UNAUTHORIZED MESSAGE BLOCKED: User {cid} (@{username}) sent: {text[:50]}")
        return
    
    # Admin hai toh shell function call karo
    shell(m)

# ========== FIXED SHELL FUNCTION ==========
def shell(m):
    """Original shell function for admins only"""
    cid = m.chat.id
    text = m.text.strip()
    username = m.from_user.username or "Unknown"
    
    # Update user stats
    update_user_stats(cid, username)
    get_user_dict(cid, active_sessions)
    
    # Check for input waiting
    input_dict = get_user_dict(cid, input_wait)
    if input_dict:
        for session_id, fd in list(input_dict.items()):
            try:
                os.write(fd, (text + "\n").encode())
                del input_dict[session_id]
                return
            except Exception as e:
                logger.error(f"Error writing to input: {e}")
                del input_dict[session_id]
    
    # Quick command mappings
    quick_map = {
        "📁 ls -la": "ls -la",
        "📂 pwd": "pwd",
        "💿 df -h": "df -h",
        "📊 system stats": None,
        "📜 ps aux | head -20": "ps aux | head -20",
        "🗑️ clear": None,
        "🛑 stop": None,
        "📝 nano": None,
        "🔄 ping 8.8.8.8 -c 4": "ping -c 4 8.8.8.8",
        "🌐 ifconfig": "ifconfig || ip addr",
        "📁 my files": None,
        "ℹ️ my info": None,
        "👑 admin panel": None,
        "📈 performance": None,
        "📤 upload zip": None,
        "🌐 public url": None
    }
    
    if text in quick_map:
        if text == "🗑️ clear":
            bot.send_message(cid, "🗑️ Chat cleared (bot-side)")
            return
        elif text == "🛑 stop":
            stop_cmd(m)
            return
        elif text == "📝 nano":
            bot.send_message(cid, "📝 *Usage:* `/nano filename`\nExample: `/nano script.py`", parse_mode="Markdown")
            return
        elif text == "📊 system stats":
            stats = get_system_stats()
            stats_msg = f"""
      📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗜𝗦𝗧𝗜𝗖𝗦 📊
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🖥️  𝗖𝗣𝗨        : {stats['cpu_bar']}  {stats['cpu']:.1f}%
💾  𝗠𝗘𝗠𝗢𝗥𝗬     : {stats['memory_bar']}  {stats['memory']:.1f}%
💿  𝗗𝗜𝗦𝗞       : {stats['disk_bar']}  {stats['disk']:.1f}%

━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱️  𝗨𝗣𝗧𝗜𝗠𝗘      : {stats['uptime']}
🔄  𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗘𝗦   : {stats['processes']}
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
"""
            bot.send_message(cid, stats_msg, parse_mode="Markdown")
            return
        elif text == "📁 my files":
            user_dir = get_user_directory(cid)
            try:
                files = os.listdir(user_dir)
                if not files:
                    bot.send_message(cid, "📁 Your directory is empty.")
                else:
                    file_list = []
                    for f in files[:15]:
                        full_path = os.path.join(user_dir, f)
                        if os.path.isfile(full_path):
                            size = os.path.getsize(full_path)
                            modified = datetime.fromtimestamp(os.path.getmtime(full_path)).strftime("%H:%M %d/%m")
                            file_list.append(f"📄 {f} ({size} bytes) - {modified}")
                        else:
                            file_list.append(f"📁 {f}/")
                    
                    msg = "📁 *YOUR FILES*\n\n" + "\n".join(file_list)
                    if len(files) > 15:
                        msg += f"\n\n... and {len(files) - 15} more files"
                    
                    bot.send_message(cid, msg, parse_mode="Markdown")
            except Exception as e:
                bot.send_message(cid, f"❌ Error listing files: {e}")
            return
        elif text == "ℹ️ my info":
            user_dir = get_user_directory(cid)
            user_data = user_stats.get(str(cid), {})
            
            info_msg = f"""
╭━━━━━━━━━━━━━━━✦
│ ℹ️ 𝗨𝗦𝗘𝗥 𝗜𝗡𝗙𝗢
╰━━━━━━━━━━━━━━━✦

👤 ID: `{cid}`
📝 @{username}
📁 `{user_dir}`

📊 *Stats*
• Commands: {user_data.get('commands', 0)}
• First: {user_data.get('first_seen', 'N/A')[:10]}
• Last: {user_data.get('last_seen', 'N/A')[:10]}
━━━━━━━━━━━━━━━━━━━━━━
"""
            bot.send_message(cid, info_msg, parse_mode="Markdown")
            return
        elif text == "👑 admin panel":
            admin_panel(m)
            return
        elif text == "📈 performance":
            show_performance(cid)
            return
        elif text == "📤 upload zip":
            public_url = get_public_base_url()
            bot.send_message(
                cid,
                f"📤 *ZIP Upload Karo!*\n\n"
                f"1️⃣ Apni `.zip` file directly is chat mein bhejo\n"
                f"2️⃣ Max size: `10 MB`\n"
                f"3️⃣ Auto extract ho jayega `{get_user_directory(cid)}` mein\n\n"
                f"🌐 *Public URL:* `{public_url}`\n\n"
                f"_Bas file attach karo aur send karo!_ 📎",
                parse_mode="Markdown"
            )
            return
        elif text == "🌐 public url":
            public_url = get_public_base_url()
            bot.send_message(
                cid,
                f"🌐 *Public URL*\n\n`{public_url}`\n\n"
                f"📝 `/nano` se files edit karo\n"
                f"🌐 `/cf start` se tunnel banao",
                parse_mode="Markdown"
            )
            return
        else:
            text = quick_map[text]
    
    # 🔥 SIRF BOT.PY KE LIYE AUTO RESTART
    if ("python" in text and "bot.py" in text) or ("python3" in text and "bot.py" in text):
        bot.send_message(cid, f"🔄 *bot.py Started*\n```\n$ {text}\n```\n⏱️ 30 min baad auto restart on hoga\n🛑 Stop: `/stop bot.py`", parse_mode="Markdown")
        run_bot_py_with_monitor(text, cid, cid)
    else:
        # Baaki sab normal execute
        session_id = generate_session_id()
        bot.send_message(cid, f"```\n$ {text}\n```", parse_mode="Markdown")
        run_cmd(text, cid, cid, session_id)

def show_performance(cid):
    """Show performance metrics"""
    stats = get_system_stats()
    
    # Get process list
    processes_list = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            processes_list.append(proc.info)
        except:
            pass
    
    # Sort by CPU usage
    processes_list.sort(key=lambda x: x['cpu_percent'], reverse=True)
    
    perf_msg = f"""
    📈 𝗣𝗘𝗥𝗙𝗢𝗥𝗠𝗔𝗡𝗖𝗘 𝗠𝗘𝗧𝗥𝗜𝗖𝗦 📈
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
🖥️  𝗖𝗣𝗨
• 𝗨𝗦𝗔𝗚𝗘        : {stats['cpu']:.1f}%
• 𝗖𝗢𝗥𝗘𝗦        : {psutil.cpu_count()}

💾  𝗠𝗘𝗠𝗢𝗥𝗬
• 𝗧𝗢𝗧𝗔𝗟        : {psutil.virtual_memory().total / (1024**3):.1f} GB
• 𝗨𝗦𝗘𝗗         : {psutil.virtual_memory().used / (1024**3):.1f} GB
• 𝗔𝗩𝗔𝗜𝗟𝗔𝗕𝗟𝗘    : {psutil.virtual_memory().available / (1024**3):.1f} GB

💿  𝗗𝗜𝗦𝗞
• 𝗧𝗢𝗧𝗔𝗟        : {psutil.disk_usage('/').total / (1024**3):.1f} GB
• 𝗨𝗦𝗘𝗗         : {psutil.disk_usage('/').used / (1024**3):.1f} GB
• 𝗙𝗥𝗘𝗘         : {psutil.disk_usage('/').free / (1024**3):.1f} GB

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         🔝 𝗧𝗢𝗣 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗘𝗦
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    for proc in processes_list[:5]:
        perf_msg += f"• {proc['name']}: {proc['cpu_percent']:.1f}% CPU, {proc['memory_percent']:.1f}% MEM\n"
    
    bot.send_message(cid, perf_msg, parse_mode="Markdown")

# ========== CALLBACK HANDLERS ==========
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    cid = call.message.chat.id
    
    try:
        if call.data == "status":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            status_cmd(call.message)
            bot.answer_callback_query(call.id)
        
        elif call.data == "stop_all":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            stopped = 0
            for user_id, proc_dict in list(processes.items()):
                for session_id, (pid, fd, start_time, cmd) in list(proc_dict.items()):
                    try:
                        os.kill(pid, signal.SIGKILL)
                        stopped += 1
                    except:
                        pass
            
            processes.clear()
            input_wait.clear()
            active_sessions.clear()
            
            bot.answer_callback_query(call.id, f"✅ Stopped {stopped} processes")
            bot.send_message(cid, f"🛑 Stopped all {stopped} processes")
            add_system_alert("WARNING", f"Admin {cid} stopped all processes")
        
        elif call.data == "admin_list":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            admin_list_text = "\n".join([f"👤 `{a}`" for a in sorted(admins) if a != MAIN_ADMIN_ID])
            main_admin_text = f"👑 Main Admin: `{MAIN_ADMIN_ID}`"
            
            bot.answer_callback_query(call.id)
            bot.send_message(cid, f"*ADMIN LIST*\n\n{main_admin_text}\n\n*Other Admins:*\n{admin_list_text if admin_list_text else 'None'}", parse_mode="Markdown")
        
        elif call.data == "add_admin":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            msg = bot.send_message(cid, "Send the user ID to add as admin (numeric ID):")
            bot.register_next_step_handler(msg, add_admin_step)
            bot.answer_callback_query(call.id)
        
        elif call.data == "remove_admin":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            msg = bot.send_message(cid, "Send the user ID to remove from admins:")
            bot.register_next_step_handler(msg, remove_admin_step)
            bot.answer_callback_query(call.id)
        
        elif call.data == "list_files":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            
            try:
                user_dir = get_user_directory(cid)
                files = os.listdir(user_dir)
                if not files:
                    bot.send_message(cid, "📁 Directory is empty.")
                else:
                    file_list = []
                    for f in files[:20]:
                        full_path = os.path.join(user_dir, f)
                        if os.path.isfile(full_path):
                            size = os.path.getsize(full_path)
                            file_list.append(f"📄 {f} ({size} bytes)")
                        else:
                            file_list.append(f"📁 {f}/")
                    
                    msg = "*FILES IN YOUR DIRECTORY:*\n\n" + "\n".join(file_list)
                    if len(files) > 20:
                        msg += f"\n\n... and {len(files)-20} more"
                    
                    bot.send_message(cid, msg, parse_mode="Markdown")
            except Exception as e:
                bot.send_message(cid, f"❌ Error: {e}")
            bot.answer_callback_query(call.id)
        
        elif call.data == "clean_logs":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            current_time = time.time()
            cleaned_sessions = 0
            cleaned_processes = 0
            
            # Clean old sessions
            for user_id, sess_dict in list(active_sessions.items()):
                for session_id, last_active in list(sess_dict.items()):
                    if current_time - last_active > 3600:  # Older than 1 hour
                        del sess_dict[session_id]
                        cleaned_sessions += 1
            
            # Clean zombie processes
            for user_id, proc_dict in list(processes.items()):
                for session_id, (pid, fd, start_time, cmd) in list(proc_dict.items()):
                    try:
                        os.kill(pid, 0)  # Check if process exists
                    except OSError:
                        # Process doesn't exist, clean up
                        del proc_dict[session_id]
                        cleaned_processes += 1
            
            bot.answer_callback_query(call.id, f"✅ Cleaned {cleaned_sessions} sessions, {cleaned_processes} processes")
            bot.send_message(cid, f"🧹 *Cleanup Complete*\n\n• Removed {cleaned_sessions} stale sessions\n• Removed {cleaned_processes} zombie processes", parse_mode="Markdown")
        
        elif call.data == "user_stats":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            stats_msg = "*USER STATISTICS*\n\n"
            for user_id, data in user_stats.items():
                stats_msg += f"👤 User {user_id} (@{data.get('username', 'N/A')}):\n"
                stats_msg += f"  • Commands: {data.get('commands', 0)}\n"
                stats_msg += f"  • First seen: {data.get('first_seen', 'N/A')[:10]}\n"
                stats_msg += f"  • Last seen: {data.get('last_seen', 'N/A')[:10]}\n\n"
            
            bot.send_message(cid, stats_msg, parse_mode="Markdown")
            bot.answer_callback_query(call.id)
        
        elif call.data == "system_alerts":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            if not system_alerts:
                bot.send_message(cid, "✅ No system alerts")
            else:
                alerts_msg = "*SYSTEM ALERTS*\n\n"
                for alert in system_alerts[-10:]:  # Show last 10 alerts
                    emoji = "⚠️" if alert['type'] == "WARNING" else "ℹ️" if alert['type'] == "INFO" else "❌"
                    alerts_msg += f"{emoji} [{alert['time']}] {alert['message']}\n"
                
                bot.send_message(cid, alerts_msg, parse_mode="Markdown")
            bot.answer_callback_query(call.id)
        
        elif call.data == "performance":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            show_performance(cid)
            bot.answer_callback_query(call.id)
        
        elif call.data == "authorize_user":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            msg = bot.send_message(cid, "Send the user ID to authorize:")
            bot.register_next_step_handler(msg, authorize_user_step)
            bot.answer_callback_query(call.id)
        
        elif call.data == "deauthorize_user":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            msg = bot.send_message(cid, "Send the user ID to deauthorize:")
            bot.register_next_step_handler(msg, deauthorize_user_step)
            bot.answer_callback_query(call.id)
        
        elif call.data == "cf_start_5000":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            bot.answer_callback_query(call.id, "⏳ Cloudflared start ho raha hai...")
            ok, result = start_cloudflared(5000)
            if ok:
                bot.send_message(cid, f"✅ *Cloudflared Active!*\n🔗 `{result}`", parse_mode="Markdown")
            else:
                bot.send_message(cid, f"❌ Failed!\n`{result}`", parse_mode="Markdown")

        elif call.data == "cf_stop":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            ok = stop_cloudflared()
            bot.answer_callback_query(call.id, "✅ Stopped!" if ok else "❌ Not running")
            bot.send_message(cid, "✅ *Cloudflared stopped!*" if ok else "❌ Cloudflared chal nahi raha tha.", parse_mode="Markdown")

        elif call.data == "zip_guide":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            public_url = get_public_base_url()
            bot.send_message(
                cid,
                f"📤 *ZIP Upload Guide*\n\n"
                f"1️⃣ Apni `.zip` file is chat mein directly bhejo\n"
                f"2️⃣ Max allowed size: `10 MB`\n"
                f"3️⃣ Auto extract ho jayega tumhare folder mein\n\n"
                f"🌐 Public URL: `{public_url}`",
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif call.data == "public_url":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            public_url = get_public_base_url()
            ngrok_info = f"\n🔗 Cloudflared: `{_cf_url}`" if _cf_url else "\n🔗 Cloudflared: Not running"
            bot.send_message(
                cid,
                f"🌐 *Public URLs*\n\n"
                f"🖥️ Server: `{public_url}`{ngrok_info}\n\n"
                f"Bot Uptime: `{get_bot_uptime()}`\n"
                f"Public IP: `{get_public_ip()}`\n\n"
                f"🌐 Tunnel start karo: `/cf start`",
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif call.data.startswith("view_"):
            filename = call.data[5:]
            safe_path = sanitize_path(cid, filename)
            
            if not safe_path:
                bot.answer_callback_query(call.id, "❌ Invalid filename!")
                return
            
            try:
                if not os.path.exists(safe_path):
                    bot.answer_callback_query(call.id, "❌ File not found!")
                    return
                
                with open(safe_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(3500)  # Limit to 3500 chars
                
                if len(content) < 3500:
                    bot.send_message(cid, f"```\n{content}\n```", parse_mode="Markdown")
                else:
                    bot.send_message(cid, f"```\n{content}\n```", parse_mode="Markdown")
                    bot.send_message(cid, "📝 File truncated (max 3500 chars shown)")
                
                bot.answer_callback_query(call.id)
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ Error: {str(e)[:50]}")
        
        elif call.data.startswith("browse_"):
            path = call.data[7:]
            safe_path = sanitize_path(cid, path)
            
            if not safe_path:
                bot.answer_callback_query(call.id, "❌ Invalid path!")
                return
            
            try:
                if not os.path.exists(safe_path):
                    bot.answer_callback_query(call.id, "❌ Path not found!")
                    return
                
                if os.path.isfile(safe_path):
                    # Show file info
                    filename = os.path.basename(safe_path)
                    size = os.path.getsize(safe_path)
                    modified = datetime.fromtimestamp(os.path.getmtime(safe_path)).strftime('%Y-%m-%d %H:%M:%S')
                    
                    info_msg = f"""
╭━━━━━━━━━━━━━━━✦
│ 📄 𝗙𝗜𝗟𝗘 𝗜𝗡𝗙𝗢
╰━━━━━━━━━━━━━━━✦

📄 `{filename}`
📁 `{safe_path}`
📊 {size} bytes
⏱️ {modified}

⚡ /nano {filename}
👁️ view_{filename}
━━━━━━━━━━━━━━━━━━━━━━
"""
                    bot.send_message(cid, info_msg, parse_mode="Markdown")
                else:
                    # List directory
                    files = os.listdir(safe_path)
                    dir_msg = f"📁 *DIRECTORY: {path}*\n\n"
                    
                    for f in files[:15]:
                        full_path = os.path.join(safe_path, f)
                        if os.path.isfile(full_path):
                            size = os.path.getsize(full_path)
                            dir_msg += f"📄 {f} ({size} bytes)\n"
                        else:
                            dir_msg += f"📁 {f}/\n"
                    
                    if len(files) > 15:
                        dir_msg += f"\n... and {len(files)-15} more"
                    
                    bot.send_message(cid, dir_msg, parse_mode="Markdown")
                
                bot.answer_callback_query(call.id)
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ Error: {str(e)[:50]}")
    
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred")

# ========== ADMIN STEP HANDLERS ==========
def add_admin_step(m):
    cid = m.chat.id
    if str(cid) != str(MAIN_ADMIN_ID):
        return
    
    try:
        new_admin = int(m.text.strip())
        if new_admin in admins:
            bot.send_message(cid, f"❌ Admin {new_admin} already exists!")
        else:
            admins.add(new_admin)
            save_data()
            bot.send_message(cid, f"✅ Added admin: `{new_admin}`", parse_mode="Markdown")
            add_system_alert("INFO", f"Added new admin: {new_admin}")
    except ValueError:
        bot.send_message(cid, "❌ Invalid user ID. Please send numeric ID only.")
    except Exception as e:
        bot.send_message(cid, f"❌ Error: {e}")

def remove_admin_step(m):
    cid = m.chat.id
    if str(cid) != str(MAIN_ADMIN_ID):
        return
    
    try:
        admin_id = int(m.text.strip())
        
        if admin_id == MAIN_ADMIN_ID:
            bot.send_message(cid, "❌ Cannot remove the main admin.")
            return
        
        if admin_id in admins:
            admins.remove(admin_id)
            save_data()
            bot.send_message(cid, f"✅ Removed admin: `{admin_id}`", parse_mode="Markdown")
            add_system_alert("INFO", f"Removed admin: {admin_id}")
        else:
            bot.send_message(cid, f"❌ Admin ID `{admin_id}` not found.", parse_mode="Markdown")
    except ValueError:
        bot.send_message(cid, "❌ Invalid user ID. Please send numeric ID only.")
    except Exception as e:
        bot.send_message(cid, f"❌ Error: {e}")

def authorize_user_step(m):
    cid = m.chat.id
    if str(cid) != str(MAIN_ADMIN_ID):
        return
    
    try:
        user_id = int(m.text.strip())
        authorized_users.add(user_id)
        save_data()
        bot.send_message(cid, f"✅ Authorized user: `{user_id}`", parse_mode="Markdown")
        add_system_alert("INFO", f"Authorized user: {user_id}")
    except ValueError:
        bot.send_message(cid, "❌ Invalid user ID. Please send numeric ID only.")
    except Exception as e:
        bot.send_message(cid, f"❌ Error: {e}")

def deauthorize_user_step(m):
    cid = m.chat.id
    if str(cid) != str(MAIN_ADMIN_ID):
        return
    
    try:
        user_id = int(m.text.strip())
        if user_id in authorized_users:
            authorized_users.remove(user_id)
            save_data()
            bot.send_message(cid, f"✅ Deauthorized user: `{user_id}`", parse_mode="Markdown")
            add_system_alert("INFO", f"Deauthorized user: {user_id}")
        else:
            bot.send_message(cid, f"❌ User ID `{user_id}` not found.", parse_mode="Markdown")
    except ValueError:
        bot.send_message(cid, "❌ Invalid user ID. Please send numeric ID only.")
    except Exception as e:
        bot.send_message(cid, f"❌ Error: {e}")

# ========== WEB INTERFACE ==========

@app.route("/edit/<sid>", methods=["GET", "POST"])
def edit(sid):
    if sid not in edit_sessions:
        return """
        <html>
        <head>
            <title>Session Expired</title>
            <style>
                body { background: #0d1117; color: #c9d1d9; font-family: Arial; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
                .container { text-align: center; padding: 40px; border-radius: 10px; background: #161b22; }
                h2 { color: #f85149; }
            </style>
        </head>
        <body>
            <div class="container">
                <h2>❌ Invalid or expired session</h2>
                <p>Please generate a new edit link from Telegram</p>
            </div>
        </body>
        </html>
        """

    session_data = edit_sessions[sid]
    file = session_data.get("file")
    user_id = session_data.get("user_id")
    filename = session_data.get("filename", os.path.basename(file))
    
    # Security check
    user_dir = get_user_directory(user_id)
    abs_path = os.path.abspath(file)
    if not abs_path.startswith(os.path.abspath(user_dir)):
        return """
        <html>
        <body style="background:#111;color:#f00;padding:20px;">
        <h2>❌ Unauthorized file access</h2>
        </body>
        </html>
        """

    if request.method == "POST":
        try:
            code_content = request.form.get("code", "")
            with open(abs_path, "w", encoding='utf-8') as f:
                f.write(code_content)

            # Don't delete session immediately, keep for 5 minutes
            session_data['saved'] = True
            session_data['save_time'] = time.time()

            return """
            <html>
            <head>
                <title>File Saved</title>
                <style>
                    body { background: #0d1117; color: #c9d1d9; font-family: Arial; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
                    .container { text-align: center; padding: 40px; border-radius: 10px; background: #161b22; }
                    h2 { color: #3fb950; }
                    .success { color: #3fb950; font-size: 48px; margin-bottom: 20px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="success">✅</div>
                    <h2>File Saved Successfully!</h2>
                    <p>You can close this window and return to Telegram</p>
                </div>
            </body>
            </html>
            """
        except Exception as e:
            return f"""
            <html>
            <head>
                <title>Error</title>
                <style>
                    body {{ background: #0d1117; color: #c9d1d9; font-family: Arial; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
                    .container {{ text-align: center; padding: 40px; border-radius: 10px; background: #161b22; }}
                    h2 {{ color: #f85149; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h2>❌ Error saving file</h2>
                    <p>{e}</p>
                </div>
            </body>
            </html>
            """
            
    try:
        with open(abs_path, "r", encoding='utf-8', errors='ignore') as f:
            code = f.read()
    except Exception as e:
        code = f"# Error loading file: {e}\n# File may be binary or corrupted"

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Termux Pro IDE - {{ filename }}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.23.0/ace.js"></script>
    <style>
        :root {
            --bg-dark: #0d1117;
            --bg-card: #161b22;
            --accent: #58a6ff;
            --accent-success: #3fb950;
            --border: #30363d;
            --text: #c9d1d9;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body { 
            margin: 0; 
            background: var(--bg-dark); 
            color: var(--text); 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif; 
        }

        .header {
            background: var(--bg-card);
            padding: 12px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 18px;
            font-weight: 600;
        }

        .logo i {
            color: var(--accent);
            font-size: 24px;
        }

        .file-info {
            font-size: 14px;
            padding: 6px 16px;
            background: #0d1117;
            border-radius: 20px;
            color: var(--accent);
            border: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .file-info i {
            font-size: 14px;
        }

        #editor {
            width: 100%;
            height: calc(100vh - 130px);
            font-size: 14px;
        }

        .footer {
            padding: 12px 24px;
            background: var(--bg-card);
            border-top: 1px solid var(--border);
            display: flex;
            justify-content: flex-end;
            gap: 12px;
        }

        .btn {
            padding: 8px 24px;
            border-radius: 6px;
            font-weight: 500;
            cursor: pointer;
            transition: 0.2s;
            border: none;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn-save {
            background: #238636;
            color: white;
        }

        .btn-save:hover { 
            background: #2ea043;
            transform: translateY(-1px);
        }

        .btn-cancel {
            background: transparent;
            color: var(--text);
            border: 1px solid var(--border);
        }

        .btn-cancel:hover {
            background: rgba(255,255,255,0.1);
        }

        .status-bar {
            background: var(--bg-card);
            padding: 4px 24px;
            font-size: 12px;
            color: #8b949e;
            display: flex;
            gap: 24px;
            border-bottom: 1px solid var(--border);
        }

        .status-bar span i {
            margin-right: 6px;
            color: var(--accent);
        }

        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }

        .saving {
            animation: pulse 1s infinite;
        }
    </style>
</head>
<body>

<div class="header">
    <div class="logo">
        <i class="fas fa-terminal"></i>
        <span>Termux Pro IDE</span>
    </div>
    <div class="file-info">
        <i class="far fa-file-code"></i>
        {{ filename }}
        <i class="fas fa-circle" style="color: #3fb950; font-size: 8px; margin-left: 8px;"></i>
        <span style="color: var(--text);">Connected</span>
    </div>
</div>

<div class="status-bar">
    <span><i class="fas fa-code-branch"></i> Session: {{ sid[:8] }}</span>
    <span><i class="far fa-clock"></i> {{ timestamp }}</span>
    <span><i class="fas fa-hdd"></i> {{ file_size }}</span>
</div>

<div id="editor">{{ code }}</div>

<form id="saveForm" method="post">
    <input type="hidden" name="code" id="hiddenCode">
    <div class="footer">
        <button type="button" onclick="window.close()" class="btn btn-cancel">
            <i class="fas fa-times"></i> Cancel
        </button>
        <button type="button" onclick="saveData()" class="btn btn-save">
            <i class="fas fa-save"></i> Save Changes
        </button>
    </div>
</form>

<script>
    var editor = ace.edit("editor");
    editor.setTheme("ace/theme/one_dark");
    editor.setShowPrintMargin(false);
    editor.setFontSize(14);
    
    // Auto-detect language
    var filename = "{{ filename }}";
    var ext = filename.split('.').pop().toLowerCase();
    
    var modeMap = {
        'py': 'python',
        'js': 'javascript',
        'html': 'html',
        'css': 'css',
        'php': 'php',
        'json': 'json',
        'xml': 'xml',
        'md': 'markdown',
        'sh': 'sh',
        'bash': 'sh',
        'txt': 'text',
        'conf': 'text',
        'ini': 'text',
        'yml': 'yaml',
        'yaml': 'yaml',
        'c': 'c_cpp',
        'cpp': 'c_cpp',
        'h': 'c_cpp',
        'java': 'java',
        'rb': 'ruby',
        'go': 'golang',
        'rs': 'rust'
    };
    
    if(modeMap[ext]) {
        editor.session.setMode("ace/mode/" + modeMap[ext]);
    }

    editor.setOptions({
        enableBasicAutocompletion: true,
        enableLiveAutocompletion: true,
        showLineNumbers: true,
        tabSize: 4,
        useSoftTabs: true
    });

    function saveData() {
        var saveBtn = document.querySelector('.btn-save');
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
        saveBtn.disabled = true;
        
        document.getElementById('hiddenCode').value = editor.getValue();
        document.getElementById('saveForm').submit();
    }

    // Auto-save indicator
    var isSaving = false;
    editor.on('change', function() {
        if(!isSaving) {
            isSaving = true;
            setTimeout(function() {
                isSaving = false;
            }, 1000);
        }
    });

    // Keyboard shortcut: Ctrl+S
    editor.commands.addCommand({
        name: 'save',
        bindKey: {win: 'Ctrl-S', mac: 'Command-S'},
        exec: function() {
            saveData();
        }
    });
</script>

</body>
</html>
""", code=code, file=file, filename=filename, sid=sid, 
           timestamp=datetime.now().strftime("%H:%M:%S"),
           file_size=f"{os.path.getsize(abs_path)} bytes")

@app.route('/')
def home():
    stats = get_system_stats()
    
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>THARMUX BOT v5| System Monitor</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{ 
            background: #0a0c0f; 
            min-height: 100vh; 
            display: flex; 
            justify-content: center; 
            align-items: center; 
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            position: relative;
            overflow-x: hidden;
        }}

        .particles {{
            position: absolute;
            width: 100%;
            height: 100%;
            background: radial-gradient(circle at 20% 50%, rgba(0, 212, 255, 0.05) 0%, transparent 50%),
                        radial-gradient(circle at 80% 80%, rgba(0, 255, 136, 0.05) 0%, transparent 50%);
            z-index: 1;
        }}

        .container {{
            position: relative;
            z-index: 10;
            max-width: 800px;
            width: 90%;
            padding: 30px;
        }}

        .status-card {{
            background: rgba(22, 27, 34, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 30px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
            border: 1px solid rgba(255,255,255,0.05);
        }}

        .header {{
            text-align: center;
            margin-bottom: 40px;
        }}

        .bot-icon {{
            width: 100px;
            height: 100px;
            margin: 0 auto 20px;
            background: linear-gradient(135deg, #00d4ff, #0066ff);
            border-radius: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 50px;
            color: white;
            box-shadow: 0 10px 30px rgba(0, 212, 255, 0.3);
            animation: float 3s ease-in-out infinite;
        }}

        @keyframes float {{
            0%, 100% {{ transform: translateY(0px); }}
            50% {{ transform: translateY(-10px); }}
        }}

        h1 {{
            color: white;
            font-size: 32px;
            font-weight: 600;
            letter-spacing: 1px;
            margin-bottom: 5px;
        }}

        .status-badge {{
            display: inline-block;
            padding: 8px 20px;
            background: rgba(0, 212, 255, 0.1);
            border: 1px solid rgba(0, 212, 255, 0.3);
            border-radius: 50px;
            color: #00d4ff;
            font-size: 14px;
            font-weight: 500;
            margin-top: 10px;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            margin: 40px 0;
        }}

        .stat-item {{
            background: rgba(255,255,255,0.03);
            border-radius: 20px;
            padding: 25px 20px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.05);
            transition: 0.3s;
        }}

        .stat-item:hover {{
            transform: translateY(-5px);
            background: rgba(255,255,255,0.05);
            border-color: rgba(0, 212, 255, 0.2);
        }}

        .stat-icon {{
            font-size: 30px;
            color: #00d4ff;
            margin-bottom: 15px;
        }}

        .stat-label {{
            color: #8b949e;
            font-size: 14px;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .stat-value {{
            color: white;
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 10px;
        }}

        .progress-bar {{
            width: 100%;
            height: 6px;
            background: rgba(255,255,255,0.1);
            border-radius: 3px;
            overflow: hidden;
            margin-top: 10px;
        }}

        .progress-fill {{
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s;
        }}

        .progress-fill.cpu {{ background: linear-gradient(90deg, #00d4ff, #0066ff); }}
        .progress-fill.memory {{ background: linear-gradient(90deg, #00ff88, #00cc66); }}
        .progress-fill.disk {{ background: linear-gradient(90deg, #ff6b6b, #ff4757); }}

        .info-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin: 30px 0;
        }}

        .info-item {{
            padding: 15px;
            background: rgba(255,255,255,0.02);
            border-radius: 15px;
            border: 1px solid rgba(255,255,255,0.05);
        }}

        .info-label {{
            color: #8b949e;
            font-size: 13px;
            margin-bottom: 5px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .info-value {{
            color: white;
            font-size: 16px;
            font-weight: 500;
        }}

        .btn-telegram {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            background: linear-gradient(135deg, #00d4ff, #0066ff);
            color: white;
            border: none;
            padding: 16px 40px;
            border-radius: 50px;
            text-decoration: none;
            font-size: 16px;
            font-weight: 600;
            transition: 0.3s;
            width: 100%;
            margin-top: 30px;
            box-shadow: 0 10px 20px rgba(0, 212, 255, 0.2);
        }}

        .btn-telegram:hover {{
            transform: translateY(-2px);
            box-shadow: 0 15px 30px rgba(0, 212, 255, 0.3);
        }}

        .footer {{
            margin-top: 30px;
            text-align: center;
            color: #484f58;
            font-size: 13px;
        }}

        .footer a {{
            color: #00d4ff;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <div class="particles"></div>
    
    <div class="container">
        <div class="status-card">
            <div class="header">
                <div class="bot-icon">
                    <i class="fas fa-robot"></i>
                </div>
                <h1>THARMUX BOT v5</h1>
                <div class="status-badge">
                    <i class="fas fa-circle" style="color: #3fb950; font-size: 10px;"></i>
                    SYSTEM ONLINE
                </div>
            </div>

            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-icon">
                        <i class="fas fa-microchip"></i>
                    </div>
                    <div class="stat-label">CPU</div>
                    <div class="stat-value">{stats['cpu']:.1f}%</div>
                    <div class="progress-bar">
                        <div class="progress-fill cpu" style="width: {stats['cpu']}%"></div>
                    </div>
                </div>

                <div class="stat-item">
                    <div class="stat-icon">
                        <i class="fas fa-memory"></i>
                    </div>
                    <div class="stat-label">MEMORY</div>
                    <div class="stat-value">{stats['memory']:.1f}%</div>
                    <div class="progress-bar">
                        <div class="progress-fill memory" style="width: {stats['memory']}%"></div>
                    </div>
                </div>

                <div class="stat-item">
                    <div class="stat-icon">
                        <i class="fas fa-hdd"></i>
                    </div>
                    <div class="stat-label">DISK</div>
                    <div class="stat-value">{stats['disk']:.1f}%</div>
                    <div class="progress-bar">
                        <div class="progress-fill disk" style="width: {stats['disk']}%"></div>
                    </div>
                </div>
            </div>

            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">
                        <i class="fas fa-clock" style="color: #00d4ff;"></i>
                        Uptime
                    </div>
                    <div class="info-value">{stats['uptime']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">
                        <i class="fas fa-tasks" style="color: #00ff88;"></i>
                        Processes
                    </div>
                    <div class="info-value">{stats['processes']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">
                        <i class="fas fa-users" style="color: #ff6b6b;"></i>
                        Active Users
                    </div>
                    <div class="info-value">{len(set(active_sessions.keys()) | set(processes.keys()))}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">
                        <i class="fas fa-code-branch" style="color: #ffd700;"></i>
                        Sessions
                    </div>
                    <div class="info-value">{sum(len(sess) for sess in active_sessions.values())}</div>
                </div>
            </div>

            <a href="https://t.me/Advancesvouts_bot" class="btn-telegram" target="_blank">
                <i class="fab fa-telegram-plane"></i>
                OPEN TELEGRAM BOT
            </a>

            <div style="margin-top: 20px; background: rgba(255,255,255,0.03); border-radius: 20px; padding: 25px; border: 1px solid rgba(255,255,255,0.05);">
                <div style="color: #8b949e; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 15px;">
                    <i class="fas fa-upload" style="color: #00d4ff; margin-right: 8px;"></i>ZIP UPLOAD
                </div>
                <form id="zipUploadForm" enctype="multipart/form-data" style="display:flex; flex-direction:column; gap:12px;">
                    <input type="file" id="zipFileInput" accept=".zip" style="
                        background: rgba(255,255,255,0.05);
                        border: 1px dashed rgba(0,212,255,0.4);
                        border-radius: 12px;
                        color: #c9d1d9;
                        padding: 12px;
                        cursor: pointer;
                        font-size: 14px;
                    ">
                    <div style="color: #8b949e; font-size: 12px;">⚠️ Max size: 10 MB | Only .zip files</div>
                    <button type="button" onclick="uploadZip()" style="
                        background: linear-gradient(135deg, #00d4ff, #0066ff);
                        color: white;
                        border: none;
                        padding: 12px 24px;
                        border-radius: 12px;
                        font-weight: 600;
                        cursor: pointer;
                        font-size: 14px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        gap: 8px;
                    ">
                        <i class="fas fa-cloud-upload-alt"></i> Upload ZIP
                    </button>
                    <div id="uploadStatus" style="color: #3fb950; font-size: 13px; text-align: center; display:none;"></div>
                </form>
            </div>

            <div style="margin-top: 15px; background: rgba(255,255,255,0.03); border-radius: 20px; padding: 20px; border: 1px solid rgba(255,255,255,0.05);">
                <div style="color: #8b949e; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px;">
                    <i class="fas fa-globe" style="color: #00ff88; margin-right: 8px;"></i>PUBLIC URL
                </div>
                <div style="color: white; font-size: 14px; word-break: break-all; background: rgba(0,0,0,0.3); padding: 10px 15px; border-radius: 10px; font-family: monospace;">
                    {get_public_base_url()}
                </div>
            </div>

            <script>
            async function uploadZip() {{
                const fileInput = document.getElementById('zipFileInput');
                const status = document.getElementById('uploadStatus');
                const file = fileInput.files[0];
                if (!file) {{ alert('Pehle ZIP file select karo!'); return; }}
                if (!file.name.endsWith('.zip')) {{ alert('Sirf .zip files allowed hain!'); return; }}
                if (file.size > 10 * 1024 * 1024) {{ alert('File 10 MB se badi hai!'); return; }}
                const formData = new FormData();
                formData.append('file', file);
                status.style.display = 'block';
                status.style.color = '#00d4ff';
                status.textContent = '⏳ Uploading...';
                try {{
                    const res = await fetch('/upload_zip', {{ method: 'POST', body: formData }});
                    const data = await res.json();
                    if (data.success) {{
                        status.style.color = '#3fb950';
                        status.textContent = '✅ ' + data.message;
                    }} else {{
                        status.style.color = '#f85149';
                        status.textContent = '❌ ' + data.message;
                    }}
                }} catch(e) {{
                    status.style.color = '#f85149';
                    status.textContent = '❌ Upload failed: ' + e.message;
                }}
            }}
            </script>

            <div class="footer">
                <p>⚡ System is fully operational | Secure Shell Access via Telegram</p>
                <p style="margin-top: 10px;">
                    <a href="#"><i class="fab fa-github"></i></a>
                    <a href="#" style="margin-left: 15px;"><i class="fas fa-shield-alt"></i></a>
                </p>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/upload_zip', methods=['POST'])
def flask_upload_zip():
    """Web dashboard se ZIP upload karo"""
    try:
        from flask import request as freq
        if 'file' not in freq.files:
            return jsonify({'success': False, 'message': 'Koi file nahi mili!'})
        file = freq.files['file']
        if not file.filename.endswith('.zip'):
            return jsonify({'success': False, 'message': 'Sirf .zip files allowed hain!'})

        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
        if size > MAX_ZIP_SIZE:
            return jsonify({'success': False, 'message': f'File too large! Max 10 MB. Your file: {size/(1024*1024):.1f} MB'})

        # Admin user directory use karo (MAIN_ADMIN_ID)
        save_dir = get_user_directory(MAIN_ADMIN_ID)
        zip_path = os.path.join(save_dir, file.filename)
        file.save(zip_path)

        ok, members = unzip_file(zip_path, save_dir)
        if ok:
            return jsonify({'success': True, 'message': f'{file.filename} extract hua! {len(members)} files milein.'})
        else:
            return jsonify({'success': False, 'message': f'Save hua lekin extract nahi hua: {members}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)[:200]})


@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'stats': get_system_stats()
    })

@app.route('/api/stats')
def api_stats():
    """API endpoint for stats"""
    stats = get_system_stats()
    stats.update({
        'active_users': len(set(active_sessions.keys()) | set(processes.keys())),
        'active_sessions': sum(len(sess) for sess in active_sessions.values()),
        'total_admins': len(admins),
        'edit_sessions': len(edit_sessions)
    })
    return jsonify(stats)

# ========== MAIN ==========
if __name__ == "__main__":
    print("🤖 Starting THARMUX v5.0...")
    print(f"👑 Main Admin: {MAIN_ADMIN_ID}")
    print(f"📁 Base Directory: {BASE_DIR}")
    print(f"📁 User Data Directory: {USER_DATA_DIR}")
    print(f"🌐 Web Interface: http://0.0.0.0:{PORT}")
    print(f"📝 Log File: {os.path.join(BASE_DIR, 'logs', LOG_FILE)}")

    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Please set your BOT_TOKEN in environment variables!")
        exit(1)

    if not MAIN_ADMIN_ID:
        print("❌ ERROR: MAIN_ADMIN_ID environment variable not set!")
        exit(1)

    # Load saved data
    load_data()

    # ========== FLASK SERVER ==========
    def run_flask():
        try:
            print(f"🚀 Starting Flask server on port {PORT}...")
            app.run(
                host="0.0.0.0",
                port=PORT,
                debug=False,
                use_reloader=False,
                threaded=True
            )
        except Exception as e:
            logger.error(f"⚠️ Flask server error: {e}")
            time.sleep(5)
            run_flask()

    # ========== TELEGRAM BOT ==========
    def run_bot():
        print("🤖 Starting Telegram bot...")
        while True:
            try:
                logger.info("Bot polling started")
                bot.infinity_polling(
                    timeout=60,
                    long_polling_timeout=60,
                    skip_pending=True
                )
            except Exception as e:
                logger.error(f"⚠️ Bot error: {e}")
                add_system_alert("ERROR", f"Bot connection error: {str(e)[:80]}")
                time.sleep(5)

    # ========== START THREADS ==========
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    bot_thread = threading.Thread(target=run_bot, daemon=True)

    flask_thread.start()
    bot_thread.start()

    add_system_alert("INFO", "Bot started successfully")

    # ========== AUTO START CLOUDFLARED ==========
    def auto_cf():
        time.sleep(5)  # Bot ke start hone ka wait karo
        logger.info("Auto-starting Cloudflared tunnel on port 5000...")
        ok, result = start_cloudflared(5000)
        if ok:
            logger.info(f"Cloudflared URL: {result}")
            try:
                bot.send_message(MAIN_ADMIN_ID,
                    f"🌐 *Cloudflared Auto-Started!*\n\n"
                    f"🔗 `{result}`\n\n"
                    f"_Bot start hote hi tunnel ready hai!_",
                    parse_mode="Markdown"
                )
            except:
                pass
        else:
            logger.warning(f"Cloudflared auto-start failed: {result}")

    cf_thread = threading.Thread(target=auto_cf, daemon=True)
    cf_thread.start()

    # ========== MONITOR LOOP ==========
    try:
        while True:
            time.sleep(60)

            # Clean old edit sessions
            current_time = time.time()
            for sid in list(edit_sessions.keys()):
                if current_time - edit_sessions[sid].get('timestamp', 0) > 3600:
                    edit_sessions.pop(sid, None)

            stats = get_system_stats()
            logger.info(
                f"System status - CPU: {stats['cpu']:.1f}%, "
                f"Memory: {stats['memory']:.1f}%, "
                f"Disk: {stats['disk']:.1f}%"
            )

            if stats['cpu'] > 80:
                add_system_alert("WARNING", f"High CPU usage: {stats['cpu']:.1f}%")
            if stats['memory'] > 80:
                add_system_alert("WARNING", f"High memory usage: {stats['memory']:.1f}%")
            if stats['disk'] > 90:
                add_system_alert("WARNING", f"Low disk space: {stats['disk']:.1f}%")

    except KeyboardInterrupt:
        print("\n👋 Shutting down gracefully...")
        save_data()
        logger.info("Bot shutdown complete")
