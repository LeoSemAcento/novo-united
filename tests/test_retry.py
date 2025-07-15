import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
import json
import shutil
import asyncio
from main-scrap.telegram-scraper import retry_failed_downloads

@pytest.mark.asyncio
async def test_retry_failed_downloads(tmp_path):
    # Setup: criar estrutura de falha simulada
    canal = tmp_path / "CanalTeste"
    media = canal / "media"
    media.mkdir(parents=True)
    failed_file = media / "failed_downloads.json"
    channel_info = canal / "channel_info.json"
    # Simula channel_info.json
    with open(channel_info, 'w', encoding='utf-8') as f:
        json.dump({"channel_id": "-100123456"}, f)
    # Simula falha
    with open(failed_file, 'w', encoding='utf-8') as f:
        json.dump([
            {"message_id": 1, "type": "imagens", "original_filename": "teste.jpg"}
        ], f)
    # Mock do Telethon
    mock_client = MagicMock()
    mock_entity = MagicMock()
    mock_message = MagicMock()
    mock_message.id = 1
    # get_entity_safe retorna entidade
    with patch("main-scrap.telegram-scraper.get_entity_safe", new=AsyncMock(return_value=mock_entity)), \
         patch.object(mock_client, 'get_messages', new=AsyncMock(return_value=mock_message)), \
         patch("main-scrap.telegram-scraper.download_media", new=AsyncMock(return_value=str(media / "teste.jpg"))):
        await retry_failed_downloads(tmp_path, mock_client, asyncio.Semaphore(1))
    # Verifica se o arquivo de falha foi removido (retry bem-sucedido)
    assert not failed_file.exists()
    # Limpeza
    shutil.rmtree(tmp_path, ignore_errors=True) 