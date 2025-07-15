import sqlite3
from pathlib import Path

def init_db(db_path):
    """Cria o banco e a tabela de mensagens se não existirem."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            date TEXT,
            sender_name TEXT,
            group_name TEXT,
            channel_origin TEXT,
            text TEXT,
            media_type TEXT,
            media_path TEXT
        )
    ''')
    conn.commit()
    return conn

def insert_message(db_path, msg_dict):
    """Insere uma mensagem no banco. msg_dict deve conter as chaves corretas."""
    conn = init_db(db_path)
    c = conn.cursor()
    c.execute('''
        INSERT INTO messages (
            message_id, date, sender_name, group_name, channel_origin, text, media_type, media_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        msg_dict.get('message_id'),
        msg_dict.get('date'),
        msg_dict.get('sender_name'),
        msg_dict.get('group_name'),
        msg_dict.get('channel_origin'),
        msg_dict.get('text'),
        msg_dict.get('media_type'),
        msg_dict.get('media_path')
    ))
    conn.commit()
    conn.close()

# Função opcional para buscar mensagens

def fetch_messages(db_path, limit=100):
    """Busca as últimas mensagens do banco."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT * FROM messages ORDER BY id DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    conn.close()
    return rows 

def get_last_message_id(db_path):
    """Retorna o maior message_id salvo no banco, ou 0 se não houver mensagens."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT MAX(message_id) FROM messages')
    result = c.fetchone()
    conn.close()
    return result[0] if result and result[0] is not None else 0 