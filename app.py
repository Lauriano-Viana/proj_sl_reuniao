import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from streamlit_calendar import calendar
import uuid

# --- CONFIGURAÇÕES E INICIALIZAÇÃO ---
st.set_page_config(
    page_title="Agendamento de Sala de Reunião",
    page_icon="📅",
    layout="wide",
)

# Carregar segredos
try:
    ADMIN_EMAIL = st.secrets["ADMIN_EMAIL"]
    EMAIL_SENDER = st.secrets["EMAIL_SENDER"]
    EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]
    GSHEET_URL = st.secrets["GSHEET_URL"]
    
    # MUITO IMPORTANTE: Carrega as credenciais do Google a partir da estrutura de dicionário nos segredos
    google_credentials_dict = st.secrets["google_credentials"]

except (FileNotFoundError, KeyError) as e:
    st.error(f"Erro ao carregar os segredos. Verifique a configuração no Streamlit Community Cloud. Erro: {e}")
    st.stop()

# Autenticação com Google Sheets
try:
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(google_credentials_dict, scopes=scopes) # MUDANÇA AQUI
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_url(GSHEET_URL)
    sheet = spreadsheet.worksheet("Agendamentos")
except Exception as e:
    st.error(f"Não foi possível conectar ao Google Sheets. Verifique suas credenciais e a URL da planilha. Erro: {e}")
    st.stop()

# --- FUNÇÕES AUXILIARES ---

def send_email(to_address, subject, body):
    """Função para enviar e-mails."""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = to_address
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, to_address, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Erro ao enviar e-mail: {e}")
        return False

def check_conflict(df, date, start_time, end_time):
    """Verifica se há conflito de horários com agendamentos APROVADOS."""
    date_str = date.strftime('%Y-%m-%d')
    
    # Filtra apenas agendamentos aprovados no mesmo dia
    approved_bookings = df[(df['Status'] == 'Aprovado') & (df['Data'] == date_str)]

    for _, row in approved_bookings.iterrows():
        existing_start = datetime.strptime(row['Início'], '%H:%M:%S').time()
        existing_end = datetime.strptime(row['Término'], '%H:%M:%S').time()
        
        # Verifica sobreposição
        # (StartA < EndB) and (EndA > StartB)
        if start_time < existing_end and end_time > existing_start:
            return True # Conflito encontrado
    return False # Sem conflito

def get_data_as_df():
    """Busca os dados da planilha e retorna como DataFrame do Pandas."""
    data = sheet.get_all_records()
    if not data:
        # Se a planilha está vazia, cria um DataFrame com as colunas certas
        return pd.DataFrame(columns=['ID', 'Nome', 'Email', 'Data', 'Início', 'Término', 'Pauta', 'Participantes', 'Descrição', 'Status', 'Criado Em', 'Equipamentos'])
    return pd.DataFrame(data)

# --- INTERFACE DO STREAMLIT ---

st.title("📅 Sistema de Agendamento de Sala de Reunião")
st.markdown("---")

# Abas de navegação
tab1, tab2, tab3 = st.tabs(["**Visualizar Calendário**", "**Solicitar Reserva**", "**Painel do Administrador**"])

# Carrega os dados uma vez
df_data = get_data_as_df()

# --- ABA 1: CALENDÁRIO ---
with tab1:
    st.header("🗓️ Calendário de Reservas Aprovadas")

    events = []
    # Filtra apenas os agendamentos aprovados
    approved_df = df_data[df_data['Status'] == 'Aprovado'].copy()
    
    # Converte colunas de data e hora para o formato datetime
    if not approved_df.empty:
        try:
            approved_df['start_datetime'] = pd.to_datetime(approved_df['Data'] + ' ' + approved_df['Início'])
            approved_df['end_datetime'] = pd.to_datetime(approved_df['Data'] + ' ' + approved_df['Término'])

            for _, row in approved_df.iterrows():
                events.append({
                    "title": f"{row['Pauta']} ({row['Nome']})",
                    "start": row['start_datetime'].isoformat(),
                    "end": row['end_datetime'].isoformat(),
                    "color": "green", # Cor para eventos aprovados
                })
        except Exception as e:
             st.warning(f"Não foi possível formatar alguns eventos do calendário. Verifique os dados na planilha. Erro: {e}")


    calendar_options = {
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": "dayGridMonth,timeGridWeek,timeGridDay",
        },
        "initialView": "timeGridWeek",
        "slotMinTime": "08:00:00",
        "slotMaxTime": "19:00:00",
        "locale": "pt-br"
    }

    calendar(events=events, options=calendar_options)

# --- ABA 2: FORMULÁRIO DE SOLICITAÇÃO ---
with tab2:
    st.header("📝 Solicitar Reserva de Sala")

    with st.form("booking_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            nome = st.text_input("Seu Nome*", help="Nome do solicitante")
            email = st.text_input("Seu E-mail*", help="E-mail para receber as notificações")
            data = st.date_input("Data da Reunião*", min_value=datetime.today())
        with col2:
            inicio = st.time_input("Horário de Início*", step=1800) # step de 30 min
            termino = st.time_input("Horário de Término*", step=1800)
        
        pauta = st.text_input("Pauta/Assunto da Reunião*")
        participantes = st.text_area("Participantes", help="Liste os nomes ou e-mails dos participantes.")
        equipamentos = st.multiselect(
            "Equipamentos Necessários",
            ["Projetor", "Webcam", "Quadro Branco", "Café/Água"]
        )
        descricao = st.text_area("Descrição/Observações Adicionais")

        submit_button = st.form_submit_button("Enviar Solicitação")

    if submit_button:
        # Validações
        if not all([nome, email, data, inicio, termino, pauta]):
            st.warning("Por favor, preencha todos os campos obrigatórios (*).")
        elif inicio >= termino:
            st.error("O horário de término deve ser posterior ao horário de início.")
        elif check_conflict(df_data, data, inicio, termino):
             st.error("Conflito de horário! Já existe uma reserva aprovada para este período.")
        else:
            # Preparar dados para a planilha
            new_booking_data = {
                'ID': str(uuid.uuid4()), # Gera um ID único
                'Nome': nome,
                'Email': email,
                'Data': data.strftime('%Y-%m-%d'),
                'Início': inicio.strftime('%H:%M:%S'),
                'Término': termino.strftime('%H:%M:%S'),
                'Pauta': pauta,
                'Participantes': participantes,
                'Descrição': descricao,
                'Status': 'Pendente',
                'Criado Em': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'Equipamentos': ", ".join(equipamentos)
            }

            # Adicionar à planilha
            sheet.append_row(list(new_booking_data.values()))

            # Enviar e-mails de notificação
            # Para o Admin
            admin_subject = f"Nova Solicitação de Reserva: {pauta}"
            admin_body = f"""
            <h3>Nova Solicitação de Reserva de Sala</h3>
            <p>Uma nova reserva foi solicitada e aguarda sua aprovação.</p>
            <ul>
                <li><strong>Solicitante:</strong> {nome} ({email})</li>
                <li><strong>Data:</strong> {data.strftime('%d/%m/%Y')}</li>
                <li><strong>Horário:</strong> {inicio.strftime('%H:%M')} - {termino.strftime('%H:%M')}</li>
                <li><strong>Pauta:</strong> {pauta}</li>
            </ul>
            <p>Acesse o painel de administração para aprovar ou rejeitar.</p>
            """
            send_email(ADMIN_EMAIL, admin_subject, admin_body)

            # Para o Solicitante
            user_subject = "Sua solicitação de reserva foi recebida!"
            user_body = f"""
            <h3>Olá, {nome}!</h3>
            <p>Sua solicitação de reserva para a sala de reuniões foi recebida com sucesso e está pendente de aprovação.</p>
            <p><strong>Detalhes da sua solicitação:</strong></p>
            <ul>
                <li><strong>Data:</strong> {data.strftime('%d/%m/%Y')}</li>
                <li><strong>Horário:</strong> {inicio.strftime('%H:%M')} - {termino.strftime('%H:%M')}</li>
                <li><strong>Pauta:</strong> {pauta}</li>
            </ul>
            <p>Você receberá um novo e-mail assim que sua solicitação for aprovada ou rejeitada.</p>
            <p>Obrigado!</p>
            """
            send_email(email, user_subject, user_body)

            st.success("Sua solicitação foi enviada com sucesso! Você receberá um e-mail de confirmação.")
            st.balloons()


# --- ABA 3: PAINEL DO ADMINISTRADOR ---
with tab3:
    st.header("🔑 Painel do Administrador")
    
    pending_df = df_data[df_data['Status'] == 'Pendente']

    if pending_df.empty:
        st.info("Não há solicitações pendentes de aprovação.")
    else:
        st.subheader("Solicitações Pendentes")
        
        # Itera sobre cada solicitação pendente
        for index, row in pending_df.iterrows():
            with st.expander(f"**{row['Data']} | {row['Início']}-{row['Término']} | {row['Pauta']}** (Solicitante: {row['Nome']})"):
                st.write(f"**ID da Reserva:** `{row['ID']}`")
                st.write(f"**E-mail:** {row['Email']}")
                st.write(f"**Participantes:** {row['Participantes']}")
                st.write(f"**Equipamentos:** {row['Equipamentos']}")
                st.write(f"**Descrição:** {row['Descrição']}")
                st.write(f"**Solicitado em:** {row['Criado Em']}")

                col1, col2, col3 = st.columns([1, 1, 4])
                
                with col1:
                    if st.button("✅ Aprovar", key=f"approve_{row['ID']}"):
                        # Atualiza o status na planilha
                        cell = sheet.find(row['ID'])
                        sheet.update_cell(cell.row, cell.col + 9, 'Aprovado') # Coluna 'Status' é a 10ª (índice 9)
                        
                        # Notifica o usuário
                        subject = "Sua reserva foi APROVADA!"
                        body = f"Olá, {row['Nome']}.<br><br>Sua reserva para a reunião '{row['Pauta']}' no dia {row['Data']} das {row['Início']} às {row['Término']} foi <b>aprovada</b>."
                        send_email(row['Email'], subject, body)
                        
                        st.success(f"Reserva '{row['Pauta']}' aprovada!")
                        st.rerun()

                with col2:
                    if st.button("❌ Rejeitar", key=f"reject_{row['ID']}"):
                        # Atualiza o status na planilha
                        cell = sheet.find(row['ID'])
                        sheet.update_cell(cell.row, cell.col + 9, 'Rejeitado')
                        
                        # Notifica o usuário
                        subject = "Sua reserva foi REJEITADA"
                        body = f"Olá, {row['Nome']}.<br><br>Sua reserva para a reunião '{row['Pauta']}' no dia {row['Data']} das {row['Início']} às {row['Término']} foi <b>rejeitada</b>. Por favor, entre em contato com o administrador para mais detalhes ou tente um novo horário."
                        send_email(row['Email'], subject, body)

                        st.warning(f"Reserva '{row['Pauta']}' rejeitada!")
                        st.rerun()

    st.markdown("---")
    st.subheader("Todos os Agendamentos")
    st.dataframe(df_data, use_container_width=True)