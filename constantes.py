# constantes.py

SALARIO_MINIMO = 1621.00
ALIQUOTA_INSS = 0.11
TETO_INSS = 8475.55  # ajuste se necessário

# Tabela IRRF mensal – 2026
FAIXAS_IRRF_2026 = [
    {"ate": 2428.80, "aliquota": 0.0,   "deducao": 0.0},
    {"ate": 2826.65, "aliquota": 0.075, "deducao": 182.16},
    {"ate": 3751.05, "aliquota": 0.15,  "deducao": 394.16},
    {"ate": 4664.68, "aliquota": 0.225, "deducao": 675.49},
    {"ate": float("inf"), "aliquota": 0.275, "deducao": 908.73},
]

# Redutor adicional IRRF 2026
IRRF_ISENCAO_TOTAL = 5000.00
IRRF_LIMITE_REDUCAO = 7350.00
IRRF_REDUCAO_FIXA = 978.62
IRRF_REDUCAO_FATOR = 0.133145