import mimetypes
from pathlib import Path
import asyncio

async def download_media(message, base_folder, semaphore):
    """
    Baixa a mídia de uma mensagem do Telethon, detecta tipo/extensão e salva na subpasta correta.
    Retorna o caminho do arquivo salvo e o tipo de mídia.
    """
    guessed_name = f"{message.id}"
    mime_type = None
    if hasattr(message, 'document') and message.document and hasattr(message.document, 'mime_type'):
        mime_type = message.document.mime_type
    elif hasattr(message, 'photo') and message.photo:
        mime_type = 'image/jpeg'
    extension = mimetypes.guess_extension(mime_type or '') or '.bin'
    # Define subpasta por tipo
    media_type = 'unknown'
    if mime_type:
        if 'image' in mime_type:
            media_type = 'images'
        elif 'video' in mime_type:
            media_type = 'videos'
        elif 'audio' in mime_type:
            media_type = 'audios'
        elif 'pdf' in mime_type or 'doc' in mime_type:
            media_type = 'docs'
    final_dir = Path(base_folder) / media_type
    final_dir.mkdir(parents=True, exist_ok=True)
    full_file_path = final_dir / f"{guessed_name}{extension}"
    async with semaphore:
        result = await message.download_media(file=full_file_path)
        if result:
            return str(full_file_path), media_type
        else:
            return None, None 