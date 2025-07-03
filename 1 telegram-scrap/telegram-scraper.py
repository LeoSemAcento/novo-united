import os
import sqlite3
import json
import csv
import asyncio
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, User, PeerChannel
from telethon.errors import FloodWaitError, RPCError
import aiohttp
import sys
import re


def display_ascii_art():
    WHITE = "\033[97m"
    RESET = "\033[0m"

    art = r"""
 _                   ___                  
| |                 / _ \                 
| |     ___  ___   / /_\ \_ __  _ __  ___ 
| |    / _ \/ _ \  |  _  | '_ \| '_ \/ __|
| |___|  __/ (_) | | | | | |_) | |_) \__ \
\_____/\___|\___/  \_| |_/ .__/| .__/|___/
                         | |   | |        
                         |_|   |_|        
"""

    print(WHITE + art + RESET)


display_ascii_art()

STATE_FILE = "state.json"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "api_id": None,
        "api_hash": None,
        "phone": None,
        "channels": {},
        "scrape_media": True,
    }


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


state = load_state()

if not state["api_id"] or not state["api_hash"] or not state["phone"]:
    state["api_id"] = int(input("Enter your API ID: "))
    state["api_hash"] = input("Enter your API Hash: ")
    state["phone"] = input("Enter your phone number: ")
    save_state(state)

client = TelegramClient("session", state["api_id"], state["api_hash"])


def sanitize_folder_name(name):
    # Substitui caracteres inválidos por espaço
    return re.sub(r'[\\/:*?"<>|]', " ", name)


def sanitize_file_name(name):
    import os

    # Separa nome e extensão
    base, ext = os.path.splitext(name)
    # Substitui caracteres inválidos por '_'
    base = re.sub(r'[\\/:*?"<>|]', "_", base)
    # Trunca para 20 caracteres
    base = base[:20]
    return base + ext


def save_message_to_db(channel, message, sender):
    channel_dir = os.path.join(os.getcwd(), channel)
    os.makedirs(channel_dir, exist_ok=True)

    db_file = os.path.join(channel_dir, f"{channel}.db")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        f"""CREATE TABLE IF NOT EXISTS messages
                  (id INTEGER PRIMARY KEY, message_id INTEGER, date TEXT, sender_id INTEGER, first_name TEXT, last_name TEXT, username TEXT, message TEXT, media_type TEXT, media_path TEXT, reply_to INTEGER)"""
    )
    c.execute(
        """INSERT OR IGNORE INTO messages (message_id, date, sender_id, first_name, last_name, username, message, media_type, media_path, reply_to)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            message.id,
            message.date.strftime("%Y-%m-%d %H:%M:%S"),
            message.sender_id,
            getattr(sender, "first_name", None) if isinstance(sender, User) else None,
            getattr(sender, "last_name", None) if isinstance(sender, User) else None,
            getattr(sender, "username", None) if isinstance(sender, User) else None,
            message.message,
            message.media.__class__.__name__ if message.media else None,
            None,
            message.reply_to_msg_id if message.reply_to else None,
        ),
    )
    conn.commit()
    conn.close()


MAX_RETRIES = 5


async def download_media(channel, message):
    if not message.media or not state["scrape_media"]:
        return None

    channel_dir = os.path.join(os.getcwd(), channel)
    media_folder = os.path.join(channel_dir, "media")
    os.makedirs(media_folder, exist_ok=True)
    media_file_name = None
    try:
        if hasattr(message.media, "document") and hasattr(
            message.media.document, "attributes"
        ):
            for attr in message.media.document.attributes:
                if hasattr(attr, "file_name"):
                    media_file_name = attr.file_name
                    break
        if not media_file_name:
            if hasattr(message.media, "file") and hasattr(message.media.file, "name"):
                media_file_name = message.media.file.name
        if not media_file_name:
            media_file_name = f"{message.id}.bin"
        # Sanitiza o nome do arquivo
        media_file_name = sanitize_file_name(media_file_name)
        media_path = os.path.join(media_folder, media_file_name)
        if os.path.exists(media_path):
            print(f"Media file already exists: {media_path}")
            return media_path
        retries = 0
        while retries < MAX_RETRIES:
            try:
                media_path = await message.download_media(file=media_path)
                if media_path:
                    print(f"Successfully downloaded media to: {media_path}")
                break
            except (TimeoutError, aiohttp.ClientError, RPCError) as e:
                retries += 1
                print(
                    f"Retrying download for message {message.id}. Attempt {retries}..."
                )
                await asyncio.sleep(2**retries)
        return media_path
    except Exception as e:
        log_path = os.path.join(media_folder, "download_errors.log")
        with open(log_path, "a", encoding="utf-8") as logf:
            logf.write(f"Error saving file for message {message.id}: {e}\n")
        print(f"Error saving file for message {message.id}: {e}")
        return None


async def rescrape_media(channel):
    channel_dir = os.path.join(os.getcwd(), channel)
    db_file = os.path.join(channel_dir, f"{channel}.db")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        "SELECT message_id FROM messages WHERE media_type IS NOT NULL AND media_path IS NULL"
    )
    rows = c.fetchall()
    conn.close()

    total_messages = len(rows)
    if total_messages == 0:
        print(f"No media files to reprocess for channel {channel}.")
        return

    for index, (message_id,) in enumerate(rows):
        try:
            entity = await client.get_entity(PeerChannel(int(channel)))
            message = await client.get_messages(entity, ids=message_id)
            media_path = await download_media(channel, message)
            if media_path:
                conn = sqlite3.connect(db_file)
                c = conn.cursor()
                c.execute(
                    """UPDATE messages SET media_path = ? WHERE message_id = ?""",
                    (media_path, message_id),
                )
                conn.commit()
                conn.close()

            progress = (index + 1) / total_messages * 100
            sys.stdout.write(
                f"\rReprocessing media for channel {channel}: {progress:.2f}% complete"
            )
            sys.stdout.flush()
        except Exception as e:
            print(f"Error reprocessing message {message_id}: {e}")
    print()


async def get_channel_title(channel_id):
    if str(channel_id).startswith("-"):
        entity = await client.get_entity(PeerChannel(int(channel_id)))
    else:
        entity = await client.get_entity(channel_id)
    return sanitize_folder_name(entity.title)


async def scrape_channel(channel_id, offset_id):
    try:
        if str(channel_id).startswith("-"):
            entity = await client.get_entity(PeerChannel(int(channel_id)))
        else:
            entity = await client.get_entity(channel_id)
        group_name = sanitize_folder_name(entity.title)
        total_messages = 0
        processed_messages = 0
        async for message in client.iter_messages(
            entity, offset_id=offset_id, reverse=True
        ):
            sys.stdout.write("\r\033[K")
            sys.stdout.write(
                f"Counting messages in: {group_name} - Messages found: {total_messages}"
            )
            sys.stdout.flush()
            total_messages += 1
        if total_messages == 0:
            print(f"No messages found in channel {group_name}.")
            return
        last_message_id = None
        processed_messages = 0
        async for message in client.iter_messages(
            entity, offset_id=offset_id, reverse=True
        ):
            try:
                sender = await message.get_sender()
                save_message_to_db(group_name, message, sender)
                if state["scrape_media"] and message.media:
                    media_path = await download_media(group_name, message)
                    if media_path:
                        conn = sqlite3.connect(
                            os.path.join(group_name, f"{group_name}.db")
                        )
                        c = conn.cursor()
                        c.execute(
                            """UPDATE messages SET media_path = ? WHERE message_id = ?""",
                            (media_path, message.id),
                        )
                        conn.commit()
                        conn.close()
                last_message_id = message.id
                processed_messages += 1
                progress = (processed_messages / total_messages) * 100
                sys.stdout.write("\r\033[K")
                sys.stdout.write(
                    f"\rScraping channel: {group_name} - Progress: {progress:.2f}%"
                )
                sys.stdout.flush()
                state["channels"][str(channel_id)] = last_message_id
                save_state(state)
            except Exception as e:
                print(f"Error processing message {message.id}: {e}")
        print()
    except ValueError as e:
        print(f"Error with channel {channel_id}: {e}")


async def continuous_scraping():
    global continuous_scraping_active
    continuous_scraping_active = True

    try:
        while continuous_scraping_active:
            for channel in state["channels"]:
                print(f"\nChecking for new messages in channel: {channel}")
                await scrape_channel(channel, state["channels"][channel])
                print(f"New messages or media scraped from channel: {channel}")
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        print("Continuous scraping stopped.")
        continuous_scraping_active = False


async def export_data():
    for channel in state["channels"]:
        export_to_csv(channel)
        export_to_json(channel)


def export_to_csv(channel):
    db_file = os.path.join(channel, f"{channel}.db")
    csv_file = os.path.join(channel, f"{channel}.csv")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("SELECT * FROM messages")
    rows = c.fetchall()
    conn.close()

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([description[0] for description in c.description])
        writer.writerows(rows)


def export_to_json(channel):
    db_file = os.path.join(channel, f"{channel}.db")
    json_file = os.path.join(channel, f"{channel}.json")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("SELECT * FROM messages")
    rows = c.fetchall()
    conn.close()

    data = [
        dict(zip([description[0] for description in c.description], row))
        for row in rows
    ]
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


async def view_channels():
    if not state["channels"]:
        print("No channels to view.")
        return

    print("\nCurrent channels:")
    for channel, last_id in state["channels"].items():
        print(f"Channel ID: {channel}, Last Message ID: {last_id}")


async def list_Channels():
    try:
        print("\nList of groups and channels joined by account: ")
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                print(f"* {dialog.title} (id: {dialog.id})")
    except Exception as e:
        print(f"Error processing: {e}")


async def manage_channels():
    while True:
        print("\nMenu:")
        print("[A] Add new channel")
        print("[B] Add multiple channels")
        print("[R] Remove channel")
        print("[X] Remove ALL Channels")
        print("[S] Scrape all channels")
        print(
            "[M] Toggle media scraping (currently {})".format(
                "enabled" if state["scrape_media"] else "disabled"
            )
        )
        print("[C] Continuous scraping")
        print("[E] Export data")
        print("[V] View saved channels")
        print("[L] List account channels")
        print("[Q] Quit")

        choice = input("Enter your choice: ").lower()
        match (choice):
            case "a":
                channel_id = input("Enter channel ID: ")
                state["channels"][channel_id] = 0
                save_state(state)
                group_name = await get_channel_title(channel_id)
                print(f"Added channel {group_name} ({channel_id}).")
            case "b":
                channels = input("Enter channel IDs separated by comma and space: ")
                for channel_id in [c.strip() for c in channels.split(",") if c.strip()]:
                    state["channels"][channel_id] = 0
                    group_name = await get_channel_title(channel_id)
                    print(f"Added channel {group_name} ({channel_id}).")
                save_state(state)
            case "r":
                channel_id = input("Enter channel ID to remove: ")
                if channel_id in state["channels"]:
                    del state["channels"][channel_id]
                    save_state(state)
                    print(f"Removed channel {channel_id}.")
                else:
                    print(f"Channel {channel_id} not found.")
            case "x":
                confirm = input(
                    "Are you sure you want to remove ALL channels? (yes/no): "
                ).lower()
                if confirm == "yes":
                    state["channels"] = {}
                    save_state(state)
                    print("All channels have been removed.")
                else:
                    print("Operation cancelled.")
            case "s":
                for channel_id in state["channels"]:
                    await scrape_channel(channel_id, state["channels"][channel_id])
            case "m":
                state["scrape_media"] = not state["scrape_media"]
                save_state(state)
                print(
                    f"Media scraping {'enabled' if state['scrape_media'] else 'disabled'}."
                )
            case "c":
                global continuous_scraping_active
                continuous_scraping_active = True
                task = asyncio.create_task(continuous_scraping())
                print("Continuous scraping started. Press Ctrl+C to stop.")
                try:
                    await asyncio.sleep(float("inf"))
                except KeyboardInterrupt:
                    continuous_scraping_active = False
                    task.cancel()
                    print("\nStopping continuous scraping...")
                    await task
            case "e":
                for channel_id in state["channels"]:
                    group_name = await get_channel_title(channel_id)
                    export_to_csv(group_name)
                    export_to_json(group_name)
            case "v":
                if not state["channels"]:
                    print("No channels to view.")
                else:
                    print("\nCurrent channels:")
                    for channel_id in state["channels"]:
                        group_name = await get_channel_title(channel_id)
                        print(f"Channel: {group_name} (ID: {channel_id})")
            case "q":
                print("Quitting...")
                sys.exit()
            case "l":
                await list_Channels()
            case _:
                print("Invalid option.")


async def main():
    await client.start()
    while True:
        await manage_channels()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted. Exiting...")
        sys.exit()
