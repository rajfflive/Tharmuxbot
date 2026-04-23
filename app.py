# ==============================================
# Project: Rajfflive Bot Pro
# Owner: @rajfflive
# Bot: @rtmxbot
# Version: 6.0 - MongoDB Integrated
# Description:
#   Advanced Telegram remote shell & file editor bot
#   with MongoDB database support
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
from pymongo import MongoClient
from bson.objectid import ObjectId
import urllib.parse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ========== CONFIGURATION (Private via Environment) ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")  # Set in environment!
MAIN_ADMIN_ID = int(os.environ.get("MAIN_ADMIN_ID", 8154922225))
PORT = int(os.environ.get("PORT", 10000))
BASE_DIR = os.getcwd()
USER_DATA_DIR = os.path.join(BASE_DIR, "user_data")
LOG_FILE = "bot.log"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB
BACKUP_COUNT = 3

# Bot Info
BOT_USERNAME = "@rtmxrobot"
OWNER_NAME = "~𝐑𝐀𝐉 !! 🪬"
BOT_NAME = "TERMUX BOT"

# ========== MONGODB CONFIGURATION ==========
MONGO_URI = os.environ.get("MONGO_URI", "")
DB_NAME = os.environ.get("DB_NAME", "rajfflive_bot")
MONGO_ENABLED = False

# Collections
users_col = None
admins_col = None
stats_col = None
sessions_col = None
alerts_col = None

# Try to connect to MongoDB
if MONGO_URI:
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()  # Test connection
        db = mongo_client[DB_NAME]
        
        # Initialize collections
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
        print("✅ MongoDB connected successfully!")
        print(f"   Database: {DB_NAME}")
    except Exception as e:
        print(f"⚠️ MongoDB connection failed: {e}")
        print("   Continuing with file-based storage...")
        MONGO_ENABLED = False

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
print(f"   BOT_TOKEN present: {'Yes' if BOT_TOKEN else 'No'}")
print(f"   MAIN_ADMIN_ID: {MAIN_ADMIN_ID}")
print(f"   BOT_USERNAME: {BOT_USERNAME}")
print(f"   OWNER_NAME: {OWNER_NAME}")
print(f"   USER_DATA_DIR: {USER_DATA_DIR}")
print(f"   MongoDB: {'Enabled' if MONGO_ENABLED else 'Disabled (using file storage)'}")

# ========== INITIALIZE BOT ==========
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== DATA STRUCTURES (Fallback) ==========
edit_sessions = {}
processes = {}
input_wait = {}
active_sessions = {}
admins = set()
user_stats = {}
system_alerts = []
MAX_ALERTS = 50
authorized_users = set()

# ========== MONGODB HELPER FUNCTIONS ==========
def mongo_save_user(user_id, username, first_name=None):
    """Save user to MongoDB"""
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
    """Update user command stats"""
    if not MONGO_ENABLED:
        return False
    try:
        users_col.update_one(
            {"user_id": user_id},
            {
                "$inc": {"commands": 1},
                "$set": {"last_command": command, "last_active": datetime.now()}
            }
        )
        
        # Save to stats collection
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
    """Save session to MongoDB"""
    if not MONGO_ENABLED:
        return False
    try:
        sessions_col.insert_one({
            "session_id": session_id,
            "user_id": user_id,
            "command": command,
            "start_time": datetime.now(),
            "status": "active"
        })
        return True
    except Exception as e:
        logger.error(f"Mongo save session error: {e}")
        return False

def mongo_update_session(session_id, status, output=None):
    """Update session status"""
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
    """Save system alert to MongoDB"""
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
        # Keep only last 100 alerts
        alerts_col.delete_many({"timestamp": {"$lt": datetime.now() - timedelta(days=7)}})
        return True
    except Exception as e:
        logger.error(f"Mongo save alert error: {e}")
        return False

def mongo_get_users(limit=100):
    """Get users from MongoDB"""
    if not MONGO_ENABLED:
        return {}
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
        return {}

def mongo_get_admins():
    """Get admins from MongoDB"""
    if not MONGO_ENABLED:
        return admins
    try:
        admin_list = set()
        for admin in admins_col.find():
            admin_list.add(admin["user_id"])
        return admin_list
    except Exception as e:
        logger.error(f"Mongo get admins error: {e}")
        return admins

def mongo_save_admin(user_id):
    """Save admin to MongoDB"""
    if not MONGO_ENABLED:
        admins.add(user_id)
        return True
    try:
        admins_col.update_one(
            {"user_id": user_id},
            {"$set": {"added_at": datetime.now()}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Mongo save admin error: {e}")
        return False

def mongo_remove_admin(user_id):
    """Remove admin from MongoDB"""
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
    """Get system stats from MongoDB"""
    if not MONGO_ENABLED:
        return {}
    try:
        total_users = users_col.count_documents({})
        total_commands = stats_col.count_documents({})
        active_sessions = sessions_col.count_documents({"status": "active"})
        return {
            "total_users": total_users,
            "total_commands": total_commands,
            "active_sessions": active_sessions
        }
    except Exception as e:
        logger.error(f"Mongo get stats error: {e}")
        return {}

# ========== DATA LOAD/SAVE (with MongoDB fallback) ==========
def load_data():
    """Load bot data from MongoDB or file"""
    global admins, user_stats, authorized_users
    
    if MONGO_ENABLED:
        # Load from MongoDB
        admin_set = mongo_get_admins()
        if admin_set:
            admins = admin_set
        else:
            admins = {MAIN_ADMIN_ID}
            mongo_save_admin(MAIN_ADMIN_ID)
        
        user_stats.update(mongo_get_users())
        logger.info(f"Data loaded from MongoDB. Admins: {len(admins)}, Users: {len(user_stats)}")
    else:
        # Fallback to file storage
        try:
            DATA_FILE = "bot_data.json"
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f:
                    data = json.load(f)
                    admins = set(data.get('admins', []))
                    user_stats = data.get('user_stats', {})
                    authorized_users = set(data.get('authorized_users', []))
            admins.add(MAIN_ADMIN_ID)
            logger.info(f"Data loaded from file. Admins: {len(admins)}, Users: {len(user_stats)}")
        except Exception as e:
            logger.error(f"⚠️ Load data failed: {e}")
            admins = {MAIN_ADMIN_ID}
            user_stats = {}
            authorized_users = set()

def save_data():
    """Save bot data (fallback for file storage)"""
    if MONGO_ENABLED:
        # MongoDB auto-saves, no need for this
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
        logger.info("Data saved to file successfully")
    except Exception as e:
        logger.error(f"⚠️ Save data failed: {e}")

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
    return is_admin(user_id)

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

def add_system_alert(alert_type, message, user_id=None):
    """Add system alert (MongoDB or memory)"""
    mongo_save_alert(alert_type, message, user_id)
    
    # Also keep in memory for quick access
    system_alerts.append({
        'type': alert_type,
        'message': message,
        'time': datetime.now().strftime("%H:%M:%S")
    })
    if len(system_alerts) > MAX_ALERTS:
        system_alerts.pop(0)

def update_user_stats(user_id, username, command=None):
    """Update user statistics"""
    user_id_str = str(user_id)
    
    if MONGO_ENABLED:
        mongo_save_user(user_id, username, None)
        if command:
            mongo_update_stats(user_id, command)
    
    # Update local stats
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
                os.execvp("bash", ["bash", "-c", cmd])
            else:
                # Parent process
                start_time = datetime.now().strftime("%H:%M:%S")
                proc_dict[session_id] = (pid, fd, start_time, cmd)
                sess_dict[session_id] = time.time()
                
                # Save to MongoDB
                mongo_save_session(session_id, user_id, cmd[:200])

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
            logger.error(f"Fatal error in run_cmd: {e}")
            try:
                bot.send_message(chat_id, f"❌ Error executing command: {str(e)[:200]}")
            except:
                pass

    threading.Thread(target=task, daemon=True).start()

# ========== KEYBOARDS ==========
def main_menu_keyboard(is_admin_user=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    buttons = [
        "📁 ls -la", "📂 pwd",
        "💿 df -h", "📊 system stats",
        "📝 nano", "🛑 stop",
        "🗑️ clear", "📁 my files",
        "ℹ️ my info", "📜 ps aux | head -20",
        "🌐ifconfig", "🔄 ping 8.8.8.8 -c 4",
        "📤 upload zip", "🌐 public url"
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

# ========== AUTO RESTART FUNCTION ==========
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
                            
                            if not auto_restart:
                                elapsed = current_time - start_time
                                if elapsed.total_seconds() >= 1800 and not thirty_min_msg_sent:
                                    auto_restart = True
                                    thirty_min_msg_sent = True
                                    bot.send_message(chat_id, f"✅ *30 min complete!*\n🔄 Auto restart ENABLED!", parse_mode="Markdown")
                            
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

                            try:
                                os.kill(pid, 0)
                            except OSError:
                                if auto_restart:
                                    bot.send_message(chat_id, f"⚠️ *Crashed!*\n🔄 Restarting...", parse_mode="Markdown")
                                    break
                                else:
                                    bot.send_message(chat_id, f"❌ *Crashed!*", parse_mode="Markdown")
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
                logger.error(f"Fatal error: {e}")
                time.sleep(3)

    threading.Thread(target=task, daemon=True).start()

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
        logger.warning(f"UNAUTHORIZED: User {cid} (@{username})")
        return

    authorized_users.add(cid)
    update_user_stats(cid, username, "/start")
    
    stats = get_system_stats()
    mongo_stats = mongo_get_stats() if MONGO_ENABLED else {}
    
    welcome_msg = f"""
         𝗥𝗔𝗝𝗙𝗙𝗟𝗜𝗩𝗘 𝗕𝗢𝗧
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

👑 Owner: {OWNER_NAME}
🤖 Bot: {BOT_USERNAME}
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
"""
    bot.send_message(cid, welcome_msg, 
                     parse_mode="Markdown", 
                     reply_markup=main_menu_keyboard(True))
    
    logger.info(f"Admin {cid} ({username}) started the bot")

@bot.message_handler(commands=["help"])
def help_cmd(m):
    cid = m.chat.id
    
    if not is_admin(cid):
        bot.send_message(cid, "🚫 Unauthorized")
        return
    
    help_msg = f"""
    📚 𝗛𝗘𝗟𝗣 & 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🖥️ 𝗕𝗔𝗦𝗜𝗖 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦
• Type any Linux command directly
• Use buttons for quick commands
• /start - Restart bot
• /help - Show this help

📝 𝗙𝗜𝗟𝗘 𝗘𝗗𝗜𝗧𝗜𝗡𝗚
• /nano <filename> - Edit files in browser

📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗜𝗡𝗙𝗢
• System Stats - View system status
• My Files - List your files
• My Info - Your user info

👑 𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦
• /admin - Open admin panel
• /status - Detailed system stats

👑 Owner: {OWNER_NAME}
🤖 Bot: {BOT_USERNAME}
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
"""
    bot.send_message(cid, help_msg, parse_mode="Markdown")

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    cid = m.chat.id
    
    if not is_admin(cid):
        bot.send_message(cid, "🚫 Unauthorized")
        return
    
    bot.send_message(cid, """
╭━━━━━━━━━━━━━━━✦
│ 🔐 𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟
╰━━━━━━━━━━━━━━━✦
""", parse_mode="Markdown", reply_markup=admin_keyboard())

@bot.message_handler(commands=["status"])
def status_cmd(m):
    cid = m.chat.id
    
    if not is_admin(cid):
        bot.send_message(cid, "🚫 Unauthorized")
        return
    
    stats = get_system_stats()
    mongo_stats = mongo_get_stats() if MONGO_ENABLED else {}
    
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

━━━━━━━━━━━━━━━━━━━━━━━━━━━
👥 𝗨𝗦𝗘𝗥 𝗦𝗧𝗔𝗧𝗜𝗦𝗧𝗜𝗖𝗦
──────────────────
• 𝗧𝗢𝗧𝗔𝗟 𝗔𝗗𝗠𝗜𝗡𝗦        : {len(admins)}
• 𝗔𝗖𝗧𝗜𝗩𝗘 𝗨𝗦𝗘𝗥𝗦        : {total_users}
• 𝗔𝗖𝗧𝗜𝗩𝗘 𝗦𝗘𝗦𝗦𝗜𝗢𝗡𝗦     : {total_sessions}
• 𝗥𝗨𝗡𝗡𝗜𝗡𝗚 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗘𝗦   : {total_processes}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 𝗗𝗔𝗧𝗔𝗕𝗔𝗦𝗘 𝗦𝗧𝗔𝗧𝗦
──────────────────
• 𝗧𝗢𝗧𝗔𝗟 𝗨𝗦𝗘𝗥𝗦        : {mongo_stats.get('total_users', 0)}
• 𝗧𝗢𝗧𝗔𝗟 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦     : {mongo_stats.get('total_commands', 0)}
• 𝗔𝗖𝗧𝗜𝗩𝗘 𝗦𝗘𝗦𝗦𝗜𝗢𝗡𝗦    : {mongo_stats.get('active_sessions', 0)}

▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
👑 Owner: {OWNER_NAME}
🤖 Bot: {BOT_USERNAME}
"""
    bot.send_message(cid, status_msg, parse_mode="Markdown")

# ========== STOP COMMAND ==========
@bot.message_handler(commands=["stop"])
def stop_cmd(m):
    cid = m.chat.id
    text = m.text.strip()
    
    if not is_admin(cid):
        bot.send_message(cid, "🚫 Unauthorized")
        return
    
    if len(text.split()) > 1 and "bot.py" in text:
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
                    bot.send_message(cid, "✅ *Stopped*", parse_mode="Markdown")
                except:
                    pass
        
        if stopped == 0:
            bot.send_message(cid, "❌ Not running!", parse_mode="Markdown")
    else:
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
    
    if not is_admin(cid):
        bot.send_message(cid, "🚫 Unauthorized")
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

    current_time = time.time()
    for sess_id in list(edit_sessions.keys()):
        if current_time - edit_sessions[sess_id].get('timestamp', 0) > 3600:
            edit_sessions.pop(sess_id, None)

    BASE_URL = os.environ.get("BASE_URL", f"http://localhost:{PORT}")
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
        f"📊 *Size:* {os.path.getsize(safe_path)} bytes",
        parse_mode="Markdown",
        reply_markup=markup
    )

# ========== ZIP UPLOAD HANDLER ==========
MAX_ZIP_SIZE = 10 * 1024 * 1024

def unzip_file(zip_path, extract_to):
    try:
        with _zipfile.ZipFile(zip_path, 'r') as zf:
            members = zf.namelist()
            zf.extractall(extract_to)
        return True, members
    except Exception as e:
        return False, str(e)

@bot.message_handler(content_types=['document'])
def handle_document(m):
    cid = m.chat.id
    if not is_admin(cid):
        bot.send_message(cid, "🚫 Unauthorized")
        return

    doc = m.document
    file_name = doc.file_name or "uploaded_file"

    if not file_name.lower().endswith('.zip'):
        bot.send_message(cid, "❌ Only `.zip` files allowed!", parse_mode="Markdown")
        return

    if doc.file_size > MAX_ZIP_SIZE:
        size_mb = doc.file_size / (1024 * 1024)
        bot.send_message(cid, f"❌ *File too large!*\n📦 Size: `{size_mb:.1f} MB`\n⚠️ Max: `10 MB`", parse_mode="Markdown")
        return

    msg = bot.send_message(cid, f"📥 *Uploading...*\n📦 `{file_name}`", parse_mode="Markdown")

    try:
        user_dir = get_user_directory(cid)
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)

        zip_save_path = os.path.join(user_dir, file_name)
        with open(zip_save_path, 'wb') as f:
            f.write(downloaded)

        ok, members = unzip_file(zip_save_path, user_dir)

        if ok:
            member_list = "\n".join([f"  📄 `{m_[:30]}`" for m_ in members[:10]])
            extra = f"\n  ...and {len(members) - 10} more" if len(members) > 10 else ""

            bot.edit_message_text(
                f"✅ *Extracted Successfully!*\n\n"
                f"📦 File: `{file_name}`\n"
                f"📂 Path: `{user_dir}`\n"
                f"🗂️ Files: `{len(members)}`\n\n"
                f"*Files:*\n{member_list}{extra}",
                cid, msg.message_id,
                parse_mode="Markdown"
            )
            add_system_alert("INFO", f"User {cid} uploaded ZIP: {file_name} ({len(members)} files)")
        else:
            bot.edit_message_text(f"⚠️ Extract failed:\n`{members}`", cid, msg.message_id, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"ZIP upload error: {e}")
        bot.edit_message_text(f"❌ Error:\n`{str(e)[:200]}`", cid, msg.message_id, parse_mode="Markdown")

# ========== MAIN MESSAGE HANDLER ==========
@bot.message_handler(func=lambda m: True)
def handle_all_messages(m):
    cid = m.chat.id
    text = m.text.strip() if m.text else ""
    username = m.from_user.username or "Unknown"
    
    if not is_admin(cid):
        bot.send_message(cid, f"🚫 Unauthorized\n\n👑 Owner: {OWNER_NAME}")
        return
    
    shell(m)

def shell(m):
    cid = m.chat.id
    text = m.text.strip()
    username = m.from_user.username or "Unknown"
    
    update_user_stats(cid, username, text[:50])
    get_user_dict(cid, active_sessions)
    
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
        "🌐ifconfig": "ifconfig || ip addr",
        "📁 my files": None,
        "ℹ️ my info": None,
        "👑 admin panel": None,
        "📈 performance": None,
        "📤 upload zip": None,
        "🌐 public url": None
    }
    
    if text in quick_map:
        if text == "🗑️ clear":
            bot.send_message(cid, "🗑️ Cleared")
            return
        elif text == "🛑 stop":
            stop_cmd(m)
            return
        elif text == "📝 nano":
            bot.send_message(cid, "📝 *Usage:* `/nano filename`", parse_mode="Markdown")
            return
        elif text == "📊 system stats":
            stats = get_system_stats()
            stats_msg = f"""
      📊 𝗦𝗬𝗦𝗧𝗘𝗠 𝗦𝗧𝗔𝗧𝗦 📊
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
🖥️  CPU    : {stats['cpu_bar']}  {stats['cpu']:.1f}%
💾  MEMORY : {stats['memory_bar']}  {stats['memory']:.1f}%
💿  DISK   : {stats['disk_bar']}  {stats['disk']:.1f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱️  UPTIME  : {stats['uptime']}
🔄  PROCS   : {stats['processes']}
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
👑 {OWNER_NAME}
"""
            bot.send_message(cid, stats_msg, parse_mode="Markdown")
            return
        elif text == "📁 my files":
            user_dir = get_user_directory(cid)
            try:
                files = os.listdir(user_dir)
                if not files:
                    bot.send_message(cid, "📁 Empty directory")
                else:
                    file_list = []
                    for f in files[:15]:
                        full_path = os.path.join(user_dir, f)
                        if os.path.isfile(full_path):
                            size = os.path.getsize(full_path)
                            file_list.append(f"📄 {f} ({size} bytes)")
                        else:
                            file_list.append(f"📁 {f}/")
                    
                    msg = "📁 *YOUR FILES*\n\n" + "\n".join(file_list)
                    if len(files) > 15:
                        msg += f"\n\n... and {len(files) - 15} more"
                    
                    bot.send_message(cid, msg, parse_mode="Markdown")
            except Exception as e:
                bot.send_message(cid, f"❌ Error: {e}")
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

📊 Stats
• Commands: {user_data.get('commands', 0)}
• First: {user_data.get('first_seen', 'N/A')[:10]}
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
            bot.send_message(
                cid,
                f"📤 *Upload ZIP*\n\n"
                f"1️⃣ Send `.zip` file directly\n"
                f"2️⃣ Max size: `10 MB`\n"
                f"3️⃣ Auto extract to `{get_user_directory(cid)}`",
                parse_mode="Markdown"
            )
            return
        elif text == "🌐 public url":
            public_url = f"http://localhost:{PORT}"
            bot.send_message(
                cid,
                f"🌐 *Public URL*\n\n`{public_url}`",
                parse_mode="Markdown"
            )
            return
        else:
            text = quick_map[text]
    
    if ("python" in text and "bot.py" in text) or ("python3" in text and "bot.py" in text):
        bot.send_message(cid, f"🔄 *Started*\n```\n$ {text}\n```", parse_mode="Markdown")
        run_bot_py_with_monitor(text, cid, cid)
    else:
        session_id = generate_session_id()
        bot.send_message(cid, f"```\n$ {text}\n```", parse_mode="Markdown")
        run_cmd(text, cid, cid, session_id)

def show_performance(cid):
    stats = get_system_stats()
    
    perf_msg = f"""
    📈 𝗣𝗘𝗥𝗙𝗢𝗥𝗠𝗔𝗡𝗖𝗘 𝗠𝗘𝗧𝗥𝗜𝗖𝗦 📈
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
🖥️  CPU
• USAGE    : {stats['cpu']:.1f}%
• CORES    : {psutil.cpu_count()}

💾  MEMORY
• TOTAL    : {psutil.virtual_memory().total / (1024**3):.1f} GB
• USED     : {psutil.virtual_memory().used / (1024**3):.1f} GB
• FREE     : {psutil.virtual_memory().free / (1024**3):.1f} GB

💿  DISK
• TOTAL    : {psutil.disk_usage('/').total / (1024**3):.1f} GB
• USED     : {psutil.disk_usage('/').used / (1024**3):.1f} GB
• FREE     : {psutil.disk_usage('/').free / (1024**3):.1f} GB
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
👑 {OWNER_NAME}
"""
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
            
            msg = bot.send_message(cid, "Send user ID to add as admin:")
            bot.register_next_step_handler(msg, add_admin_step)
            bot.answer_callback_query(call.id)
        
        elif call.data == "remove_admin":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            msg = bot.send_message(cid, "Send user ID to remove from admins:")
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
                    bot.send_message(cid, "📁 Directory empty")
                else:
                    file_list = []
                    for f in files[:20]:
                        full_path = os.path.join(user_dir, f)
                        if os.path.isfile(full_path):
                            size = os.path.getsize(full_path)
                            file_list.append(f"📄 {f} ({size} bytes)")
                        else:
                            file_list.append(f"📁 {f}/")
                    
                    msg = "*FILES:*\n\n" + "\n".join(file_list)
                    if len(files) > 20:
                        msg += f"\n\n... and {len(files)-20} more"
                    
                    bot.send_message(cid, msg, parse_mode="Markdown")
            except Exception as e:
                bot.send_message(cid, f"❌ Error: {e}")
            bot.answer_callback_query(call.id)
        
        elif call.data == "user_stats":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            if str(cid) != str(MAIN_ADMIN_ID):
                bot.answer_callback_query(call.id, "❌ Main admin only!")
                return
            
            if MONGO_ENABLED:
                stats_msg = "*USER STATISTICS (MongoDB)*\n\n"
                for user_id, data in mongo_get_users().items():
                    stats_msg += f"👤 User {user_id} (@{data.get('username', 'N/A')}):\n"
                    stats_msg += f"  • Commands: {data.get('commands', 0)}\n"
                    stats_msg += f"  • Last seen: {data.get('last_seen', 'N/A')[:10]}\n\n"
            else:
                stats_msg = "*USER STATISTICS (File)*\n\n"
                for user_id, data in user_stats.items():
                    stats_msg += f"👤 User {user_id} (@{data.get('username', 'N/A')}):\n"
                    stats_msg += f"  • Commands: {data.get('commands', 0)}\n"
                    stats_msg += f"  • Last seen: {data.get('last_seen', 'N/A')[:10]}\n\n"
            
            bot.send_message(cid, stats_msg, parse_mode="Markdown")
            bot.answer_callback_query(call.id)
        
        elif call.data == "performance":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            show_performance(cid)
            bot.answer_callback_query(call.id)
        
        elif call.data == "public_url":
            if not is_admin(cid):
                bot.answer_callback_query(call.id, "❌ Not authorized!")
                return
            public_url = f"http://localhost:{PORT}"
            bot.send_message(cid, f"🌐 *Public URL*\n\n`{public_url}`", parse_mode="Markdown")
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
                    content = f.read(3500)
                
                bot.send_message(cid, f"```\n{content}\n```", parse_mode="Markdown")
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
━━━━━━━━━━━━━━━━━━━━━━
"""
                    bot.send_message(cid, info_msg, parse_mode="Markdown")
                else:
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
        bot.answer_callback_query(call.id, "❌ Error occurred")

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
            if MONGO_ENABLED:
                mongo_save_admin(new_admin)
            else:
                save_data()
            bot.send_message(cid, f"✅ Added admin: `{new_admin}`", parse_mode="Markdown")
            add_system_alert("INFO", f"Added new admin: {new_admin}")
    except ValueError:
        bot.send_message(cid, "❌ Invalid user ID. Send numeric ID only.")
    except Exception as e:
        bot.send_message(cid, f"❌ Error: {e}")

def remove_admin_step(m):
    cid = m.chat.id
    if str(cid) != str(MAIN_ADMIN_ID):
        return
    
    try:
        admin_id = int(m.text.strip())
        
        if admin_id == MAIN_ADMIN_ID:
            bot.send_message(cid, "❌ Cannot remove main admin.")
            return
        
        if admin_id in admins:
            admins.remove(admin_id)
            if MONGO_ENABLED:
                mongo_remove_admin(admin_id)
            else:
                save_data()
            bot.send_message(cid, f"✅ Removed admin: `{admin_id}`", parse_mode="Markdown")
            add_system_alert("INFO", f"Removed admin: {admin_id}")
        else:
            bot.send_message(cid, f"❌ Admin ID `{admin_id}` not found.", parse_mode="Markdown")
    except ValueError:
        bot.send_message(cid, "❌ Invalid user ID.")
    except Exception as e:
        bot.send_message(cid, f"❌ Error: {e}")

# ========== WEB INTERFACE ==========
@app.route("/edit/<sid>", methods=["GET", "POST"])
def edit(sid):
    if sid not in edit_sessions:
        return """
        <html>
        <head><title>Session Expired</title>
        <style>
            body { background: #0d1117; color: #c9d1d9; font-family: Arial; display: flex; justify-content: center; align-items: center; height: 100vh; }
            .container { text-align: center; padding: 40px; background: #161b22; border-radius: 10px; }
            h2 { color: #f85149; }
        </style>
        </head>
        <body>
            <div class="container">
                <h2>❌ Invalid or expired session</h2>
                <p>Generate a new edit link from Telegram</p>
            </div>
        </body>
        </html>
        """

    session_data = edit_sessions[sid]
    file = session_data.get("file")
    user_id = session_data.get("user_id")
    filename = session_data.get("filename", os.path.basename(file))
    
    user_dir = get_user_directory(user_id)
    abs_path = os.path.abspath(file)
    if not abs_path.startswith(os.path.abspath(user_dir)):
        return "<h2>❌ Unauthorized</h2>"

    if request.method == "POST":
        try:
            code_content = request.form.get("code", "")
            with open(abs_path, "w", encoding='utf-8') as f:
                f.write(code_content)
            return """
            <html>
            <head><title>Saved</title>
            <style>
                body { background: #0d1117; color: #c9d1d9; display: flex; justify-content: center; align-items: center; height: 100vh; }
                .container { text-align: center; padding: 40px; background: #161b22; border-radius: 10px; }
                h2 { color: #3fb950; }
            </style>
            </head>
            <body>
                <div class="container">
                    <h2>✅ File Saved!</h2>
                    <p>You can close this window</p>
                </div>
            </body>
            </html>
            """
        except Exception as e:
            return f"<h2>❌ Error: {e}</h2>"
            
    try:
        with open(abs_path, "r", encoding='utf-8', errors='ignore') as f:
            code = f.read()
    except Exception as e:
        code = f"# Error loading file: {e}"

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Rajfflive Bot - Edit {{ filename }}</title>
    <style>
        body { margin:0; background:#0d1117; color:#c9d1d9; font-family:monospace; }
        .header { background:#161b22; padding:10px 20px; border-bottom:1px solid #30363d; }
        .header h1 { margin:0; font-size:20px; }
        .header small { color:#8b949e; }
        textarea { width:100%; height:calc(100vh - 100px); background:#0d1117; color:#c9d1d9; border:none; padding:20px; font-family:monospace; font-size:14px; outline:none; }
        .footer { padding:10px 20px; background:#161b22; border-top:1px solid #30363d; text-align:center; }
        button { background:#238636; color:white; border:none; padding:8px 24px; border-radius:6px; cursor:pointer; font-size:14px; }
        button:hover { background:#2ea043; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📝 Rajfflive Bot Pro <small>- Editing: {{ filename }}</small></h1>
    </div>
    <form method="post">
        <textarea name="code">{{ code }}</textarea>
        <div class="footer">
            <button type="submit">💾 Save File</button>
        </div>
    </form>
</body>
</html>
""", code=code, filename=filename)

@app.route('/')
def home():
    stats = get_system_stats()
    mongo_stats = mongo_get_stats() if MONGO_ENABLED else {}
    
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Rajfflive Bot Pro</title>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ background: linear-gradient(135deg, #0a0c0f 0%, #0d1117 100%); min-height:100vh; display:flex; justify-content:center; align-items:center; font-family:'Segoe UI',Arial,sans-serif; }}
        .card {{ background:rgba(22,27,34,0.95); backdrop-filter:blur(10px); border-radius:30px; padding:40px; max-width:500px; width:90%; text-align:center; border:1px solid rgba(255,255,255,0.05); box-shadow:0 20px 40px rgba(0,0,0,0.5); }}
        .icon {{ font-size:80px; margin-bottom:20px; }}
        h1 {{ color:white; font-size:28px; margin-bottom:10px; }}
        .badge {{ display:inline-block; padding:5px 15px; background:rgba(0,212,255,0.1); border:1px solid rgba(0,212,255,0.3); border-radius:50px; color:#00d4ff; font-size:12px; margin-bottom:20px; }}
        .stats {{ background:rgba(255,255,255,0.03); border-radius:20px; padding:20px; margin:20px 0; }}
        .stat-row {{ display:flex; justify-content:space-between; margin:10px 0; color:#8b949e; }}
        .stat-value {{ color:white; font-weight:bold; }}
        .progress {{ height:6px; background:rgba(255,255,255,0.1); border-radius:3px; overflow:hidden; margin-top:5px; }}
        .progress-fill {{ height:100%; background:linear-gradient(90deg,#00d4ff,#0066ff); transition:width 0.3s; }}
        .footer {{ margin-top:20px; color:#484f58; font-size:12px; }}
        a {{ color:#00d4ff; text-decoration:none; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">🤖</div>
        <h1>Rajfflive Bot Pro</h1>
        <div class="badge">✅ SYSTEM ONLINE</div>
        
        <div class="stats">
            <div class="stat-row">
                <span>🖥️ CPU</span>
                <span class="stat-value">{stats['cpu']:.1f}%</span>
            </div>
            <div class="progress"><div class="progress-fill" style="width:{stats['cpu']}%"></div></div>
            
            <div class="stat-row">
                <span>💾 Memory</span>
                <span class="stat-value">{stats['memory']:.1f}%</span>
            </div>
            <div class="progress"><div class="progress-fill" style="width:{stats['memory']}%"></div></div>
            
            <div class="stat-row">
                <span>💿 Disk</span>
                <span class="stat-value">{stats['disk']:.1f}%</span>
            </div>
            <div class="progress"><div class="progress-fill" style="width:{stats['disk']}%"></div></div>
        </div>
        
        <div class="stats">
            <div class="stat-row"><span>⏱️ Uptime</span><span class="stat-value">{stats['uptime']}</span></div>
            <div class="stat-row"><span>📊 DB Users</span><span class="stat-value">{mongo_stats.get('total_users', 0)}</span></div>
            <div class="stat-row"><span>📝 Commands</span><span class="stat-value">{mongo_stats.get('total_commands', 0)}</span></div>
        </div>
        
        <div class="footer">
            👑 Owner: <a href="#">@{OWNER_NAME[1:]}</a><br>
            🤖 Bot: <a href="#">{BOT_USERNAME}</a><br>
            <span style="color:#3fb950;">● Online</span>
        </div>
    </div>
</body>
</html>
"""

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'owner': 'rajfflive',
        'bot': 'rtmxbot',
        'timestamp': datetime.now().isoformat(),
        'mongodb': MONGO_ENABLED
    })

@app.route('/api/stats')
def api_stats():
    stats = get_system_stats()
    stats.update({
        'active_users': len(set(active_sessions.keys()) | set(processes.keys())),
        'active_sessions': sum(len(sess) for sess in active_sessions.values()),
        'total_admins': len(admins),
        'mongodb_enabled': MONGO_ENABLED,
        'owner': 'rajfflive',
        'bot': 'rtmxbot'
    })
    if MONGO_ENABLED:
        stats.update(mongo_get_stats())
    return jsonify(stats)

# ========== MAIN ==========
if __name__ == "__main__":
    print("="*50)
    print("🤖 Rajfflive Bot Pro v6.0")
    print(f"👑 Owner: {OWNER_NAME}")
    print(f"🤖 Bot: {BOT_USERNAME}")
    print(f"📁 Base Directory: {BASE_DIR}")
    print(f"🌐 Web Interface: http://0.0.0.0:{PORT}")
    print("="*50)

    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN not set in environment variables!")
        print("   Create a .env file with: BOT_TOKEN=your_token_here")
        exit(1)

    # Load saved data
    load_data()

    # Start Flask in a separate thread
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

    # Start bot in a separate thread    def run_bot():
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

    # Start threads
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    bot_thread = threading.Thread(target=run_bot, daemon=True)

    flask_thread.start()
    bot_thread.start()

    add_system_alert("INFO", f"{BOT_NAME} started successfully")

    # Monitor loop
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
                add_system_alert("WARNING", f"High CPU: {stats['cpu']:.1f}%")
            if stats['memory'] > 80:
                add_system_alert("WARNING", f"High memory: {stats['memory']:.1f}%")
            if stats['disk'] > 90:
                add_system_alert("WARNING", f"Low disk space: {stats['disk']:.1f}%")

    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        save_data()
        logger.info("Bot shutdown complete")
