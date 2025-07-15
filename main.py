import sys
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


# =================== CONFIGURAÇÕES =================== #
CONFIG_PATH = 'config.json'
def get_api_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        api_id = config.get('API_ID')
        api_hash = config.get('API_HASH')
        if api_id and api_hash and api_id != 'SEU_API_ID' and api_hash != 'SEU_API_HASH':
            return api_id, api_hash
    # Se não existir ou for placeholder, pedir ao usuário
    print('Configuração da API do Telegram não encontrada.')
    while True:
        api_id = input('Digite seu API_ID do Telegram: ').strip()
        if api_id.isdigit():
            break
        print('API_ID deve ser um número inteiro.')
    api_hash = input('Digite seu API_HASH do Telegram: ').strip()
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump({'API_ID': api_id, 'API_HASH': api_hash}, f, ensure_ascii=False, indent=2)
    return api_id, api_hash

API_ID, API_HASH = get_api_config()
SESSION_NAME = 'scraper_session'
DOWNLOADS_BASE = 'downloads'
SEMAPHORE_LIMIT = 5
# ===================================================== #

def get_download_path(group_name, channel_title=None):
    if channel_title:
        return os.path.join(DOWNLOADS_BASE, group_name, channel_title)
    return os.path.join(DOWNLOADS_BASE, group_name)


def log_diario(folder, message, group_name, channel_origin, media_type=None, media_path=None):
    # Função para log diário, pode ser expandida conforme necessário
    pass


def extract_ids_from_text(text: str):
    # Extrai IDs de canais/grupos de um texto
    return re.findall(r'-?\d+', text)


def clean_temp_files(base_folder):
    # Limpa arquivos temporários, se necessário
    pass

async def get_entity_safe(client, peer, channel_id=None):
    try:
        return await client.get_entity(peer)
    except Exception as e:
        logger.error(f"Erro ao obter entidade: {e}")
        return None

async def download_media(download_path, message, semaphore):
    # Função simplificada para download de mídia
    async with semaphore:
        # Lógica de download de mídia
        pass

async def rescrape_media(channel):
    # Função para rebaixar mídias de um canal
    pass

async def get_channel_title(channel_id):
    # Função para obter o título do canal
    pass

def normalize_id(channel_id):
    # Normaliza o ID do canal
    return str(channel_id)

async def discover_internal_channels(group_id, group_title):
    # Descobre canais internos de um grupo
    pass

async def scrape_channel(channel_id, offset_id, download_path):
    # Função principal de scraping de canal
    pass

async def continuous_scraping():
    # Função para scraping contínuo
    pass

async def export_data():
    # Função para exportar dados
    pass

def export_to_csv(channel):
    # Exporta dados para CSV
    pass

def export_to_json(channel):
    # Exporta dados para JSON
    pass

async def view_channels():
    # Visualiza canais
    pass

async def list_Channels():
    # Lista canais
    pass

async def manage_channels():
    # Gerencia canais
    pass

def generate_failure_report():
    # Gera relatório de falhas
    pass

async def retry_problematic_downloads():
    # Re-tenta downloads problemáticos
    pass

async def retry_failed_downloads(base_folder, client, semaphore):
    # Re-tenta downloads falhos
    pass

def menu():
    print("\nMenu:")
    print("[A] Adicionar canais/grupos (cole bloco de texto com IDs)")
    print("[R] Remover canais/grupos (cole bloco de texto com IDs)")
    print("[V] Ver canais salvos")
    print("[S] Scrape all channels")
    print("[E] Exportar dados (JSON/CSV)")
    print("[Q] Sair")
    return input("Escolha uma opção: ").strip().lower()

def main():
    # Dicionário de canais salvos: {id: {group_name, channel_origin}}
    if os.path.exists('channels_state.json'):
        import json
        with open('channels_state.json', 'r', encoding='utf-8') as f:
            channels = json.load(f)
    else:
        channels = {}
    while True:
        op = menu()
        if op == 'a':
            print("Cole o(s) ID(s) ou bloco de texto contendo os IDs dos grupos/canais a adicionar:")
            input_text = input()
            ids = extract_ids_from_text(input_text)
            if not ids:
                print("Nenhum ID válido encontrado.")
                continue
            with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
                for group_id in ids:
                    try:
                        entity = client.get_entity(PeerChannel(int(group_id.split('_')[0])))
                        group_name = sanitize_folder_name(entity.title)
                        channel_origin = group_name  # Para grupos simples
                        channels[group_id] = {'group_name': group_name, 'channel_origin': channel_origin}
                        print(f"Adicionado: {group_name} (ID: {group_id})")
                    except Exception as e:
                        print(f"[ERRO] Falha ao adicionar {group_id}: {e}")
            with open('channels_state.json', 'w', encoding='utf-8') as f:
                import json
                json.dump(channels, f, ensure_ascii=False, indent=2)
        elif op == 'r':
            print("Cole o(s) ID(s) ou bloco de texto contendo os IDs dos canais a remover:")
            input_text = input()
            ids = extract_ids_from_text(input_text)
            removed = []
            for channel_id in ids:
                if channel_id in channels:
                    del channels[channel_id]
                    removed.append(channel_id)
            with open('channels_state.json', 'w', encoding='utf-8') as f:
                import json
                json.dump(channels, f, ensure_ascii=False, indent=2)
            if removed:
                print(f"Removidos: {', '.join(removed)}")
            else:
                print("Nenhum canal removido. IDs não encontrados.")
        elif op == 'v':
            if not channels:
                print("Nenhum canal salvo.")
            else:
                print("Canais salvos:")
                for cid, info in channels.items():
                    print(f"- {info['group_name']} (ID: {cid})")
        elif op == 's':
            if not channels:
                print("Nenhum canal salvo para scraping.")
                continue
            with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
                semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
                for cid, info in channels.items():
                    print(f"Scraping: {info['group_name']} (ID: {cid})")
                    group_folder = os.path.join(DOWNLOADS_BASE, info['group_name'], info['channel_origin'])
                    os.makedirs(group_folder, exist_ok=True)
                    db_path = os.path.join(group_folder, 'mensagens.db')
                    entity = client.get_entity(PeerChannel(int(cid.split('_')[0])))
                    min_id = get_last_message_id(db_path)
                    client.loop.run_until_complete(scrape_channel(client, entity, info['group_name'], info['channel_origin'], semaphore, db_path, min_id=min_id))
        elif op == 'e':
            print("Exportar dados de qual canal? (cole o ID ou bloco de texto)")
            input_text = input()
            ids = extract_ids_from_text(input_text)
            for cid in ids:
                if cid in channels:
                    group_folder = os.path.join(DOWNLOADS_BASE, channels[cid]['group_name'], channels[cid]['channel_origin'])
                    db_path = os.path.join(group_folder, 'mensagens.db')
                    export_to_json(db_path)
                    export_to_csv(db_path)
                else:
                    print(f"Canal não encontrado: {cid}")
        elif op == 'q':
            print("Saindo...")
            break
        else:
            print("Opção inválida.")

# Exibe o banner ao iniciar
if __name__ == "__main__":
    display_ascii_art()
    main() 