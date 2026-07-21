import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import smtplib
import random
import time
import sqlite3
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ==========================================
# إعدادات البوت وقاعدة البيانات
# ==========================================
BOT_TOKEN = '8654491813:AAF6oRCzEk1EKJE8Fe9fi48DyQY4OVlHAp4'
bot = telebot.TeleBot(BOT_TOKEN)

active_campaigns = {}
user_states = {}

def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            email TEXT,
            password TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# دوال قاعدة البيانات
# ==========================================
def add_accounts_db(user_id, accounts_list):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    for acc in accounts_list:
        cursor.execute("INSERT INTO accounts (user_id, email, password) VALUES (?, ?, ?)", 
                       (user_id, acc['email'], acc['password']))
    conn.commit()
    conn.close()

def get_accounts_db(user_id, only_active=False):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    if only_active:
        cursor.execute("SELECT id, email, password, is_active FROM accounts WHERE user_id=? AND is_active=1", (user_id,))
    else:
        cursor.execute("SELECT id, email, password, is_active FROM accounts WHERE user_id=?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{'id': r[0], 'email': r[1], 'password': r[2], 'is_active': bool(r[3])} for r in rows]

def delete_account_db(user_id, acc_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM accounts WHERE id=? AND user_id=?", (acc_id, user_id))
    conn.commit()
    conn.close()

def delete_all_accounts_db(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM accounts WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def disable_account_db(acc_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE accounts SET is_active=0 WHERE id=?", (acc_id,))
    conn.commit()
    conn.close()

# ==========================================
# الأزرار
# ==========================================
def main_menu_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💼 حسابات الإرسال", callback_data="menu_accounts"),
        InlineKeyboardButton("🚀 ابدأ الشد (حملة جديدة)", callback_data="menu_campaign")
    )
    markup.add(
        InlineKeyboardButton("📊 مراقبة الحملة الحالية", callback_data="monitor_campaign"),
        InlineKeyboardButton("🛑 إيقاف الحملة", callback_data="stop_campaign")
    )
    return markup

def accounts_menu_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ إضافة حسابات", callback_data="acc_add"),
        InlineKeyboardButton("📋 عرض الحسابات", callback_data="acc_view")
    )
    markup.add(
        InlineKeyboardButton("🗑️ حذف حساب محدد", callback_data="acc_delete"),
        InlineKeyboardButton("⚠️ مسح كل الحسابات", callback_data="acc_clear")
    )
    markup.add(InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="menu_main"))
    return markup

def cancel_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ إلغاء", callback_data="menu_main"))
    return markup

def monitor_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔄 تحديث الإحصائيات", callback_data="monitor_campaign"),
        InlineKeyboardButton("🛑 إيقاف الحملة", callback_data="stop_campaign"),
        InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")
    )
    return markup

# ==========================================
# دالة نصوص المراقبة
# ==========================================
def get_monitor_text(user_id):
    stats = active_campaigns.get(user_id)
    if not stats or stats['status'] != 'running':
        return None
    
    accs_count = len(get_accounts_db(user_id, only_active=True))
    current_time = datetime.now().strftime("%H:%M:%S")
    
    text = (
        "📊 *الحملة الحالية (مراقبة)*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ وقت بدء الحملة: `{stats['start_time']}`\n"
        f"🔄 تم إرسال: `{stats['task_counter']}`\n"
        f"✅ نجاح: `{stats['success']}`\n"
        f"❌ فشل: `{stats['failed']}`\n"
        f"🎯 المستلم الحالي: `{stats['current_target']}`\n"
        f"🟢 الحسابات النشطة: `{accs_count}`\n"
        f"⚠️ آخر خطأ: `{stats['last_error']}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ آخر تحديث: {current_time}"
    )
    return text

# ==========================================
# نواة الإرسال
# ==========================================
def send_email(sender_email, sender_password, to_email, subject, body):
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=20)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return True, "نجاح", False
    except smtplib.SMTPDataError as e:
        error_msg = e.smtp_error.decode('utf-8', errors='ignore') if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        if "quota" in error_msg.lower() or "limit" in error_msg.lower() or e.smtp_code == 550:
            return False, "تخطي الحد اليومي (تم الحظر)", True
        return False, "خطأ في البيانات", False
    except smtplib.SMTPAuthenticationError:
        return False, "خطأ في المصادقة أو الباسورد", True
    except Exception as e:
        return False, f"خطأ شبكة/نظام: {str(e)}", False

# ==========================================
# محرك الحملة (Thread)
# ==========================================
def campaign_worker(user_id, templates, send_mode, total_runs, infinite_loop):
    stats = active_campaigns[user_id]
    template_index = 0
    accounts = get_accounts_db(user_id, only_active=True)
    
    if not accounts:
        stats['status'] = 'stopped_no_accounts'
        bot.send_message(user_id, "❌ **فشلت الحملة:** لا توجد حسابات نشطة للبدء.", parse_mode="Markdown")
        return

    selected_account = accounts[0] if send_mode == 'specific' else None

    while stats['status'] == 'running':
        if not infinite_loop and stats['task_counter'] >= total_runs:
            stats['status'] = 'finished'
            bot.send_message(user_id, "✅ **اكتملت الحملة بنجاح!**\nتم إرسال العدد المطلوب.", parse_mode="Markdown")
            break

        current_template = templates[template_index]
        stats['task_counter'] += 1
        stats['current_target'] = current_template['to']

        while stats['status'] == 'running':
            current_active = get_accounts_db(user_id, only_active=True)
            if not current_active:
                stats['status'] = 'stopped_all_limited'
                bot.send_message(user_id, "🚨 **توقف اضطراري:** جميع الحسابات محظورة أو وصلت للحد الأقصى.", parse_mode="Markdown")
                return

            if send_mode == 'specific':
                if any(acc['id'] == selected_account['id'] for acc in current_active):
                    acc_to_use = selected_account
                else:
                    acc_to_use = random.choice(current_active)
                    send_mode = 'random'
            else:
                acc_to_use = random.choice(current_active)

            success, msg, should_disable = send_email(
                acc_to_use['email'], acc_to_use['password'], 
                current_template['to'], current_template['subject'], current_template['body']
            )

            if success:
                stats['success'] += 1
                stats['last_error'] = 'لا يوجد'
                time.sleep(1)
                break
            else:
                stats['failed'] += 1
                stats['last_error'] = msg
                if should_disable:
                    disable_account_db(acc_to_use['id'])
                    continue 
                else:
                    time.sleep(3)
                    break 

        template_index = (template_index + 1) % len(templates)

# ==========================================
# أوامر البوت
# ==========================================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.chat.id
    text = (
        "مرحبا بيك في بوت الشد الخاص بي @bfix9\n\n"
        "هذا البوت لإدارة الحسابات وإرسال الرسائل بشكل منظم.\n"
        "اختر من القائمة أدناه للبدء:"
    )
    bot.send_message(user_id, text, reply_markup=main_menu_markup())

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data

    if data == "menu_main":
        bot.edit_message_text("🌟 *القائمة الرئيسية*", user_id, msg_id, reply_markup=main_menu_markup(), parse_mode="Markdown")
        if user_id in user_states: del user_states[user_id]

    elif data == "menu_accounts":
        accs = get_accounts_db(user_id)
        bot.edit_message_text(f"💼 *إدارة حسابات الإرسال*\nعدد حساباتك الحالية: `{len(accs)}`", user_id, msg_id, reply_markup=accounts_menu_markup(), parse_mode="Markdown")

    elif data == "acc_view":
        accs = get_accounts_db(user_id)
        if not accs:
            bot.answer_callback_query(call.id, "لا توجد حسابات مضافة!", show_alert=True)
            return
        text = "📋 *قائمة حساباتك:*\n\n"
        for idx, acc in enumerate(accs):
            status = "🟢 نشط" if acc['is_active'] else "🔴 محظور"
            text += f"{idx+1}. `{acc['email']}` - {status}\n"
        bot.edit_message_text(text, user_id, msg_id, reply_markup=accounts_menu_markup(), parse_mode="Markdown")

    elif data == "acc_add":
        msg = bot.edit_message_text("أرسل الحسابات الآن بالصيغة التالية:\n`email:password; email2:password`", user_id, msg_id, reply_markup=cancel_markup(), parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_accounts)

    elif data == "acc_clear":
        delete_all_accounts_db(user_id)
        bot.answer_callback_query(call.id, "تم مسح جميع حساباتك بنجاح!", show_alert=True)
        bot.edit_message_text("تم مسح الحسابات.", user_id, msg_id, reply_markup=accounts_menu_markup())

    elif data == "acc_delete":
        msg = bot.edit_message_text("ارسل الإيميل الذي تريد حذفه:", user_id, msg_id, reply_markup=cancel_markup())
        bot.register_next_step_handler(msg, process_delete_account)

    elif data == "menu_campaign":
        if active_campaigns.get(user_id, {}).get('status') == 'running':
            bot.answer_callback_query(call.id, "لديك حملة شغالة حالياً! قم بإيقافها أولاً.", show_alert=True)
            return
        if not get_accounts_db(user_id, only_active=True):
            bot.answer_callback_query(call.id, "ليس لديك أي حسابات نشطة للبدء!", show_alert=True)
            return
        
        user_states[user_id] = {'templates': []}
        msg = bot.edit_message_text("كم تريد ارسال رسالة؟ (ارسل الرقم)", user_id, msg_id, reply_markup=cancel_markup())
        bot.register_next_step_handler(msg, process_campaign_templates_count)

    elif data == "monitor_campaign":
        text = get_monitor_text(user_id)
        if text:
            try:
                bot.edit_message_text(text, user_id, msg_id, reply_markup=monitor_markup(), parse_mode="Markdown")
            except telebot.apihelper.ApiTelegramException:
                bot.answer_callback_query(call.id, "لم تتغير الإحصائيات منذ آخر تحديث.", show_alert=False)
        else:
            bot.answer_callback_query(call.id, "لا توجد حملة شغالة حالياً.", show_alert=True)

    elif data == "stop_campaign":
        if user_id in active_campaigns and active_campaigns[user_id]['status'] == 'running':
            active_campaigns[user_id]['status'] = 'stopped_by_user'
            bot.answer_callback_query(call.id, "تم إيقاف الحملة بنجاح.", show_alert=True)
            bot.edit_message_text("🛑 تم إيقاف الحملة.", user_id, msg_id, reply_markup=main_menu_markup())
        else:
            bot.answer_callback_query(call.id, "لا توجد حملة شغالة حالياً.", show_alert=True)

# ==========================================
# خطوات الإدخال
# ==========================================
def process_add_accounts(message):
    user_id = message.chat.id
    raw_text = message.text
    if raw_text.startswith('/'): return
    
    accounts = []
    parts = raw_text.split(';')
    for part in parts:
        if ':' in part:
            email, password = part.split(':', 1)
            accounts.append({'email': email.strip(), 'password': password.strip()})
    
    if accounts:
        add_accounts_db(user_id, accounts)
        bot.send_message(user_id, f"✅ تم إضافة {len(accounts)} حساب بنجاح.", reply_markup=accounts_menu_markup())
    else:
        bot.send_message(user_id, "❌ صيغة خاطئة. حاول مجدداً.", reply_markup=accounts_menu_markup())

def process_delete_account(message):
    user_id = message.chat.id
    target_email = message.text.strip()
    
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM accounts WHERE user_id=? AND email=?", (user_id, target_email))
    row = cursor.fetchone()
    if row:
        delete_account_db(user_id, row[0])
        bot.send_message(user_id, f"✅ تم حذف الحساب `{target_email}`.", reply_markup=accounts_menu_markup(), parse_mode="Markdown")
    else:
        bot.send_message(user_id, "❌ لم يتم العثور على هذا الحساب.", reply_markup=accounts_menu_markup())
    conn.close()

def process_campaign_templates_count(message):
    user_id = message.chat.id
    try:
        count = int(message.text)
        user_states[user_id]['total_templates'] = count
        user_states[user_id]['current_template'] = 1
        ask_template_to(message)
    except ValueError:
        bot.send_message(user_id, "❌ الرجاء إرسال أرقام فقط.", reply_markup=main_menu_markup())

def ask_template_to(message):
    user_id = message.chat.id
    curr = user_states[user_id]['current_template']
    total = user_states[user_id]['total_templates']
    msg = bot.send_message(user_id, f"📝 *الرسالة {curr} من أصل {total}*\nارسل حساب المستلم:", reply_markup=cancel_markup(), parse_mode="Markdown")
    bot.register_next_step_handler(msg, ask_template_subject)

def ask_template_subject(message):
    user_id = message.chat.id
    user_states[user_id]['temp_to'] = message.text.strip()
    msg = bot.send_message(user_id, "ارسل عنوان الرسالة:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, ask_template_body)

def ask_template_body(message):
    user_id = message.chat.id
    user_states[user_id]['temp_subject'] = message.text.strip()
    msg = bot.send_message(user_id, "ارسل الرسالة:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_template)

def save_template(message):
    user_id = message.chat.id
    body = message.text
    
    user_states[user_id]['templates'].append({
        'to': user_states[user_id]['temp_to'],
        'subject': user_states[user_id]['temp_subject'],
        'body': body
    })
    
    curr = user_states[user_id]['current_template']
    if curr < user_states[user_id]['total_templates']:
        user_states[user_id]['current_template'] += 1
        ask_template_to(message)
    else:
        msg = bot.send_message(user_id, "⚙️ اختر نمط الإرسال:\n1. إرسال بحساب محدد\n2. إرسال عشوائي", reply_markup=cancel_markup())
        bot.register_next_step_handler(msg, ask_campaign_loop)

def ask_campaign_loop(message):
    user_id = message.chat.id
    choice = message.text.strip()
    user_states[user_id]['send_mode'] = 'specific' if choice == '1' else 'random'
    
    msg = bot.send_message(user_id, "🔁 هل تريد الإرسال المفتوح (اللانهائي) أم عدد محدد؟\nارسل `0` لنمط لا نهائي، أو ارسل العدد (مثال: 1000).", parse_mode="Markdown", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, start_campaign_thread)

def start_campaign_thread(message):
    user_id = message.chat.id
    try:
        total_runs = int(message.text.strip())
        infinite_loop = (total_runs == 0)
    except ValueError:
        bot.send_message(user_id, "❌ إدخال خاطئ. تم الإلغاء.", reply_markup=main_menu_markup())
        return

    templates = user_states[user_id]['templates']
    send_mode = user_states[user_id]['send_mode']
    
    active_campaigns[user_id] = {
        'status': 'running',
        'task_counter': 0,
        'success': 0,
        'failed': 0,
        'last_error': 'لا يوجد',
        'current_target': 'يتم التجهيز...',
        'start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    thread = threading.Thread(target=campaign_worker, args=(user_id, templates, send_mode, total_runs, infinite_loop))
    thread.daemon = True
    thread.start()
    
    bot.send_message(user_id, "🚀 *تم انطلاق الحملة!*", parse_mode="Markdown")
    
    # استدعاء دالة المراقبة وإرسالها مباشرة دون أخطاء
    monitor_text = get_monitor_text(user_id)
    if monitor_text:
        bot.send_message(user_id, monitor_text, reply_markup=monitor_markup(), parse_mode="Markdown")
        
    del user_states[user_id]

# ==========================================
# التشغيل
# ==========================================
if __name__ == '__main__':
    print("Bot is running...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
