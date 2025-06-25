# ==============================================================================
# VERSÃO FINAL E FUNCIONAL DO app.py - 24 de Junho de 2025
# ==============================================================================

import os
import requests
import uuid
import mercadopago
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from unidecode import unidecode
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- CONFIGURAÇÕES GERAIS (LIDAS DO AMBIENTE DO RENDER) ---
MP_ACCESS_TOKEN = os.getenv('MP_ACCESS_TOKEN')
PARENT_FOLDER_ID = os.getenv('PARENT_FOLDER_ID')
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')

app = Flask(__name__)

# --- MEMÓRIA TEMPORÁRIA DE PEDIDOS ---
pedidos_pendentes = {}

# --- TABELA DE PREÇOS E SERVIÇOS ---
SERVICOS = {
    'impressao': {'descricao': 'Impressão P&B', 'preco': 1.50, 'instrucao': 'Envie o arquivo.'},
    'imprimir': {'descricao': 'Impressão P&B', 'preco': 1.50, 'instrucao': 'Envie o arquivo.'},
    'curriculo': {'descricao': 'Criação de Currículo', 'preco': 15.00, 'instrucao': "Envie 'quero um currículo'."},
    'certidao': {'descricao': 'Emissão de Certidão', 'preco': 10.00, 'instrucao': "Envie 'preciso da certidão'."},
    'foto': {'descricao': 'Impressão de Foto 3x4', 'preco': 8.00, 'instrucao': "Envie 'imprimir foto 3x4'."}
}

# --- FUNÇÕES AUXILIARES ---

def normalize_text(text):
    """Remove acentos e converte para minúsculas."""
    return unidecode(text.lower())

def upload_to_drive(file_path, file_name, user_phone_number):
    """Faz o upload de um arquivo para o Google Drive."""
    SERVICE_ACCOUNT_FILE = 'credentials.json'
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)
    novo_nome_arquivo = f"{user_phone_number}-{file_name}"
    file_metadata = {'name': novo_nome_arquivo, 'parents': [PARENT_FOLDER_ID]}
    media = MediaFileUpload(file_path, mimetype='application/octet-stream', resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    print(f"Arquivo '{novo_nome_arquivo}' enviado para o Google Drive com ID: {file.get('id')}")
    os.remove(file_path)

#
# SUBSTITUA SUA FUNÇÃO ANTIGA POR ESTA VERSÃO CORRIGIDA
#
def gerar_cobranca_pix(valor, descricao):
    """Gera uma cobrança Pix única via API do Mercado Pago."""
    try:
        if not MP_ACCESS_TOKEN:
            print("ERRO: MP_ACCESS_TOKEN não encontrado nas variáveis de ambiente.")
            return None, None

        sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
        id_unico_referencia = str(uuid.uuid4())
        hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME')
        url_notificacao = f"https://{hostname}/pix-webhook" if hostname else None

        # AQUI ESTÁ A MUDANÇA: Adicionamos o bloco "payer"
        request_data = {
            "transaction_amount": round(float(valor), 2),
            "description": descricao,
            "payment_method_id": "pix",
            "payer": {
                "email": "test@example.com"  # Email genérico para o pagador
            },
            "notification_url": url_notificacao,
            "external_reference": id_unico_referencia
        }
        
        payment_response = sdk.payment().create(request_data)
        payment = payment_response["response"]

        if payment_response["status"] in [200, 201]:
            copia_e_cola = payment["point_of_interaction"]["transaction_data"]["qr_code"]
            payment_id = payment['id']
            print(f"Cobrança Pix (ID: {payment_id}) gerada com sucesso.")
            return copia_e_cola, payment_id
        else:
            print(f"ERRO do Mercado Pago: {payment_response}")
            return None, None
    except Exception as e:
        print(f"ERRO CRÍTICO ao gerar cobrança Pix: {e}")
        return None, None

def enviar_whatsapp(para_numero, mensagem_texto):
    """Envia uma mensagem de WhatsApp usando a API da Twilio."""
    try:
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
            print("ERRO: Variáveis de ambiente da Twilio não configuradas.")
            return
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
                          body=mensagem_texto,
                          from_=f'whatsapp:{TWILIO_WHATSAPP_NUMBER}',
                          to=f'whatsapp:{para_numero}'
                      )
        print(f"Mensagem de confirmação enviada para {para_numero}. SID: {message.sid}")
    except Exception as e:
        print(f"ERRO ao enviar mensagem de confirmação via WhatsApp: {e}")

# --- ROTAS (ENDPOINTS) DO FLASK ---

#
# SUBSTITUA TODA A SUA FUNÇÃO WHATSAPP_REPLY POR ESTA VERSÃO CORRIGIDA
#
@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    """Rota principal que lida com as mensagens do WhatsApp."""
    num_media = int(request.values.get("NumMedia", 0))
    corpo_mensagem_normalizado = normalize_text(request.values.get('Body', ''))
    numero_cliente = request.values.get('From', '').replace('whatsapp:', '')
    
    response = MessagingResponse()
    servico_encontrado = None

    print(f"Mensagem recebida de {numero_cliente}: '{request.values.get('Body', '')}' (NumMedia: {num_media})")

    if num_media > 0:
        try:
            media_url = request.values.get('MediaUrl0')
            original_filename = media_url.split('/')[-1]
            r = requests.get(media_url, stream=True)
            if not os.path.exists('temp_files'):
                os.makedirs('temp_files')
            temp_filepath = os.path.join("temp_files", original_filename)
            with open(temp_filepath, 'wb') as f:
                f.write(r.content)
            
            upload_to_drive(temp_filepath, original_filename, numero_cliente)
            
            servico_encontrado = SERVICOS['impressao']
            servico_encontrado['descricao'] = f"Impressão do arquivo '{original_filename}'"
        except Exception as e:
            print(f"ERRO no processamento do arquivo: {e}")
            response.message("Opa, tive um problema técnico ao processar seu arquivo. Tente novamente.")
            return str(response)
    else:
        for chave, detalhes in SERVICOS.items():
            if chave in corpo_mensagem_normalizado:
                servico_encontrado = detalhes
                print(f"Palavra-chave '{chave}' encontrada! Ativando serviço: {detalhes['descricao']}")
                break
    
    if servico_encontrado:
        descricao = servico_encontrado['descricao']
        preco = servico_encontrado['preco']
        preco_formatado = f"R$ {preco:.2f}".replace('.', ',')
        
        print(f"Gerando cobrança Pix de {preco_formatado} para '{descricao}'...")
        pix_copia_e_cola, payment_id = gerar_cobranca_pix(preco, descricao)

        if pix_copia_e_cola:
            msg_instrucoes = (
                f"Serviço: {descricao}\n"
                f"Valor: {preco_formatado}\n\n"
                f"✅ *Seu PIX foi gerado!*\n\n"
                f"Copie o código da *próxima mensagem* e cole no seu app do banco."
            )
            response.message(msg_instrucoes)
            response.message(pix_copia_e_cola)
            pedidos_pendentes[str(payment_id)] = numero_cliente
            print(f"Aguardando pagamento para o ID {payment_id} do cliente {numero_cliente}")
        else:
            msg_text = "Opa, desculpe! Tive um problema ao gerar seu Pix. Por favor, tente novamente em alguns instantes."
            response.message(msg_text)
    else:
        print("Nenhuma palavra-chave encontrada. Enviando menu de ajuda.")
        menu_ajuda = "Olá! Não entendi qual serviço você deseja. Nossos serviços disponíveis são:"
        servicos_unicos = {}
        for detalhes in SERVICOS.values():
            servicos_unicos[detalhes['descricao']] = detalhes['instrucao']
        for descricao, instrucao in servicos_unicos.items():
            menu_ajuda += f"\n\n📄 *{descricao}*: {instrucao}"
        response.message(menu_ajuda)

    # ESTA É A LINHA DO ERRO. Note que ela está alinhada com o 'if servico_encontrado'
    # mas ainda está DENTRO do 'def whatsapp_reply'.
    return str(response)
    
def pix_webhook_handler():
    """Recebe e processa notificações de pagamento do Mercado Pago."""
    data = request.json
    print("Webhook do Mercado Pago recebido!")
    print(data)
    if data.get("type") == "payment":
        payment_id = data["data"]["id"]
        sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
        payment_info = sdk.payment().get(payment_id)
        if payment_info["status"] == 200:
            payment_status = payment_info["response"]["status"]
            print(f"Status do pagamento {payment_id}: {payment_status}")
            if payment_status == "approved":
                numero_cliente = pedidos_pendentes.pop(str(payment_id), None)
                if numero_cliente:
                    print(f"Pagamento APROVADO! Enviando confirmação para {numero_cliente}...")
                    mensagem_confirmacao = "✅ Pagamento confirmado com sucesso! Seu pedido já está na fila de produção."
                    enviar_whatsapp(numero_cliente, mensagem_confirmacao)
                else:
                    print(f"AVISO: Pagamento {payment_id} aprovado, mas não foi encontrado na lista de pedidos pendentes.")
    return "OK", 200

if __name__ == "__main__":
    app.run(port=5002)