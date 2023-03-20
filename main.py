#!/usr/bin/python3 -u

from google.cloud import datastore, logging as gcloud_logger
from telegram.client import Telegram

import logging
import os
import operator
import string
import random
import threading
import time
import typing as t

##################### Configuration Begin ######################
YOUR_QUESTION = os.environ.get("YOUR_QUESTION", "<RANDOM_SUM>")
YOUR_ANSWER = os.environ.get("YOUR_ANSWER", "<RANDOM_SUM>")
TELEGRAM_DB_PASSWORD = os.environ.get("TELEGRAM_DB_PASSWORD")
TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID") # Get api_id and api_hash at my.telegram.org
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH")
TELEGRAM_PHONE = os.environ.get("TELEGRAM_PHONE") # Phone number in International Format. Example: '+8617719890604'
##################### Configuration End ########################

logger = gcloud_logger.Client()
logger.setup_logging()

OPERATORS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
}

def random_operator():
    return random.choice(list(OPERATORS.items()))

def random_number(char_num):
    return int("".join(random.choice(string.digits) for _ in range(char_num)))

# Only generates a random equation on startup, need to make it generate a new one per chat id
if YOUR_QUESTION == "<RANDOM_SUM>":
    op_string, op_func = random_operator()
    num_1 = random_number(3)
    num_2 = random_number(3)
    YOUR_ANSWER = str(op_func(num_1, num_2))
    YOUR_QUESTION = f"{num_1} {op_string} {num_2} = ?"

tg = Telegram(
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    phone=TELEGRAM_PHONE,
    database_encryption_key=TELEGRAM_DB_PASSWORD,
    files_directory='/tmp/tdlib_files/',
)

datastore_client = datastore.Client()
task_key = datastore_client.key("telegram-watchdog", "whitelist")

# Prepares the new entity
task = datastore_client.get(task_key)
if task is None:
    task = datastore.Entity(key=task_key)
    task["description"] = "Allowlisted Chat IDs"
    task["chat_ids"] = []

def read_allowlist():
    chat_ids = task["chat_ids"]
    if any(chat_ids):
        logging.info("Loaded the following saved chat IDs: %s", chat_ids)
    return chat_ids

def write_allowlist():
    task["chat_ids"] = allowlisted_chat_ids
    datastore_client.put(task)

def add_to_allowlist(chat_ids: t.List[int]):
    allowlisted_chat_ids.extend([chat_id for chat_id in chat_ids if chat_id not in allowlisted_chat_ids])
    write_allowlist()

allowlisted_chat_ids: t.List[int] = read_allowlist()

magic_text = '[Watchdog]'
msg_verify = 'This account is protected by Telegram Antispam WatchDog.\nPlease answer the question to continue:\n' + YOUR_QUESTION
msg_allowlisted = 'Allowlisted this chat.'
msg_passed = 'You have passed the verification. Thanks!\n'

# We need to mark_message_read() for 30 times, with one second interval. That's the only method to eliminate GMS notification.
# Format: [(chat_id, msg_id, count), ...]
# count will decrease from 30 to 0 by a timer in another thread.
remove_gms_notify_queue = []
remove_gms_notify_queue_lock = threading.Lock()

def mark_msg_read(chat_id, msg_id):
    # This function must be called multiple times. For example, call it once a second, for 8 times.
    # You must call mark_msg_read_finish() after the last mark_msg_read(). You must wait as long as possible before calling mark_msg_read_finish(), to make the mark_msg_read reliable.
    # This problem only appears in GMS notification.
    fn_data = {
        '@type': 'openChat',
        'chat_id': chat_id,
    }
    tg._tdjson.send(fn_data)

    fn_data = {
        '@type': 'viewMessages',
        'chat_id': chat_id,
        'message_ids': [msg_id],
        'force_read': True,
    }
    tg._tdjson.send(fn_data)

def mark_msg_read_finish(chat_id):
    fn_data = {
        '@type': 'closeChat',
        'chat_id': chat_id,
    }
    tg._tdjson.send(fn_data)

def timer_handler():
    # In every second, check if there is any message to be marked as read.
    global remove_gms_notify_queue
    with remove_gms_notify_queue_lock:
        result_list = []
        for entry in remove_gms_notify_queue:
            chat_id, msg_id, count = entry
            mark_msg_read(chat_id, msg_id)
            if count-1 > 0:
                result_list.append((chat_id, msg_id, count-1))
            else:
                mark_msg_read_finish(chat_id)
        remove_gms_notify_queue = result_list

def message_handler(update):
    chat_id = update['message']['chat_id']
    msg_id = update['message']['id']
    message_content = update['message']['content']
    is_outgoing = update['message']['is_outgoing']
    message_text = message_content.get('text', {}).get('text', '')

    # This handler will block all message which satisfies ALL of the following condition:
    # 1. Incoming
    # 2. Not from group chat (Personal chat)
    # 3. chat_id is not in allowlist
    # 4. chat_id is not 777000 (Telegram official notification)
    # Maybe we can allowlist sender_id instead of chat_id, but I think it doesn't make a difference.

    if chat_id < 0 or chat_id == 777000:
        return
    if chat_id in allowlisted_chat_ids:
        return
    if is_outgoing:
        # Send any outgoing message to add unknown chat to allowlist. (Except verification message)
        if magic_text in message_text:
            return
        allowlisted_chat_ids.append(chat_id)
        write_allowlist()
        tg.send_message(chat_id=chat_id, text=magic_text + msg_allowlisted)
        return

    logging.info("Received a new private chat message which needs verification, chat_id=%s", chat_id)
    # Mark as read to suppress the notification.
    mark_msg_read(chat_id, msg_id)

    if message_content['@type'] == 'messageText' and message_text.lower() == YOUR_ANSWER.lower():
        # Answer is correct: add to allowlist and send hello
        logging.debug("good answer")
        allowlisted_chat_ids.append(chat_id)
        write_allowlist()
        tg.send_message(chat_id=chat_id, text=magic_text + msg_passed)
    else:
        # Answer is not correct: send verification message and delete his message.
        logging.debug("bad answer: %s, expected: %s", message_text.lower(), YOUR_ANSWER.lower())
        tg.send_message(chat_id=chat_id, text=magic_text + msg_verify)
        tg.delete_messages(chat_id, [msg_id])
        with remove_gms_notify_queue_lock:
            remove_gms_notify_queue.append((chat_id, msg_id, 16))

def timer_thread_func():
    while True:
        timer_handler()
        time.sleep(1)

if __name__ == "__main__":
    tg.login()
    result = tg.get_chats()
    result.wait()
    current_chat_ids = result.update.get("chat_ids", [])
    logging.info("Started Telegram Antispam Watchdog. API test by listing your chats: %s", current_chat_ids)
    if not any(allowlisted_chat_ids):
        logging.info("Adding the following chat IDs as we have an empty allowlist: %s", current_chat_ids)
        add_to_allowlist(current_chat_ids)

    missed_new_chats = [chat_id for chat_id in current_chat_ids if chat_id not in allowlisted_chat_ids]
    # If there are any new messages while the application was not running, let's challenge them.
    if any(missed_new_chats):
        messages = []
        for chat_id in missed_new_chats:
            messages_res = tg.get_chat_history(chat_id, limit=1)
            messages_res.wait()
            messages.append(messages_res.update.get("messages"))
        if any(messages):
            logging.info("Will challenge for the following missed messages: %s", messages)
            [message_handler({"message": message[0]}) for message in messages]

    threading.Thread(target=timer_thread_func).start()
    tg.add_message_handler(message_handler)
    tg.idle()
    logging.info("Exited")
    os._exit(0)
