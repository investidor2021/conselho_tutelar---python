# repositorio.py

import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os


import streamlit as st


def conectar_planilha():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = None
    if hasattr(st, "secrets"):
        secret_info = st.secrets.get("gcp_service_account")
        if secret_info:
            try:
                creds_dict = dict(secret_info)
                creds = Credentials.from_service_account_info(
                    creds_dict,
                    scopes=scopes
                )
            except Exception as e:
                st.error("Erro ao carregar gcp_service_account de st.secrets. Verifique seu Secret ou use credenciais.json.")
                raise

    if creds is None:
        local_cred_path = "credenciais.json"
        if not os.path.exists(local_cred_path):
            raise FileNotFoundError(
                f"Arquivo de credenciais não encontrado: {local_cred_path}. "
                "Adicione o arquivo local ou configure st.secrets['gcp_service_account']."
            )
        creds = Credentials.from_service_account_file(
            local_cred_path,
            scopes=scopes
        )


    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key("1EJN2eziO3rpv2KFavAMIJbD7UQyZZOChGLXt81VTHww")

    return spreadsheet.worksheet("base_conselheiros")


def carregar_dados(sheet):
    dados = sheet.get_all_records()
    return pd.DataFrame(dados) if dados else pd.DataFrame()


def salvar_registro(sheet, registro: dict):
    headers = sheet.row_values(1)
    if not headers:
        headers = list(registro.keys())
        sheet.insert_row(headers, 1)
    else:
        headers_lower = {h.lower(): h for h in headers}
        novos = [k for k in registro.keys() if k.lower() not in headers_lower]
        if novos:
            headers.extend(novos)
            sheet.update("1:1", [headers])

    registro_lower = {k.lower(): v for k, v in registro.items()}
    linha = []
    for h in headers:
        if h in registro:
            linha.append(registro.get(h, ""))
        else:
            linha.append(registro_lower.get(h.lower(), ""))
    sheet.append_row(linha)

def pagamento_ja_existe(sheet, nome, referencia, tipo):
    registros = sheet.get_all_records()
    for r in registros:
        if (
            r.get("nome") == nome and
            r.get("referencia") == referencia and
            r.get("tipo") == tipo
        ):
            return True
    return False
