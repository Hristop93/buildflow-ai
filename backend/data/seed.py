"""
Buildflow AI — seed data (core regulatory knowledge).

Extracted from Buildflow_AI_schema.xlsx. This is the etalon: the engines must
reproduce the Excel numbers (critical path 420 days, fees 39 870 BGN, IRR ~11.8%).

Values are REPRESENTATIVE and must be verified against current acts per municipality
(see SPEC.md, Phase 0). Structure is final; numbers are placeholders for real data.
"""

# --- Institutions -----------------------------------------------------------
INSTITUTIONS = [
    {"id": "INST-01", "name": "Главен архитект / Община (ЕСУТ)", "type": "общинска"},
    {"id": "INST-02", "name": "РИОСВ", "type": "държавна"},
    {"id": "INST-03", "name": "Електроразпределително дружество (ЕРП)", "type": "оператор"},
    {"id": "INST-04", "name": "ЕСО ЕАД", "type": "оператор"},
    {"id": "INST-05", "name": "КЕВР", "type": "регулатор"},
    {"id": "INST-06", "name": "ДНСК", "type": "държавна"},
    {"id": "INST-07", "name": "СГКК / Кадастър", "type": "държавна"},
    {"id": "INST-08", "name": "Областна дирекция Земеделие", "type": "държавна"},
    {"id": "INST-11", "name": "Възложител / Проектант (КИИП)", "type": "частна"},
]

# --- Normative acts (versioned; nothing is ever deleted in DB) ---------------
ACTS = [
    {"id": "ACT-01", "title": "ЗУТ", "level": "state", "article": "чл.137", "valid_from": "1998-01-01", "valid_to": None},
    {"id": "ACT-02", "title": "ЗУТ", "level": "state", "article": "чл.140", "valid_from": "1998-01-01", "valid_to": None},
    {"id": "ACT-03", "title": "ЗУТ", "level": "state", "article": "чл.142", "valid_from": "1998-01-01", "valid_to": None},
    {"id": "ACT-04", "title": "ЗУТ", "level": "state", "article": "чл.148", "valid_from": "1998-01-01", "valid_to": None},
    {"id": "ACT-05", "title": "ЗУТ", "level": "state", "article": "чл.177", "valid_from": "1998-01-01", "valid_to": None},
    {"id": "ACT-06", "title": "ЗКИР", "level": "state", "article": "чл.55", "valid_from": "2000-01-01", "valid_to": None},
    {"id": "ACT-08", "title": "ЗЕ", "level": "state", "article": "чл.39", "valid_from": "2003-01-01", "valid_to": None},
    {"id": "ACT-09", "title": "ЗООС", "level": "state", "article": "чл.93", "valid_from": "2002-01-01", "valid_to": None},
    {"id": "ACT-10", "title": "ЗОЗЗ", "level": "state", "article": "чл.17-24", "valid_from": "1996-01-01", "valid_to": None},
    {"id": "ACT-13", "title": "Тарифа КЕВР", "level": "state", "article": "—", "valid_from": "2020-01-01", "valid_to": None},
    {"id": "ACT-14", "title": "Тарифа №14 (ДНСК)", "level": "state", "article": "—", "valid_from": "2020-01-01", "valid_to": None},
]

# --- Procedures (graph nodes) -----------------------------------------------
# duration_days is the planned/statutory duration used by ScheduleEngine.
PROCEDURES = [
    {"id": "PRO-01", "name": "Документ за собственост/суперфиция", "institution": "INST-11", "duration_days": 10, "act": None},
    {"id": "PRO-02", "name": "Издаване на скица", "institution": "INST-07", "duration_days": 14, "act": "ACT-06"},
    {"id": "PRO-03", "name": "Искане на условия за присъединяване", "institution": "INST-03", "duration_days": 45, "act": "ACT-08"},
    {"id": "PRO-04", "name": "Виза за проектиране", "institution": "INST-01", "duration_days": 14, "act": "ACT-02"},
    {"id": "PRO-05", "name": "Промяна на предназначение на земята", "institution": "INST-08", "duration_days": 60, "act": "ACT-10"},
    {"id": "PRO-06", "name": "Преценка за необходимост от ОВОС", "institution": "INST-02", "duration_days": 30, "act": "ACT-09"},
    {"id": "PRO-07", "name": "Изработване на инвестиционен проект", "institution": "INST-11", "duration_days": 60, "act": None},
    {"id": "PRO-08", "name": "Оценка за съответствие", "institution": "INST-01", "duration_days": 14, "act": "ACT-03"},
    {"id": "PRO-09", "name": "Издаване на разрешение за строеж", "institution": "INST-01", "duration_days": 21, "act": "ACT-04"},
    {"id": "PRO-10", "name": "Сключване на договор за присъединяване", "institution": "INST-03", "duration_days": 30, "act": "ACT-08"},
    {"id": "PRO-11", "name": "Строително-монтажни работи", "institution": "INST-11", "duration_days": 120, "act": None},
    {"id": "PRO-12", "name": "Въвеждане в експлоатация", "institution": "INST-06", "duration_days": 60, "act": "ACT-05"},
    {"id": "PRO-13", "name": "Лицензиране/регистрация в КЕВР", "institution": "INST-05", "duration_days": 90, "act": "ACT-13"},
]

# --- Dependencies (edges: successor depends on predecessors) ------------------
DEPENDENCIES = {
    "PRO-02": ["PRO-01"],
    "PRO-03": ["PRO-01"],
    "PRO-04": ["PRO-02"],
    "PRO-05": ["PRO-02"],
    "PRO-06": ["PRO-02"],
    "PRO-07": ["PRO-04", "PRO-03"],
    "PRO-08": ["PRO-07"],
    "PRO-09": ["PRO-08", "PRO-05", "PRO-06"],
    "PRO-10": ["PRO-09"],
    "PRO-11": ["PRO-09"],
    "PRO-12": ["PRO-11", "PRO-10"],
    "PRO-13": ["PRO-12"],
}

# --- Fee tariffs ------------------------------------------------------------
# basis: 'fixed' | 'per_sqm_rzp' | 'pct_of_value' | 'per_mw'
FEE_TARIFFS = [
    {"id": "FEE-01", "procedure": "PRO-02", "desc": "Такса скица", "basis": "fixed", "rate": 20, "act": "ACT-06"},
    {"id": "FEE-02", "procedure": "PRO-04", "desc": "Такса виза за проектиране", "basis": "fixed", "rate": 100, "act": "ACT-02"},
    {"id": "FEE-03", "procedure": "PRO-06", "desc": "Такса преценка ОВОС", "basis": "fixed", "rate": 500, "act": "ACT-09"},
    {"id": "FEE-04", "procedure": "PRO-05", "desc": "Такса промяна предназначение", "basis": "fixed", "rate": 5000, "act": "ACT-10"},
    {"id": "FEE-05", "procedure": "PRO-08", "desc": "Оценка за съответствие", "basis": "pct_of_value", "rate": 0.003, "act": "ACT-03"},
    {"id": "FEE-06", "procedure": "PRO-09", "desc": "Такса разрешение за строеж", "basis": "per_sqm_rzp", "rate": 1.5, "act": "ACT-04"},
    {"id": "FEE-07", "procedure": "PRO-12", "desc": "Такса въвеждане в експлоатация", "basis": "fixed", "rate": 1500, "act": "ACT-14"},
    {"id": "FEE-08", "procedure": "PRO-13", "desc": "Такса лиценз КЕВР", "basis": "fixed", "rate": 2000, "act": "ACT-13"},
]

# --- Rules (conditional include/exclude/switch) ------------------------------
RULES = [
    {"id": "R-01", "param": "land_status", "op": "!=", "value": "agricultural", "action": "exclude", "target": "PRO-05"},
    {"id": "R-02", "param": "power_mw", "op": "<", "value": 1, "action": "exclude", "target": "PRO-13"},
    {"id": "R-03", "param": "voltage", "op": "=", "value": "high", "action": "switch_institution", "target": "PRO-03", "target_institution": "INST-04"},
    # Note: the OVOS *screening* (PRO-06) is always present; only a FULL OVOS/Natura
    # assessment would be a separate conditional procedure (added when protected_zone=True).
]

# --- Project types ----------------------------------------------------------
PROJECT_TYPES = {
    "pv_ground": {
        "name": "Наземна фотоволтаична централа",
        "procedures": [p["id"] for p in PROCEDURES],  # all 13 in the base set
    },
}

# --- Reference inputs for the etalon test (the verified PV example) ----------
ETALON_PARAMS = {
    "project_type": "pv_ground",
    "land_status": "agricultural",
    "voltage": "medium",
    "protected_zone": False,
    "power_mw": 5,
    "rzp_sqm": 500,
    "invest_value": 10_000_000,
    # economics
    "specific_capex_per_kw": 1300,
    "yield_kwh_kwp": 1350,
    "ppa_price": 160,
    "opex_per_kw": 25,
    "degradation": 0.005,
    "years": 20,
    "wacc": 0.08,
    "hurdle_rate": 0.09,
    "tax_rate": 0.10,
}
