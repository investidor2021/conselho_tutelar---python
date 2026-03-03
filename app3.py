# app.py

import io
from datetime import date, timedelta
import streamlit as st
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from repositorio import pagamento_ja_existe
from reportlab.lib.utils import simpleSplit

from calculos import (
    calcular_mensal,
    calcular_ferias,
    calcular_rescisao,
    aplicar_faltas,
    calcular_irrf_2026,
    calcular_inss_rateado,
)
from constantes import TETO_INSS
from repositorio import conectar_planilha, carregar_dados, salvar_registro


def _fmt_moeda(valor):
    try:
        return f"R$ {float(valor):.2f}"
    except (TypeError, ValueError):
        return "R$ 0.00"


def _fmt_moeda_br(valor):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        numero = 0.0
    texto = f"{numero:,.2f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _fmt_data(data):
    if not data:
        return ""
    try:
        return data.strftime("%d/%m/%Y")
    except AttributeError:
        return str(data)


def _parse_num_ptbr(valor):
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return None
    texto = texto.replace("R$", "").replace(" ", "")
    if "," in texto and "." in texto:
        last_comma = texto.rfind(",")
        last_dot = texto.rfind(".")
        if last_dot > last_comma:
            # formato 1,234.56 -> remove milhar e mantém ponto decimal
            texto = texto.replace(",", "")
        else:
            # formato 1.234,56 -> remove milhar e troca vírgula por ponto
            texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _safe_float(valor, padrao=0.0):
    parsed = _parse_num_ptbr(valor)
    if parsed is None:
        return padrao
    return parsed


def _draw_label_val(c, x_left, x_right, y, label, value, font="Helvetica", size=10.5):
    c.setFont(font, size)
    label = str(label)
    value = str(value)
    label_w = pdfmetrics.stringWidth(label, font, size)
    value_w = pdfmetrics.stringWidth(value, font, size)
    dot_w = pdfmetrics.stringWidth(".", font, size)
    available = x_right - (x_left + label_w + value_w + 4)
    dots = max(int(available / dot_w), 0)
    c.drawString(x_left, y, f"{label} {'.' * dots}")
    c.drawString(x_right - value_w, y, value)


def _parse_referencia(referencia):
    try:
        mes, ano = referencia.split("/")
        return int(mes), int(ano)
    except ValueError:
        return None, None


def _is_julho(referencia):
    mes, _ = _parse_referencia(referencia)
    return mes == 7


def _add_meses(referencia, meses):
    mes, ano = _parse_referencia(referencia)
    if mes is None:
        return referencia
    total = (ano * 12 + (mes - 1)) + meses
    novo_ano = total // 12
    novo_mes = (total % 12) + 1
    return f"{novo_mes:02d}/{novo_ano}"


def _dias_no_mes(ano, mes):
    if mes == 12:
        prox = date(ano + 1, 1, 1)
    else:
        prox = date(ano, mes + 1, 1)
    return (prox - date(ano, mes, 1)).days


def _calcular_ferias_bruto(valor_base, dias_ferias):
    salario_proporcional = (valor_base / 30) * dias_ferias
    terco_constitucional = salario_proporcional / 3
    return round(salario_proporcional + terco_constitucional, 2)


def _calcular_ferias_componentes(valor_base, dias_ferias):
    salario_proporcional = (valor_base / 30) * dias_ferias
    terco_constitucional = salario_proporcional / 3
    return round(salario_proporcional, 2), round(terco_constitucional, 2)


def _calcular_lancamentos_ferias(referencia, valor_base, data_inicio, dias_ferias):
    end_date = data_inicio + timedelta(days=dias_ferias - 1)
    dias_mes_inicio = _dias_no_mes(data_inicio.year, data_inicio.month)
    dias_ferias_mes_inicio = min(dias_ferias, dias_mes_inicio - data_inicio.day + 1)
    dias_ferias_mes_seguinte = dias_ferias - dias_ferias_mes_inicio

    dias_trab_mes_inicio = 30 - dias_ferias_mes_inicio
    dias_trab_mes_seguinte = 30 - dias_ferias_mes_seguinte

    ferias_bruto = _calcular_ferias_bruto(valor_base, dias_ferias)

    lancamentos = []
    # 1) Mês atual: salário mês anterior + férias
    lancamentos.append({
        "etapa": "Férias - Pagamento (mês atual)",
        "referencia": referencia,
        "dias_trabalhados": "",
        "dias_desconto": "",
        "ferias_bruto": ferias_bruto,
        "proventos": [
            ("Salário mês anterior", valor_base),
            (f"Férias {dias_ferias} dias + 1/3", ferias_bruto),
        ],
        "descontos": [],
        "bruto_base": valor_base + ferias_bruto,
    })

    # 2) Mês seguinte: pagar dias trabalhados no mês do início
    lancamentos.append({
        "etapa": "Férias - Dias trabalhados (mês seguinte)",
        "referencia": _add_meses(referencia, 1),
        "dias_trabalhados": dias_trab_mes_inicio,
        "dias_desconto": "",
        "ferias_bruto": 0.0,
        "proventos": [
            (f"Dias trabalhados ({dias_trab_mes_inicio} dias)", (valor_base / 30) * dias_trab_mes_inicio),
        ],
        "descontos": [],
        "bruto_base": (valor_base / 30) * dias_trab_mes_inicio,
    })

    # 3) Mês 3: descontar dias de férias que caíram no mês seguinte
    lancamentos.append({
        "etapa": "Férias - Ajuste (mês 3)",
        "referencia": _add_meses(referencia, 2),
        "dias_trabalhados": dias_trab_mes_seguinte,
        "dias_desconto": dias_ferias_mes_seguinte,
        "ferias_bruto": 0.0,
        "proventos": [
            (f"Salário mês anterior", valor_base),
        ],
        "descontos": [
            (f"Desconto férias ({dias_ferias_mes_seguinte} dias)", (valor_base / 30) * dias_ferias_mes_seguinte),
        ],
        "bruto_base": (valor_base / 30) * dias_trab_mes_seguinte,
    })

    return lancamentos, end_date, dias_ferias_mes_inicio, dias_ferias_mes_seguinte


def _tem_ferias_no_periodo(df, nome, referencia):
    if df.empty:
        return False
    if "nome" not in df.columns or "referencia" not in df.columns or "tipo" not in df.columns:
        return False
    filtro = (df["nome"] == nome) & (df["referencia"] == referencia)
    if not filtro.any():
        return False
    tipos = df.loc[filtro, "tipo"].astype(str)
    return tipos.str.contains("Férias").any()


def _normalizar_valor_registro(valor):
    numero = _safe_float(valor, 0.0)
    if numero >= 10000 and abs(numero - int(numero)) < 1e-6:
        return numero / 100.0
    return numero


def _proventos_descontos_row(row, normalizar_valor=None):
    if normalizar_valor is None:
        normalizar_valor = lambda x: _safe_float(x, 0.0)
    etapa = str(row.get("etapa", ""))
    salario_base = normalizar_valor(row.get("salario_base", 0.0))
    dias_trabalhados = _safe_float(row.get("dias_trabalhados", 0.0))
    dias_desconto = _safe_float(row.get("dias_desconto", 0.0))
    ferias_dias = row.get("ferias_dias", "")
    decimo = normalizar_valor(row.get("decimo_terceiro", 0.0))

    proventos = []
    descontos = []

    if "Pagamento" in etapa:
        ferias_bruto = normalizar_valor(row.get("ferias_bruto", 0.0))
        ferias_salario = normalizar_valor(row.get("ferias_salario", 0.0))
        ferias_terco = normalizar_valor(row.get("ferias_terco", 0.0))
        if ferias_bruto == 0.0:
            ferias_bruto = _calcular_ferias_bruto(salario_base, float(ferias_dias or 0))
        if ferias_salario == 0.0 and ferias_terco == 0.0:
            ferias_salario, ferias_terco = _calcular_ferias_componentes(
                salario_base, float(ferias_dias or 0)
            )
        proventos = [
            ("Salário mês anterior", salario_base),
            (f"Férias {ferias_dias} dias", ferias_salario),
            ("1/3 de férias", ferias_terco),
        ]
        inss_salario = normalizar_valor(row.get("inss_salario", 0.0))
        inss_ferias = normalizar_valor(row.get("inss_ferias", 0.0))
        if inss_salario or inss_ferias:
            descontos = [
                ("INSS salário", inss_salario),
                ("INSS férias", inss_ferias),
                ("IRRF", normalizar_valor(row.get("irrf", 0.0))),
            ]
    elif "Dias trabalhados" in etapa:
        proventos = [
            (f"Dias trabalhados ({int(dias_trabalhados)} dias)", (salario_base / 30) * dias_trabalhados),
        ]
    elif "Ajuste" in etapa:
        proventos = [
            ("Salário mês anterior", salario_base),
        ]
        descontos = [
            (f"Desconto férias ({int(dias_desconto)} dias)", (salario_base / 30) * dias_desconto),
        ]
    else:
        if decimo > 0:
            proventos = [
                ("Salario base", salario_base),
                ("1/2 13º", decimo),
            ]

    return proventos, descontos

def _draw_label_block(c, x, x_max, y, label, value, font_size=10.5):
    # Label
    c.setFont("Helvetica-Bold", font_size)
    c.drawString(x, y, label)

    # Valor (linha inteira abaixo)
    c.setFont("Helvetica", font_size)
    max_width = x_max - x
    linhas = simpleSplit(str(value), "Helvetica", font_size, max_width)

    text_y = y - font_size - 2
    for linha in linhas:
        c.drawString(x, text_y, linha)
        text_y -= font_size + 2

    return text_y

def gerar_pdf_pagamento(brasao_path, dados, resultado):
    buffer = io.BytesIO()
    page_width, page_height = A4
    c = canvas.Canvas(buffer, pagesize=A4)

    margin_x = 15 * mm
    margin_top = 15 * mm
    margin_bottom = 18 * mm

    # Header with centered brasao and prefeitura text
    brasao = ImageReader(brasao_path)
    brasao_w = 28 * mm
    brasao_h = 28 * mm
    brasao_x = (page_width - brasao_w) / 2
    brasao_y = page_height - margin_top - brasao_h
    c.drawImage(brasao, brasao_x, brasao_y, width=brasao_w, height=brasao_h, mask="auto")

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(page_width / 2, brasao_y - 5 * mm, "PREFEITURA MUNICIPAL")
    c.setFont("Helvetica", 10)
    c.drawCentredString(page_width / 2, brasao_y - 11 * mm, "Vargem Grande do Sul - SP")
    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(page_width / 2, brasao_y - 17 * mm, "A Perola da Mantiqueira")

    # Title
    title_y = page_height - margin_top - 54 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin_x, title_y, "Relatorio de Pagamento")

    # Boxes
    box_left = margin_x
    box_right = page_width - margin_x
    box_width = box_right - box_left
    section_gap = 6 * mm

    # Section: Dados do pagamento
    section1_top = title_y - 8 * mm
    section1_height = 48 * mm
    c.setLineWidth(0.6)
    c.rect(box_left, section1_top - section1_height, box_width, section1_height)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(box_left + 4 * mm, section1_top - 6 * mm, "Dados do pagamento")



    col_left_x = box_left + 6 * mm
    col_right_x = box_left + box_width / 2 + 4 * mm
    y = section1_top - 14 * mm
    line_gap = 6 * mm
    c.setFont("Helvetica", 8)
    left_right = box_left + box_width / 2 - 4 * mm
    y = _draw_label_block(
    c,
    col_left_x,
    box_left + box_width - 6 * mm,  # largura total da caixa
    y,
    "Credor(a)",
    dados.get("nome", "")
    ) 

    _draw_label_val(c, col_left_x, left_right, y, "Tipo", dados.get("tipo", ""))
    y -= line_gap
    if dados.get("etapa"):
        _draw_label_val(c, col_left_x, left_right, y, "Etapa", dados.get("etapa"))
        y -= line_gap
    if dados.get("competencia"):
        _draw_label_val(c, col_left_x, left_right, y, "Competência", dados.get("competencia"))
        y -= line_gap
    _draw_label_val(
        c,
        col_left_x,
        left_right,
        y,
        "Valor bruto",
        _fmt_moeda_br(dados.get("valor_original", dados.get("valor"))),
    )

    y2 = section1_top - 14 * mm
    right_right = box_right - 6 * mm
    _draw_label_val(c, col_right_x, right_right, y2, "Dias de falta", dados.get("dias_falta", ""))
    y2 -= line_gap
    if dados.get("teto_inss"):
        _draw_label_val(c, col_right_x, right_right, y2, "Teto INSS", _fmt_moeda_br(dados.get("teto_inss")))
        y2 -= line_gap
    if dados.get("dias_ferias"):
        _draw_label_val(c, col_right_x, right_right, y2, "Dias de ferias", dados.get("dias_ferias"))
        y2 -= line_gap
    if dados.get("data_inicio"):
        _draw_label_val(c, col_right_x, right_right, y2, "Inicio das ferias", dados.get("data_inicio"))
        y2 -= line_gap
    if dados.get("data_termino"):
        _draw_label_val(c, col_right_x, right_right, y2, "Termino das ferias", dados.get("data_termino"))

    # Section: Holerite (Proventos / Descontos)
    section2_top = section1_top - section1_height - section_gap
    section2_height = 70 * mm
    c.rect(box_left, section2_top - section2_height, box_width, section2_height)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(box_left + 4 * mm, section2_top - 6 * mm, "Holerite")

    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(col_left_x, section2_top - 14 * mm, "Proventos")
    c.drawString(col_right_x, section2_top - 14 * mm, "Descontos")

    y = section2_top - 22 * mm
    c.setFont("Helvetica", 10.5)
    proventos = dados.get("proventos")
    descontos = dados.get("descontos")
    total_proventos = 0.0
    total_descontos = 0.0

    if proventos or descontos:
        y_prov = y
        if proventos:
            for desc, valor in proventos:
                total_proventos += _safe_float(valor)
                _draw_label_val(
                    c,
                    col_left_x,
                    box_left + box_width / 2 - 4 * mm,
                    y_prov,
                    desc,
                    _fmt_moeda_br(valor),
                )
                y_prov -= line_gap

        y_desc = y
        if descontos:
            for desc, valor in descontos:
                if valor > 0:
                    total_descontos += _safe_float(valor)
                    _draw_label_val(
                        c,
                        col_right_x,
                        box_right - 6 * mm,
                        y_desc,
                        desc,
                        _fmt_moeda_br(valor),
                    )
                    y_desc -= line_gap

        if not dados.get("descontos_completos"):
            total_descontos += _safe_float(resultado.get("inss")) + _safe_float(resultado.get("irrf"))
            _draw_label_val(
                c,
                col_right_x,
                box_right - 6 * mm,
                y_desc,
                "INSS",
                _fmt_moeda_br(resultado.get("inss")),
            )
            y_desc -= line_gap
            _draw_label_val(
                c,
                col_right_x,
                box_right - 6 * mm,
                y_desc,
                "IRRF",
                _fmt_moeda_br(resultado.get("irrf")),
            )
    else:
        valor_original = dados.get("valor_original", dados.get("valor", 0.0))
        valor_ajustado = dados.get("valor_ajustado", dados.get("valor", 0.0))
        desconto_faltas = max(_safe_float(valor_original) - _safe_float(valor_ajustado), 0.0)
        total_proventos = _safe_float(resultado.get("bruto", valor_original))
        total_descontos = desconto_faltas + _safe_float(resultado.get("inss")) + _safe_float(resultado.get("irrf"))

        # Proventos
        _draw_label_val(
            c,
            col_left_x,
            box_left + box_width / 2 - 4 * mm,
            y,
            "Vencimentos",
            _fmt_moeda_br(valor_original),
        )
        y -= line_gap
        _draw_label_val(
            c,
            col_left_x,
            box_left + box_width / 2 - 4 * mm,
            y,
            "Bruto calculado",
            _fmt_moeda_br(resultado.get("bruto")),
        )

        # Descontos
        y2 = section2_top - 22 * mm
        if desconto_faltas > 0:
            _draw_label_val(
                c,
                col_right_x,
                box_right - 6 * mm,
                y2,
                "Faltas",
                _fmt_moeda_br(desconto_faltas),
            )
            y2 -= line_gap
        _draw_label_val(
            c,
            col_right_x,
            box_right - 6 * mm,
            y2,
            "INSS",
            _fmt_moeda_br(resultado.get("inss")),
        )
        y2 -= line_gap
        _draw_label_val(
            c,
            col_right_x,
            box_right - 6 * mm,
            y2,
            "IRRF",
            _fmt_moeda_br(resultado.get("irrf")),
        )

    # Totais proventos/descontos
    y_total = section2_top - section2_height + 20 * mm
    c.setFont("Helvetica-Bold", 10.5)
    _draw_label_val(
        c,
        col_left_x,
        box_left + box_width / 2 - 4 * mm,
        y_total,
        "Total proventos",
        _fmt_moeda_br(total_proventos),
    )
    _draw_label_val(
        c,
        col_right_x,
        box_right - 6 * mm,
        y_total,
        "Total descontos",
        _fmt_moeda_br(total_descontos),
    )

    # Totais
    y_tot = section2_top - section2_height + 12 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(col_left_x, y_tot, f"Liquido a receber: {_fmt_moeda_br(resultado.get('liquido'))}")

    # Signature line
    sign_y = margin_bottom + 18 * mm
    c.setFont("Helvetica", 10)
    c.line(box_left, sign_y, box_left + 70 * mm, sign_y)
    c.drawString(box_left, sign_y - 4 * mm, "Assinatura")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer



st.set_page_config(page_title="Conselho Tutelar", layout="wide")

if "resultado" not in st.session_state:
    st.session_state.resultado = None
if "resultado_ferias" not in st.session_state:
    st.session_state.resultado_ferias = None
if "valor_ajustado" not in st.session_state:
    st.session_state.valor_ajustado = None
if "valor_original" not in st.session_state:
    st.session_state.valor_original = None


st.title("💼 Sistema de Pagamentos – Conselho Tutelar")

nomes = [
    "BRUNA SIMOES GUTIERRES",
    "CLEIDE APARECIDA PATROCINIO CAVALARI",
    "CRISTINA ALVES CARDOSO",
    "ISABELA FACONI",
    "SONIA HELENA ROQUE DE CARVALHO",
    "FERNANDA ROBERTA DONNINI (SUPLENTE)",
    "LUCIEN DONIZETE SILVA"
]



menu = st.sidebar.radio(
    "Menu",
    ["➕ Novo Pagamento", "📊 Registros", "ℹ️ Sobre"]
)


sheet = conectar_planilha()

# =========================
# 📄 NOVO PAGAMENTO
# =========================
if menu == "➕ Novo Pagamento":
    st.subheader("Novo pagamento")

    
    col1, col2, col3, col4= st.columns([3,1,1,2])

    with col1:
        nome = st.selectbox("Nome da Conselheira", nomes)
        
    with col2:
        mes = st.selectbox("Referência Mês", [f"{i:02d}" for i in range(1, 13)])
        
        
    
    with col3:
        ano = st.selectbox("Ano", range(2026, 2031))
        

    with col4:
        referencia = f"{mes}/{ano}"
        st.write("Ref.:")
        st.write(referencia)


    df_registros = carregar_dados(sheet)
    tem_ferias_ref = _tem_ferias_no_periodo(df_registros, nome, referencia)
    
    tipo = st.radio(
        "Tipo",
        ["Mensal", "Férias", "Rescisão"],
        horizontal=True
    )
    if tipo == "Mensal" and tem_ferias_ref:
        st.warning("Já existem lançamentos de férias para esta pessoa e referência. Evite pagar mês cheio.")
    dias_ferias = None
    data_inicio = None
    data_termino = None
    if tipo == "Férias":
        c1, c2, c3,c4 = st.columns([1, 2, 2,8])
        with c1:
            dias_ferias = st.selectbox("Dias", [15, 30])
        with c2:
            data_inicio = st.date_input("Início", format="DD/MM/YYYY")
        with c3:
            if dias_ferias:
                data_termino = data_inicio + timedelta(days=dias_ferias - 1)
            st.text_input(
                "Término",
                value=_fmt_data(data_termino),
                disabled=True
            )

    col1, col2, col3,col4 = st.columns([2, 2, 1,10])

    with col1:
        valor = st.number_input("Valor bruto Salarial", value=3645.32, step=100.0)
    with col2:
        teto = st.number_input("Teto Inss", value=8475.55)
    with col3:    
        dias_falta = st.number_input("Dias de falta", min_value=0, max_value=30, step=1)

    pagar_decimo = False
    valor_decimo = 0.0
    if _is_julho(referencia):
        c13_1, c13_2 = st.columns([1, 2])
        with c13_1:
            pagar_decimo = st.checkbox("Pagar 1/2 13º", value=False)
        with c13_2:
            if pagar_decimo:
                valor_decimo = st.number_input(
                    "Valor 1/2 13º",
                    min_value=0.0,
                    value=round(valor / 2, 2),
                    step=100.0
                )
    resultado = st.session_state.resultado


    if st.button("Calcular"):
        valor_ajustado = aplicar_faltas(valor, dias_falta)
        st.session_state.valor_original = valor
        st.session_state.valor_ajustado = valor_ajustado
        st.session_state.resultado = None
        st.session_state.resultado_ferias = None

        if tipo == "Mensal":
            if tem_ferias_ref:
                st.error("Já existem lançamentos de férias para esta referência. Ajuste o pagamento.")
                st.stop()
            total_bruto = valor_ajustado + (valor_decimo if pagar_decimo else 0.0)
            st.session_state.resultado = calcular_mensal(total_bruto)

        elif tipo == "Férias":
            if not data_inicio or not dias_ferias:
                st.error("Informe a data de início e os dias de férias.")
                st.stop()

            lancamentos, end_date, dias_ferias_mes_inicio, dias_ferias_mes_seguinte = _calcular_lancamentos_ferias(
                referencia, valor_ajustado, data_inicio, dias_ferias
            )

            resultados = []
            for lanc in lancamentos:
                if "Pagamento" in lanc["etapa"]:
                    salario_base = valor_ajustado
                    ferias_bruto = lanc.get("ferias_bruto", 0.0)
                    total_bruto = salario_base + ferias_bruto

                    descontos_inss = calcular_inss_rateado([salario_base, ferias_bruto])
                    inss_salario = descontos_inss[0]
                    inss_ferias = descontos_inss[1]
                    inss_total = round(inss_salario + inss_ferias, 2)
                    base_inss = min(total_bruto, TETO_INSS)

                    base_ir = total_bruto - inss_total
                    ir = calcular_irrf_2026(base_ir)

                    liquido = round(total_bruto - inss_total - ir["ir_final"], 2)
                    res = {
                        "bruto": round(total_bruto, 2),
                        "base_inss": round(base_inss, 2),
                        "inss": round(inss_total, 2),
                        "base_ir": round(base_ir, 2),
                        "ir_base": ir["ir_base"],
                        "redutor": ir["redutor"],
                        "irrf": ir["ir_final"],
                        "liquido": liquido,
                        "isento": ir["isento"],
                        "inss_salario": round(inss_salario, 2),
                        "inss_ferias": round(inss_ferias, 2),
                    }
                    resultados.append(res)
                else:
                    resultados.append(calcular_mensal(lanc["bruto_base"]))

            st.session_state.resultado_ferias = {
                "lancamentos": lancamentos,
                "resultados": resultados,
                "ferias_inicio": data_inicio,
                "ferias_termino": end_date,
                "ferias_dias": dias_ferias,
                "ferias_dias_mes_inicio": dias_ferias_mes_inicio,
                "ferias_dias_mes_seguinte": dias_ferias_mes_seguinte,
                "valor_original": valor,
                "valor_ajustado": valor_ajustado
            }

        else:
            st.session_state.resultado = calcular_rescisao(valor_ajustado)

        st.success("Cálculo realizado com sucesso")

        if st.session_state.resultado_ferias:
            dados_ferias = st.session_state.resultado_ferias
            linhas = []
            for lanc, res in zip(dados_ferias["lancamentos"], dados_ferias["resultados"]):
                linhas.append({
                    "Etapa": lanc["etapa"],
                    "Referência": lanc["referencia"],
                    "Competência": lanc["referencia"],
                    "Bruto": _fmt_moeda_br(res["bruto"]),
                    "INSS": _fmt_moeda_br(res["inss"]),
                    "IRRF": _fmt_moeda_br(res["irrf"]),
                    "Líquido": _fmt_moeda_br(res["liquido"]),
                })

            st.dataframe(pd.DataFrame(linhas), use_container_width=True)

            st.subheader("Detalhamento por etapa")
            for lanc, res in zip(dados_ferias["lancamentos"], dados_ferias["resultados"]):
                st.markdown(f"**{lanc['etapa']}**  \nReferência/Competência: `{lanc['referencia']}`")
                c1, c2 = st.columns(2)
                with c1:
                    st.caption("Proventos")
                    if "Pagamento" in lanc["etapa"]:
                        ferias_salario, ferias_terco = _calcular_ferias_componentes(
                            valor_ajustado, dias_ferias
                        )
                        st.write(f"Salário mês anterior: {_fmt_moeda_br(valor_ajustado)}")
                        st.write(f"Férias {dias_ferias} dias: {_fmt_moeda_br(ferias_salario)}")
                        st.write(f"1/3 de férias: {_fmt_moeda_br(ferias_terco)}")
                    else:
                        for desc, valor_item in lanc.get("proventos", []):
                            st.write(f"{desc}: {_fmt_moeda_br(valor_item)}")
                with c2:
                    st.caption("Descontos")
                    if "Pagamento" in lanc["etapa"]:
                        st.write(f"INSS salário: {_fmt_moeda_br(res.get('inss_salario', 0.0))}")
                        st.write(f"INSS férias: {_fmt_moeda_br(res.get('inss_ferias', 0.0))}")
                        st.write(f"IRRF: {_fmt_moeda_br(res['irrf'])}")
                    else:
                        for desc, valor_item in lanc.get("descontos", []):
                            if valor_item > 0:
                                st.write(f"{desc}: {_fmt_moeda_br(valor_item)}")
                        st.write(f"INSS: {_fmt_moeda_br(res['inss'])}")
                        st.write(f"IRRF: {_fmt_moeda_br(res['irrf'])}")
                st.write(f"**Líquido:** {_fmt_moeda_br(res['liquido'])}")
                st.markdown("---")

            for idx, (lanc, res) in enumerate(zip(dados_ferias["lancamentos"], dados_ferias["resultados"])):
                ferias_salario, ferias_terco = _calcular_ferias_componentes(
                    valor, dias_ferias
                )
                dados_pdf = {
                    "nome": nome,
                    "referencia": lanc["referencia"],
                    "competencia": lanc["referencia"],
                    "tipo": "Férias",
                    "etapa": lanc["etapa"],
                    "valor": lanc["bruto_base"],
                    "valor_original": valor,
                    "valor_ajustado": valor_ajustado,
                    "dias_falta": dias_falta,
                    "dias_ferias": dias_ferias,
                    "data_inicio": _fmt_data(data_inicio),
                    "data_termino": _fmt_data(dados_ferias["ferias_termino"]),
                    "teto_inss": TETO_INSS,
                    "proventos": lanc.get("proventos", []),
                    "descontos": lanc.get("descontos", []),
                    "descontos_completos": True if "Pagamento" in lanc["etapa"] else False,
                }
                if "Pagamento" in lanc["etapa"]:
                    dados_pdf["proventos"] = [
                        ("Salário mês anterior", valor_ajustado),
                        (f"Férias {dias_ferias} dias", ferias_salario),
                        ("1/3 de férias", ferias_terco),
                    ]
                    dados_pdf["descontos"] = [
                        ("INSS salário", res.get("inss_salario", 0.0)),
                        ("INSS férias", res.get("inss_ferias", 0.0)),
                        ("IRRF", res.get("irrf", 0.0)),
                    ]
                pdf_buffer = gerar_pdf_pagamento("brasao.jpg", dados_pdf, res)
                st.download_button(
                    label=f"Gerar PDF - {lanc['etapa']}",
                    data=pdf_buffer,
                    file_name=f"pagamento_{nome}_{lanc['referencia']}.pdf",
                    mime="application/pdf",
                    key=f"pdf_ferias_{idx}"
                )
        else:
            resultado = st.session_state.resultado
            col1, col2, col3 = st.columns(3)

            col1.metric("💰 Valor Bruto (original)", _fmt_moeda_br(valor))
            col1.metric("💰 Valor com faltas", _fmt_moeda_br(valor_ajustado))
            if pagar_decimo:
                col1.metric("💰 1/2 13º", _fmt_moeda_br(valor_decimo))
            col1.metric("🧾 Base INSS", _fmt_moeda_br(resultado["base_inss"]))
            col1.metric("🧮 INSS", _fmt_moeda_br(resultado["inss"]))

            col2.metric("📉 Base IR", _fmt_moeda_br(resultado["base_ir"]))
            col2.metric("🧠 IR pela tabela", _fmt_moeda_br(resultado["ir_base"]))
            col2.metric("🎁 Redutor IR 2026", _fmt_moeda_br(resultado["redutor"]))

            col3.metric("💸 IR Final", _fmt_moeda_br(resultado["irrf"]))
            col3.metric("🧮 Líquido", _fmt_moeda_br(resultado["liquido"]))

            if resultado["isento"]:
                st.success("✅ Isento de IR pela regra de 2026")

            dados_pdf = {
                "nome": nome,
                "referencia": referencia,
                "competencia": referencia,
                "tipo": tipo,
                "valor": valor_ajustado + (valor_decimo if pagar_decimo else 0.0),
                "valor_original": valor,
                "valor_ajustado": valor_ajustado,
                "dias_falta": dias_falta,
                "dias_ferias": "",
                "data_inicio": "",
                "data_termino": "",
                "teto_inss": TETO_INSS
            }
            if pagar_decimo:
                dados_pdf["proventos"] = [
                    ("Salario base", valor_ajustado),
                    ("1/2 13º", valor_decimo),
                ]
                dados_pdf["descontos"] = []
                dados_pdf["descontos_completos"] = False

            pdf_buffer = gerar_pdf_pagamento("brasao.jpg", dados_pdf, resultado)
            st.download_button(
                label="Gerar PDF para impressao",
                data=pdf_buffer,
                file_name=f"pagamento_{nome}_{referencia}.pdf",
                mime="application/pdf"
            )

    st.markdown("---")

    pode_salvar = st.session_state.resultado is not None or st.session_state.resultado_ferias is not None
    if pode_salvar and st.button("Salvar"):
        if st.session_state.resultado_ferias:
            dados_ferias = st.session_state.resultado_ferias
            grupo_id = f"{nome}-{_fmt_data(dados_ferias['ferias_inicio'])}-{dados_ferias['ferias_dias']}"
            for lanc, res in zip(dados_ferias["lancamentos"], dados_ferias["resultados"]):
                if pagamento_ja_existe(sheet, nome, lanc["referencia"], "Férias"):
                    st.error(f"❌ Já existe lançamento de férias para {lanc['referencia']}.")
                    st.stop()
                registro = {
                    "nome": nome,
                    "referencia": lanc["referencia"],
                    "competencia": lanc["referencia"],
                    "tipo": "Férias",
                    "etapa": lanc["etapa"],
                    "ferias_grupo": grupo_id,
                    "ferias_inicio": _fmt_data(dados_ferias["ferias_inicio"]),
                    "ferias_termino": _fmt_data(dados_ferias["ferias_termino"]),
                    "ferias_dias": dados_ferias["ferias_dias"],
                    "ferias_dias_mes_inicio": dados_ferias["ferias_dias_mes_inicio"],
                    "ferias_dias_mes_seguinte": dados_ferias["ferias_dias_mes_seguinte"],
                    "ferias_bruto": lanc.get("ferias_bruto", 0.0),
                    "ferias_salario": "",
                    "ferias_terco": "",
                    "dias_trabalhados": lanc["dias_trabalhados"],
                    "dias_desconto": lanc["dias_desconto"],
                    "salario_base": dados_ferias["valor_original"],
                    "salario_ajustado": dados_ferias["valor_ajustado"],
                    "bruto": res["bruto"],
                    "base_inss": res["base_inss"],
                    "inss": res["inss"],
                    "inss_salario": "",
                    "inss_ferias": "",
                    "base_ir": res["base_ir"],
                    "ir_base": res["ir_base"],
                    "redutor": res["redutor"],
                    "irrf": res["irrf"],
                    "liquido": res["liquido"],
                }
                if "Pagamento" in lanc["etapa"]:
                    ferias_salario, ferias_terco = _calcular_ferias_componentes(
                        dados_ferias["valor_ajustado"], dados_ferias["ferias_dias"]
                    )
                    registro["ferias_salario"] = ferias_salario
                    registro["ferias_terco"] = ferias_terco
                    registro["inss_salario"] = res.get("inss_salario", 0.0)
                    registro["inss_ferias"] = res.get("inss_ferias", 0.0)
                salvar_registro(sheet, registro)

            st.success("Lançamentos de férias salvos com sucesso!")
        else:
            resultado = st.session_state.resultado
            valor_original = st.session_state.valor_original if st.session_state.valor_original is not None else valor
            valor_ajustado = st.session_state.valor_ajustado if st.session_state.valor_ajustado is not None else valor
            if pagamento_ja_existe(sheet, nome, referencia, tipo):
                st.error("❌ Já existe um pagamento cadastrado para esse período.")
                st.stop()
            registro = {
                "nome": nome,
                "referencia": referencia,
                "competencia": referencia,
                "tipo": tipo,
                "salario_base": valor_original,
                "salario_ajustado": valor_ajustado,
                "decimo_terceiro": valor_decimo if pagar_decimo else "",
                "dias_falta": dias_falta,
                "bruto": resultado["bruto"],
                "base_inss": resultado["base_inss"],
                "inss": resultado["inss"],
                "base_ir": resultado["base_ir"],
                "ir_base": resultado["ir_base"],
                "redutor": resultado["redutor"],
                "irrf": resultado["irrf"],
                "liquido": resultado["liquido"],
            }

            salvar_registro(sheet, registro)
            st.success("Registro salvo com sucesso!")

# =========================
# 📊 REGISTROS
# =========================
elif menu == "📊 Registros":
    st.subheader("Pagamentos registrados")
    df = carregar_dados(sheet)
    st.dataframe(df, use_container_width=True)

    if df.empty:
        st.info("Nenhum registro encontrado.")
    else:
        opcoes = []
        for i, row in df.iterrows():
            label = f"{row.get('nome', '')} | {row.get('referencia', '')} | {row.get('tipo', '')} | {row.get('etapa', '')}"
            opcoes.append((label, i))

        selecao = st.selectbox(
            "Selecionar registro para gerar PDF",
            options=opcoes,
            format_func=lambda x: x[0]
        )

        if selecao:
            idx = selecao[1]
            row = df.loc[idx]
            proventos, descontos = _proventos_descontos_row(row, normalizar_valor=_normalizar_valor_registro)
            dados_pdf = {
                "nome": row.get("nome", ""),
                "referencia": row.get("referencia", ""),
                "competencia": row.get("competencia", row.get("referencia", "")),
                "tipo": row.get("tipo", ""),
                "etapa": row.get("etapa", ""),
                "valor": _normalizar_valor_registro(row.get("bruto", 0.0)),
                "valor_original": _normalizar_valor_registro(row.get("salario_base", row.get("bruto", 0.0))),
                "valor_ajustado": _normalizar_valor_registro(row.get("salario_ajustado", row.get("bruto", 0.0))),
                "dias_falta": row.get("dias_falta", ""),
                "dias_ferias": row.get("ferias_dias", ""),
                "data_inicio": row.get("ferias_inicio", ""),
                "data_termino": row.get("ferias_termino", ""),
                "teto_inss": TETO_INSS,
                "proventos": proventos,
                "descontos": descontos,
                "descontos_completos": True if descontos else False,
            }

            resultado_pdf = {
                "bruto": _normalizar_valor_registro(row.get("bruto", 0.0)),
                "base_inss": _normalizar_valor_registro(row.get("base_inss", 0.0)),
                "inss": _normalizar_valor_registro(row.get("inss", 0.0)),
                "base_ir": _normalizar_valor_registro(row.get("base_ir", 0.0)),
                "ir_base": _normalizar_valor_registro(row.get("ir_base", 0.0)),
                "redutor": _normalizar_valor_registro(row.get("redutor", 0.0)),
                "irrf": _normalizar_valor_registro(row.get("irrf", 0.0)),
                "liquido": _normalizar_valor_registro(row.get("liquido", 0.0))
            }

            pdf_buffer = gerar_pdf_pagamento("brasao.jpg", dados_pdf, resultado_pdf)
            st.download_button(
                label="Gerar PDF do registro",
                data=pdf_buffer,
                file_name=f"pagamento_{dados_pdf['nome']}_{dados_pdf['referencia']}.pdf",
                mime="application/pdf"
            )

# =========================
# ℹ️ SOBRE
# =========================
else:
    st.info("""
    Sistema em Streamlit  
    Dados armazenados no Google Sheets  
    Cálculo conforme regras do JS original  
    """)
