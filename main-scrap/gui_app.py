import PySimpleGUI as sg
from telegram_client import TelegramSession
import threading

# Layout da tela de credenciais
layout_credenciais = [
    [sg.Text('API ID')],
    [sg.Input(key='API_ID')],
    [sg.Text('API Hash')],
    [sg.Input(key='API_HASH')],
    [sg.Text('Telefone (com + e DDD)')],
    [sg.Input(key='PHONE')],
    [sg.Button('Confirma')]
]

# Layout da tela de token
layout_token = [
    [sg.Text('Insira o código/token enviado pelo Telegram')],
    [sg.Input(key='TOKEN')],
    [sg.Button('Confirmar Token')],
    [sg.Button('Voltar')]
]

# Layout da tela principal
layout_principal = [
    [sg.Text('Leo Apps - Menu Principal', font=('Any', 16))],
    [sg.Button('Adicionar Canal')],
    [sg.Button('Adicionar Múltiplos Canais')],
    [sg.Button('Remover Canal')],
    [sg.Button('Remover TODOS os Canais')],
    [sg.Button('Raspar Todos os Canais')],
    [sg.Button('Ativar/Desativar Download de Mídia')],
    [sg.Button('Raspagem Contínua')],
    [sg.Button('Exportar Dados')],
    [sg.Button('Visualizar Canais Salvos')],
    [sg.Button('Listar Canais da Conta')],
    [sg.Button('Sair')],
    [sg.Text('ID do Canal:'), sg.Input(key='CANAL_ID', size=(20,1))],
    [sg.Multiline('', size=(60,10), key='LOGS', disabled=True)]
]

# Variáveis globais para credenciais
api_id = None
api_hash = None
phone = None
token = None
telegram_session = TelegramSession()

# Função para autenticação real
def autenticar(api_id, api_hash, phone, code_callback, log_callback):
    try:
        telegram_session.start(api_id, api_hash, phone, code_callback)
        log_callback('Autenticação realizada com sucesso!')
        return True
    except Exception as e:
        log_callback(f'Erro na autenticação: {e}')
        return False

def tela_credenciais():
    window = sg.Window('Leo Apps - Credenciais', layout_credenciais)
    while True:
        event, values = window.read()
        if event == sg.WINDOW_CLOSED:
            window.close()
            return None
        if event == 'Confirma':
            window.close()
            return values['API_ID'], values['API_HASH'], values['PHONE']

def tela_token():
    window = sg.Window('Leo Apps - Token', layout_token)
    while True:
        event, values = window.read()
        if event == sg.WINDOW_CLOSED:
            window.close()
            return None, False
        if event == 'Confirmar Token':
            window.close()
            return values['TOKEN'], True
        if event == 'Voltar':
            window.close()
            return None, False

def run_in_thread(target, args, window):
    threading.Thread(target=target, args=args, daemon=True).start()

def list_channels_thread(window):
    try:
        channels = telegram_session.list_dialogs()
        window.write_event_value('-CHANNELS_LOADED-', channels)
    except Exception as e:
        window.write_event_value('-CHANNELS_ERROR-', str(e))

def scrape_channels_thread(window):
    def log_callback(message):
        window.write_event_value('-LOG_UPDATE-', message)
    
    try:
        telegram_session.scrape_channels(log_callback)
    except Exception as e:
        window.write_event_value('-LOG_UPDATE-', f"Erro fatal durante a raspagem: {e}")

def tela_principal():
    window = sg.Window('Leo Apps - Menu', layout_principal, finalize=True)
    while True:
        event, values = window.read()
        if event == sg.WINDOW_CLOSED or event == 'Sair':
            telegram_session.disconnect()
            break
        
        canal_id = values.get('CANAL_ID', '').strip()

        if event == 'Adicionar Canal':
            if canal_id:
                result = telegram_session.add_channel(canal_id)
                window['LOGS'].update(f'{result}\n', append=True)
            else:
                window['LOGS'].update('Por favor, insira um ID de canal.\n', append=True)
        
        elif event == 'Remover Canal':
            if canal_id:
                result = telegram_session.remove_channel(canal_id)
                window['LOGS'].update(f'{result}\n', append=True)
            else:
                window['LOGS'].update('Por favor, insira um ID de canal para remover.\n', append=True)

        elif event == 'Remover TODOS os Canais':
            if sg.popup_yes_no('Tem certeza que deseja remover TODOS os canais?') == 'Yes':
                result = telegram_session.remove_all_channels()
                window['LOGS'].update(f'{result}\n', append=True)

        elif event == 'Visualizar Canais Salvos':
            channels = telegram_session.view_channels()
            if channels:
                log_message = "Canais salvos:\n" + "\n".join(channels)
            else:
                log_message = "Nenhum canal salvo."
            window['LOGS'].update(log_message)

        elif event == 'Listar Canais da Conta':
            window['LOGS'].update('Buscando canais...\n')
            run_in_thread(list_channels_thread, (window,), window)
        
        elif event == '-CHANNELS_LOADED-':
            channels = values[event]
            log_message = "Canais encontrados:\n" + "\n".join(channels)
            window['LOGS'].update(log_message)
        
        elif event == '-CHANNELS_ERROR-':
            error_message = values[event]
            window['LOGS'].update(f"Erro ao buscar canais: {error_message}\n")

        elif event == 'Raspar Todos os Canais':
            window['LOGS'].update('Iniciando processo de raspagem...\n')
            run_in_thread(scrape_channels_thread, (window,), window)

        elif event == '-LOG_UPDATE-':
            message = values[event]
            window['LOGS'].update(f"{message}\n", append=True)

        # Outros botões (ainda a serem implementados)
        elif event in ('Adicionar Múltiplos Canais', 'Ativar/Desativar Download de Mídia', 'Raspagem Contínua', 'Exportar Dados'):
            window['LOGS'].update(f'Funcionalidade "{event}" ainda não implementada.\n', append=True)

    window.close()

def main():
    global api_id, api_hash, phone

    while True:
        credenciais = tela_credenciais()
        if not credenciais:
            break
        
        api_id, api_hash, phone = credenciais

        # A função de callback agora só retorna o token, que será obtido da GUI
        def get_token_from_gui():
            token_val, confirmado = tela_token()
            if not confirmado:
                return None  # Usuário clicou em 'Voltar'
            return token_val

        # A autenticação agora é um processo de duas etapas
        # 1. Enviar o código
        # 2. Fazer login com o código (token)
        
        # Usaremos uma variável para armazenar o resultado da thread
        auth_result = {}

        def send_code_and_login():
            try:
                # Conecta e envia o código
                telegram_session.start(api_id, api_hash, phone, get_token_from_gui)
                auth_result['success'] = True
            except Exception as e:
                # Captura erros como número de telefone inválido
                auth_result['error'] = str(e)

        # Executa a conexão e o envio do código em uma thread
        auth_thread = threading.Thread(target=send_code_and_login, daemon=True)
        auth_thread.start()
        auth_thread.join() # Espera a conclusão

        if 'error' in auth_result:
            sg.popup_error(f"Erro na autenticação: {auth_result['error']}")
            continue # Volta para a tela de credenciais

        if auth_result.get('success'):
            # Se a autenticação (incluindo o sign_in com token) for bem-sucedida
            tela_principal()
            break # Encerra o app após sair da tela principal
        else:
            # Se o processo de envio de código falhou ou o usuário voltou,
            # a lógica dentro de start() já terá lidado com isso.
            # Se o sign_in falhar, a exceção será capturada.
            # Se o usuário clicou em 'Voltar', o callback retornou None.
            # Em ambos os casos, o fluxo deve voltar para a tela de credenciais.
            sg.popup("A autenticação não foi concluída. Tente novamente.")
            continue

if __name__ == '__main__':
    main()
