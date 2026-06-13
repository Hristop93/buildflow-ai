# CSV шаблони за въвеждане на данни

Попълни тези CSV-та (UTF-8, разделител запетая) и ги качи през админ API-то.
Десетична запетая в числата се приема (напр. `2,5`). Празна клетка = няма стойност.

## Импорт (админ роля). `dry_run=true` проверява без да записва — пусни го ПЪРВО.

```
POST /admin/import/municipalities      ?dry_run=true   (Content-Type: text/csv, тялото = CSV)
POST /admin/import/institutions
POST /admin/import/acts
POST /admin/import/documents
POST /admin/import/procedures
POST /admin/import/procedure-inputs
POST /admin/import/dependencies
POST /admin/import/tariffs
```

Пример (PowerShell):
```powershell
Invoke-RestMethod "http://127.0.0.1:8000/admin/import/tariffs?dry_run=true" `
  -Method Post -ContentType "text/csv" -InFile tariffs.csv -WebSession $admin
```

## Ред на импорт (заради зависимостите между таблиците)
1. `municipalities.csv`  (вече заредени 265; ползвай само за корекции)
2. `institutions.csv`     (институции)
3. `acts.csv`             (нормативни актове — id-тата ти ги задаваш, напр. `ZUT-148`)
4. `documents.csv`        (документи)
5. `procedures.csv`       (процедури — реферират институция/акт/изходен документ)
6. `procedure_inputs.csv` (кои документи са вход за коя процедура)
7. `dependencies.csv`     (последователност на процедурите)
8. `tariffs.csv`          (таксите — реферират процедура/община/акт)

## Поведение
- **Всичко или нищо за файл**: ако някой ред е грешен → 422 с номера на реда, нищо не се записва.
- **Идемпотентно**: повторно качване на същия файл не дублира (актове/връзки се пропускат; процедури/документи се обновяват).
- **Тарифи**: същата тарифа се пропуска; различна ставка **версионира** старата (пази историята).
- **Община по ИМЕ** (празно = национално/държавно ниво).

## Допустими стойности
- `level` (acts): `state` | `municipal`
- `term_basis` (procedures): `calendar` | `working` (работни дни)
- `basis` (tariffs): `fixed` | `per_sqm_rzp` | `pct_of_value` | `per_mw`
- `link_type` (dependencies): `finish_start` | `start_start`
- `coverage_status` (municipalities): `verified` | `partial` | `none`

## Правила (rules) — НЕ са CSV
Условните правила (include/exclude/switch, вкл. съставни условия) се въвеждат през
`POST /admin/rules` (JSON), защото носят структура, която не се събира в клетка.
