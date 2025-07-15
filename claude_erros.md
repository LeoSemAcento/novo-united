# Relatório de Erros e Diagnóstico — Criação de Subpastas e Extração de Arquivos

## 1. Principais Locais de Erro e Log

- O código faz uso de muitos try/except e logs com print e traceback.print_exc(), especialmente em:
  - download_media (media.py, telegram-scraper.py)
  - save_message_to_db (telegram-scraper.py)
  - scraping de mensagens (scraper.py, telegram-scraper.py)
  - criação de pastas (os.makedirs, Path(...).mkdir)

- Exemplo de log de erro:
  ```python
  except Exception as e:
      print(f"[ERRO] Falha ao baixar mídia: {e}")
      import traceback
      traceback.print_exc()
  ```

- Falhas na criação de subpastas geralmente aparecem como erros de permissão, caminho inválido ou nomes não sanitizados.

## 2. Diagnóstico Específico: Criação de Subpastas

- O app usa funções como:
  ```python
  final_dir = Path(base_folder) / media_type
  final_dir.mkdir(parents=True, exist_ok=True)
  ```
  e
  ```python
  os.makedirs(os.path.join(path_completo, "media"), exist_ok=True)
  ```

- Se o nome do grupo/canal não for sanitizado corretamente, pode gerar erros de caminho inválido (caracteres proibidos, espaços, etc).
- O uso de sanitize_folder_name é fundamental, mas pode haver casos onde o nome ainda fica inválido ou muito longo.

- Erros típicos:
  - FileNotFoundError: [Errno 2] No such file or directory: ...
  - PermissionError: [Errno 13] Permission denied: ...
  - OSError: [Errno 36] File name too long: ...

## 3. Diagnóstico Específico: Extração de Conversas/Arquivos Separados

- O código tenta criar subpastas para cada canal dentro do grupo:
  ```python
  path_completo = os.path.join(DOWNLOADS_BASE, group_name, channel_origin)
  os.makedirs(os.path.join(path_completo, "media"), exist_ok=True)
  ```
- Se channel_origin não for único ou sanitizado, pode sobrescrever ou misturar arquivos.
- O scraping de mensagens e mídias é feito em loops aninhados, e qualquer erro de pasta pode interromper o processo para aquele canal.

## 4. Logs e Falhas Recentes

- Os logs de erro são salvos em logs/app.log (via log_event) e também impressos no terminal.
- Falhas de download são registradas em downloads/[grupo]/[canal]/failed_downloads.json.
- O comando de retry lê esses arquivos e tenta novamente, logando novas falhas.

## 5. Recomendações Imediatas

- Verifique se todos os nomes de grupo/canal estão sendo passados por sanitize_folder_name antes de criar pastas.
- Adicione prints/logs extras logo antes de cada os.makedirs para capturar o caminho exato que está falhando.
- Confira permissões da pasta downloads e se não há conflitos de nomes.
- Se possível, rode o app com um grupo/canal problemático e cole aqui o erro exato do terminal/log.

## 6. Exemplo de Diagnóstico de Caminho

Adicione este trecho antes de criar a pasta:
```python
print(f"[DEBUG] Tentando criar pasta: {os.path.join(path_completo, 'media')}")
```
Assim, se der erro, você saberá o caminho exato que está causando problema.

## 7. Resumo dos Últimos Erros Possíveis

- Falha ao criar subpasta: nome inválido, muito longo ou permissão negada.
- Falha ao baixar mídia: caminho inexistente, pasta não criada, permissão negada.
- Falha ao salvar mensagem: erro de banco de dados por caminho inválido.
- Falha ao separar arquivos por canal: channel_origin não sanitizado ou duplicado.

---

Se necessário, envie logs recentes ou exemplos de erro para análise mais aprofundada. 