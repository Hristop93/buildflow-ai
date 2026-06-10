# BUILDFLOW AI — Функционална спецификация v1.0

> Документът е план за разработка. Език на кода: английски (имена на таблици, променливи, ендпойнти). Език на интерфейса: български. Всяка секция е инструкция за изпълнение в Claude Code.

---

## 1. Концепция в едно изречение

Уеб платформа, в която инвеститор въвежда параметрите на проекта си и получава — според закупеното ниво — пълен регулаторен маршрут с такси, цитирани към конкретни членове от нормативни актове, времева линия с критичен път и икономическа обосновка с риск-анализ, като всяка корекция на срок преизчислява всичко в реално време.

---

## 2. Архитектура и стек

```
[React SPA (Vite)] ⇄ [FastAPI бекенд] ⇄ [PostgreSQL]
                          │
                          ├─ RuleEngine      (сглобява графа на проекта)
                          ├─ FeeEngine       (такси + цитати)
                          ├─ ScheduleEngine  (критичен път, CPM)
                          ├─ EconEngine      (IRR/NPV/LCOE + Monte Carlo)
                          └─ ReportGenerator (xlsx + pdf експорт)
```

- **Бекенд:** Python 3.12 + FastAPI + SQLAlchemy + Alembic (миграции). Python, защото генераторът на доклади (openpyxl) и финансовите изчисления вече са прототипирани на Python.
- **База:** PostgreSQL 16. Една база, схеми `core` (нормативно знание) и `app` (потребители/проекти).
- **Фронтенд:** React + Vite + TypeScript. Графики: recharts. Gantt: собствен компонент (SVG).
- **Автентикация:** имейл + парола, JWT в httpOnly cookie. По-късно: Google OAuth.
- **Плащания:** Stripe (карти) — фаза 2 добавя фактуриране с ДДС.
- **Хостинг:** един VPS (Hetzner/Contabo) с Docker Compose: api + db + nginx. Мобилен достъп: responsive уеб (PWA). Native app — извън обхват до фаза 4.

---

## 3. База данни

### 3.1 Схема `core` — нормативното знание (ровът на продукта)

```sql
municipalities(id, name, region, coverage_status, verified_at)
-- coverage_status: 'verified' | 'partial' | 'none' — показва се на потребителя

normative_acts(id, act_type, title, level, municipality_id NULL,
               article, valid_from, valid_to NULL, supersedes_id NULL,
               source_url, verified_at, verified_by)
-- level: 'state' | 'municipal'. Версиониране: нов ред + valid_to на стария.
-- НИЩО не се трие. Докладите цитират конкретен ред (act_id) => възпроизводимост.

institutions(id, name, inst_type, competence, default_term_days)

documents(id, name, issuer_institution_id, doc_type, note)

procedures(id, name, institution_id, output_document_id,
           statutory_term_days, act_id, note)

procedure_inputs(procedure_id, document_id)   -- M:N входни документи

dependencies(successor_id, predecessor_id, link_type)
-- link_type: 'finish_start' (засега единствен)

fee_tariffs(id, procedure_id, description, basis, rate,
            municipality_id NULL, act_id, valid_from, valid_to NULL)
-- basis: 'fixed' | 'per_sqm_rzp' | 'pct_of_value' | 'per_mw'
-- Изчисление: fee = basis_value(project) × rate

rules(id, param_name, operator, value, action, target_procedure_id,
      target_institution_id NULL, explanation)
-- operator: '=' | '!=' | '>=' | '<=' | 'in'
-- action: 'include' | 'exclude' | 'switch_institution'

project_types(id, name, base_procedure_set JSONB)
-- 'pv_ground', 'pv_roof', 'residential', 'industrial', 'infrastructure'...
-- Фаза 1 покрива САМО 'pv_ground'.
```

### 3.2 Схема `app` — потребители и проекти

```sql
users(id, email, password_hash, full_name, company, created_at, gdpr_consent_at)

projects(id, user_id, name, project_type_id, municipality_id,
         tier, status, created_at)
-- tier: 'free' | 'standard' | 'pro' | 'dd' (закупено ниво ЗА ТОЗИ проект)

project_params(project_id, param_name, value)
-- land_status, power_mw, voltage, protected_zone, category, rzp_sqm,
-- invest_value, ppa_price, yield_kwh_kwp, opex, wacc, hurdle_rate...

project_nodes(id, project_id, procedure_id, status,
              planned_duration_days, actual_start, actual_end,
              computed_start_day, computed_end_day, is_critical)
-- status: 'pending' | 'active' | 'done' | 'delayed' | 'excluded'
-- Инстанцираният граф: копие на процедурите за конкретния проект.

project_fees(id, project_id, node_id, fee_tariff_id,
             basis_value, computed_amount, act_snapshot JSONB)
-- act_snapshot пази цитата КЪМ МОМЕНТА на изчисление (възпроизводимост)

project_versions(id, project_id, version_no, snapshot JSONB,
                 reason, created_at)
-- Всяко преизчисление = нова версия. snapshot: целият изчислен резултат.

events(id, project_id, node_id NULL, event_type, payload JSONB,
       created_at, created_by)
-- журнал: 'date_changed', 'status_changed', 'tariff_updated', 'recalc'...

orders(id, user_id, project_id, tier, amount, currency,
       stripe_payment_id, status, invoice_no, created_at)

subscriptions(id, user_id, project_id, plan, active_until,
              stripe_sub_id, status)
-- абонамент "актуалност": мониторинг на актовете + преизчисление
```

---

## 4. Изчислителните машини (бекенд модули)

### 4.1 RuleEngine — `engines/rules.py`
Вход: `project_type + project_params`. Изход: списък активни процедури + институции.
1. Взема `base_procedure_set` за типа проект.
2. Прилага всички `rules` по ред: include / exclude / switch_institution.
3. Създава/обновява `project_nodes` (изключените получават status='excluded').
Правило: НИКОГА не генерира процедури извън базата — никакъв LLM в това ядро.

### 4.2 FeeEngine — `engines/fees.py`
За всеки активен възел: намира tariff WHERE municipality (или NULL=национална)
AND valid_from <= today < COALESCE(valid_to,'infinity').
`amount = resolve_basis(project_params, basis) × rate`.
Записва `project_fees` + act_snapshot (заглавие, член, дата в сила, URL).
Ако няма тарифа за общината → amount=NULL + флаг 'no_coverage' (показва се честно).

### 4.3 ScheduleEngine — `engines/schedule.py`
Класически CPM forward pass по `dependencies`:
`start = max(end на предшествениците)`, `end = start + duration`.
duration: `actual` ако има, иначе `planned`, иначе `statutory_term_days`.
Маркира критичния път (`is_critical`). Изход: общ срок + дати по възли.

### 4.4 EconEngine — `engines/economics.py`
- 20-годишен паричен поток: производство (с деградация 0.5%/г) × цена − OPEX − данък 10%; CAPEX = мощност × спец.CAPEX + Σ такси (от FeeEngine).
- Строителният период идва от ScheduleEngine (изместване на потоците).
- Метрики: IRR (бисекция), NPV, LCOE, прост payback.
- Присъда: `relevant` ако IRR≥hurdle; `resilient` ако и P5(MonteCarlo)≥hurdle;
  `borderline` ако само базов минава; `risky` иначе.
- MonteCarlo (само tier='dd'): N=5000, нормални разпределения върху
  ppa_price, yield, capex, delay → P(IRR≥hurdle), P5–P95, P(NPV>0).

### 4.5 Recalc контракт (реалното време)
Всяка промяна (дата, статус, тарифа) → `POST /projects/{id}/recalc`:
RuleEngine (ако параметър) → FeeEngine → ScheduleEngine → EconEngine →
нов ред в `project_versions` + събитие в `events`.
Цел: < 300 ms за единичен проект (без MonteCarlo); MonteCarlo async (≤ 5 s).

---

## 5. Екрани

### 5.1 Публични
| Екран | Съдържание |
|---|---|
| Landing | Стойност + как работи (3 стъпки) + ценови нива + лого/бранд (navy #1F4E78, amber #C55A11) |
| Pricing | Матрица версии × секции (виж §6) |
| Login / Register | имейл+парола, GDPR съгласие чекбокс (задължителен), потвърждение по имейл |

### 5.2 Приложение (след вход)
**Dashboard** — списък проекти: име, тип, община, статус-светофар на присъдата, бутон „Нов проект“.

**Wizard „Нов проект“** — 4 стъпки, всяка с валидация:
1. Тип проект (фаза 1: само наземна ФЕЦ; останалите „очаквайте скоро“)
2. Локация: община (dropdown с coverage индикатор: ✔ сверена / ⚠ частична / ✖ няма данни), статут на земята, защитена зона
3. Технически: мощност MW, напрежение, категория по чл.137, РЗП (ако е приложимо)
4. Финансови: инвест. стойност, цена PPA, добив, OPEX, WACC, изискуема норма
→ „Генерирай“ → пълно изчисление → проектен изглед.

**Проектен изглед** — лява навигация със секции (заключените са видими, но с катинар + CTA за надграждане):

| Секция | Съдържание | Видима при |
|---|---|---|
| Резюме | брой процедури, диапазон срок, диапазон такси, БЕЗ детайли | free |
| Маршрут | пълният граф: процедури, институции, документи вход/изход, основание (член+акт) на всяка стъпка | standard |
| Такси | таблица: такса, формула, сума, член+акт+дата в сила, линк; ОБЩО | standard |
| График | Gantt с критичен път (червено), редактируеми дати по възел, статус dropdown | pro |
| Икономика | CAPEX, IRR, NPV, LCOE, payback + присъда (зелено/жълто/червено) | pro |
| Риск | Monte Carlo: голям % „минава прага“, хистограма, P5–P95, светофар устойчивост | dd |
| Журнал | хронология на промените: кой, кога, какво, ефект върху срока и IRR | pro |
| Експорт | Excel пакет (като прототипа: всички листове) + PDF доклад; печат „изчислено по актове в сила към ДАТА“; опция „заяви експертна валидация“ | dd |

**Редакция в реално време (секция График):** клик върху възел → панел: статус, реална начална/крайна дата, причина (задължително поле при забавяне) → Запази → recalc → Gantt, икономика и присъда се обновяват на място, банер: „Промяната измести срока с +X дни и IRR с −Y п.п. (версия N)“.

### 5.3 Админ панел (само ти; роля 'admin')
| Екран | Функция |
|---|---|
| Актове | CRUD + версиониране (нов ред при изменение, никога презапис), поле verified_at/by |
| Процедури и правила | редакция на графа и условията; тест-бутон „симулирай проект“ |
| Тарифи | по община, с валидност; импорт от CSV |
| Покритие | карта/списък на общините: кога е сверена всяка, кои тарифи липсват |
| Потребители и поръчки | списък, статуси на плащания, ръчно вдигане на tier |
| Опашка валидации | DD заявки за експертен преглед → статус → качване на заверен PDF |

---

## 6. Версии и достъп

| | Free | Standard | Pro | Due-diligence |
|---|---|---|---|---|
| Резюме | ✔ | ✔ | ✔ | ✔ |
| Маршрут + Такси с цитати | | ✔ | ✔ | ✔ |
| График (редактируем) + Икономика + Журнал | | | ✔ | ✔ |
| Monte Carlo + Експорт + опция експертна валидация | | | | ✔ |
| Абонамент „Актуалност“ (мониторинг на актове + авто-преизчисление + известия) | добавя се към всяко платено ниво |

- Tier се купува **на проект** (не на акаунт) — съответства на това как инвеститорът мисли.
- Gating: бекендът ВИНАГИ смята всичко; API връща само разрешените секции (проверка на сървъра, не само в UI).
- Цените не се фиксират в спецификацията — задават се в config + админ панела.

## 7. API (REST, основни ендпойнти)

```
POST /auth/register | POST /auth/login | POST /auth/logout
GET  /me

GET/POST  /projects                  GET/PATCH/DELETE /projects/{id}
POST /projects/{id}/recalc           GET /projects/{id}/versions
GET  /projects/{id}/sections/{name}  -- gated по tier
PATCH /projects/{id}/nodes/{nodeId}  -- статус/дати → тригерира recalc
GET  /projects/{id}/export/xlsx      GET /projects/{id}/export/pdf  -- tier dd

POST /orders/checkout (tier, project_id) → Stripe session
POST /webhooks/stripe                -- потвърждение → вдига tier

GET  /catalog/municipalities         -- с coverage_status
GET  /catalog/project-types

-- admin (роля admin):
CRUD /admin/acts /admin/procedures /admin/rules /admin/tariffs
GET  /admin/coverage  /admin/orders  /admin/validation-queue
```

---

## 8. Нефункционални изисквания

- **Възпроизводимост:** всеки експортиран доклад съдържа версията на проекта и snapshot на цитираните актове. Същият вход + същата дата = същият резултат.
- **Одит:** всички промени по core-схемата и по проектите се логват в events.
- **GDPR:** съгласие при регистрация; изтриване на акаунт изтрива проектите (актовете остават — те не са лични данни); данни в ЕС.
- **Дисклеймър:** във всеки доклад и във футъра: „информационна и аналитична подкрепа, не правен или инвестиционен съвет“.
- **Сигурност:** bcrypt, rate limiting на auth, HTTPS навсякъде, роля admin отделно.
- **Език:** UI на български; архитектурата готова за i18n (фаза 4: английски за чужди инвеститори).

---

## 9. Фази на изграждане

**Фаза 0 — Валидация (преди код!):** лист 12 от Excel-а попълнен за ≥1 реален проект, ≥1 община сверена (Варна). Без това фаза 1 не започва.

**Фаза 1 — MVP (ядро):**
DB схема + миграции → импорт на core-данните от Excel-а → четирите машини с unit тестове (Excel-ът е еталонът: същият вход трябва да даде 420 дни, 39 870 лв, IRR 11,8%) → auth → wizard → проектен изглед със секции Резюме/Маршрут/Такси → Stripe checkout → админ: актове+тарифи.

**Фаза 2 — Pro слой:** Gantt с редакция + recalc в реално време + версии + журнал + Икономика + експорт Excel.

**Фаза 3 — DD слой:** Monte Carlo (async) + PDF доклад + опашка за експертна валидация + абонамент „Актуалност“ с мониторинг и известия (имейл).

**Фаза 4 — Разширяване:** още типове проекти, още общини, PWA полиране, i18n, евентуално native app.

Критерий за готовност на всяка фаза: реален потребител минава пътя от край до край без твоя намеса.

---

## 10. Отворени решения (за уточняване преди фаза 1)

1. Имена и цени на нивата (Standard/Pro/DD са работни).
2. Stripe или БГ доставчик (ePay/myPOS) за плащания — зависи от фактуриране/ДДС статуса на твоето ЕООД.
3. Колко общини в старта (препоръка: Варна + 2).
4. Домейн и име: „Buildflow AI“ — да се провери свободен домейн и търговска марка.
5. Схемата за сертифициране (вътрешен печат / КИИП заверка / партньор) — фаза 3.
