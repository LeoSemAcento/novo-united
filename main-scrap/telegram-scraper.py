import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
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
import re
from datetime import datetime
from telethon.errors.rpcerrorlist import ServerError, ChannelInvalidError, ChannelPrivateError, TimeoutError
import glob
import threading
import mimetypes
from pathlib import Path

# ===== IMPORTAÇÕES DAS FUNÇÕES UTILITÁRIAS =====
from utils import (
    logger,
    sanitize_folder_name_advanced,
    validate_and_create_path,
    get_media_info,
    MIME_EXTENSIONS
)


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

    logger.info("Exibindo arte ASCII do app.")
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
        logger.info("[MIGRATION] State migrado para novo formato de canais.")
        save_state(state)

state = load_state()
migrate_state_channels()

if not state["api_id"] or not state["api_hash"] or not state["phone"]:
    state["api_id"] = int(input("Enter your API ID: "))
    state["api_hash"] = input("Enter your API Hash: ")
    state["phone"] = input("Enter your phone number: ")
    save_state(state)

client = TelegramClient("session", state["api_id"], state["api_hash"])


# Dicionário global de locks por arquivo de banco
_db_locks = {}
_db_locks_lock = threading.Lock()

def get_db_lock(db_file):
    with _db_locks_lock:
        if db_file not in _db_locks:
            _db_locks[db_file] = asyncio.Lock()
        return _db_locks[db_file]


def save_message_to_db(folder, message, group_name, channel_origin, media_type=None, media_path=None):
    db_file = Path(folder) / "mensagens.db"
    try:
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                date TEXT,
                sender_name TEXT,
                group_name TEXT,
                channel_origin TEXT,
                text TEXT,
                media_type TEXT,
                media_path TEXT
            )"""
        )
        sender_name = None
        if hasattr(message, 'sender') and message.sender:
            sender_name = getattr(message.sender, 'first_name', None) or getattr(message.sender, 'username', None)
        c.execute(
            """INSERT INTO messages (message_id, date, sender_name, group_name, channel_origin, text, media_type, media_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message.id,
                str(message.date),
                sender_name,
                group_name,
                channel_origin,
                getattr(message, 'text', None),
                media_type,
                str(media_path) if media_path else None
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERRO][DB] Falha ao salvar mensagem no SQLite: {e}. Salvando em JSON como fallback.")
        save_message_to_json(folder, message, group_name, channel_origin, media_type, media_path)


def save_message_to_json(folder, message, group_name, channel_origin, media_type=None, media_path=None):
    msg_data = {
        "id": message.id,
        "date": str(message.date),
        "sender_name": getattr(message.sender, 'first_name', None) if hasattr(message, 'sender') and message.sender else None,
        "group_name": group_name,
        "channel_origin": channel_origin,
        "text": getattr(message, 'text', None),
        "media_type": media_type,
        "media_path": str(media_path) if media_path else None
    }
    path = Path(folder) / "mensagens.json"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg_data, ensure_ascii=False) + "\n")


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


async def download_media(download_path, message, semaphore):
    try:
        # Usa detecção robusta de mídia
        media_info = get_media_info(message)
        if not media_info['filename']:
            logger.warning(f"Mensagem {message.id} não tem mídia válida")
            return None
        # Cria subpasta por tipo
        final_path = Path(download_path) / "media" / media_info['type']
        final_path = validate_and_create_path(final_path, f"pasta de mídia {media_info['type']}")
        filename_base = media_info['filename']
        extension = media_info['extension']
        file_path = final_path / f"{filename_base}{extension}"
        # Evita sobrescrever arquivos
        counter = 1
        while file_path.exists():
            file_path = final_path / f"{filename_base}_{counter}{extension}"
            counter += 1
        logger.info(f"📥 Baixando {media_info['type']}: {file_path.name}")
        async with semaphore:
            result = await message.download_media(file=str(file_path))
        if result and file_path.exists():
            file_size = file_path.stat().st_size
            if file_size == 0:
                logger.warning(f"Arquivo baixado está vazio: {file_path}")
                file_path.unlink()
                # Registrar falha
                failed_log = final_path.parent / 'failed_downloads.json'
                failure_info = {
                    'message_id': message.id,
                    'filename': file_path.name,
                    'path': str(file_path),
                    'size': 0,
                    'type': media_info['type'],
                    'original_filename': media_info.get('original_filename'),
                    'error': 'Arquivo vazio',
                    'failed_at': datetime.now().isoformat()
                }
                failures = []
                if failed_log.exists():
                    with open(failed_log, 'r', encoding='utf-8') as f:
                        failures = json.load(f)
                failures.append(failure_info)
                with open(failed_log, 'w', encoding='utf-8') as f:
                    json.dump(failures, f, ensure_ascii=False, indent=2)
                return None
            logger.info(f"✅ Download concluído: {file_path.name} ({file_size / 1024:.1f} KB)")
            # Registrar sucesso
            success_log = final_path.parent / 'download_success.json'
            download_info = {
                'message_id': message.id,
                'filename': file_path.name,
                'path': str(file_path),
                'size': file_size,
                'type': media_info['type'],
                'original_filename': media_info.get('original_filename'),
                'download_date': datetime.now().isoformat()
            }
            successes = []
            if success_log.exists():
                with open(success_log, 'r', encoding='utf-8') as f:
                    successes = json.load(f)
            successes.append(download_info)
            with open(success_log, 'w', encoding='utf-8') as f:
                json.dump(successes, f, ensure_ascii=False, indent=2)
            return str(file_path)
        else:
            logger.warning(f"[DOWNLOAD] ❌ Falhou para {file_path.name}")
            # Registrar falha
            failed_log = final_path.parent / 'failed_downloads.json'
            failure_info = {
                'message_id': message.id,
                'filename': file_path.name,
                'path': str(file_path),
                'size': 0,
                'type': media_info['type'],
                'original_filename': media_info.get('original_filename'),
                'error': 'Falha no download',
                'failed_at': datetime.now().isoformat()
            }
            failures = []
            if failed_log.exists():
                with open(failed_log, 'r', encoding='utf-8') as f:
                    failures = json.load(f)
            failures.append(failure_info)
            with open(failed_log, 'w', encoding='utf-8') as f:
                json.dump(failures, f, ensure_ascii=False, indent=2)
            return None
    except Exception as e:
        logger.error(f"[ERRO] Falha ao baixar mídia: {e}", exc_info=True)
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
        logger.info(f"No media files to reprocess for channel {channel}.")
        return

    for index, (message_id,) in enumerate(rows):
        try:
            normalized_id = normalize_id(message_id)
            logger.debug(f"[DEBUG] ID original: {message_id} | ID normalizado: {normalized_id}")
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
        return sanitize_folder_name_advanced(entity.title)
    return "Desconhecido"


def normalize_id(channel_id):
    """Normaliza o ID do canal, adicionando prefixo -100 se necessário."""
    channel_id_str = str(channel_id)
    if channel_id_str.startswith('-100'):
        return channel_id_str
    elif channel_id_str.isdigit() and len(channel_id_str) >= 9:
        return f"-100{channel_id_str}"
    return channel_id_str


async def discover_internal_channels(group_id, group_title):
    try:
        normalized_id = normalize_id(group_id)
        logger.debug(f"[DEBUG] ID original: {group_id} | ID normalizado: {normalized_id}")
        entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
        if not entity:
            logger.warning(f"[SKIP] Canal/tópico {normalized_id} inválido ou removido. Pulando.")
            return
        logger.info(f"\n🔍 Descobrindo canais internos do grupo: {entity.title}")
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
                        logger.info(f"  📋 Tópico de fórum encontrado: {topic.title} (ID: {topic.id})")
            except Exception as e:
                logger.warning(f"  ⚠️ Erro ao buscar tópicos de fórum: {e}")
        if discovered_channels:
            logger.info(f"\n✅ Total de {len(discovered_channels)} canais internos descobertos!")
            return discovered_channels
        else:
            logger.info("  ℹ️ Nenhum canal interno encontrado para este grupo.")
            return []
    except Exception as e:
        logger.error(f"  ❌ Erro ao descobrir canais internos: {e}")
        return []


async def scrape_channel(channel_id, offset_id, download_path):
    group_name = "Desconhecido"  # Inicializa com valor padrão
    # Robustez: se offset_id for dict, extrair corretamente
    if isinstance(offset_id, dict):
        logger.warning("[WARNING] Chamada incorreta para scrape_channel detectada. Corrigindo parâmetros automaticamente.")
        last_id = offset_id.get("last_id", 0)
        group_name = offset_id.get("group_name", "Desconhecido")
        channel_title = offset_id.get("channel_title", None)
        normalized_id = normalize_id(channel_id)
        entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
        if entity and hasattr(entity, 'title'):
            channel_title = sanitize_folder_name_advanced(entity.title)
        if 'group_name' in offset_id and offset_id['group_name'] != "Desconhecido":
            group_name = sanitize_folder_name_advanced(offset_id['group_name'])
        elif entity and hasattr(entity, 'title'):
            group_name = sanitize_folder_name_advanced(entity.title)
        download_path = get_download_path(group_name, channel_title)
        offset_id = last_id
    try:
        original_id = channel_id
        if isinstance(channel_id, dict):
            channel_id = channel_id.get('id') or channel_id.get('channel_id') or list(channel_id.values())[0]
        if isinstance(channel_id, str) and '_' in channel_id:
            channel_id = channel_id.split('_')[0]
        try:
            normalized_id = normalize_id(channel_id)
        except Exception as e:
            logger.error(f"[ERRO] Não foi possível normalizar o ID {original_id}: {e}. Removendo do state.")
            if str(original_id) in state["channels"]:
                del state["channels"][str(original_id)]
                save_state(state)
            return
        logger.debug(f"[DEBUG] ID original: {original_id} | ID normalizado: {normalized_id}")
        entity = await get_entity_safe(client, PeerChannel(int(normalized_id)), normalized_id)
        if not entity:
            logger.warning(f"[SKIP] Canal/tópico {normalized_id} inválido ou removido. Pulando.")
            if str(original_id) in state["channels"]:
                del state["channels"][str(original_id)]
                save_state(state)
            return
        if entity and hasattr(entity, 'title'):
            channel_name = sanitize_folder_name_advanced(entity.title)
        else:
            channel_name = "Desconhecido"
        # Adiciona sufixo único se for canal interno
        channel_suffix = None
        if isinstance(original_id, str) and '_' in original_id:
            channel_suffix = original_id.split('_')[1]
        if channel_suffix:
            unique_folder_name = f"{channel_name}_{channel_suffix}"
        else:
            unique_folder_name = channel_name
        group_name = unique_folder_name  # Garante valor
        logger.info(f"🚀 Iniciando scraping para canal: {group_name}")
        total_messages = 0
        processed_messages = 0
        download_count = 0
        total_downloads = 0
        semaphore = asyncio.Semaphore(1)  # downloads sequenciais
        # Contar total de mensagens
        try:
            async for message in client.iter_messages(
                entity, offset_id=offset_id, reverse=True
            ):
                total_messages += 1
        except (RPCError, ConnectionError, Exception) as e:
            logger.error(f"[ERROR] Failed to count messages for {group_name}: {e}")
            return
        logger.info(f"[INFO] Total de {total_messages} mensagens para processar em {group_name}")
        # Processar mensagens
        try:
            async for message in client.iter_messages(
                entity, offset_id=offset_id, reverse=True
            ):
                try:
                    # Ignorar mensagens sem texto nem mídia
                    if not (getattr(message, 'text', None) or message.media):
                        continue
                    sender = await message.get_sender()
                    # Detecta origem do canal (encaminhada ou principal)
                    if hasattr(message, 'forward') and message.forward and hasattr(message.forward, 'chat') and message.forward.chat:
                        channel_origin = sanitize_folder_name_advanced(getattr(message.forward.chat, 'title', None) or str(getattr(message.forward.chat, 'id', 'Desconhecido')))
                    else:
                        channel_origin = "_grupo_principal"
                    path_completo = os.path.join(DOWNLOADS_BASE, group_name, channel_origin)
                    validate_and_create_path(os.path.join(path_completo, "media"), "pasta de mídia")
                    save_message_to_db(path_completo, message, group_name, channel_origin)
                    # Inicializa variáveis para cada mensagem
                    media_type = None
                    media_path = None
                    if state["scrape_media"] and message.media:
                        download_count += 1
                        logger.info(f"\n[DOWNLOAD {download_count}] Processando arquivo...")
                        media_path = await download_media(path_completo, message, semaphore)
                        # Determina o tipo de mídia se possível
                        info = get_media_info(message)
                        media_type = info['type'] if info else None
                    processed_messages += 1
                    progress = (processed_messages / total_messages) * 100
                    sys.stdout.write("\r\033[K")
                    sys.stdout.write(
                        f"\rScraping channel: {group_name} - Progress: {progress:.2f}% ({processed_messages}/{total_messages})"
                    )
                    sys.stdout.flush()
                    # Atualizar last_id apenas se o canal estiver no state
                    if str(normalized_id) in state["channels"]:
                        state["channels"][str(normalized_id)]["last_id"] = message.id
                        save_state(state)
                    # Gerar log diário
                    log_diario(path_completo, message, group_name, channel_origin, media_type, media_path)
                except Exception as e:
                    logger.error(f"[ERRO] Falha ao processar mensagem {getattr(message, 'id', '?')}: {e}", exc_info=True)
        except (RPCError, ConnectionError, Exception) as e:
            logger.error(f"[ERROR] Failed to iterate/process messages for {group_name}: {e}")
        # Geração de arquivos de metadados
        channel_folder = Path(DOWNLOADS_BASE) / group_name
        channel_info_file = channel_folder / 'channel_info.json'
        statistics_file = channel_folder / 'statistics.json'
        # channel_info.json
        channel_info_data = {
            'channel_id': original_id,
            'group_name': group_name,
            'normalized_id': normalized_id,
            'scraping_date': datetime.now().isoformat(),
            'folder': str(channel_folder),
        }
        try:
            with open(channel_info_file, 'w', encoding='utf-8') as f:
                json.dump(channel_info_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Arquivo channel_info.json salvo em {channel_info_file}")
        except Exception as e:
            logger.error(f"Erro ao salvar channel_info.json: {e}")
        # statistics.json
        statistics_data = {
            'total_messages': total_messages,
            'processed_messages': processed_messages,
            'downloads': download_count,
            'scraping_date': datetime.now().isoformat(),
            'group_name': group_name,
        }
        try:
            with open(statistics_file, 'w', encoding='utf-8') as f:
                json.dump(statistics_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Arquivo statistics.json salvo em {statistics_file}")
        except Exception as e:
            logger.error(f"Erro ao salvar statistics.json: {e}")
        logger.info(f"\n[INFO] Scraping concluído para {group_name}: {processed_messages} mensagens processadas, {download_count} arquivos baixados")
        logger.info(f"📊 Estatísticas finais: total={total_messages}, processadas={processed_messages}, downloads={download_count}")
    except ValueError as e:
        logger.error(f"Error with channel {normalized_id}: {e}")


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
            print("Cole o(s) ID(s) ou bloco de texto contendo os IDs dos grupos/canais a adicionar:")
            input_text = input()
            ids = extract_ids_from_text(input_text)
            if not ids:
                print("Nenhum ID válido encontrado no texto colado.")
            for group_id in ids:
                try:
                    normalized_id = normalize_id(group_id)
                    logger.debug(f"[DEBUG] ID original: {group_id} | ID normalizado: {normalized_id}")
                    entity = await get_entity_safe(client, PeerChannel(int(normalized_id.split('_')[0])), normalized_id)
                    if not entity:
                        print(f"[SKIP] Canal/tópico {normalized_id} inválido ou removido. Pulando.")
                        continue
                    group_name = sanitize_folder_name_advanced(entity.title)
                    discovered = await discover_internal_channels(normalized_id, group_name)
                    if discovered:
                        print(f"\n📋 Resumo da adição de canais internos para o grupo '{group_name}':")
                        for ch in discovered:
                            ch_id = ch["id"]
                            ch_title = ch["title"]
                            if str(normalize_id(ch_id)) not in state["channels"]:
                                state["channels"][str(normalize_id(ch_id))] = {"last_id": 0, "group_name": group_name, "channel_title": ch_title}
                                print(f"  ➕ Canal interno adicionado: {group_name} / {ch_title} ({ch_id})")
                        print(f"\n✅ Total de {len(discovered)} canais internos adicionados para o grupo '{group_name}'.\n")
                        print(f"   Total de canais para raspagem: {len(discovered)+1}")
                    else:
                        # Grupo sem canais internos
                        if str(normalize_id(group_id)) not in state["channels"]:
                            state["channels"][str(normalize_id(group_id))] = {"last_id": 0, "group_name": group_name}
                            print(f"✅ Adicionado grupo: {group_name} ({group_id})")
                    save_state(state)
                except Exception as e:
                    print(f"Erro ao adicionar grupo {group_id}: {e}")
        elif choice == "r":
            print("Cole o(s) ID(s) ou bloco de texto contendo os IDs dos canais a remover:")
            input_text = input()
            ids = extract_ids_from_text(input_text)
            removed = []
            for channel_id in ids:
                if channel_id in state["channels"]:
                    del state["channels"][channel_id]
                    removed.append(channel_id)
            save_state(state)
            if removed:
                print(f"Removidos: {', '.join(removed)}")
            else:
                print("Nenhum canal removido. IDs não encontrados no state.")
        elif choice == "x":
            confirm = input(
                "Are you sure you want to remove ALL channels? (yes/no): "
            ).lower()
            if confirm in ["yes", "y", "sim"]:
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
    try:
        # Após scraping, executar retry automático
        logger.info("\n🔄 Executando sistema de retry de downloads falhos...")
        await retry_failed_downloads(DOWNLOADS_BASE, client, asyncio.Semaphore(1))
    except Exception as e:
        logger.critical(f"❌ Erro crítico na execução: {e}", exc_info=True)
    finally:
        await client.disconnect()
        logger.info("\n👋 Cliente desconectado. Scraping finalizado!")


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
                result = await download_media(download_path, message, asyncio.Semaphore(1))
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


async def retry_failed_downloads(base_folder, client, semaphore):
    """Sistema inteligente de retry para downloads falhos."""
    logger.info("🔄 Iniciando sistema de retry de downloads falhos...")
    failed_files = list(Path(base_folder).rglob('failed_downloads.json'))
    total_retries = 0
    success_retries = 0
    for failed_file in failed_files:
        try:
            with open(failed_file, 'r', encoding='utf-8') as f:
                failures = json.load(f)
            if not failures:
                continue
            logger.info(f"📁 Processando {len(failures)} falhas em: {failed_file.parent}")
            new_failures = []
            for failure in failures:
                total_retries += 1
                try:
                    # Buscar canal e mensagem
                    # Tenta inferir o canal pelo caminho do arquivo
                    channel_folder = failed_file.parent.parent  # .../canal/media
                    group_name = channel_folder.name
                    # Tenta buscar o channel_id pelo channel_info.json
                    channel_info_file = channel_folder / 'channel_info.json'
                    channel_id = None
                    if channel_info_file.exists():
                        with open(channel_info_file, 'r', encoding='utf-8') as f:
                            info = json.load(f)
                            channel_id = info.get('channel_id')
                    if not channel_id:
                        logger.warning(f"Não foi possível determinar o channel_id para retry em {failed_file}")
                        new_failures.append(failure)
                        continue
                    entity = await get_entity_safe(client, PeerChannel(int(str(channel_id).split('_')[0])), channel_id)
                    if not entity:
                        logger.warning(f"Entidade não encontrada para channel_id {channel_id}")
                        new_failures.append(failure)
                        continue
                    message_id = failure['message_id']
                    message = await client.get_messages(entity, ids=message_id)
                    if not message:
                        logger.warning(f"Mensagem {message_id} não encontrada no canal {channel_id}")
                        new_failures.append(failure)
                        continue
                    logger.info(f"🔄 Retry para mensagem {message_id} em {group_name}")
                    result = await download_media(channel_folder, message, semaphore)
                    if result:
                        logger.info(f"✅ Retry bem-sucedido para mensagem {message_id} em {group_name}")
                        success_retries += 1
                        # Registrar sucesso
                        success_log = channel_folder / 'download_success.json'
                        download_info = {
                            'message_id': message.id,
                            'filename': Path(result).name,
                            'path': str(result),
                            'size': Path(result).stat().st_size,
                            'type': failure.get('type'),
                            'original_filename': failure.get('original_filename'),
                            'download_date': datetime.now().isoformat(),
                            'retry': True
                        }
                        successes = []
                        if success_log.exists():
                            with open(success_log, 'r', encoding='utf-8') as f:
                                successes = json.load(f)
                        successes.append(download_info)
                        with open(success_log, 'w', encoding='utf-8') as f:
                            json.dump(successes, f, ensure_ascii=False, indent=2)
                        continue  # Não adiciona à lista de falhas
                    else:
                        logger.warning(f"❌ Retry falhou para mensagem {message_id} em {group_name}")
                        failure['retry_failed_at'] = datetime.now().isoformat()
                        new_failures.append(failure)
                except Exception as e:
                    logger.error(f"Erro no retry: {e}", exc_info=True)
                    failure['retry_failed_at'] = datetime.now().isoformat()
                    new_failures.append(failure)
            # Atualiza arquivo de falhas
            if new_failures:
                with open(failed_file, 'w', encoding='utf-8') as f:
                    json.dump(new_failures, f, ensure_ascii=False, indent=2)
            else:
                failed_file.unlink()
        except Exception as e:
            logger.error(f"Erro ao processar arquivo de falhas {failed_file}: {e}", exc_info=True)
    logger.info(f"✅ Retry concluído: {success_retries}/{total_retries} sucessos")


# Função utilitária para obter o caminho de download correto

def get_download_path(group_name, channel_title=None):
    group_name = sanitize_folder_name_advanced(group_name)
    if channel_title:
        channel_title = sanitize_folder_name_advanced(channel_title)
        return os.path.join(group_name, channel_title)
    return group_name


def log_diario(folder, message, group_name, channel_origin, media_type=None, media_path=None):
    """Gera um log diário por grupo/canal, com resumo das mensagens processadas."""
    from datetime import datetime
    log_name = f"log_{datetime.now().strftime('%Y-%m-%d')}.md"
    log_path = Path(folder) / log_name
    resumo = f"- [{message.date.strftime('%H:%M:%S')}] ID: {message.id} | "
    if getattr(message, 'text', None):
        resumo += f"Texto: {message.text[:50].replace('\n',' ')}"
    if media_type and media_path:
        resumo += f" | Mídia: {media_type} ({media_path})"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(resumo + "\n")


def extract_ids_from_text(text: str):
    """Extrai todos os IDs de canais/grupos do Telegram de um bloco de texto, aceitando -100... e IDs positivos longos."""
    # Aceita -1001234567890, 1234567890, 1808506136, etc
    pattern = r'(-100\d{10,}|[1-9]\d{8,})'
    return re.findall(pattern, text)


def clean_temp_files(base_folder):
    """Remove arquivos .test_write e pastas de teste temporárias."""
    logger.info("Limpando arquivos temporários...")
    for path in Path(base_folder).rglob('.test_write'):
        try:
            path.unlink()
            logger.info(f"Removido: {path}")
        except Exception as e:
            logger.warning(f"Falha ao remover {path}: {e}")
    # Remove pastas de teste
    test_dirs = [p for p in Path(base_folder).glob('test*') if p.is_dir()]
    for d in test_dirs:
        try:
            import shutil
            shutil.rmtree(d)
            logger.info(f"Pasta de teste removida: {d}")
        except Exception as e:
            logger.warning(f"Falha ao remover pasta {d}: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted. Exiting...")
        sys.exit()
