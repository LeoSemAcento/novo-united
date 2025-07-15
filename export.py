import sqlite3
import json
import csv
from pathlib import Path

def export_to_json(db_path, output_path=None):
    """Exporta todas as mensagens do banco para um arquivo JSON."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT * FROM messages')
    rows = c.fetchall()
    columns = [desc[0] for desc in c.description]
    data = [dict(zip(columns, row)) for row in rows]
    conn.close()
    if not output_path:
        output_path = Path(db_path).with_suffix('.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Exportado para {output_path}")

def export_to_csv(db_path, output_path=None):
    """Exporta todas as mensagens do banco para um arquivo CSV."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT * FROM messages')
    rows = c.fetchall()
    columns = [desc[0] for desc in c.description]
    conn.close()
    if not output_path:
        output_path = Path(db_path).with_suffix('.csv')
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    print(f"Exportado para {output_path}") 