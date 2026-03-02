import streamlit as st
import pandas as pd
from calculos import (
    calcular_mensal,
    calcular_ferias,
    aplicar_faltas
)
from repositorio import (
    conectar_planilha,
    salvar_registro,
    pagamento_ja_existe
)

st.set_page_config(page_title="Folha Conselho Tutelar", layout="wide")

st.sidebar.title("📋 Menu")

pagina = st.sidebar.radio(
    "Navegação",
    ["Lançamento", "Consulta", "Resumo"]
)


if "resultado" not in st.session_state:
    st.session_state.resultado = None

sheet = conectar_planilha()

st.title("💼 Sistema de Pagamentos – Conselho Tutelar")

# ===== INPUTS =====
col1, col2, col3 = st.columns(3)

with col1:
    nome = st.selectbox("Conselheira", sheet.col_values(1)[1:])

with col2:
    referencia = st.text_input("Mês / Ano (MM/AAAA)")

with col3:
    tipo = st.selectbox("Tipo de pagamento", ["Mensal", "Férias", "Rescisão"])

valor = st.number_input("Valor bruto", min_value=0.0, step=100.0)

dias_falta = st.number_input(
    "Dias de falta",
    min_value=0,
    max_value=30,
    step=1
)

# Campos extras de férias
dias_ferias = None
data_inicio = None

if tipo == "Férias":
    colf1, colf2 = st.columns(2)
    with colf1:
        dias_ferias = st.selectbox("Dias de férias", [15, 30])
    with colf2:
        data_inicio = st.date_input("Início das férias")

# ===== BOTÃO CALCULAR =====
if st.button("Calcular"):
    valor_ajustado = aplicar_faltas(valor, dias_falta)

    if tipo == "Mensal":
        st.session_state.resultado = calcular_mensal(valor_ajustado)

    elif tipo == "Férias":
        st.session_state.resultado = calcular_ferias(valor_ajustado, dias_ferias)

    else:
        st.session_state.resultado = calcular_mensal(valor_ajustado)

resultado = st.session_state.resultado

# ===== RESULTADOS =====
if resultado:
    st.subheader("📊 Resultado")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Bruto", f"R$ {resultado['bruto']:.2f}")
    c2.metric("🏛️ INSS", f"R$ {resultado['inss']:.2f}")
    c3.metric("📉 IRRF", f"R$ {resultado['irrf']:.2f}")
    c4.metric("💵 Líquido", f"R$ {resultado['liquido']:.2f}")

# ===== SALVAR =====
if resultado and st.button("Salvar"):
    if pagamento_ja_existe(sheet, nome, referencia, tipo):
        st.error("❌ Já existe um pagamento cadastrado para esse período.")
        st.stop()

    registro = {
        "nome": nome,
        "referencia": referencia,
        "tipo": tipo,
        "valor_bruto": resultado["bruto"],
        "inss": resultado["inss"],
        "irrf": resultado["irrf"],
        "liquido": resultado["liquido"],
        "dias_falta": dias_falta,
        "dias_ferias": dias_ferias or "",
        "inicio_ferias": str(data_inicio) if data_inicio else ""
    }

    salvar_registro(sheet, registro)
    st.success("✅ Registro salvo com sucesso!")
