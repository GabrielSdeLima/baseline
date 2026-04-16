# Baseline — Plano de Implementação

## Visão Geral

Baseline é uma plataforma de dados longitudinais de saúde pessoal. O sistema cruza dados de performance (Garmin, dispositivos) com dados de estado clínico (peso, temperatura, sintomas) para permitir inferências de saúde — por exemplo, prever inflamação cruzando HRV, temperatura e peso.

**Prioridade:** Base de dados relacional rigorosa, arquitetura de ingestão bem pensada e API sólida. UI não é foco.

---

## 1. Estrutura de Pastas

```
baseline/
├── PLAN.md
├── README.md
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
├── .env.example
├── .gitignore
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI app factory
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                    # Settings via pydantic-settings
│   │   ├── database.py                  # AsyncEngine, async sessionmaker
│   │   └── dependencies.py              # get_db dependency
│   ├── models/
│   │   ├── __init__.py                  # Re-exports all models (para Alembic)
│   │   ├── base.py                      # DeclarativeBase + mixins
│   │   ├── user.py
│   │   ├── data_source.py
│   │   ├── metric_type.py
│   │   ├── raw_payload.py
│   │   ├── measurement.py
│   │   ├── exercise.py
│   │   ├── workout.py                   # workout_sessions + workout_sets
│   │   ├── medication.py                # definitions + regimens + logs
│   │   ├── symptom.py                   # symptoms + symptom_logs
│   │   └── daily_checkpoint.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py                    # Schemas compartilhados (paginação, etc.)
│   │   ├── measurement.py
│   │   ├── raw_payload.py
│   │   ├── workout.py
│   │   ├── medication.py
│   │   ├── symptom.py
│   │   └── daily_checkpoint.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py                      # BaseRepository genérico
│   │   ├── measurement.py
│   │   ├── raw_payload.py
│   │   ├── workout.py
│   │   ├── medication.py
│   │   ├── symptom.py
│   │   └── daily_checkpoint.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ingestion.py                 # Raw → Curated pipeline
│   │   ├── measurement.py
│   │   ├── workout.py
│   │   ├── medication.py
│   │   ├── symptom.py
│   │   └── daily_checkpoint.py
│   └── api/
│       ├── __init__.py
│       └── v1/
│           ├── __init__.py
│           ├── router.py                # Agrega todos os sub-routers
│           ├── measurements.py
│           ├── raw_payloads.py
│           ├── workouts.py
│           ├── medications.py
│           ├── symptoms.py
│           └── daily_checkpoints.py
├── scripts/
│   └── seed.py                          # Dados realistas cruzados
├── tests/
│   ├── __init__.py
│   ├── conftest.py                      # Fixtures: test DB, async client
│   ├── test_measurements.py
│   ├── test_ingestion.py
│   ├── test_workouts.py
│   ├── test_medications.py
│   ├── test_symptoms.py
│   └── test_daily_checkpoints.py
└── docs/
    ├── architecture.md
    └── data-model.md
```

### Decisões Arquiteturais

- **Clean Architecture pragmática:** Sem ports/adapters excessivos. Camadas claras: Models → Repositories → Services → API.
- **Repository Pattern:** Repositories encapsulam queries SQLAlchemy. Services orquestram lógica de negócio. API é fina (validação + roteamento).
- **Dependency Injection:** Via `Depends()` do FastAPI. `get_db` injeta sessão async.
- **Async:** AsyncSession + asyncpg. SQLAlchemy 2.0 suporta async nativamente. Mantemos async por default, mas sem complexidade desnecessária (ex: sem lazy loading implícito — usamos `selectinload` explícito).

---

## 2. Schema do Banco de Dados

### Convenções Gerais

- **PKs de lookup tables** (baixo volume, referência): `SERIAL` (integer auto-increment).
- **PKs de tabelas de alto volume** (measurements, logs, sessions): `UUID` gerado como UUIDv7 na aplicação (time-sortable, B-tree friendly).
- **Timestamps:** Todos `TIMESTAMPTZ` (timezone-aware). `ingested_at` sempre `DEFAULT NOW()`.
- **Tripla temporal:** `measured_at`, `recorded_at`, `ingested_at` em tabelas de medição (measurements). Outras tabelas de evento usam timestamps de domínio próprios (ex: `started_at`/`ended_at` para workouts, `scheduled_at`/`taken_at` para medication_logs) mais `recorded_at` e `ingested_at`.
- **`created_at` / `updated_at`:** Lookup tables (data_sources, metric_types, exercises, symptoms, medication_definitions) têm apenas `created_at` (dados de referência imutáveis). Entidades mutáveis (users, medication_regimens) têm `created_at` + `updated_at`. Tabelas de evento/fato usam `ingested_at` como timestamp de criação — sem `created_at`/`updated_at` separados.
- **Soft-delete:** Não implementado no V1. Dados nunca são sobrescritos (append-only por design).

---

### 2.1 `users`

Tabela de usuários do sistema.

| Coluna       | Tipo                     | Constraints              |
|--------------|--------------------------|--------------------------|
| `id`         | `UUID`                   | PK, default UUIDv7       |
| `email`      | `VARCHAR(255)`           | UNIQUE, NOT NULL         |
| `name`       | `VARCHAR(255)`           | NOT NULL                 |
| `timezone`   | `VARCHAR(63)`            | NOT NULL, DEFAULT 'UTC'  |
| `created_at` | `TIMESTAMPTZ`            | NOT NULL, DEFAULT NOW()  |
| `updated_at` | `TIMESTAMPTZ`            | NOT NULL, DEFAULT NOW()  |

**Indexes:** PK(`id`), UNIQUE(`email`).

> Sem autenticação no V1 — para o case, o foco é no modelo de dados. User existe como entidade de domínio para multi-tenancy futuro.

---

### 2.2 `data_sources`

Catálogo global de tipos de fonte de dados. No V1, é um registro de referência (não representa uma conexão configurada por usuário — apenas identifica a origem dos dados).

| Coluna        | Tipo            | Constraints              |
|---------------|-----------------|--------------------------|
| `id`          | `SERIAL`        | PK                       |
| `slug`        | `VARCHAR(63)`   | UNIQUE, NOT NULL         |
| `name`        | `VARCHAR(127)`  | NOT NULL                 |
| `source_type` | `VARCHAR(31)`   | NOT NULL                 |
| `description` | `TEXT`          |                          |
| `created_at`  | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()  |

**Valores iniciais:** `manual`, `garmin`, `withings`, `apple_health`.
**`source_type`:** `device`, `app`, `manual`, `integration`.

> **V1:** Catálogo global. Sem `user_id`, sem credenciais, sem estado de sync. Futuras versões podem adicionar `user_source_connections` para modelar conexões OAuth por usuário.

---

### 2.3 `metric_types`

Lookup de tipos de métrica. Extensível sem migrations.

| Coluna            | Tipo            | Constraints              |
|-------------------|-----------------|--------------------------|
| `id`              | `SERIAL`        | PK                       |
| `slug`            | `VARCHAR(63)`   | UNIQUE, NOT NULL         |
| `name`            | `VARCHAR(127)`  | NOT NULL                 |
| `category`        | `VARCHAR(63)`   | NOT NULL                 |
| `default_unit`    | `VARCHAR(31)`   | NOT NULL                 |
| `value_precision` | `SMALLINT`      |                          |
| `description`     | `TEXT`          |                          |
| `created_at`      | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()  |

**Categorias:** `body_composition`, `cardiovascular`, `activity`, `vitals`, `sleep`, `respiratory`.

**Valores iniciais:**

| slug                | name                  | category           | default_unit | precision |
|---------------------|-----------------------|--------------------|--------------|-----------|
| `weight`            | Weight                | body_composition   | kg           | 2         |
| `body_fat_pct`      | Body Fat %            | body_composition   | %            | 1         |
| `body_temperature`  | Body Temperature      | vitals             | °C           | 1         |
| `resting_hr`        | Resting Heart Rate    | cardiovascular     | bpm          | 0         |
| `hrv_rmssd`         | HRV (RMSSD)           | cardiovascular     | ms           | 1         |
| `spo2`              | SpO2                  | respiratory        | %            | 0         |
| `steps`             | Steps                 | activity           | steps        | 0         |
| `active_calories`   | Active Calories       | activity           | kcal         | 0         |
| `sleep_duration`    | Sleep Duration        | sleep              | min          | 0         |
| `sleep_score`       | Sleep Score           | sleep              | score        | 0         |
| `stress_level`      | Stress Level          | cardiovascular     | score        | 0         |
| `respiratory_rate`  | Respiratory Rate      | respiratory        | brpm         | 1         |

---

### 2.4 `raw_payloads`

Camada RAW. Preservação do dado bruto original para auditoria e reprocessamento.

| Coluna              | Tipo            | Constraints                         |
|---------------------|-----------------|-------------------------------------|
| `id`                | `UUID`          | PK, UUIDv7                         |
| `user_id`           | `UUID`          | FK → users, NOT NULL               |
| `source_id`         | `INTEGER`       | FK → data_sources, NOT NULL        |
| `external_id`       | `VARCHAR(255)`  |                                     |
| `payload_type`      | `VARCHAR(63)`   | NOT NULL                           |
| `payload_json`      | `JSONB`         | NOT NULL                           |
| `ingested_at`       | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()            |
| `processing_status` | `VARCHAR(31)`   | NOT NULL, DEFAULT 'pending'        |
| `processed_at`      | `TIMESTAMPTZ`   |                                     |
| `error_message`     | `TEXT`          |                                     |

**Indexes:**
- PK(`id`)
- UNIQUE(`source_id`, `external_id`) WHERE `external_id IS NOT NULL` — deduplicação de payloads externos
- INDEX(`user_id`, `ingested_at`)
- INDEX(`processing_status`) WHERE `processing_status = 'pending'` — partial index para fila de processamento

**`processing_status`:** `pending`, `processed`, `failed`, `skipped`.
**`payload_type`:** `garmin_daily_summary`, `garmin_activity`, `withings_measurement`, `manual_entry`, etc.

---

### 2.5 `measurements`

Tabela central (camada CURATED). Medições numéricas normalizadas.

| Coluna              | Tipo            | Constraints                         |
|---------------------|-----------------|-------------------------------------|
| `id`                | `UUID`          | PK, UUIDv7                         |
| `user_id`           | `UUID`          | FK → users, NOT NULL               |
| `metric_type_id`    | `INTEGER`       | FK → metric_types, NOT NULL        |
| `source_id`         | `INTEGER`       | FK → data_sources, NOT NULL        |
| `value_num`         | `NUMERIC`       | NOT NULL                           |
| `unit`              | `VARCHAR(31)`   | NOT NULL                           |
| `measured_at`       | `TIMESTAMPTZ`   | NOT NULL                           |
| `started_at`        | `TIMESTAMPTZ`   |                                     |
| `ended_at`          | `TIMESTAMPTZ`   |                                     |
| `recorded_at`       | `TIMESTAMPTZ`   | NOT NULL                           |
| `ingested_at`       | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()            |
| `aggregation_level` | `VARCHAR(15)`   | NOT NULL, DEFAULT 'spot'           |
| `is_derived`        | `BOOLEAN`       | NOT NULL, DEFAULT FALSE            |
| `confidence`        | `NUMERIC(3,2)`  | CHECK(0 <= confidence <= 1)        |
| `context`           | `JSONB`         |                                     |
| `raw_payload_id`    | `UUID`          | FK → raw_payloads                  |

**Indexes:**
- PK(`id`)
- INDEX(`user_id`, `measured_at`) — query padrão: "minhas medições em um período"
- INDEX(`user_id`, `metric_type_id`, `measured_at`) — "meu peso nos últimos 30 dias"
- INDEX(`raw_payload_id`) — rastreabilidade raw → curated

**`aggregation_level`:** `spot` (ponto único), `hourly`, `daily`.
**`started_at` / `ended_at`:** Opcionais. Para medições pontuais (peso, temperatura), ficam NULL. Para medições que cobrem um período (sleep_duration de 23h a 7h, steps diários), delimitam o intervalo. `measured_at` é sempre o ponto de referência principal.
**`confidence`:** 0.0 a 1.0. Dados manuais podem ter confidence menor que dados de device.

---

### 2.6 `exercises`

Lookup de exercícios. Modelagem séria, sem texto livre.

| Coluna         | Tipo            | Constraints              |
|----------------|-----------------|--------------------------|
| `id`           | `SERIAL`        | PK                       |
| `slug`         | `VARCHAR(63)`   | UNIQUE, NOT NULL         |
| `name`         | `VARCHAR(127)`  | NOT NULL                 |
| `category`     | `VARCHAR(31)`   | NOT NULL                 |
| `muscle_group` | `VARCHAR(63)`   |                          |
| `equipment`    | `VARCHAR(63)`   |                          |
| `description`  | `TEXT`          |                          |
| `created_at`   | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()  |

**`category`:** `strength`, `cardio`, `flexibility`, `sport`, `compound`.
**`muscle_group`:** `chest`, `back`, `legs`, `shoulders`, `arms`, `core`, `full_body`.

---

### 2.7 `workout_sessions`

Sessão de treino. Timestamps de domínio são `started_at`/`ended_at` (início e fim do treino), sem `measured_at` — o conceito de "quando ocorreu" é inerente a `started_at`. Mantém `recorded_at` e `ingested_at` para rastreabilidade.

| Coluna            | Tipo            | Constraints                         |
|-------------------|-----------------|-------------------------------------|
| `id`              | `UUID`          | PK, UUIDv7                         |
| `user_id`         | `UUID`          | FK → users, NOT NULL               |
| `source_id`       | `INTEGER`       | FK → data_sources, NOT NULL        |
| `title`           | `VARCHAR(255)`  |                                     |
| `workout_type`    | `VARCHAR(31)`   | NOT NULL                           |
| `started_at`      | `TIMESTAMPTZ`   | NOT NULL                           |
| `ended_at`        | `TIMESTAMPTZ`   |                                     |
| `duration_seconds`| `INTEGER`       |                                     |
| `perceived_effort`| `SMALLINT`      | CHECK(1 <= perceived_effort <= 10) |
| `notes`           | `TEXT`          |                                     |
| `recorded_at`     | `TIMESTAMPTZ`   | NOT NULL                           |
| `ingested_at`     | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()            |
| `raw_payload_id`  | `UUID`          | FK → raw_payloads                  |
| `context`         | `JSONB`         |                                     |

**Indexes:**
- PK(`id`)
- INDEX(`user_id`, `started_at`)

**`workout_type`:** `strength`, `cardio`, `mixed`, `flexibility`, `sport`.

---

### 2.8 `workout_sets`

Sets individuais dentro de uma sessão.

| Coluna              | Tipo            | Constraints                          |
|---------------------|-----------------|--------------------------------------|
| `id`                | `UUID`          | PK, UUIDv7                          |
| `workout_session_id`| `UUID`          | FK → workout_sessions, NOT NULL     |
| `exercise_id`       | `INTEGER`       | FK → exercises, NOT NULL            |
| `set_number`        | `SMALLINT`      | NOT NULL                            |
| `reps`              | `SMALLINT`      |                                      |
| `weight_kg`         | `NUMERIC(7,2)`  |                                      |
| `duration_seconds`  | `INTEGER`       |                                      |
| `distance_meters`   | `NUMERIC(10,2)` |                                      |
| `rest_seconds`      | `SMALLINT`      |                                      |
| `notes`             | `TEXT`          |                                      |

**Indexes:**
- PK(`id`)
- INDEX(`workout_session_id`)

> `reps` + `weight_kg` para strength. `duration_seconds` + `distance_meters` para cardio. Flexível sem ser genérico demais.

---

### 2.9 `medication_definitions`

Cadastro de medicamentos.

| Coluna              | Tipo            | Constraints              |
|---------------------|-----------------|--------------------------|
| `id`                | `SERIAL`        | PK                       |
| `name`              | `VARCHAR(255)`  | NOT NULL                 |
| `active_ingredient` | `VARCHAR(255)`  |                          |
| `dosage_form`       | `VARCHAR(63)`   |                          |
| `description`       | `TEXT`          |                          |
| `created_at`        | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()  |

**`dosage_form`:** `tablet`, `capsule`, `liquid`, `injection`, `topical`, `inhaler`.

---

### 2.10 `medication_regimens`

Prescrição/plano: qual medicamento, qual dosagem, qual frequência.

| Coluna          | Tipo            | Constraints                           |
|-----------------|-----------------|---------------------------------------|
| `id`            | `UUID`          | PK, UUIDv7                           |
| `user_id`       | `UUID`          | FK → users, NOT NULL                 |
| `medication_id` | `INTEGER`       | FK → medication_definitions, NOT NULL|
| `dosage_amount` | `NUMERIC(7,2)`  | NOT NULL                             |
| `dosage_unit`   | `VARCHAR(31)`   | NOT NULL                             |
| `frequency`     | `VARCHAR(31)`   | NOT NULL                             |
| `instructions`  | `TEXT`          |                                       |
| `prescribed_by` | `VARCHAR(255)`  |                                       |
| `started_at`    | `DATE`          | NOT NULL                             |
| `ended_at`      | `DATE`          |                                       |
| `is_active`     | `BOOLEAN`       | NOT NULL, DEFAULT TRUE               |
| `created_at`    | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()              |
| `updated_at`    | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()              |

**Indexes:**
- PK(`id`)
- INDEX(`user_id`, `is_active`)

**`frequency`:** `daily`, `twice_daily`, `three_times_daily`, `weekly`, `as_needed`.

---

### 2.11 `medication_logs`

O ato de tomar (ou pular) uma dose. Temporalidade rica de evento — cada log carrega múltiplos timestamps com semânticas distintas.

| Coluna          | Tipo            | Constraints                           |
|-----------------|-----------------|---------------------------------------|
| `id`            | `UUID`          | PK, UUIDv7                           |
| `user_id`       | `UUID`          | FK → users, NOT NULL                 |
| `regimen_id`    | `UUID`          | FK → medication_regimens, NOT NULL   |
| `status`        | `VARCHAR(15)`   | NOT NULL                             |
| `scheduled_at`  | `TIMESTAMPTZ`   | NOT NULL                             |
| `taken_at`      | `TIMESTAMPTZ`   |                                       |
| `dosage_amount` | `NUMERIC(7,2)`  |                                       |
| `dosage_unit`   | `VARCHAR(31)`   |                                       |
| `notes`         | `TEXT`          |                                       |
| `recorded_at`   | `TIMESTAMPTZ`   | NOT NULL                             |
| `ingested_at`   | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()              |

**Indexes:**
- PK(`id`)
- INDEX(`user_id`, `scheduled_at`)
- INDEX(`regimen_id`)

**`status`:** `taken`, `skipped`, `delayed`.

> Temporalidade rica: `scheduled_at` = quando deveria ter tomado (prescrição). `taken_at` = quando efetivamente tomou (ação). `recorded_at` = quando registrou no sistema (observação). `ingested_at` = quando entrou no banco (sistema). Não é a tripla temporal canônica (measured/recorded/ingested), mas um modelo temporal próprio adequado ao domínio de medicação.

---

### 2.12 `symptoms`

Lookup de sintomas possíveis.

| Coluna       | Tipo            | Constraints              |
|--------------|-----------------|--------------------------|
| `id`         | `SERIAL`        | PK                       |
| `slug`       | `VARCHAR(63)`   | UNIQUE, NOT NULL         |
| `name`       | `VARCHAR(127)`  | NOT NULL                 |
| `category`   | `VARCHAR(63)`   | NOT NULL                 |
| `description`| `TEXT`          |                          |
| `created_at` | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()  |

**`category`:** `pain`, `digestive`, `respiratory`, `neurological`, `systemic`, `musculoskeletal`, `dermatological`.

---

### 2.13 `symptom_logs`

Registro de ocorrência de sintoma, com intensidade, status e tripla temporal.

| Coluna              | Tipo            | Constraints                    |
|---------------------|-----------------|--------------------------------|
| `id`                | `UUID`          | PK, UUIDv7                    |
| `user_id`           | `UUID`          | FK → users, NOT NULL          |
| `symptom_id`        | `INTEGER`       | FK → symptoms, NOT NULL       |
| `intensity`         | `SMALLINT`      | NOT NULL, CHECK(1-10)         |
| `status`            | `VARCHAR(15)`   | NOT NULL, DEFAULT 'active'    |
| `trigger`           | `VARCHAR(255)`  |                                |
| `functional_impact` | `VARCHAR(15)`   |                                |
| `started_at`        | `TIMESTAMPTZ`   | NOT NULL                      |
| `ended_at`          | `TIMESTAMPTZ`   |                                |
| `notes`             | `TEXT`          |                                |
| `recorded_at`       | `TIMESTAMPTZ`   | NOT NULL                      |
| `ingested_at`       | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()       |
| `context`           | `JSONB`         |                                |

**Indexes:**
- PK(`id`)
- INDEX(`user_id`, `started_at`)

**`status`:** `active`, `resolved`, `improving`, `worsening`.
**`functional_impact`:** `none`, `mild`, `moderate`, `severe`.

---

### 2.14 `daily_checkpoints`

Eventos semânticos ricos — check-ins diários (manhã, noite).

| Coluna              | Tipo            | Constraints                              |
|---------------------|-----------------|------------------------------------------|
| `id`                | `UUID`          | PK, UUIDv7                              |
| `user_id`           | `UUID`          | FK → users, NOT NULL                    |
| `checkpoint_type`   | `VARCHAR(15)`   | NOT NULL                                |
| `checkpoint_date`   | `DATE`          | NOT NULL                                |
| `checkpoint_at`     | `TIMESTAMPTZ`   | NOT NULL                                |
| `mood`              | `SMALLINT`      | CHECK(1-10)                             |
| `energy`            | `SMALLINT`      | CHECK(1-10)                             |
| `sleep_quality`     | `SMALLINT`      | CHECK(1-10)                             |
| `body_state_score`  | `SMALLINT`      | CHECK(1-10)                             |
| `notes`             | `TEXT`          |                                          |
| `recorded_at`       | `TIMESTAMPTZ`   | NOT NULL                                |
| `ingested_at`       | `TIMESTAMPTZ`   | NOT NULL, DEFAULT NOW()                 |
| `context`           | `JSONB`         |                                          |

**Indexes:**
- PK(`id`)
- UNIQUE(`user_id`, `checkpoint_type`, `checkpoint_date`) — **garante no máximo 1 checkpoint por tipo/dia/usuário**
- INDEX(`user_id`, `checkpoint_date`)

**`checkpoint_type`:** `morning`, `night`.

---

## 3. Diagrama de Relacionamentos

```
users
  ├──< raw_payloads          (user_id)
  ├──< measurements          (user_id)
  ├──< workout_sessions      (user_id)
  ├──< medication_regimens   (user_id)
  ├──< medication_logs       (user_id)
  ├──< symptom_logs          (user_id)
  └──< daily_checkpoints     (user_id)

data_sources
  ├──< raw_payloads          (source_id)
  ├──< measurements          (source_id)
  └──< workout_sessions      (source_id)

metric_types ──< measurements       (metric_type_id)

raw_payloads
  ├──< measurements          (raw_payload_id)  ← FK real
  └──< workout_sessions      (raw_payload_id)  ← FK real

exercises ──< workout_sets          (exercise_id)

workout_sessions ──< workout_sets   (workout_session_id)

medication_definitions ──< medication_regimens (medication_id)

medication_regimens ──< medication_logs       (regimen_id)

symptoms ──< symptom_logs           (symptom_id)
```

**Todas as setas são FKs reais no banco de dados.** Nenhuma integridade é "apenas na camada de serviço".

---

## 4. Fluxo de Ingestão (Raw → Curated)

```
External API / Manual Input
         │
         ▼
   ┌─────────────┐
   │ raw_payloads │  ← JSON bruto preservado, processing_status = 'pending'
   └──────┬──────┘
          │
          ▼
   ┌─────────────────┐
   │ Ingestion Service│  ← Parseia, valida, normaliza unidades
   └──────┬──────────┘
          │
          ├──▶ measurements       (com raw_payload_id = FK para rastreabilidade)
          ├──▶ workout_sessions   (idem)
          └──▶ ...
          │
          ▼
   raw_payloads.processing_status = 'processed'
```

**Regras de ingestão:**
1. Todo dado externo passa por `raw_payloads` primeiro (append-only).
2. O serviço de ingestão parseia e cria registros curados com FK para o raw.
3. Se falhar, marca `processing_status = 'failed'` com `error_message`.
4. Dados manuais podem ir direto para curated (com `raw_payload_id = NULL`) — mas ainda assim registrar `recorded_at`.
5. Reprocessamento: mudar status para `pending`, rodar ingestão novamente. Curated antigos permanecem (append-only, sem DELETE/UPDATE).

---

## 5. Stack Técnica

| Componente      | Escolha                  | Justificativa                                    |
|-----------------|--------------------------|--------------------------------------------------|
| Runtime         | Python 3.12+             | Tipagem moderna, performance                     |
| Framework       | FastAPI                  | Async-first, OpenAPI automático, DI nativo       |
| ORM             | SQLAlchemy 2.0           | Mapped classes, async support, maduro            |
| Migrations      | Alembic                  | Standard para SQLAlchemy                         |
| Validation      | Pydantic v2              | Integrado ao FastAPI, rápido                     |
| Database        | PostgreSQL 16            | Robusto, JSONB nativo, partial indexes           |
| Driver          | asyncpg                  | Async driver para PostgreSQL                     |
| Testes          | pytest + httpx           | Async test client para FastAPI                   |
| Linting         | Ruff                     | All-in-one linter + formatter                    |
| Container       | Docker + docker-compose  | Dev environment consistente                      |
| ID Generation   | uuid7 (uuid6 lib)        | Time-sortable, B-tree optimized                  |

---

## 6. Fases de Execução

### Fase 1: Planejamento ✓
- [x] Definir estrutura de pastas
- [x] Definir schema completo do banco
- [x] Documentar fluxo de ingestão
- [x] Aprovação do usuário

### Fase 2: Infraestrutura e Banco de Dados ✓
- [x] docker-compose.yml + Dockerfile
- [x] pyproject.toml (dependências)
- [x] app/core/ (config, database, dependencies)
- [x] app/models/ (todos os models SQLAlchemy)
- [x] Alembic setup + primeira migration
- [x] Subir banco e rodar migration

### Fase 3: Core Logic e API ✓
- [x] app/schemas/ (Pydantic v2)
- [x] app/repositories/ (queries)
- [x] app/services/ (lógica de negócio + ingestão)
- [x] app/api/v1/ (endpoints)
- [x] Ruff setup + fix

### Fase 4: Hardening e Prova de Valor
- [x] tests/conftest.py (infra: test DB, session isolation, fixtures)
- [x] tests/test_invariants.py (FK, UNIQUE, CHECK constraints no banco)
- [x] tests/test_ingestion.py (idempotência, rollback, dedup, rastreabilidade)
- [x] tests/test_domain_rules.py (resolução de slug, autorização, TZDatetime)
- [x] tests/test_api.py (HTTP integration: status codes, paginação, erros)
- [x] scripts/seed.py (30 dias fisiológicos: baseline→overreach→illness→recovery)
- [x] scripts/analytics.sql (7 queries cross-domain provando valor do schema)
- [x] docs/architecture.md (trade-offs e decisões técnicas)
- [x] docs/data-model.md (schema, temporal semantics, V1 constraints)
- [x] README.md (posicionamento como longitudinal health data platform)
