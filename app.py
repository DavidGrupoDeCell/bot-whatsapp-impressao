# ==============================================================================
# VERSÃO COMPLETA E CORRIGIDA DO app.py - 24 de Junho de 2025
# ==============================================================================

import os
import requests
import uuid
import mercadopago
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from unidecode import unidecode
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- CONFIGURAÇÕES GERAIS ---
# Essas variáveis serão lidas do ambiente do Render
# (ou podem ser definidas aqui para teste local)
MP_ACCESS_TOKEN = os.getenv('MP_ACCESS_TOKEN')
PARENT_FOLDER_ID = os.getenv('PARENT_FOLDER_ID')

app = Flask(__name__)

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

def gerar_cobranca_pix(valor, descricao):
    """Gera uma cobrança Pix única via API do Mercado Pago."""
    try:
        if not MP_ACCESS_TOKEN:
            print("ERRO: MP_ACCESS_TOKEN não encontrado nas variáveis de ambiente.")
            return None, None

        sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
        id_unico_referencia = str(uuid.uuid4())
        
        # O Render fornece esta variável de ambiente automaticamente com a URL do seu serviço
        hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME')
        url_notificacao = f"https://{hostname}/pix-webhook" if hostname else None

        request_data = {
            "transaction_amount": round(float(valor), 2),
            "description": descricao,
            "payment_method_id": "pix",
            "notification_url": url_notificacao,
            "external_reference": id_unico_referencia
        }
        
        payment_response = sdk.payment().create(request_data)
        payment = payment_response["response"]

        if payment_response["status"] in [200, 201]:
            copia_e_cola = payment["point_of_interaction"]["transaction_data"]["qr_code"]
            payment_id = payment['id']
            print(f"Cobrança Pix (ID: {payment_id}) gerada com sucesso para a referência {id_unico_referencia}")
            return copia_e_cola, payment_id
        else:
            print(f"ERRO do Mercado Pago: {payment_response}")
            return None, None
    except Exception as e:
        print(f"ERRO CRÍTICO ao gerar cobrança Pix: {e}")
        return None, None

# --- ROTAS PRINCIPAIS DO FLASK ---

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
            msg_text = (
                f"Serviço: {descricao}\n"
                f"Valor: {preco_formatado}\n\n"
                f"✅ *Seu PIX foi gerado!*\n\n"
                f"Clique no código abaixo para copiar e pague no seu app do banco:\n\n"
                f"`{pix_copia_e_cola}`"
            )
            print(f"Aguardando pagamento para o ID do Mercado Pago: {payment_id}")
        else:
            msg_text = "Opa, desculpe! Tive um problema ao gerar seu Pix. Por favor, tente novamente em alguns instantes."
        
        response.message(msg_text)
    else:
        print("Nenhuma palavra-chave encontrada. Enviando menu de ajuda.")
        menu_ajuda = "Olá! Não entendi qual serviço você deseja. Nossos serviços disponíveis são:\n"
        servicos_unicos = {}
        for detalhes in SERVICOS.values():
            servicos_unicos[detalhes['descricao']] = detalhes['instrucao']
        for descricao, instrucao in servicos_unicos.items():
            menu_ajuda += f"\n📄 *{descricao}*: {instrucao}"
        response.message(menu_ajuda)

    return str(response)

@app.route("/pix-webhook", methods=['POST'])
def pix_webhook_handler():
    """Recebe e processa notificações de pagamento do Mercado Pago."""
    data = request.json
    print("Webhook do Mercado Pago recebido!")
    print(data)
    # Aqui entrará a lógica futura para confirmar o pagamento
    return "OK", 200

if __name__ == "__main__":
    app.run(port=5002)