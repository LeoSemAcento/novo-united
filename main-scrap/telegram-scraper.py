import os
import sqlite3
import json
import csv
import asyncio
from telethon import TelegramClient
from telethon.tl.types import (
    MessageMediaPhoto,
    MessageMediaDocument,
    User,
    PeerChannel,
    ForumTopic,
)
from telethon.tl.functions.channels import GetForumTopicsRequest
from telethon.errors import FloodWaitError, RPCError
import aiohttp
import sys
import re
from datetime import datetime


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


def normalize_id(channel_id):
    """Normaliza o ID do canal, adicionando prefixo -100 se necessário"""
    channel_id_str = str(channel_id)
    if channel_id_str.startswith('-100'):
        return channel_id_str
    elif channel_id_str.isdigit() and len(channel_id_str) >= 6:
        return f"-100{channel_id_str}"
    return channel_id_str


async def discover_internal_channels(group_id):
    """Descobre automaticamente todos os canais internos de um grupo"""
    try:
        normalized_id = normalize_id(group_id)
        entity = await client.get_entity(PeerChannel(int(normalized_id)))
        
        print(f"\n🔍 Descobrindo canais internos do grupo: {entity.title}")
        
        discovered_channels = []
        
        # Busca por canais internos nos diálogos
        async for dialog in client.iter_dialogs():
            if dialog.is_channel and not dialog.is_group:
                try:
                    dialog_entity = await client.get_entity(dialog.id)
                    
                    # Verifica se o canal está relacionado ao grupo
                    # Esta é uma heurística - pode precisar de ajustes baseados na estrutura específica
                    if hasattr(dialog_entity, 'linked_chat') and dialog_entity.linked_chat:
                        if str(dialog_entity.linked_chat.id) == str(entity.id):
                            discovered_channels.append({
                                'id': str(dialog_entity.id),
                                'title': dialog_entity.title
                            })
                            print(f"  📢 Canal interno encontrado: {dialog_entity.title} (ID: {dialog_entity.id})")
                    
                    # Verifica se o canal tem nome similar ao grupo (heurística adicional)
                    elif entity.title.lower() in dialog_entity.title.lower() or dialog_entity.title.lower() in entity.title.lower():
                        discovered_channels.append({
                            'id': str(dialog_entity.id),
                            'title': dialog_entity.title
                        })
                        print(f"  📢 Canal relacionado encontrado: {dialog_entity.title} (ID: {dialog_entity.id})")
                        
                except Exception as e:
                    continue
        
        # Busca por tópicos de fórum se o grupo for um fórum
        if getattr(entity, 'forum', False):
            try:
                topics_result = await client(
                    GetForumTopicsRequest(
                        channel=entity,
                        offset_date=datetime.now(),
                        offset_id=0,
                        offset_topic=0,
                        limit=100,
                    )
                )
                
                for topic in topics_result.topics:
                    if isinstance(topic, ForumTopic):
                        # Para tópicos de fórum, usamos o ID do grupo + ID do tópico
                        topic_full_id = f"{normalized_id}_{topic.id}"
                        discovered_channels.append({
                            'id': topic_full_id,
                            'title': f"{entity.title} - {topic.title}"
                        })
                        print(f"  📋 Tópico de fórum encontrado: {topic.title} (ID: {topic.id})")
                        
            except Exception as e:
                print(f"  ⚠️ Erro ao buscar tópicos de fórum: {e}")
        
        if discovered_channels:
            print(f"\n✅ Total de {len(discovered_channels)} canais internos descobertos!")
            return discovered_channels
        else:
            print("  ℹ️ Nenhum canal interno encontrado para este grupo.")
            return []
            
    except Exception as e:
        print(f"  ❌ Erro ao descobrir canais internos: {e}")
        return []


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
        now = datetime.now()
        filename = f"Canais {now.strftime('%d-%m-%y %H-%M')}.txt"
        print(f"\nListando Grupos e salvando em '{filename}'...")

        with open(filename, "w", encoding="utf-8") as f:
            async for dialog in client.iter_dialogs():
                if not (dialog.is_group or dialog.is_channel):
                    continue

                try:
                    entity = await client.get_entity(dialog.id)

                    title = entity.title
                    print(title)
                    f.write(f"{title}\n")

                    # Format ID
                    entity_id_str = str(entity.id)
                    if entity_id_str.startswith("-100"):
                        formatted_id = entity_id_str[4:]
                    else:
                        formatted_id = entity_id_str
                    print(formatted_id)
                    f.write(f"{formatted_id}\n")

                    if getattr(entity, "forum", False):
                        topics_result = await client(
                            GetForumTopicsRequest(
                                channel=entity,
                                offset_date=datetime.now(),
                                offset_id=0,
                                offset_topic=0,
                                limit=100,
                            )
                        )
                        for topic in topics_result.topics:
                            if isinstance(topic, ForumTopic):
                                topic_title = f"\t{topic.title}"
                                topic_id = f"\t{topic.id}"
                                print(topic_title)
                                print(topic_id)
                                f.write(f"{topic_title}\n")
                                f.write(f"{topic_id}\n")

                except Exception as e:
                    error_msg = f"Error processing '{dialog.name}': {e}"
                    print(error_msg)
                    f.write(f"{error_msg}\n")

        print(f"Lista de canais salva com sucesso em '{filename}'.")

    except Exception as e:
        print(f"Error listing channels: {e}")


async def manage_channels():
    while True:
        print("\nMenu:")
        print("A - Adicionar grupos (um ou vários IDs ou bloco de texto)")
        print("[R] Remove channel")
        print("[X] Remove ALL Channels")
        print("[S] Scrape all channels")
        print("[M] Toggle media scraping (currently {})".format("enabled" if state["scrape_media"] else "disabled"))
        print("[C] Continuous scraping")
        print("[E] Export data")
        print("[V] View saved channels")
        print("[L] Listar Grupos")
        print("[Q] Quit")

        choice = input("Enter your choice: ").lower()
        match (choice):
            case "a":
                channels_input = input("Digite o(s) ID(s) do(s) grupo(s) ou cole bloco de texto: ")
                import re
                # Extrai todos os números com 6 ou mais dígitos (IDs do Telegram)
                ids = re.findall(r"\b\d{6,}\b", channels_input)
                nomes_adicionados = []
                canais_internos_encontrados = []
                
                for channel_id in ids:
                    test_id = normalize_id(channel_id)
                    try:
                        group_name = await get_channel_title(test_id)
                        state["channels"][test_id] = 0
                        nomes_adicionados.append(group_name)
                        save_state(state)
                        print(f"✅ Adicionado grupo: {group_name} ({test_id})")
                        
                        # Descobre canais internos automaticamente
                        internal_channels = await discover_internal_channels(test_id)
                        if internal_channels:
                            for internal_channel in internal_channels:
                                internal_id = internal_channel['id']
                                internal_title = internal_channel['title']
                                state["channels"][internal_id] = 0
                                canais_internos_encontrados.append(internal_title)
                                print(f"  ➕ Canal interno adicionado: {internal_title} ({internal_id})")
                            save_state(state)
                            
                    except Exception as e:
                        print(f"❌ Não foi possível adicionar {channel_id}: {e}")
                
                if nomes_adicionados:
                    print(f"\n📋 Resumo da adição:")
                    print(f"   Grupos adicionados: {', '.join(nomes_adicionados)}")
                    if canais_internos_encontrados:
                        print(f"   Canais internos descobertos: {len(canais_internos_encontrados)}")
                        for canal in canais_internos_encontrados:
                            print(f"     - {canal}")
                    print(f"   Total de canais para raspagem: {len(state['channels'])}")
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
