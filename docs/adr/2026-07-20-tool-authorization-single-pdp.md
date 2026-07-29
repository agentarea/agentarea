# ADR: Единый авторитет авторизации инструментов (Tool Authorization)

- **Дата:** 2026-07-20
- **Статус:** Accepted (направление зафиксировано; открытые продуктовые решения — §9)
- **Ветка:** `refactor/agent-chat-task-conversation`

## 1. Проблема и решение

Авторизация тула была размазана по пяти несогласованным механизмам (hand-typed
`tool:` строки, OpenFGA-граф, task-policy, interceptor-гейт, workflow-префлайт), и
каждый недавний баг — следствие этого: disclosure говорил «да», enforcement — «нет».

**Решение одной фразой:** единый **авторитет** (PDP). Гранты хранятся в **OpenFGA**
(таплы + условия). Caller не носит и не передаёт гранты — он передаёт только
`subject (WHO) + object (canonical id) + ctx (params)` и получает вердикт.
Zero-trust: нет гранта → deny, без fallback ([[feedback_no_default_fallbacks]]).

> **Единый контрол-плейн = единая точка РЕШЕНИЯ, а не единое хранилище.** PDP
> делегирует вычисление OpenFGA (ABAC/relationship). OpenFGA — evaluator за
> авторитетом, единственное место в коде, где звучит вендор.

---

## 2. Формальная модель (теория множеств) — ИСТОЧНИК ИСТИНЫ

### Множества

- **𝕋** — универсум каноничных возможностей (`mcp:<inst>:<name>`, `code:<name>`, `agent:<id>:delegate`; тип-объект в OpenFGA — `Capability`, без `tool:` префикса).
- **CF ⊂ 𝕋** — control-flow тулы (`completion`, `request_user_input`, …). Не возможности, всегда разрешены.
- **C ⊆ 𝕋** — composition агента для задачи = `MCP exposure ∪ skills ∪ code ∪ delegation ∪ task-additions`.

### Принципал и контекст (единственное, что морозим)

- **s** — subject (WHO), заморожен при создании (из IdP).
- **e** — `task_epoch`, заморожен.
- **ctx** — `{ epoch=e, task_id, resource, time=τ }`. Только это caller и передаёт.

### Оракул авторизации (OpenFGA Check)

Гранты в OpenFGA; условия (seal / scope / validity) считаются **внутри** Check по ctx.

```text
check(s, t, ctx) ∈ { ALLOW, APPROVAL, DENY }        для t ∈ 𝕋
```

`DENY` — значение при **ответившем** оракуле. Недоступность оракула ≠ DENY: check не
определён → активити падает и **ретраится** (no fallback).

### Гранты как разбиение по вердикту

```text
A(ctx) = { t : check = ALLOW }
P(ctx) = { t : check = APPROVAL }
Γ(ctx) = A(ctx) ∪ P(ctx)          (granted)
deny   = 𝕋 \ Γ(ctx)                (дополнение — НИКОГДА не дисклоузим)
```

### Потолок и динамика (seal)

```text
G_e     = { грант : created_at ≤ e }          (запечатанная база)
G_task  = { грант : scope = task_id }          (авторизованные добавки на лету)
Ceiling = G_e ∪ G_task                          (максимальный surface задачи)
R(τ)    = { гранты, отозванные к моменту τ }

Γ(ctx_τ) = ( Ceiling \ R(τ) ) ∩ { t : ABAC(t, ctx_τ) }      ABAC = scope ∈ resource, τ < valid_until
```

- **Анти-инъекция (инвариант):** `∀ τ ≥ e : Γ(ctx_τ) ⊆ Ceiling`. Грант, созданный после `e` и не привязанный к `task_id`, в задачу не течёт.
- **Отзыв монотонно-субтрактивен:** `R` только растёт ⇒ `Γ` во времени только сужается.

### Disclosure (что видит модель на ходу)

    D = ( Γ(ctx_turn) ∩ C ) ∪ CF

- **Denied вне контекста:** `D ∩ deny = ∅` — модель не видит `𝕋 \ Γ` (0 лишних токенов).
- Показываем `A ∪ P` (approval-тулы тоже — гейт эскалирует человеку); `deny` — никогда.

### Правило dispatch (запрошенный t при ctx_d)

    t ∈ CF          → ALLOW
    t ∈ A(ctx_d)    → ALLOW
    t ∈ P(ctx_d)    → APPROVAL
    t ∉ Γ(ctx_d)    → DENY     (default; = не скомпонован ∨ не гранчен ∨ отозван ∨ вне scope ∨ протух ∨ галлюцинация)

- **Zero-trust / no fallback:** дефолт — DENY. Исполнение требует `t ∈ Γ(ctx_d) ∪ CF`.

### Связь disclosure ↔ dispatch

Амбиентно `Γ(ctx_d) ⊆ Γ(ctx_turn)`:
- дисклоузнутый тул может быть **denied на dispatch** (редко: отзыв в середине хода);
- тул `∉ D` может только упереться в deny (галлюцинация);
- **никогда:** `t ∉ Γ` не исполняется.

---

## 3. Архитектура (DDD: порты/адаптеры)

Имена — по **концерну**, не по хранилищу. Вендор — только в имени адаптера.

```
agentarea_common.auth            ← Shared kernel: value objects + порты
  ├─ CapabilityId                (VO: canonical id + kind)
  ├─ AuthorizationRequest        (VO: subject, object, ctx)
  ├─ AuthorizationDecision       (VO: ALLOW|APPROVAL|DENY, reason)
  └─ ToolAuthority               (Port: authorize(request) -> decision ; list_granted(subject, ctx) -> set)

agentarea_governance             ← реализация авторитета
  └─ OpenFgaToolAuthority        (адаптер порта: Check / ListObjects + условия seal/scope/validity)
                                    ЕДИНСТВЕННОЕ место со словом OpenFGA

Composition (контекст Agents/Execution, ОТДЕЛЬНО от авторитета)
  └─ CapabilityResolver          (agent+task -> canonical objects C ; НЕ решает доступ)

PEP — точки принуждения (зависят ТОЛЬКО от порта ToolAuthority):
  ├─ disclosure  (prepare_turn activity)   D = list_granted(WHO, ctx) ∩ C ∪ CF
  ├─ dispatch    (execute_tool activity)   authorize(WHO, object, ctx)
  └─ mcp_proxy   (api)                     authorize(WHO, object, ctx)
```

- Caller подаёт `(WHO, object, ctx)` → авторитет решает. «Нет такого тула для тебя» = deny, вернувшийся от авторитета, а не self-check у caller.
- Composition (что существует) и Authorization (можно ли) сходятся в авторитете; на инвокации источник (`mcp/code/delegate`) неважен — единый `CapabilityId`.

---

## 4. Флоу

**Создание задачи (один раз):**
1. Аутентификация WHO через IdP → `subject` (+ on-behalf-of, workspace, цепочка делегирования).
2. FREEZE на задачу: `{ WHO, task_epoch }`. Гранты НЕ материализуем.

**Каждый LLM-ход:**
3. `prepare_turn` (activity): `D = list_granted(WHO, ctx) ∩ C ∪ CF` → модель видит только granted.
4. LLM-колл с `D`.

**Каждый вызов тула (dispatch, execute activity):**
5. requested tool → `CapabilityId` + resource.
6. `authorize(WHO, object, ctx={resource, now, task_epoch})` → OpenFGA Check.
7. `A→ALLOW · P→APPROVAL · иначе DENY`. Различаем **DENY (решение, не ретраим)** vs **сбой оракула (ошибка → ретрай)**. Контекст — **WHO-scoped, НЕ system** (фикс confused-deputy).

**Дельты на лету (в OpenFGA, задача подхватывает на следующем Check):**
- REVOKE = удалить тапл → следующий Check → deny (live).
- ADD = тапл с `scope=task_id` → авторизованное добавление.
- Новый workspace-грант → в задачу не течёт (условие `created_at ≤ task_epoch`).

**Делегирование (спец-случай):** живой Check внутри активити `CREATE_DELEGATION_TASK` → возвращает авторизованный canonical target → child стартует только после успеха.

---

## 5. Determinism (Temporal)

- Workflow-код детерминирован → **никакого IO**; решение авторитета зависит от изменяемого состояния → только в **активити** (результат в истории, replay берёт записанное).
- Морозим только `{WHO, task_epoch}` (маленький детерминированный вход).
- `prepare_turn` и `authorize` — активити. Workflow тупой: подаёт `(WHO, object, ctx)`, получает вердикт.
- Параллельные тулы: внутри одного workflow однопоточно/детерминировано; на инвокации каждый вызов авторизуется независимо. Расходуемые гранты (rate-limit/budget) — атомарно у источника, не наша булева авторизация.

---

## 6. Что меняем

### Phase 1 — CORE (делает zero-trust настоящим, проверяемо на живом агенте)
1. **OpenFGA-модель:** каноничные объекты + отношение `can_invoke`, условие seal `created_at ≤ task_epoch` (+ resource/validity как ABAC).
2. **Порт `ToolAuthority` + `OpenFgaToolAuthority`** (`common.auth` порт, `governance` адаптер). Убрать default-allow из `tool_authorization.py`; `authorize` = deny-by-default по OpenFGA.
3. **`CapabilityId`** (canonical id: `mcp:<inst>:<name>` / `code:<name>` / `agent:<id>:delegate`) + резолв requested tool → id.
4. **Создание задачи** (`task_service`): FREEZE `{WHO, task_epoch}` (не surface).
5. **Dispatch** (`agent_execution_activities:~783`): `authorize(WHO, object, ctx)`; **deny vs ошибка**; **фикс confused-deputy ~L800** (WHO-scoped, убрать system-context).
6. **Disclosure на ход** (`helpers`/`workflow`): `list_granted(WHO, ctx) ∩ C ∪ CF`; denied не дисклоузим.
7. **Гейт** (`workflow:2135`): зовёт авторитет, без самопроверки набора.
8. **MCP-прокси** (`mcp_proxy:134`): тот же `authorize`, WHO на запрос.
9. **Проверка на реальном агенте** (neuresearch): грант→работает; удалили тапл→след. dispatch deny; user A ≠ user B.

### Phase 2 — LATER (модель уже вмещает)
- Авторизованные добавки на лету (`scope=task_id`) + UX отзыва.
- Resource/scope ABAC (файлы) через context-условия.
- Делегирование в `CREATE_DELEGATION_TASK`.
- Кэш (consistency tokens) — если упрётся в перф.

---

## 7. Инварианты (из §2, для ревью)

- **Zero-trust:** исполнение требует `t ∈ Γ(ctx_d) ∪ CF`; дефолт — DENY.
- **No fallback:** сбой оракула → ретрай, не deny.
- **Анти-инъекция:** `Γ(ctx_τ) ⊆ Ceiling` — бегущая задача не расширяется чужим грантом.
- **Отзыв субтрактивен и live:** `R` растёт ⇒ `Γ` сужается на следующем Check.
- **Disclosure = granted-only:** `D ∩ deny = ∅`.
- **WHO целостен:** задача Alice остаётся исполнением Alice, даже если Bob апрувит.

---

## 8. Аудит / enterprise

Enterprise-гарантия — не «набор неизменен», а **deny-by-default + полный аудит**: ничто
не попало в surface без решения авторитета, и каждый add/revoke — запись. OpenFGA
таплы + история изменений дают этот след.

---

## 9. Открытые продуктовые решения

1. **Идентичность делегированной задачи:** originating creator vs owner делегирующего агента.
2. **Отзыв у бегущей задачи:** хирургически (убрать тул) vs kill/pause (для скомпрометированного кредла).
3. **Миграция/аудит** существующих `tool-access` грантов в live-сторах перед включением seal.

---

## 10. Rollout (инкремент 3 — флип, требует живого стека и проверки на реальном агенте)

Структура (порт/адаптер/resolver/service/DI/модель) готова, инертна и не меняет
поведение. Флип — **отдельный выверенный шаг**, НЕ big-bang: OpenFGA-модель —
общий стор (ReBAC Connections/Workspace/Agent), кривая заливка ломает всю
авторизацию. Порядок:

1. **Залить модель безопасно:** OpenFGA хранит версии; пишем новую authorization-model
   (тип `Capability` аддитивен) и перецеливаем `authorization_model_id`. Проверить,
   что существующие ReBAC-проверки (Connections/Workspace) не сломались.
2. **Grant-seeding:** при создании задачи резолвим composition `C` (`CapabilityResolver`)
   и пишем `can_invoke` таплы (`subject`, `created_at`) + `needs_approval` из approval-политики.
   Без этого deny-by-default задении́т всё.
3. **Shadow-режим (обязателен перед enforcement):** на dispatch считать вердикт
   `ToolAuthorizationService.authorize` **параллельно** с живым `decide_tool_policy`,
   логировать расхождения, НО принуждать по-старому. Прогнать neuresearch, убедиться,
   что новый путь совпадает (composed→allow, non-composed→deny).
4. **Freeze `{WHO, task_epoch}`** в `task_service`, прокинуть в ctx активити.
5. **Flip enforcement:** PEP'ы (`helpers`/`workflow:2135`, `activities:783`, `mcp_proxy:134`)
   → `ToolAuthorizationService`; удалить default-allow ветку `decide_tool_policy`;
   обновить комментарий `factory.py`.
6. **Фикс confused-deputy** `activities:~800`: `create_system_context` → user-scoped
   из `request.user_id`, fail-hard если пуст ([[feedback_no_default_fallbacks]]).
7. **Проверка на реальном агенте (neuresearch), обязательна:** грант→работает ·
   удалили тапл→след. dispatch deny · user A ≠ user B · сбой OpenFGA→ретрай (не deny) ·
   disclosure не показывает denied.

Только после зелёного shadow + (7) снимать default-allow. Enforcement-флип (5) —
одна строка на PEP, легко откатить (вернуть `decide_tool_policy`).
