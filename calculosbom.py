# calculos.py
import math

from constantes import (
    SALARIO_MINIMO,
    ALIQUOTA_INSS,
    TETO_INSS,
    FAIXAS_IRRF_2026,
    IRRF_ISENCAO_TOTAL,
    IRRF_LIMITE_REDUCAO,
    IRRF_REDUCAO_FIXA,
    IRRF_REDUCAO_FATOR,
)


# =====================
# INSS
# =====================
def calcular_inss(valor_bruto):
    if valor_bruto <= 0:
        return 0.0, 0.0

    base = max(valor_bruto, SALARIO_MINIMO)
    base = min(base, TETO_INSS)

    desconto = math.floor(base * ALIQUOTA_INSS * 100) / 100
    return desconto, base


def calcular_inss_rateado(valores):
    total = sum(valores)
    total_limitado = min(total, TETO_INSS)

    descontos = []
    for valor in valores:
        proporcao = valor / total if total > 0 else 0
        desconto = total_limitado * ALIQUOTA_INSS * proporcao
        desconto = math.floor(desconto * 100) / 100
        descontos.append(desconto)

    return descontos



# =====================
# IRRF BASE (tabela normal)
# =====================
def calcular_irrf_base(base_ir):
    if base_ir <= 0:
        return 0.0

    for faixa in FAIXAS_IRRF_2026:
        if base_ir <= faixa["ate"]:
            imposto = (base_ir * faixa["aliquota"]) - faixa["deducao"]
            return round(max(imposto, 0), 2)

    return 0.0


# =====================
# REDUTOR EXTRA 2026
# =====================
def calcular_redutor_irrf(base_ir):
    if base_ir <= IRRF_ISENCAO_TOTAL:
        return float("inf")  # zera tudo

    if base_ir <= IRRF_LIMITE_REDUCAO:
        return round(
            IRRF_REDUCAO_FIXA - (IRRF_REDUCAO_FATOR * base_ir),
            2
        )

    return 0.0


# =====================
# IRRF FINAL
# =====================
def calcular_irrf_2026(base_ir):
    imposto_base = calcular_irrf_base(base_ir)
    redutor = calcular_redutor_irrf(base_ir)

    if redutor == float("inf"):
        imposto_final = 0.0
        redutor_aplicado = imposto_base
    else:
        imposto_final = max(imposto_base - redutor, 0)
        redutor_aplicado = imposto_base - imposto_final

    return {
        "ir_base": round(imposto_base, 2),
        "redutor": round(redutor_aplicado, 2),
        "ir_final": round(imposto_final, 2),
        "isento": imposto_final == 0 and base_ir <= IRRF_LIMITE_REDUCAO
    }



# =====================
# CÁLCULOS PRINCIPAIS
# =====================
def calcular_mensal(valor_bruto):
    inss, base_inss = calcular_inss(valor_bruto)
    base_ir = valor_bruto - inss

    ir = calcular_irrf_2026(base_ir)

    liquido = round(
        valor_bruto - inss - ir["ir_final"], 2
    )

    return {
        "bruto": round(valor_bruto, 2),
        "base_inss": base_inss,
        "inss": inss,
        "base_ir": round(base_ir, 2),
        "ir_base": ir["ir_base"],
        "redutor": ir["redutor"],
        "irrf": ir["ir_final"],
        "liquido": liquido,
        "isento": ir["isento"]
    }



def calcular_ferias(valor_bruto, dias_ferias):
    salario_proporcional = (valor_bruto / 30) * dias_ferias
    terco_constitucional = salario_proporcional / 3
    bruto = salario_proporcional + terco_constitucional

    inss, base_inss = calcular_inss(bruto)
    base_ir = bruto - inss

    ir = calcular_irrf_2026(base_ir)

    liquido = round(
        bruto - inss - ir["ir_final"], 2
    )

    return {
        "bruto": round(bruto, 2),
        "base_inss": base_inss,
        "inss": inss,
        "base_ir": round(base_ir, 2),
        "ir_base": ir["ir_base"],
        "redutor": ir["redutor"],
        "irrf": ir["ir_final"],
        "liquido": liquido,
        "isento": ir["isento"]
    }


def calcular_rescisao(valor_bruto):
    resultado = calcular_mensal(valor_bruto)
    resultado["observacao"] = "Rescisão"
    return resultado

def aplicar_faltas(valor_bruto, dias_falta):
    valor_dia = valor_bruto / 30
    desconto = valor_dia * dias_falta
    return round(valor_bruto - desconto, 2)
