# Scraper Telegram Robusto

## Visão Geral

Este projeto realiza scraping completo de canais e grupos do Telegram, com:
- Sistema de logs centralizado
- Sanitização avançada de nomes
- Criação segura de subpastas
- Retry inteligente para downloads falhos
- Geração de metadados detalhados
- Testes automatizados
- Configuração externa via `config.json`

## Como Rodar

1. Instale as dependências:
   ```bash
   pip install -r main-scrap/requirements.txt
   ```
2. Configure seu `config.json` (opcional, já vem com defaults).
3. Execute o scraper:
   ```bash
   python main-scrap/telegram-scraper.py
   ```
4. Para rodar os testes:
   ```bash
   pytest tests/
   ```

## Estrutura de Pastas
```
downloads/
└── Nome_do_Grupo_Principal/
    └── Nome_do_Canal_Unico_123/
        ├── imagens/
        ├── videos/
        ├── audios/
        ├── documentos/
        ├── stickers/
        ├── gifs/
        ├── arquivos/
        ├── outros/
        ├── logs/
        │   └── scraping_20250110_143022.log
        ├── database/
        │   └── mensagens.db
        ├── channel_info.json
        ├── statistics.json
        ├── download_success.json
        └── failed_downloads.json
```

## Arquivos de Metadados
- `channel_info.json`: Informações do canal
- `statistics.json`: Estatísticas do scraping
- `download_success.json`: Downloads bem-sucedidos
- `failed_downloads.json`: Downloads falhos (retry automático)

## Logs
- Todos os eventos críticos são registrados em `logs/` e no console.
- Exemplo de log:
  ```
  2024-07-25 14:30:22 - TelegramScraper - INFO - [scrape_channel:123] - 🚀 Iniciando scraping para canal: CanalTeste
  ```

## Configuração
- Parâmetros em `config.json`:
  - `MAX_PATH_LENGTH`: Limite de caracteres no caminho
  - `SEMAPHORE_LIMIT`: Paralelismo de downloads
  - `DOWNLOADS_BASE`: Pasta base dos downloads
  - `LOG_LEVEL`: Nível de log
  - `TEMP_DIR`: Pasta temporária para testes

## Testes Automatizados
- Testes unitários em `tests/` para funções utilitárias e sistema de retry.
- Use `pytest` para rodar todos os testes.

## Troubleshooting
- **FloodWaitError**: O scraper aguarda automaticamente o tempo necessário.
- **Canal privado/inválido**: O canal é pulado e logado.
- **Falhas de download**: São registradas e reprocessadas automaticamente.
- **Limpeza de temporários**: Use a função `clean_temp_files` para remover arquivos de teste.

## Alertas e Monitoramento
- O sistema pode ser expandido para enviar alertas por e-mail ou Telegram em caso de falhas críticas ou excesso de retries.

## Contribuição
- Sinta-se à vontade para abrir issues ou PRs para melhorias! 