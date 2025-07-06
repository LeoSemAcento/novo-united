from telethon import TelegramClient
from telethon.tl.types import Channel, PeerChannel
from telethon.errors.rpcerrorlist import ChannelInvalidError, ChannelPrivateError, FloodWaitError, ServerError, TimeoutError
import asyncio
import os

class TelegramSession:
    def __init__(self, channels_file='canais.txt'):
        self.client = None
        self.loop = None
        self.channels_file = channels_file
        self._ensure_channels_file_exists()

    def start(self, api_id, api_hash, phone, code_callback):
        # Garante que o loop seja criado e definido na thread que o utiliza
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        self.client = TelegramClient('session', api_id, api_hash, loop=self.loop)
        return self.loop.run_until_complete(self._start(phone, code_callback))

    async def _start(self, phone, code_callback):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.send_code_request(phone)
            code = code_callback()
            await self.client.sign_in(phone, code)
        return self.client

    def disconnect(self):
        if self.client and self.client.is_connected():
            self.loop.run_until_complete(self.client.disconnect())

    async def _list_dialogs(self):
        dialogs = await self.client.get_dialogs()
        channels = []
        for dialog in dialogs:
            if dialog.is_channel:
                channels.append(f"ID: {dialog.entity.id}, Título: {dialog.entity.title}")
        return channels

    def list_dialogs(self):
        if self.client and self.client.is_connected():
            return self.loop.run_until_complete(self._list_dialogs())
        return ["Cliente não conectado."]

    def _ensure_channels_file_exists(self):
        try:
            with open(self.channels_file, 'x') as f:
                pass  # Cria o arquivo se não existir
        except FileExistsError:
            pass  # O arquivo já existe

    def view_channels(self):
        with open(self.channels_file, 'r') as f:
            channels = [line.strip() for line in f.readlines()]
        return channels

    def add_channel(self, channel_id):
        channels = self.view_channels()
        if channel_id not in channels:
            with open(self.channels_file, 'a') as f:
                f.write(f"{channel_id}\n")
            return f"Canal {channel_id} adicionado."
        return f"Canal {channel_id} já existe na lista."

    def remove_channel(self, channel_id):
        channels = self.view_channels()
        if channel_id in channels:
            channels.remove(channel_id)
            with open(self.channels_file, 'w') as f:
                for channel in channels:
                    f.write(f"{channel}\n")
            return f"Canal {channel_id} removido."
        return f"Canal {channel_id} não encontrado na lista."

    def remove_all_channels(self):
        with open(self.channels_file, 'w') as f:
            pass # Esvazia o arquivo
        return "Todos os canais foram removidos."

    # Helper seguro para get_entity
    async def get_entity_safe(self, peer, channel_id=None):
        try:
            return await self.client.get_entity(peer)
        except (ChannelInvalidError, ChannelPrivateError, ValueError) as e:
            print(f"[REMOVIDO DEFINITIVO] Canal/tópico {peer} removido do state: {e}")
            return None
        except (FloodWaitError, ServerError, TimeoutError) as e:
            print(f"[TEMPORÁRIO] Falha temporária ao acessar {peer}: {e}. Tente novamente mais tarde.")
            return None
        except Exception as e:
            print(f"[ERRO DESCONHECIDO] Falha ao acessar {peer}: {e}")
            return None

    async def _scrape_channel(self, channel_id, log_callback):
        try:
            entity = await self.get_entity_safe(PeerChannel(int(channel_id)), channel_id)
            if not entity:
                log_callback(f"Canal/tópico {channel_id} inválido ou removido. Pulando.")
                return False
            channel_title = entity.title.replace('/', '_').replace('\\', '_') # Sanitize title for folder name
            channel_folder = f"downloads/{channel_title}_{channel_id}"
            os.makedirs(channel_folder, exist_ok=True)

            log_callback(f"Iniciando raspagem do canal: {entity.title}")
            log_callback(f"Salvando arquivos em: {channel_folder}")

            log_file_path = os.path.join(channel_folder, "messages.log")

            with open(log_file_path, "w", encoding="utf-8") as f:
                async for message in self.client.iter_messages(entity, limit=100): # Limite de 100 por simplicidade
                    # Salva a mensagem de texto
                    f.write(f"De: {message.sender_id}, Data: {message.date}, Mensagem: {message.text}\n")
                    
                    # Baixa a mídia se existir
                    if message.media:
                        log_callback(f"Baixando mídia da mensagem {message.id}...")
                        # O path do download será dentro da pasta do canal
                        await self.client.download_media(message, file=channel_folder)

            log_callback(f"Raspagem do canal {entity.title} concluída.")
            return True
        except Exception as e:
            log_callback(f"Erro ao raspar o canal {channel_id}: {e}")
            return False

    def scrape_channels(self, log_callback):
        if not (self.client and self.client.is_connected()):
            log_callback("Cliente não conectado.")
            return

        channels_to_scrape = self.view_channels()
        if not channels_to_scrape:
            log_callback("Nenhum canal salvo para raspar.")
            return

        log_callback(f"Iniciando raspagem de {len(channels_to_scrape)} canais...")
        for channel_id in channels_to_scrape:
            self.loop.run_until_complete(self._scrape_channel(channel_id, log_callback))
        log_callback("Processo de raspagem finalizado.")
