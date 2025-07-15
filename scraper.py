import asyncio
from pathlib import Path
from telethon.tl.types import PeerChannel
from utils import sanitize_folder_name, log_event
from db import insert_message
from media import download_media

async def scrape_channel(client, entity, group_name, channel_origin, semaphore, db_path, min_id=None):
    """
    Faz scraping de todas as mensagens de um canal/grupo, salva no banco e baixa mídia.
    min_id: se fornecido, só busca mensagens com id > min_id
    """
    iter_kwargs = {'reverse': True}
    if min_id:
        iter_kwargs['min_id'] = min_id
    async for message in client.iter_messages(entity, **iter_kwargs):
        try:
            # Ignorar mensagens sem texto nem mídia
            if not (getattr(message, 'text', None) or message.media):
                continue
            sender = await message.get_sender()
            sender_name = sanitize_folder_name(getattr(sender, 'username', None) or getattr(sender, 'first_name', None) or "anon")
            media_path = None
            media_type = None
            if message.media:
                media_path, media_type = await download_media(message, Path(db_path).parent / "media", semaphore)
            msg_dict = {
                'message_id': message.id,
                'date': str(message.date),
                'sender_name': sender_name,
                'group_name': group_name,
                'channel_origin': channel_origin,
                'text': getattr(message, 'text', None),
                'media_type': media_type,
                'media_path': media_path
            }
            insert_message(db_path, msg_dict)
        except Exception as e:
            log_event(f"[ERRO] Falha ao processar mensagem {getattr(message, 'id', '?')}: {e}")
            import traceback
            traceback.print_exc() 