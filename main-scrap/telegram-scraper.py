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
from telethon.errors.rpcerrorlist import ServerError, ChannelInvalidError, ChannelPrivateError, TimeoutError
import glob
import threading


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
DOWNLOADS_BASE = os.path.join(os.getcwd(), 'downloads')


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


def migrate_state_channels():
    changed = False
    for channel_id, channel_info in list(state.get("channels", {}).items()):
        if isinstance(channel_info, int):
            state["channels"][channel_id] = {
                "last_id": channel_info,
                "group_name": "Desconhecido",
                "channel_title": "Desconhecido"
            }
            changed = True
    if changed:
        print("[MIGRATION] State migrado para novo formato de canais.")
        save_state(state)


state = load_state()
migrate_state_channels()

if not state["api_id"] or not state["api_hash"] or not state["phone"]:
    state["api_id"] = int(input("Enter your API ID: "))
    state["api_hash"] = input("Enter your API Hash: ")
    state["phone"] = input("Enter your phone number: ")
    save_state(state)

client = TelegramClient("session", state["api_id"], state["api_hash"])


def sanitize_folder_name(name):
    # Substitui caracteres inválidos por espaço e remove espaços duplicados
    if not name or not isinstance(name, str):
        return "Desconhecido"
    sanitized = re.sub(r'[\\/:*?"<>|]', " ", name)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized if sanitized else "Desconhecido"


def sanitize_file_name(name):
    import os

    # Separa nome e extensão
    base, ext = os.path.splitext(name)
    # Substitui caracteres inválidos por '_'
    base = re.sub(r'[\\/:*?"<>|]', "_", base)
    # Trunca para 20 caracteres
    base = base[:20]
    return base + ext


# Dicionário global de locks por arquivo de banco
_db_locks = {}
_db_locks_lock = threading.Lock()

def get_db_lock(db_file):
    with _db_locks_lock:
        if db_file not in _db_locks:
            _db_locks[db_file] = asyncio.Lock()
        return _db_locks[db_file]


async def save_message_to_db(download_path, message, sender, base_dir=None):
    if base_dir is None:
        base_dir = os.getcwd()
    channel_dir = os.path.join(base_dir, download_path)
    os.makedirs(channel_dir, exist_ok=True)
    db_file = os.path.join(channel_dir, f"{os.path.basename(download_path)}.db")
    db_lock = get_db_lock(db_file)
    async with db_lock:
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


# Helper para log detalhado de falhas
def log_failed_download(download_path, message_id, reason, group_name, channel_title, file_name=None):
    failed_log = os.path.join(DOWNLOADS_BASE, download_path, "failed_downloads.json")
    entry = {
        "message_id": message_id,
        "datetime": datetime.now().isoformat(),
        "reason": str(reason),
        "group_name": group_name,
        "channel_title": channel_title,
        "file_name": file_name or ""
    }
    try:
        if os.path.exists(failed_log):
            with open(failed_log, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = []
        data.append(entry)
        with open(failed_log, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[LOG ERROR] Falha ao registrar erro de download: {e}")


# Helper seguro para get_entity
async def get_entity_safe(client, peer, channel_id=None):
    # Segurança extra: nunca permitir chamada direta a client.get_entity fora deste helper
    import inspect
    stack = inspect.stack()
    for frame in stack[1:]:
        if 'get_entity' in frame.code_context[0] and 'get_entity_safe' not in frame.code_context[0]:
            print('[SECURITY WARNING] Chamada insegura a client.get_entity detectada! Use sempre get_entity_safe.')
    try:
        return await client.get_entity(peer)
    except (ChannelInvalidError, ChannelPrivateError, ValueError) as e:
        print(f"[REMOVIDO DEFINITIVO] Canal/tópico {peer} removido do state: {e}")
        if channel_id and str(channel_id) in state["channels"]:
            del state["channels"][str(channel_id)]
            save_state(state)
        return None
    except (FloodWaitError, ServerError, TimeoutError) as e:
        print(f"[TEMPORÁRIO] Falha temporária ao acessar {peer}: {e}. Tente novamente mais tarde.")
        return None
    except Exception as e:
        print(f"[ERRO] Falha inesperada ao acessar {peer}: {e}")
        return None


async def download_media(download_path, message, semaphore, group_name=None, channel_title=None):
    if not message.media or not state["scrape_media"]:
        return None
    channel_dir = os.path.join(DOWNLOADS_BASE, download_path)
    media_folder = os.path.join(channel_dir, "media")
    os.makedirs(media_folder, exist_ok=True)
    message_id = message.id
    failed_db = os.path.join(channel_dir, "failed.json")
    failed_ids = set()
    if os.path.exists(failed_db):
        try:
            with open(failed_db, "r", encoding="utf-8") as f:
                failed_ids = set(json.load(f))
        except Exception:
            failed_ids = set()
    if message_id in failed_ids:
        print(f"[SKIP] Mensagem {message_id} já marcada como FAILED. Ignorando download.")
        return None
    # Determinar nome do arquivo
    file_name = f"{message_id}.bin"
    if message.media and hasattr(message.media, 'document') and getattr(message.media.document, 'attributes', None):
        for attr in message.media.document.attributes:
            if hasattr(attr, 'file_name'):
                file_name = attr.file_name
                break
    media_path = os.path.join(media_folder, file_name)
    
    # Mostrar início do download
    print(f"[DOWNLOAD] Iniciando download: {file_name} (ID: {message_id})")
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with semaphore:
                print(f"[DOWNLOAD] Tentativa {attempt}/{MAX_RETRIES} para {file_name}...")
                result_path = await message.download_media(file=media_path)
            if result_path:
                print(f"[DOWNLOAD] ✅ Sucesso: {file_name} -> {os.path.abspath(result_path)}")
                return result_path
            else:
                print(f"[DOWNLOAD] ❌ Download retornou None para mensagem {message_id}!")
        except Exception as e:
            print(f"[DOWNLOAD] ⚠️ Tentativa {attempt} falhou para {file_name}: {e}")
            if attempt < MAX_RETRIES:
                print(f"[DOWNLOAD] Aguardando 2 segundos antes da próxima tentativa...")
                await asyncio.sleep(2)
    
    # Após 5 tentativas, marca como FAILED e loga detalhado
    print(f"[DOWNLOAD] ❌ Falha definitiva ao baixar {file_name} (ID: {message_id})")
    failed_ids.add(message_id)
    with open(failed_db, "w", encoding="utf-8") as f:
        json.dump(list(failed_ids), f, ensure_ascii=False, indent=2)
    log_failed_download(download_path, message_id, e, group_name, channel_title, file_name)
    return None


async def rescrape_media(channel):
    channel_dir = os.path.join(os.getcwd(), channel)
    db_file = os.path.join(channel_dir, f"{channel}.db")
    db_lock = get_db_lock(db_file)
    async with db_lock:
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
            normalized_id = normalize_id(message_id)
            print(f"[DEBUG] ID original: {message_id} | ID normalizado: {normalized_id}")
            entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
            message = await client.get_messages(entity, ids=message_id)
            media_path = await download_media(channel, message)
            if media_path:
                async with db_lock:
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
    normalized_id = normalize_id(channel_id)
    entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
    if entity and hasattr(entity, 'title'):
        return sanitize_folder_name(entity.title)
    return "Desconhecido"


def normalize_id(channel_id):
    """Normaliza o ID do canal, adicionando prefixo -100 se necessário"""
    channel_id_str = str(channel_id)
    if channel_id_str.startswith('-100'):
        return channel_id_str
    elif channel_id_str.isdigit() and len(channel_id_str) >= 6:
        return f"-100{channel_id_str}"
    return channel_id_str


async def discover_internal_channels(group_id, group_title):
    try:
        normalized_id = normalize_id(group_id)
        print(f"[DEBUG] ID original: {group_id} | ID normalizado: {normalized_id}")
        entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
        if not entity:
            print(f"[SKIP] Canal/tópico {normalized_id} inválido ou removido. Pulando.")
            return
        print(f"\n🔍 Descobrindo canais internos do grupo: {entity.title}")
        discovered_channels = []
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
                        topic_full_id = f"{normalized_id}_{topic.id}"
                        discovered_channels.append({
                            'id': topic_full_id,
                            'title': topic.title
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


async def scrape_channel(channel_id, offset_id, download_path):
    # Robustez: se offset_id for dict, extrair corretamente
    if isinstance(offset_id, dict):
        print("[WARNING] Chamada incorreta para scrape_channel detectada. Corrigindo parâmetros automaticamente.")
        last_id = offset_id.get("last_id", 0)
        group_name = offset_id.get("group_name", "Desconhecido")
        channel_title = offset_id.get("channel_title", None)
        # Buscar nomes reais se possível
        normalized_id = normalize_id(channel_id)
        entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
        if entity and hasattr(entity, 'title'):
            channel_title = sanitize_folder_name(entity.title)
        if 'group_name' in offset_id and offset_id['group_name'] != "Desconhecido":
            group_name = sanitize_folder_name(offset_id['group_name'])
        elif entity and hasattr(entity, 'title'):
            group_name = sanitize_folder_name(entity.title)
        download_path = get_download_path(group_name, channel_title)
        offset_id = last_id
    try:
        # Robustez extra: tratar qualquer tipo de channel_id
        original_id = channel_id
        if isinstance(channel_id, dict):
            channel_id = channel_id.get('id') or channel_id.get('channel_id') or list(channel_id.values())[0]
        if isinstance(channel_id, str) and '_' in channel_id:
            channel_id = channel_id.split('_')[0]
        try:
            normalized_id = normalize_id(channel_id)
        except Exception as e:
            print(f"[ERRO] Não foi possível normalizar o ID {original_id}: {e}. Removendo do state.")
            if str(original_id) in state["channels"]:
                del state["channels"][str(original_id)]
                save_state(state)
            return
        print(f"[DEBUG] ID original: {original_id} | ID normalizado: {normalized_id}")
        entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
        if not entity:
            print(f"[SKIP] Canal/tópico {normalized_id} inválido ou removido. Pulando.")
            if str(original_id) in state["channels"]:
                del state["channels"][str(original_id)]
                save_state(state)
            return
        if entity and hasattr(entity, 'title'):
            channel_title = sanitize_folder_name(entity.title)
        else:
            channel_title = "Desconhecido"
        # Buscar group_name do state se possível
        group_name = None
        if str(original_id) in state["channels"]:
            group_name = state["channels"][str(original_id)].get("group_name", None)
        if not group_name or group_name == "Desconhecido":
            group_name = channel_title
        download_path = get_download_path(group_name, channel_title)
        total_messages = 0
        processed_messages = 0
        semaphore = asyncio.Semaphore(10)
        try:
            async for message in client.iter_messages(
                entity, offset_id=offset_id, reverse=True
            ):
                sys.stdout.write("\r\033[K")
                sys.stdout.write(
                    f"Counting messages in: {group_name} - Messages found: {total_messages}"
                )
                sys.stdout.flush()
                total_messages += 1
        except (RPCError, ConnectionError, Exception) as e:
            print(f"[ERROR] Failed to iterate messages for {group_name}: {e}")
            return
        if total_messages == 0:
            print(f"No messages found in channel {group_name}.")
            return
        last_message_id = None
        processed_messages = 0
        download_count = 0
        total_downloads = 0
        
        # Primeiro, contar quantos downloads serão necessários
        try:
            async for message in client.iter_messages(
                entity, offset_id=offset_id, reverse=True
            ):
                if state["scrape_media"] and message.media:
                    total_downloads += 1
        except (RPCError, ConnectionError, Exception) as e:
            print(f"[ERROR] Failed to count downloads for {group_name}: {e}")
            return
        
        print(f"[INFO] Total de {total_downloads} arquivos para download em {group_name}")
        
        # Agora processar mensagens e fazer downloads sequenciais
        try:
            async for message in client.iter_messages(
                entity, offset_id=offset_id, reverse=True
            ):
                try:
                    sender = await message.get_sender()
                    save_message_to_db(download_path, message, sender, base_dir=DOWNLOADS_BASE)
                    
                    if state["scrape_media"] and message.media:
                        download_count += 1
                        print(f"\n[DOWNLOAD {download_count}/{total_downloads}] Processando arquivo...")
                        await download_media(download_path, message, semaphore, group_name, channel_title)
                    
                    last_message_id = message.id
                    processed_messages += 1
                    progress = (processed_messages / total_messages) * 100
                    sys.stdout.write("\r\033[K")
                    sys.stdout.write(
                        f"\rScraping channel: {group_name} - Progress: {progress:.2f}% ({processed_messages}/{total_messages})"
                    )
                    sys.stdout.flush()
                    state["channels"][str(normalized_id)]["last_id"] = last_message_id
                    save_state(state)
                except Exception as e:
                    if "very old message" in str(e) or "too many messages had to be ignored" in str(e):
                        print(f"[SKIP] Canal/tópico {normalized_id} pulado por mensagens antigas/ignoradas. Avançando last_id.")
                        # Avança o last_id para pular buraco
                        state["channels"][normalized_id]["last_id"] = state["channels"][normalized_id]["last_id"] + 100
                        save_state()
                        return
                    else:
                        print(f"[ERRO] Falha ao processar mensagem: {e}")
        except (RPCError, ConnectionError, Exception) as e:
            print(f"[ERROR] Failed to iterate/process messages for {group_name}: {e}")
        
        print(f"\n[INFO] Scraping concluído para {group_name}: {processed_messages} mensagens processadas, {download_count} arquivos baixados")
    except ValueError as e:
        print(f"Error with channel {normalized_id}: {e}")


async def continuous_scraping():
    global continuous_scraping_active
    continuous_scraping_active = True
    try:
        while continuous_scraping_active:
            for channel_id, channel_info in list(state["channels"].items()):
                print(f"\nChecking for new messages in channel: {channel_id}")
                last_id = channel_info["last_id"]
                group_name = channel_info["group_name"]
                channel_title = channel_info.get("channel_title")
                download_path = get_download_path(group_name, channel_title)
                await scrape_channel(channel_id, last_id, download_path)
                print(f"New messages or media scraped from channel: {channel_id}")
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
                    normalized_id = normalize_id(dialog.id)
                    entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
                    if not entity:
                        print(f"[SKIP] Canal/tópico {normalized_id} inválido ou removido. Pulando.")
                        continue

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
        # Exibe resumo dos canais salvos ao iniciar o menu
        if state["channels"]:
            print("\nCanais salvos na memória: {}".format(len(state["channels"])))
            for channel_id, channel_info in list(state["channels"].items())[:5]:
                try:
                    group_name = channel_info["group_name"]
                    channel_title = channel_info.get("channel_title")
                    if channel_title:
                        print(f"- {group_name} / {channel_title} (ID: {channel_id})")
                    else:
                        print(f"- {group_name} (ID: {channel_id})")
                except Exception:
                    print(f"- ID: {channel_id}")
            if len(state["channels"]) > 5:
                print(f"... e mais {len(state['channels'])-5} canais.")
        else:
            print("\nNenhum canal salvo. Use [A] para adicionar canais.")
        print("\nMenu:")
        print("[A] Adicionar grupos (um ou vários IDs ou bloco de texto)")
        print("[R] Remove channel")
        print("[X] Remove ALL Channels")
        print("[S] Scrape all channels")
        print("[M] Toggle media scraping (currently {})".format("enabled" if state["scrape_media"] else "disabled"))
        print("[C] Continuous scraping")
        print("[E] Export data")
        print("[V] View saved channels")
        print("[L] Listar Grupos")
        print("[F] Retry problemáticos")
        print("[R] Relatório de falhas")
        print("[Q] Quit")
        choice = input("Enter your choice: ").strip().lower()
        if choice == "a":
            group_ids = input("Digite o(s) ID(s) do(s) grupo(s) ou cole bloco de texto: ").split()
            for group_id in group_ids:
                try:
                    normalized_id = normalize_id(group_id)
                    print(f"[DEBUG] ID original: {group_id} | ID normalizado: {normalized_id}")
                    entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
                    if not entity:
                        print(f"[SKIP] Canal/tópico {normalized_id} inválido ou removido. Pulando.")
                        continue
                    group_name = sanitize_folder_name(entity.title)
                    discovered = await discover_internal_channels(normalized_id, group_name)
                    if discovered:
                        for ch in discovered:
                            ch_id = ch["id"]
                            ch_title = ch["title"]
                            state["channels"][str(normalize_id(ch_id))] = {"last_id": 0, "group_name": group_name, "channel_title": ch_title}
                            print(f"  ➕ Canal interno adicionado: {group_name} / {ch_title} ({ch_id})")
                        print(f"📋 Resumo da adição:\n   Grupos adicionados: {group_name}\n   Canais internos descobertos: {len(discovered)}")
                        for ch in discovered:
                            print(f"     - {ch['title']}")
                        print(f"   Total de canais para raspagem: {len(discovered)+1}")
                    else:
                        # Grupo sem canais internos
                        state["channels"][str(normalize_id(group_id))] = {"last_id": 0, "group_name": group_name}
                        print(f"✅ Adicionado grupo: {group_name} ({group_id})")
                    save_state(state)
                except Exception as e:
                    print(f"Erro ao adicionar grupo {group_id}: {e}")
        elif choice == "r":
            channel_id = input("Enter channel ID to remove: ")
            if channel_id in state["channels"]:
                del state["channels"][channel_id]
                save_state(state)
                print(f"Removed channel {channel_id}.")
            else:
                print(f"Channel {channel_id} not found.")
        elif choice == "x":
            confirm = input(
                "Are you sure you want to remove ALL channels? (yes/no): "
            ).lower()
            if confirm == "yes":
                state["channels"] = {}
                save_state(state)
                print("All channels have been removed.")
            else:
                print("Operation cancelled.")
        elif choice == "s":
            for channel_id, channel_info in list(state["channels"].items()):
                last_id = channel_info["last_id"]
                group_name = channel_info["group_name"]
                channel_title = channel_info.get("channel_title")
                download_path = get_download_path(group_name, channel_title)
                await scrape_channel(channel_id, last_id, download_path)
        elif choice == "m":
            state["scrape_media"] = not state["scrape_media"]
            save_state(state)
            print(
                f"Media scraping {'enabled' if state['scrape_media'] else 'disabled'}."
            )
        elif choice == "c":
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
        elif choice == "e":
            for channel_id in state["channels"]:
                group_name = state["channels"][channel_id]["group_name"]
                export_to_csv(group_name)
                export_to_json(group_name)
        elif choice == "v":
            if not state["channels"]:
                print("No channels to view.")
            else:
                print("\nCurrent channels:")
                for channel_id in state["channels"]:
                    group_name = state["channels"][channel_id]["group_name"]
                    print(f"Channel: {group_name} (ID: {channel_id})")
        elif choice == "f":
            await retry_problematic_downloads()
        elif choice == "r":
            generate_failure_report()
        elif choice == "q":
            print("Quitting...")
            sys.exit()
        elif choice == "l":
            await list_Channels()
        else:
            print("Invalid option.")


async def main():
    await client.start()
    while True:
        await manage_channels()


def generate_failure_report():
    from datetime import datetime
    now = datetime.now().strftime("%d-%m-%y %H-%M")
    report_path = f"relatorio_falhas {now}.csv"
    with open(report_path, "w", encoding="utf-8", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Grupo", "Canal/Tópico", "message_id", "Nome do arquivo", "Motivo", "Data/Hora"])
        for failed_file in glob.glob(os.path.join(DOWNLOADS_BASE, "*", "failed_downloads.json")):
            group = os.path.basename(os.path.dirname(os.path.dirname(failed_file)))
            channel = os.path.basename(os.path.dirname(failed_file))
            try:
                with open(failed_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for entry in data:
                    writer.writerow([
                        entry.get("group_name", group),
                        entry.get("channel_title", channel),
                        entry.get("message_id", ""),
                        entry.get("file_name", ""),
                        entry.get("reason", ""),
                        entry.get("datetime", "")
                    ])
            except Exception as e:
                print(f"[REPORT ERROR] Falha ao ler {failed_file}: {e}")
    print(f"Relatório de falhas gerado: {report_path}")


async def retry_problematic_downloads():
    print("Iniciando retry de arquivos problemáticos...")
    for failed_file in glob.glob(os.path.join(DOWNLOADS_BASE, "*", "failed_downloads.json")):
        group = os.path.basename(os.path.dirname(os.path.dirname(failed_file)))
        channel = os.path.basename(os.path.dirname(failed_file))
        download_path = os.path.join(group, channel)
        try:
            with open(failed_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[RETRY ERROR] Falha ao ler {failed_file}: {e}")
            continue
        if not data:
            continue
        # Retry em batches de 10
        batch = data[:10]
        rest = data[10:]
        new_failed = []
        for entry in batch:
            message_id = entry["message_id"]
            file_name = entry.get("file_name")
            motivo = entry.get("reason")
            try:
                # Buscar a mensagem pelo ID
                normalized_id = normalize_id(message_id)
                print(f"[DEBUG] ID original: {message_id} | ID normalizado: {normalized_id}")
                entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
                if not entity:
                    new_failed.append(entry)
                    continue
                message = await client.get_messages(entity, ids=message_id)
                # Checar se já existe o arquivo
                channel_dir = os.path.join(DOWNLOADS_BASE, download_path)
                media_folder = os.path.join(channel_dir, "media")
                if file_name and os.path.exists(os.path.join(media_folder, file_name)):
                    print(f"[SKIP] Arquivo já existe: {file_name}")
                    continue
                # Tentar baixar
                result = await download_media(download_path, message, asyncio.Semaphore(1), group, channel)
                if result:
                    print(f"[RETRY OK] Baixado: {file_name or message_id}")
                else:
                    print(f"[RETRY FAIL] Falha ao baixar: {file_name or message_id}")
                    entry["datetime"] = datetime.now().isoformat()
                    new_failed.append(entry)
            except Exception as e:
                print(f"[RETRY ERROR] Falha ao tentar baixar {file_name or message_id}: {e}")
                entry["reason"] = str(e)
                entry["datetime"] = datetime.now().isoformat()
                new_failed.append(entry)
        # Atualiza o arquivo de falhas
        with open(failed_file, "w", encoding="utf-8") as f:
            json.dump(rest + new_failed, f, ensure_ascii=False, indent=2)
    print("Retry de arquivos problemáticos finalizado.")


# Função utilitária para obter o caminho de download correto

def get_download_path(group_name, channel_title=None):
    group_name = sanitize_folder_name(group_name)
    if channel_title:
        channel_title = sanitize_folder_name(channel_title)
        return os.path.join(group_name, channel_title)
    return group_name


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted. Exiting...")
        sys.exit()
