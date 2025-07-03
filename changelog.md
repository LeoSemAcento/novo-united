# Log de Alterações

## 03/07/2025

- **[FEATURE]** Clonados repositórios iniciais do projeto.
  - `telegram-scrap` (branch: desenvolvimento)
  - `telegram-ids-scraper`
- **[FEATURE]** Atualizada a função de listagem de canais no app `1 telegram-scrap`.
  - A função agora lista apenas grupos e canais, ignorando usuários.
  - O formato de saída foi ajustado para exibir o nome do grupo/canal, o ID formatado e os tópicos de fóruns, conforme especificado.
  - O rótulo da opção no menu foi alterado para "Listar Grupos".
- **[FEATURE]** Implementada a gravação da lista de canais em um arquivo de texto.
  - A lista de grupos e canais gerada pela opção "L" agora é salva em um arquivo `.txt`.
  - O nome do arquivo é gerado dinamicamente no formato `Canais DD-MM-AA HH-MM.txt`.
