# repositorio.py

import gspread
from google.oauth2.service_account import Credentials
import pandas as pd


def conectar_planilha():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_file(
        "credenciais.json",
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
        novos = [k for k in registro.keys() if k not in headers]
        if novos:
            headers.extend(novos)
            sheet.update("1:1", [headers])

    linha = [registro.get(h, "") for h in headers]
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
