# Changelog - Telegram Scraper

## [2.0.0] - 2025-07-03

### ✨ Novas Funcionalidades

#### 🔍 Descoberta Automática de Canais Internos
- **Função `discover_internal_channels()`**: Descobre automaticamente todos os canais internos de um grupo
- **Busca inteligente**: Identifica canais relacionados por nome e estrutura
- **Suporte a fóruns**: Detecta e adiciona tópicos de fórum automaticamente
- **Integração automática**: Ao adicionar um grupo, todos os canais internos são descobertos e adicionados

#### 🔧 Normalização de IDs
- **Função `normalize_id()`**: Normaliza automaticamente IDs de canais
- **Adição de prefixo**: Adiciona `-100` automaticamente quando necessário
- **Validação**: Verifica se o ID é válido antes de processar

#### 📊 Interface Melhorada
- **Feedback visual**: Emojis e cores para melhor experiência do usuário
- **Resumo detalhado**: Mostra todos os grupos e canais adicionados
- **Progresso em tempo real**: Indica o progresso das operações
- **Tratamento de erros**: Mensagens de erro mais claras e informativas

### 🔄 Melhorias na Opção A (Adicionar Grupos)

#### Antes:
```
Digite o(s) ID(s) do(s) grupo(s) ou cole bloco de texto: 1234567890
Adicionado: Nome do Grupo (-1001234567890)
Você adicionou os grupos: Nome do Grupo
```

#### Agora:
```
Digite o(s) ID(s) do(s) grupo(s) ou cole bloco de texto: 1234567890

🔍 Descobrindo canais internos do grupo: Nome do Grupo
  📢 Canal interno encontrado: Canal Interno 1 (ID: -1009876543210)
  📢 Canal relacionado encontrado: Canal Relacionado (ID: -1001112223333)
  📋 Tópico de fórum encontrado: Tópico Importante (ID: 5)

✅ Total de 3 canais internos descobertos!
✅ Adicionado grupo: Nome do Grupo (-1001234567890)
  ➕ Canal interno adicionado: Canal Interno 1 (-1009876543210)
  ➕ Canal interno adicionado: Canal Relacionado (-1001112223333)
  ➕ Canal interno adicionado: Nome do Grupo - Tópico Importante (-1001234567890_5)

📋 Resumo da adição:
   Grupos adicionados: Nome do Grupo
   Canais internos descobertos: 3
     - Canal Interno 1
     - Canal Relacionado
     - Nome do Grupo - Tópico Importante
   Total de canais para raspagem: 4
```

### 🧪 Testes

#### Script de Teste
- **`test_discovery.py`**: Script completo para testar todas as novas funcionalidades
- **Testes unitários**: Validação de normalização de IDs
- **Testes de integração**: Verificação da descoberta automática
- **Testes de interface**: Validação do feedback visual

### 📁 Estrutura de Arquivos

```
main-scrap/
├── telegram-scraper.py      # Script principal (atualizado)
├── test_discovery.py        # Script de testes (novo)
├── CHANGELOG.md            # Este arquivo (novo)
├── logs-guia.txt           # Log de desenvolvimento (atualizado)
└── ... (outros arquivos)
```

### 🔧 Como Usar

#### 1. Descoberta Automática
```bash
# Execute o script principal
python telegram-scraper.py

# Escolha a opção A
# Cole um bloco de texto com IDs de grupos
# O sistema descobrirá automaticamente todos os canais internos
```

#### 2. Testes
```bash
# Execute os testes
python test_discovery.py

# Verifique se todas as funcionalidades estão funcionando
```

### 🐛 Correções

- **Normalização de IDs**: Corrigido problema com IDs que não tinham prefixo `-100`
- **Tratamento de erros**: Melhorado o tratamento de exceções na descoberta de canais
- **Interface**: Corrigidos problemas de formatação no menu

### 📈 Performance

- **Descoberta otimizada**: Busca eficiente por canais relacionados
- **Cache de entidades**: Evita requisições desnecessárias ao Telegram
- **Processamento em lote**: Adiciona múltiplos canais de uma vez

### 🔮 Próximas Versões

#### [2.1.0] - Planejado
- Interface gráfica (GUI) completa
- Configurações avançadas de descoberta
- Filtros personalizados para canais
- Relatórios detalhados de descoberta

#### [2.2.0] - Planejado
- Integração com APIs externas
- Backup automático de configurações
- Sincronização entre dispositivos
- Análise de conteúdo automática

---

## [1.0.0] - 2025-07-02

### Funcionalidades Base
- Sistema de scraping básico
- Interface de menu simples
- Download de mídia
- Exportação de dados
- Sistema de estado persistente 