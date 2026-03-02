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


# ===== UTILIDADES =====

def aplicar_faltas(valor_bruto, dias_falta):
    valor_dia = valor_bruto / 30
    desconto = valor_dia * dias_falta
    return round(valor_bruto - desconto, 2)


# ===== INSS =====

def calcular_inss(valor_bruto):
    base = min(valor_bruto, TETO_INSS)
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


# ===== IR =====

def calcular_irrf_2026(base_ir):
    for faixa in FAIXAS_IRRF_2026:
        if base_ir <= faixa["ate"]:
            imposto = base_ir * faixa["aliquota"] - faixa["deducao"]
            imposto = max(0, imposto)
            imposto = math.floor(imposto * 100) / 100
            return {
                "ir_base": base_ir,
                "redutor": faixa["deducao"],
                "ir_final": imposto,
                "isento": faixa["aliquota"] == 0
            }


# ===== CÁLCULOS PRINCIPAIS =====

def calcular_mensal(valor_bruto):
    inss, base_inss = calcular_inss(valor_bruto)
    base_ir = valor_bruto - inss
    ir = calcular_irrf_2026(base_ir)
    liquido = round(valor_bruto - inss - ir["ir_final"], 2)

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
    liquido = round(bruto - inss - ir["ir_final"], 2)

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