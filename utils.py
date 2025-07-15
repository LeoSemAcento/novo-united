import logging
import sys
import json
import re
import unicodedata
from pathlib import Path
from datetime import datetime
import mimetypes
import os
import smtplib
from email.message import EmailMessage

# Carregar configurações do config.json
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        CONFIG = json.load(f)
else:
    CONFIG = {}

MAX_PATH_LENGTH = CONFIG.get('MAX_PATH_LENGTH', 200)

# =================== SISTEMA DE LOGS =================== #
class ScraperLogger:
    """Sistema centralizado de logs com múltiplos níveis e destinos."""
    def __init__(self, base_path='logs', debug_mode=True):
        self.base_path = Path(base_path)
        self.base_path.mkdir(exist_ok=True)
        self.logger = logging.getLogger('TelegramScraper')
        self.logger.setLevel(logging.DEBUG if debug_mode else logging.INFO)
        self.logger.handlers.clear()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
        )
        fh = logging.FileHandler(
            self.base_path / f'scraper_{datetime.now().strftime("%Y%m%d")}.log',
            encoding='utf-8'
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)
        self.error_logger = logging.getLogger('TelegramScraper.Errors')
        error_handler = logging.FileHandler(
            self.base_path / 'errors.log',
            encoding='utf-8'
        )
        error_handler.setFormatter(formatter)
        self.error_logger.addHandler(error_handler)
    def debug(self, msg, extra_data=None):
        if extra_data:
            msg = f"{msg} | Data: {json.dumps(extra_data, ensure_ascii=False)}"
        self.logger.debug(msg)
    def info(self, msg):
        self.logger.info(msg)
    def warning(self, msg):
        self.logger.warning(msg)
    def error(self, msg, exc_info=True):
        self.logger.error(msg, exc_info=exc_info)
        self.error_logger.error(msg, exc_info=exc_info)
    def critical(self, msg, exc_info=True):
        self.logger.critical(msg, exc_info=exc_info)
        self.error_logger.critical(msg, exc_info=exc_info)

# Instância global do logger (pode ser importada em outros módulos)
logger = ScraperLogger()

# =================== SANITIZAÇÃO AVANÇADA =================== #
def sanitize_folder_name_advanced(name, max_length=50):
    """
    Sanitização avançada de nomes para garantir compatibilidade total.
    """
    if not name or not isinstance(name, str):
        logger.warning(f"Nome inválido recebido para sanitização: {name}")
        return "Desconhecido"
    logger.debug(f"Sanitizando nome: '{name}'")
    # 1. Normaliza unicode (remove acentos)
    name = unicodedata.normalize('NFKD', name)
    name = ''.join([c for c in name if not unicodedata.combining(c)])
    # 2. Remove caracteres problemáticos (Windows + Linux + MacOS)
    invalid_chars = r'<>:"/\\|?*\x00-\x1f\x7f'
    name = re.sub(f'[{re.escape(invalid_chars)}]', '_', name)
    # 3. Remove espaços extras e substitui por underscore
    name = re.sub(r'\s+', '_', name.strip())
    # 4. Remove pontos e espaços no início e fim
    name = name.strip('. ')
    # 5. Evita nomes reservados do Windows
    reserved_names = [
        'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4',
        'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2',
        'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    ]
    if name.upper() in reserved_names:
        name = f"{name}_file"
    # 6. Limita o tamanho
    if len(name) > max_length:
        name = name[:max_length-3] + '...'
    # 7. Garante que não está vazio
    if not name:
        name = "Sem_Nome"
    logger.debug(f"Nome sanitizado: '{name}'")
    return name

# =================== VALIDAÇÃO DE CAMINHOS =================== #

def validate_and_create_path(path, description="pasta"):
    """
    Valida e cria um caminho com diagnóstico detalhado.
    """
    try:
        path = Path(path)
        if len(str(path)) > MAX_PATH_LENGTH:
            logger.warning(f"Caminho muito longo ({len(str(path))} chars): {path}")
            parts = path.parts
            if len(parts) > 2:
                shortened = Path(parts[0]) / "..." / sanitize_folder_name_advanced(parts[-1], 30)
                logger.info(f"Caminho encurtado para: {shortened}")
                path = shortened
        logger.debug(f"Criando {description}: {path}")
        path.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            raise OSError(f"Falha ao criar {description}: {path}")
        test_file = path / '.test_write'
        try:
            test_file.write_text('test')
            test_file.unlink()
        except Exception as e:
            raise PermissionError(f"Sem permissão de escrita em {path}: {e}")
        logger.info(f"✅ {description.capitalize()} criada com sucesso: {path}")
        return path
    except Exception as e:
        logger.error(f"❌ Erro ao criar {description}: {path} - {str(e)}")
        raise

# =================== DETECÇÃO APRIMORADA DE TIPOS =================== #
MIME_EXTENSIONS = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/bmp': '.bmp',
    'image/svg+xml': '.svg',
    'image/tiff': '.tiff',
    'video/mp4': '.mp4',
    'video/x-matroska': '.mkv',
    'video/webm': '.webm',
    'video/avi': '.avi',
    'video/quicktime': '.mov',
    'video/x-msvideo': '.avi',
    'video/x-flv': '.flv',
    'audio/mpeg': '.mp3',
    'audio/ogg': '.ogg',
    'audio/wav': '.wav',
    'audio/x-m4a': '.m4a',
    'audio/aac': '.aac',
    'audio/flac': '.flac',
    'audio/opus': '.opus',
    'application/pdf': '.pdf',
    'application/msword': '.doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/vnd.ms-excel': '.xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'application/vnd.ms-powerpoint': '.ppt',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
    'text/plain': '.txt',
    'application/zip': '.zip',
    'application/x-rar-compressed': '.rar',
    'application/x-7z-compressed': '.7z',
    'application/x-tar': '.tar',
    'application/gzip': '.gz',
    'application/x-tgsticker': '.tgs',
    'application/vnd.android.package-archive': '.apk',
    'application/x-executable': '.exe',
    'application/json': '.json',
}

def get_media_info(message):
    """
    Extrai informações detalhadas da mídia com fallbacks robustos.
    """
    try:
        from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo, DocumentAttributeAudio, DocumentAttributeAnimated
        media_type = 'outros'
        extension = '.bin'
        filename = None
        original_filename = None
        if hasattr(message, 'photo') and message.photo:
            media_type = 'imagens'
            extension = '.jpg'
            filename = f"photo_{message.id}"
            logger.debug(f"Detectado como foto: {filename}")
        elif hasattr(message, 'document') and message.document:
            doc = message.document
            mime_type = getattr(doc, 'mime_type', '')
            logger.debug(f"Documento detectado. MIME: {mime_type}")
            for attr in doc.attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    original_filename = attr.file_name
                    filename = sanitize_folder_name_advanced(original_filename, 100)
                    if '.' in original_filename:
                        original_ext = '.' + original_filename.split('.')[-1].lower()
                        extension = original_ext
                        logger.debug(f"Nome original: {original_filename}, Extensão: {extension}")
                    break
                elif isinstance(attr, DocumentAttributeVideo):
                    media_type = 'videos'
                    if not filename:
                        filename = f"video_{message.id}"
                elif isinstance(attr, DocumentAttributeAudio):
                    media_type = 'audios'
                    if not filename:
                        filename = f"audio_{message.id}"
                elif isinstance(attr, DocumentAttributeAnimated):
                    media_type = 'gifs'
                    if not filename:
                        filename = f"gif_{message.id}"
            if not filename:
                if mime_type:
                    if 'image' in mime_type:
                        media_type = 'imagens'
                        filename = f"image_{message.id}"
                    elif 'video' in mime_type:
                        media_type = 'videos'
                        filename = f"video_{message.id}"
                    elif 'audio' in mime_type:
                        media_type = 'audios'
                        filename = f"audio_{message.id}"
                    elif 'pdf' in mime_type or 'document' in mime_type:
                        media_type = 'documentos'
                        filename = f"document_{message.id}"
                    elif 'zip' in mime_type or 'rar' in mime_type or 'compressed' in mime_type:
                        media_type = 'arquivos'
                        filename = f"archive_{message.id}"
                    else:
                        filename = f"file_{message.id}"
                else:
                    filename = f"file_{message.id}"
            if extension == '.bin' and mime_type:
                extension = MIME_EXTENSIONS.get(mime_type, '.bin')
                logger.debug(f"Extensão determinada por MIME: {extension}")
        elif hasattr(message, 'sticker') and message.sticker:
            media_type = 'stickers'
            extension = '.webp'
            filename = f"sticker_{message.id}"
        elif hasattr(message, 'voice') and message.voice:
            media_type = 'audios'
            extension = '.ogg'
            filename = f"voice_{message.id}"
        elif hasattr(message, 'video_note') and message.video_note:
            media_type = 'videos'
            extension = '.mp4'
            filename = f"videonote_{message.id}"
        elif hasattr(message, 'gif') and message.gif:
            media_type = 'gifs'
            extension = '.gif'
            filename = f"gif_{message.id}"
        if filename and extension != '.bin' and filename.endswith(extension):
            filename = filename[:-len(extension)]
        logger.debug(f"Mídia processada: tipo={media_type}, arquivo={filename}{extension}")
        return {
            'type': media_type,
            'extension': extension,
            'filename': filename,
            'original_filename': original_filename
        }
    except Exception as e:
        logger.error(f"Erro ao detectar informações da mídia: {e}")
        return {
            'type': 'outros',
            'extension': '.bin',
            'filename': f"error_{getattr(message, 'id', 'unknown')}",
            'original_filename': None
        }

def send_alert(subject, body, to_email=None):
    """Envia alerta por e-mail (exemplo básico)."""
    if not to_email:
        logger.warning("E-mail de destino não configurado para alertas.")
        return
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = 'alerta@seusistema.com'
        msg['To'] = to_email
        # Exemplo: localhost SMTP
        with smtplib.SMTP('localhost') as s:
            s.send_message(msg)
        logger.info(f"Alerta enviado para {to_email}")
    except Exception as e:
        logger.error(f"Falha ao enviar alerta: {e}")

# =================== FUNÇÕES COMPATIBILIDADE =================== #

def sanitize_folder_name(name, max_length=50):
    """
    Alias para sanitize_folder_name_advanced para compatibilidade.
    """
    return sanitize_folder_name_advanced(name, max_length)

def extract_ids_from_text(text: str):
    """
    Extrai IDs de canal/grupo de um texto.
    Suporta formatos: -1001234567890, 1234567890, @username, t.me/username
    """
    if not text:
        return []
    ids = []
    import re
    # IDs numéricos simples (8+ dígitos)
    numeric_pattern = r'(?<!\d)(-?100\d{8,}|\d{8,})(?!\d)'
    numeric_ids = re.findall(numeric_pattern, text)
    ids.extend(numeric_ids)
    # Usernames (@username)
    username_pattern = r'@(\w{5,})'
    usernames = re.findall(username_pattern, text)
    ids.extend([f"@{username}" for username in usernames])
    # Links t.me/username
    tme_pattern = r't\.me\/(\w{5,})'
    tme_usernames = re.findall(tme_pattern, text)
    ids.extend([f"@{username}" for username in tme_usernames])
    # Remove duplicatas mantendo ordem
    seen = set()
    unique_ids = []
    for id_val in ids:
        if id_val not in seen:
            seen.add(id_val)
            unique_ids.append(id_val)
    logger.debug(f"IDs extraídos de '{text[:100]}...': {unique_ids}")
    return unique_ids

def log_event(msg, log_file="logs/app.log"):
    """
    Função simples de log para compatibilidade.
    """
    logger.info(msg) 