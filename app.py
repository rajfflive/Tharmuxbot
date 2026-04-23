# ==============================================
# Project: Rajfflive Bot Pro
# Owner: @rajfflive
# Bot: @rtmxbot
# Version: 6.0 - MongoDB Fixed
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
import logging
import re
import zipfile as _zipfile
from logging.handlers import RotatingFileHandler

# ========== MONGODB SETUP ==========
try:
    from pymongo import MongoClient
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False
    print("⚠️ pymongo not installed, installing...")
    os.system("pip install pymongo -q")
    from pymongo import MongoClient
    MONGO_AVAILABLE = True

# ========== CONFIGURATION (Render Environment Variables) ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MAIN_ADMIN_ID = int(os.environ.get("MAIN_ADMIN_ID", 8154922225))
PORT = int(os.environ.get("PORT", 10000))
BASE_DIR = os.getcwd()
USER_DATA_DIR = os.path.join(BASE_DIR, "user_data")
LOG_FILE = "bot.log"

# MongoDB Configuration (Free MongoDB Atlas)
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://rajfflive:rajfflive123@cluster0.xkjjy.mongodb.net/?retryWrites=true&w=majority")
DB_NAME = os.environ.get("DB_NAME", "rajfflive_bot")

# Bot Info
BOT_USERNAME = "@rtmxrobot"
OWNER_NAME = "~𝐑𝐀𝐉 !! 🪬"
BOT_NAME = "TERMUX BOT"

# Create directories
os.makedirs(USER_DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

# ========== LOGGING SETUP ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            os.path.join(BASE_DIR, "logs", LOG_FILE),
            maxBytes=5*1024*1024,
            backupCount=3
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== CONNECT TO MONGODB ==========
MONGO_ENABLED = False
mongo_client = None
db = None
users_col = None
admins_col = None
stats_col = None
sessions_col = None
alerts_col = None

try:
    logger.info(f"Connecting to MongoDB: {DB_NAME}")
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    mongo_client.admin.command('ping')
    db = mongo_client[DB_NAME]
    
    # Create collections
    users_col = db.users
    admins_col = db.admins
    stats_col = db.stats
    sessions_col = db.sessions
    alerts_col = db.alerts
    
    # Create indexes
    users_col.create_index("user_id", unique=True)
    admins_col.create_index("user_id", unique=True)
    sessions_col.create_index("session_id", unique=True)
    stats_col.create_index("timestamp")
    
    MONGO_ENABLED = True
    logger.info("✅ MongoDB connected successfully!")
    
    # Save main admin to MongoDB
    admins_col.update_one(
        {"user_id": MAIN_ADMIN_ID},
        {"$set": {"username": "rajfflive", "role": "owner", "added_at": datetime.now()}},
        upsert=True
    )
except Exception as e:
    logger.error(f"❌ MongoDB connection failed: {e}")
    logger.info("⚠️ Continuing with file-based storage...")
    MONGO_ENABLED = False

print("🔧 Configuration loaded:")
print(f"   PORT: {PORT}")
print(f"   BOT_TOKEN: {'Yes' if BOT_TOKEN else 'No'}")
print(f"   MAIN_ADMIN_ID: {MAIN_ADMIN_ID}")
print(f"   MongoDB: {'Enabled' if MONGO_ENABLED else 'Disabled'}")
print(f"   Owner: {OWNER_NAME}")
print(f"   Bot: {BOT_USERNAME}")

# ========== INITIALIZE BOT ==========
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== DATA STRUCTURES ==========
edit_sessions = {}
processes = {}
input_wait = {}
active_sessions = {}
admins = set()
user_stats = {}
authorized_users = set()
system_alerts = []
MAX_ALERTS = 50

# ========== MONGODB HELPER FUNCTIONS ==========
def mongo_save_user(user_id, username, first_name=None):
    if not MONGO_ENABLED:
        return False
    try:
        users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "username": username,
                    "first_name": first_name,
                    "last_seen": datetime.now()
                },
                "$setOnInsert": {
                    "first_seen": datetime.now(),
                    "commands": 0
                }
            },
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Mongo save user error: {e}")
        return False

def mongo_update_stats(user_id, command):
    if not MONGO_ENABLED:
        return False
    try:
        users_col.update_one(
            {"user_id": user_id},
            {
                "$inc": {"commands": 1},
                "$set": {"last_command": command[:100], "last_active": datetime.now()}
            }
        )
        stats_col.insert_one({
            "user_id": user_id,
            "command": command[:100],
            "timestamp": datetime.now()
        })
        return True
    except Exception as e:
        logger.error(f"Mongo update stats error: {e}")
        return False

def mongo_save_session(session_id, user_id, command):
    if not MONGO_ENABLED:
        return False
    try:
        sessions_col.insert_one({
            "session_id": session_id,
            "user_id": user_id,
            "command": command[:200],
            "start_time": datetime.now(),
            "status": "active"
        })
        return True
    except Exception as e:
        logger.error(f"Mongo save session error: {e}")
        return False

def mongo_update_session(session_id, status, output=None):
    if not MONGO_ENABLED:
        return False
    try:
        update_data = {"status": status, "end_time": datetime.now()}
        if output:
            update_data["output"] = output[:1000]
        sessions_col.update_one({"session_id": session_id}, {"$set": update_data})
        return True
    except Exception as e:
        logger.error(f"Mongo update session error: {e}")
        return False

def mongo_save_alert(alert_type, message, user_id=None):
    if not MONGO_ENABLED:
        system_alerts.append({
            'type': alert_type,
            'message': message,
            'time': datetime.now().strftime("%H:%M:%S")
        })
        if len(system_alerts) > MAX_ALERTS:
            system_alerts.pop(0)
        return False
    try:
        alerts_col.insert_one({
            "type": alert_type,
            "message": message,
            "user_id": user_id,
            "timestamp": datetime.now()
        })
        alerts_col.delete_many({"timestamp": {"$lt": datetime.now() - timedelta(days=7)}})
        return True
    except Exception as e:
        logger.error(f"Mongo save alert error: {e}")
        return False

def mongo_get_users(limit=100):
    if not MONGO_ENABLED:
        return user_stats
    try:
        users = {}
        for user in users_col.find().limit(limit):
            users[str(user["user_id"])] = {
                "username": user.get("username", "Unknown"),
                "commands": user.get("commands", 0),
                "first_seen": user.get("first_seen", datetime.now()).isoformat(),
                "last_seen": user.get("last_seen", datetime.now()).isoformat()
            }
        return users
    except Exception as e:
        logger.error(f"Mongo get users error: {e}")
        return user_stats

def mongo_get_admins():
    if not MONGO_ENABLED:
        return admins
    try:
        admin_list = set()
        for admin in admins_col.find():
            admin_list.add(admin["user_id"])
        if MAIN_ADMIN_ID not in admin_list:
            admin_list.add(MAIN_ADMIN_ID)
        return admin_list
    except Exception as e:
        logger.error(f"Mongo get admins error: {e}")
        return admins

def mongo_save_admin(user_id, username=None):
    if not MONGO_ENABLED:
        admins.add(user_id)
        return True
    try:
        admins_col.update_one(
            {"user_id": user_id},
            {"$set": {"username": username, "added_at": datetime.now()}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Mongo save admin error: {e}")
        return False

def mongo_remove_admin(user_id):
    if not MONGO_ENABLED:
        admins.discard(user_id)
        return True
    try:
        admins_col.delete_one({"user_id": user_id})
        return True
    except Exception as e:
        logger.error(f"Mongo remove admin error: {e}")
        return False

def mongo_get_stats():
    if not MONGO_ENABLED:
        return {}
    try:
        total_users = users_col.count_documents({})
        total_commands = stats_col.count_documents({})
        active_sessions = sessions_col.count_documents({"status": "active"})
        total_admins = admins_col.count_documents({})
        return {
            "total_users": total_users,
            "total_commands": total_commands,
            "active_sessions": active_sessions,
            "total_admins": total_admins
        }
    except Exception as e:
        logger.error(f"Mongo get stats error: {e}")
        return {}

# ========== DATA LOAD/SAVE ==========
def load_data():
    global admins, user_stats, authorized_users
    
    if MONGO_ENABLED:
        admin_set = mongo_get_admins()
        if admin_set:
            admins = admin_set
        else:
            admins = {MAIN_ADMIN_ID}
            mongo_save_admin(MAIN_ADMIN_ID)
        
        user_stats.update(mongo_get_users())
        logger.info(f"Data loaded from MongoDB. Admins: {len(admins)}, Users: {len(user_stats)}")
    else:
        try:
            DATA_FILE = "bot_data.json"
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f:
                    data = json.load(f)
                    admins = set(data.get('admins', []))
                    user_stats = data.get('user_stats', {})
                    authorized_users = set(data.get('authorized_users', []))
            admins.add(MAIN_ADMIN_ID)
            logger.info(f"Data loaded from file. Admins: {len(admins)}")
        except Exception as e:
            logger.error(f"Load data failed: {e}")
            admins = {MAIN_ADMIN_ID}
            user_stats = {}
            authorized_users = set()

def save_data():
    if MONGO_ENABLED:
        return
    try:
        DATA_FILE = "bot_data.json"
        data = {
            'admins': list(admins),
            'user_stats': user_stats,
            'authorized_users': list(authorized_users)
        }
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info("Data saved to file")
    except Exception as e:
        logger.error(f"Save data failed: {e}")

# ========== HELPER FUNCTIONS ==========
def get_user_directory(user_id):
    path = os.path.join(USER_DATA_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

def is_admin(user_id):
    return str(user_id) == str(MAIN_ADMIN_ID) or user_id in admins

def is_authorized(user_id):
    return is_admin(user_id)

def sanitize_path(user_id, path):
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
    if user_id not in dict_obj:
        dict_obj[user_id] = {}
    return dict_obj[user_id]

def generate_session_id():
    return str(uuid.uuid4())

def get_system_stats():
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_bars = int(cpu_percent / 10)
        cpu_bar = "▒" * cpu_bars + "░" * (10 - cpu_bars)
        
        memory = psutil.virtual_memory()
        mem_percent = memory.percent
        mem_bars = int(mem_percent / 10)
        mem_bar = "▒" * mem_bars + "░" * (10 - mem_bars)
        
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_bars = int(disk_percent / 10)
        disk_bar = "▒" * disk_bars + "░" * (10 - disk_bars)
        
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        
        return {
            'cpu': cpu_percent,
            'cpu_bar': cpu_bar,
            'memory': mem_percent,
            'memory_bar': mem_bar,
            'disk': disk_percent,
            'disk_bar': disk_bar,
            'uptime': str(uptime).split('.')[0],
            'processes': len(psutil.pids()),
            'boot_time': boot_time.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {
            'cpu': 0, 'cpu_bar': "░"*10,
            'memory': 0, 'memory_bar': "░"*10,
            'disk': 0, 'disk_bar': "░"*10,
            'uptime': "N/A", 'processes': 0, 'boot_time': "N/A"
        }

def add_system_alert(alert_type, message, user_id=None):
    mongo_save_alert(alert_type, message, user_id)
    system_alerts.append({
        'type': alert_type,
        'message': message,
        'time': datetime.now().strftime("%H:%M:%S")
    })
    if len(system_alerts) > MAX_ALERTS:
        system_alerts.pop(0)

def update_user_stats(user_id, username, command=None):
    user_id_str = str(user_id)
    
    if MONGO_ENABLED:
        mongo_save_user(user_id, username)
        if command:
            mongo_update_stats(user_id, command)
    
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
    
    if not MONGO_ENABLED:
        save_data()

def run_cmd(cmd, user_id, chat_id, session_id):
    def task():
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
                proc_dict[session_id] = (pid, fd, datetime.now().strftime("%H:%M:%S"), cmd)
                sess_dict[session_id] = time.time()
                
                mongo_save_session(session_id, user_id, cmd)

                try:
                    while True:
                        rlist, _, _ = select.select([fd], [], [], 0.1)
                        if fd in rlist:
                            try:
                                out = os.read(fd, 1024).decode(errors="ignore")
                            except OSError:
                                break
                            if out:
                                for i in range(0, len(out), 3500):
                                    try:
                                        bot.send_message(chat_id, f"```\n{out[i:i+3500]}\n```", parse_mode="Markdown")
                                    except:
                                        pass
                            if out.strip().endswith(":"):
                                input_dict[session_id] = fd
                        try:
                            os.kill(pid, 0)
                        except OSError:
                            break
                        time.sleep(0.1)
                except Exception as e:
                    logger.error(f"Command error: {e}")
                finally:
                    mongo_update_session(session_id, "completed")
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
            try:
                bot.send_message(chat_id, f"❌ Error: {str(e)[:200]}")
            except:
                pass
    threading.Thread(target=task, daemon=True).start()

# ========== KEYBOARDS ==========
def main_menu_keyboard(is_admin_user=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "📁 ls -la", "📂 pwd", "💿 df -h", "📊 system stats",
        "📝 nano", "🛑 stop", "🗑️ clear", "📁 my files",
        "ℹ️ my info", "📜 ps aux", "🌐 ifconfig",
        "🔄 ping google.com -c 2", "📤 upload zip"
    ]
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
        types.InlineKeyboardButton("📊 User Stats", callback_data="user_stats"),
        types.InlineKeyboardButton("📈 Performance", callback_data="performance"),
        types.InlineKeyboardButton("📤 ZIP Guide", callback_data="zip_guide"),
        types.InlineKeyboardButton("🌐 Public URL", callback_data="public_url")
    )
    return markup

# ========== MESSAGE HANDLERS ==========
@bot.message_handler(commands=["start"])
def start(m):
    cid = m.chat.id
    username = m.from_user.username or "Unknown"
    first_name = m.from_user.first_name or "User"
    
    if not is_admin(cid):
        bot.send_message(cid, f"""
╭━━━━━━━━━━━━━━━✦
│ 🚫 𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗
╰━━━━━━━━━━━━━━━✦

🔒 This bot is private.

👑 Owner: {OWNER_NAME}
🤖 Bot: {BOT_USERNAME}

━━━━━━━━━━━━━━━━━━━━━━
""")
        return

    authorized_users.add(cid)
    update_user_stats(cid, username, "/start")
    stats = get_system_stats()
    mongo_stats = mongo_get_stats() if MONGO_ENABLED else {}
    
    welcome_msg = f"""
    𝗥𝗔𝗝𝗙𝗙𝗟𝗜𝗩𝗘 𝗕𝗢𝗧
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

👋 Hello {first_name}!

──────────────────
📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗨𝗦
──────────────────
🖥️  CPU    : {stats['cpu_bar']}  {stats['cpu']:.1f}%
💾  Memory : {stats['memory_bar']}  {stats['memory']:.1f}%
💿  Disk   : {stats['disk_bar']}  {stats['disk']:.1f}%

━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 Type any Linux command
📝 /nano filename - Edit files

👑 Owner: {OWNER_NAME}
🤖 Bot: {BOT_USERNAME}
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
"""
    bot.send_message(cid, welcome_msg, parse_mode="Markdown", reply_markup=main_menu_keyboard(True))

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    cid = m.chat.id
    if not is_admin(cid):
        bot.send_message(cid, "🚫 Unauthorized")
        return
    bot.send_message(cid, "🔐 Admin Panel", reply_markup=admin_keyboard())

@bot.message_handler(commands=["status"])
def status_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    
    stats = get_system_stats()
    mongo_stats = mongo_get_stats() if MONGO_ENABLED else {}
    total_processes = sum(len(procs) for procs in processes.values())
    total_sessions = sum(len(sess) for sess in active_sessions.values())
    total_users = len(set(active_sessions.keys()) | set(processes.keys()))
    
    status_msg = f"""
📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗨𝗦
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🖥️ CPU    : {stats['cpu_bar']} {stats['cpu']:.1f}%
💾 Memory : {stats['memory_bar']} {stats['memory']:.1f}%
💿 Disk   : {stats['disk_bar']} {stats['disk']:.1f}%

⏱️ Uptime: {stats['uptime']}
🔄 Processes: {stats['processes']}

👥 USERS
• Admins: {len(admins)}
• Active: {total_users}
• Sessions: {total_sessions}

📊 DATABASE
• MongoDB: {'✅ Connected' if MONGO_ENABLED else '❌ Disabled'}
• Total Users: {mongo_stats.get('total_users', 0)}
• Total Commands: {mongo_stats.get('total_commands', 0)}

👑 Owner: {OWNER_NAME}
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
"""
    bot.send_message(cid, status_msg, parse_mode="Markdown")

@bot.message_handler(commands=["stop"])
def stop_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    
    proc_dict = get_user_dict(cid, processes)
    stopped = 0
    for session_id in list(proc_dict.keys()):
        try:
            pid, fd, _, _ = proc_dict[session_id]
            os.kill(pid, signal.SIGKILL)
            stopped += 1
        except:
            pass
        del proc_dict[session_id]
    
    if stopped > 0:
        bot.send_message(cid, f"✅ Stopped {stopped} processes!")
    else:
        bot.send_message(cid, "⚠️ No running processes.")

@bot.message_handler(commands=["nano"])
def nano_cmd(m):
    cid = m.chat.id
    if not is_admin(cid):
        return

    args = m.text.strip().split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(cid, "📝 Usage: `/nano filename`", parse_mode="Markdown")
        return

    filename = args[1].strip()
    safe_path = sanitize_path(cid, filename)
    if not safe_path:
        bot.send_message(cid, "❌ Invalid filename!")
        return

    try:
        if not os.path.exists(safe_path):
            open(safe_path, 'w').close()
            bot.send_message(cid, f"✅ Created: `{filename}`", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(cid, f"❌ Error: {e}")
        return
    
    sid = str(uuid.uuid4())
    edit_sessions[sid] = {
        "file": safe_path,
        "user_id": cid,
        "timestamp": time.time(),
        "filename": filename
    }
    
    BASE_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', f'localhost:{PORT}')}"
    link = f"{BASE_URL}/edit/{sid}"
    
    bot.send_message(cid, f"📝 Edit file: `{filename}`\n✏️ [Click here]({link})", parse_mode="Markdown")

@bot.message_handler(content_types=['document'])
def handle_document(m):
    cid = m.chat.id
    if not is_admin(cid):
        return

    doc = m.document
    file_name = doc.file_name or "uploaded.zip"
    
    if not file_name.lower().endswith('.zip'):
        bot.send_message(cid, "❌ Only .zip files allowed!")
        return
    
    MAX_ZIP_SIZE = 10 * 1024 * 1024
    if doc.file_size > MAX_ZIP_SIZE:
        bot.send_message(cid, f"❌ File too large! Max 10MB")
        return

    msg = bot.send_message(cid, f"📥 Uploading `{file_name}`...", parse_mode="Markdown")

    try:
        user_dir = get_user_directory(cid)
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        zip_path = os.path.join(user_dir, file_name)
        with open(zip_path, 'wb') as f:
            f.write(downloaded)
        
        with _zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(user_dir)
            members = zf.namelist()
        
        bot.edit_message_text(
            f"✅ Extracted!\n📦 {file_name}\n📂 {len(members)} files",
            cid, msg.message_id
        )
        add_system_alert("INFO", f"Uploaded ZIP: {file_name}")
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", cid, msg.message_id)

@bot.message_handler(func=lambda m: True)
def handle_all(m):
    cid = m.chat.id
    if not is_admin(cid):
        return
    
    text = m.text.strip()
    username = m.from_user.username or "Unknown"
    
    update_user_stats(cid, username, text[:50])
    
    # Check input waiting
    input_dict = get_user_dict(cid, input_wait)
    if input_dict:
        for session_id, fd in list(input_dict.items()):
            try:
                os.write(fd, (text + "\n").encode())
                del input_dict[session_id]
                return
            except:
                del input_dict[session_id]
    
    # Quick buttons
    quick_map = {
        "📁 ls -la": "ls -la",
        "📂 pwd": "pwd",
        "💿 df -h": "df -h",
        "📊 system stats": None,
        "📜 ps aux": "ps aux | head -20",
        "🗑️ clear": None,
        "🛑 stop": None,
        "📝 nano": None,
        "🔄 ping google.com -c 2": "ping -c 2 google.com",
        "🌐 ifconfig": "ifconfig || ip addr",
        "📁 my files": None,
        "ℹ️ my info": None,
        "👑 admin panel": None,
        "📈 performance": None,
        "📤 upload zip": None
    }
    
    if text in quick_map:
        if text == "🗑️ clear":
            bot.send_message(cid, "Cleared")
            return
        elif text == "🛑 stop":
            stop_cmd(m)
            return
        elif text == "📝 nano":
            bot.send_message(cid, "Use /nano filename")
            return
        elif text == "📊 system stats":
            status_cmd(m)
            return
        elif text == "📁 my files":
            user_dir = get_user_directory(cid)
            try:
                files = os.listdir(user_dir)
                if not files:
                    bot.send_message(cid, "Empty directory")
                else:
                    file_list = []
                    for f in files[:15]:
                        full_path = os.path.join(user_dir, f)
                        if os.path.isfile(full_path):
                            size = os.path.getsize(full_path)
                            file_list.append(f"📄 {f} ({size} bytes)")
                        else:
                            file_list.append(f"📁 {f}/")
                    bot.send_message(cid, "📁 Your files:\n" + "\n".join(file_list))
            except Exception as e:
                bot.send_message(cid, f"Error: {e}")
            return
        elif text == "ℹ️ my info":
            user_dir = get_user_directory(cid)
            user_data = user_stats.get(str(cid), {})
            info_msg = f"""
👤 ID: `{cid}`
📝 @{username}
📁 `{user_dir}`
📊 Commands: {user_data.get('commands', 0)}
👑 Owner: {OWNER_NAME}
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
            bot.send_message(cid, "Send a .zip file directly (max 10MB)")
            return
        else:
            text = quick_map[text]
    
    # Execute command
    session_id = generate_session_id()
    bot.send_message(cid, f"```\n$ {text}\n```", parse_mode="Markdown")
    run_cmd(text, cid, cid, session_id)

def show_performance(cid):
    stats = get_system_stats()
    perf_msg = f"""
📈 PERFORMANCE
▬▬▬▬▬▬▬▬▬▬▬▬▬
CPU: {stats['cpu']:.1f}%
Memory: {stats['memory']:.1f}%
Disk: {stats['disk']:.1f}%
Uptime: {stats['uptime']}
Processes: {stats['processes']}
"""
    bot.send_message(cid, perf_msg)

# ========== CALLBACK HANDLERS ==========
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    cid = call.message.chat.id
    
    try:
        if not is_admin(cid):
            bot.answer_callback_query(call.id, "Unauthorized")
            return
        
        if call.data == "status":
            status_cmd(call.message)
        elif call.data == "stop_all":
            for user_id, proc_dict in list(processes.items()):
                for session_id, (pid, fd, _, _) in list(proc_dict.items()):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except:
                        pass
            processes.clear()
            input_wait.clear()
            active_sessions.clear()
            bot.send_message(cid, "✅ Stopped all processes")
        elif call.data == "admin_list":
            admin_list = "\n".join([f"👤 {a}" for a in sorted(admins) if a != MAIN_ADMIN_ID])
            bot.send_message(cid, f"👑 Main Admin: {MAIN_ADMIN_ID}\n\nOther Admins:\n{admin_list or 'None'}")
        elif call.data == "add_admin":
            msg = bot.send_message(cid, "Send user ID to add as admin:")
            bot.register_next_step_handler(msg, add_admin_step)
        elif call.data == "remove_admin":
            msg = bot.send_message(cid, "Send user ID to remove:")
            bot.register_next_step_handler(msg, remove_admin_step)
        elif call.data == "list_files":
            user_dir = get_user_directory(cid)
            files = os.listdir(user_dir)
            if files:
                bot.send_message(cid, "📁 Files:\n" + "\n".join(f"• {f}" for f in files[:20]))
            else:
                bot.send_message(cid, "Empty directory")
        elif call.data == "user_stats":
            if MONGO_ENABLED:
                stats_msg = "*User Stats (MongoDB)*\n"
                for uid, data in mongo_get_users().items():
                    stats_msg += f"👤 {uid} (@{data.get('username','?')}): {data.get('commands',0)} commands\n"
            else:
                stats_msg = "*User Stats (File)*\n"
                for uid, data in user_stats.items():
                    stats_msg += f"👤 {uid} (@{data.get('username','?')}): {data.get('commands',0)} commands\n"
            bot.send_message(cid, stats_msg, parse_mode="Markdown")
        elif call.data == "performance":
            show_performance(cid)
        elif call.data == "public_url":
            url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}"
            bot.send_message(cid, f"🌐 Public URL: {url}")
        elif call.data == "zip_guide":
            bot.send_message(cid, "📤 Send a .zip file directly (max 10MB)")
        
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Callback error: {e}")

def add_admin_step(m):
    cid = m.chat.id
    if cid != MAIN_ADMIN_ID:
        return
    try:
        uid = int(m.text.strip())
        if uid in admins:
            bot.send_message(cid, f"❌ Admin {uid} already exists!")
        else:
            admins.add(uid)
            mongo_save_admin(uid, m.from_user.username if m.from_user else "Unknown")
            save_data()
            bot.send_message(cid, f"✅ Admin {uid} added")
            add_system_alert("INFO", f"Added admin: {uid}")
    except:
        bot.send_message(cid, "Invalid ID")

def remove_admin_step(m):
    cid = m.chat.id
    if cid != MAIN_ADMIN_ID:
        return
    try:
        uid = int(m.text.strip())
        if uid == MAIN_ADMIN_ID:
            bot.send_message(cid, "❌ Cannot remove main admin!")
            return
        if uid in admins:
            admins.remove(uid)
            mongo_remove_admin(uid)
            save_data()
            bot.send_message(cid, f"✅ Removed {uid}")
            add_system_alert("INFO", f"Removed admin: {uid}")
        else:
            bot.send_message(cid, "Not an admin")
    except:
        bot.send_message(cid, "Invalid ID")

# ========== WEB INTERFACE ==========
@app.route("/edit/<sid>", methods=["GET", "POST"])
def edit(sid):
    if sid not in edit_sessions:
        return "Session expired", 404
    
    sess = edit_sessions[sid]
    filepath = sess['file']
    filename = sess.get('filename', os.path.basename(filepath))
    
    if request.method == "POST":
        try:
            content = request.form.get("code", "")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return """
            <html><body style="background:#0d1117;color:#fff;text-align:center;padding:50px;">
            <h2>✅ File Saved!</h2>
            <p>You can close this window</p>
            </body></html>
            """
        except Exception as e:
            return f"❌ Error: {e}"
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except:
        content = ""
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Edit {filename}</title>
    <style>
        body {{ margin:0; background:#0d1117; color:#c9d1d9; font-family:monospace; }}
        .header {{ background:#161b22; padding:10px 20px; border-bottom:1px solid #30363d; }}
        textarea {{ width:100%; height:calc(100vh - 100px); background:#0d1117; color:#c9d1d9; border:none; padding:20px; font-size:14px; }}
        button {{ background:#238636; color:white; padding:10px 24px; border:none; border-radius:6px; cursor:pointer; margin:10px; }}
    </style>
    </head>
    <body>
        <div class="header"><strong>✏️ Editing: {filename}</strong></div>
        <form method="post">
            <textarea name="code">{content}</textarea>
            <div style="text-align:center;"><button type="submit">💾 Save File</button></div>
        </form>
    </body>
    </html>
    """

@app.route('/')
def home():
    stats = get_system_stats()
    mongo_stats = mongo_get_stats() if MONGO_ENABLED else {}
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Rajfflive Bot Pro</title>
        <style>
            body {{ background: linear-gradient(135deg, #0a0c0f, #0d1117); color:#c9d1d9; font-family:Arial; display:flex; justify-content:center; align-items:center; height:100vh; text-align:center; }}
            .card {{ background:rgba(22,27,34,0.95); border-radius:30px; padding:40px; max-width:500px; }}
            h1 {{ color:#00d4ff; }}
            .badge {{ background:#238636; display:inline-block; padding:5px 15px; border-radius:50px; font-size:12px; }}
            .stats {{ margin:20px 0; text-align:left; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🤖 Rajfflive Bot Pro</h1>
            <div class="badge">✅ ONLINE</div>
            <div class="stats">
                <p>CPU: {stats['cpu']:.1f}% | Memory: {stats['memory']:.1f}%</p>
                <p>Uptime: {stats['uptime']}</p>
                <p>MongoDB: {'✅ Connected' if MONGO_ENABLED else '❌ Disabled'}</p>
                <p>Users: {mongo_stats.get('total_users', 0)}</p>
            </div>
            <p>👑 Owner: {OWNER_NAME}</p>
            <p>🤖 Bot: {BOT_USERNAME}</p>
        </div>
    </body>
    </html>
    """

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "owner": "rajfflive",
        "bot": "rtmxbot",
        "mongodb": MONGO_ENABLED,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/stats')
def api_stats():
    stats = get_system_stats()
    mongo_stats = mongo_get_stats() if MONGO_ENABLED else {}
    stats.update(mongo_stats)
    stats.update({
        "owner": "rajfflive",
        "bot": "rtmxbot",
        "mongodb": MONGO_ENABLED
    })
    return jsonify(stats)

# ========== FIX 409 ERROR ==========
print("\n🔧 Fixing 409 Conflict Error...")
try:
    temp_bot = telebot.TeleBot(BOT_TOKEN)
    temp_bot.remove_webhook()
    print("✅ Webhook removed")
    time.sleep(2)
    
    updates = temp_bot.get_updates(offset=-1, timeout=1, limit=1)
    print(f"✅ Cleared {len(updates)} pending updates")
    time.sleep(1)
except Exception as e:
    print(f"⚠️ {e}")

# ========== MAIN ==========
if __name__ == "__main__":
    print("="*50)
    print(f"🤖 {BOT_NAME}")
    print(f"👑 Owner: {OWNER_NAME}")
    print(f"🤖 Bot: {BOT_USERNAME}")
    print(f"🌐 Port: {PORT}")
    print(f"📊 MongoDB: {'✅ Connected' if MONGO_ENABLED else '❌ Disabled'}")
    print("="*50)
    
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN not set!")
        exit(1)
    
    load_data()
    
    # Flask thread
    def run_flask():
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Bot thread
    def run_bot():
        print("🤖 Starting bot polling...")
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                logger.error(f"Bot error: {e}")
                time.sleep(5)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    add_system_alert("INFO", f"{BOT_NAME} started successfully")
    
    try:
        while True:
            time.sleep(60)
            current_time = time.time()
            for sid in list(edit_sessions.keys()):
                if current_time - edit_sessions[sid].get('timestamp', 0) > 3600:
                    edit_sessions.pop(sid, None)
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        save_data()
        if mongo_client:
            mongo_client.close()
