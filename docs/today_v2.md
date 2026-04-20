# Today v2

## Objetivo

Today é a **superfície de execução diária** do Baseline. Não é dashboard, não é histórico, não é análise.

Um usuário abre Today para responder três perguntas, nessa ordem:

1. **O que preciso fazer hoje?** (ação)
2. **Como está meu dia até agora?** (leitura compacta)
3. **Posso confiar no que estou vendo?** (confiança no dado)

Qualquer coisa que não altere pelo menos uma dessas três respostas **não entra em Today**.

## Regra de entrada

Um item só aparece em Today se alterar:

- **Ação de hoje** — algo que o usuário precisa ou pode fazer agora.
- **Leitura compacta de hoje** — estado atual do corpo/rotina, hoje.
- **Confiança mínima** — se a fonte está ok, degradada ou bloqueada.

Se não altera nenhuma das três, pertence a outra superfície (Progress, Record, System).

## O que entra

- `DailyProtocol` do dia (o que se espera executar).
- Status de completude de cada item do protocolo.
- Sinais atuais compactos (peso de hoje, temperatura de hoje, sintomas ativos, HRV de hoje se relevante).
- Blockers (falta de pareamento, sync travada, fonte sem dado).
- Nível de confiança agregado (`trust`).

## O que **não** entra

- Gráficos longitudinais, heatmaps, séries temporais → **Progress**.
- Edição de regimens, configuração de fontes, pareamento → **Record** / **System**.
- Detalhe histórico de qualquer métrica → **Progress**.
- Score contínuo, pontuação de bem-estar, "health score".
- Nenhum dado não diário arbitrariamente trazido só porque existe.

## Conceito de `DailyProtocol`

`DailyProtocol` é o contrato implícito do dia — o conjunto mínimo de coisas que o usuário se comprometeu a executar e registrar hoje.

Itens cobertos na v1:

- `check_in` — registro matinal (mood/energy/sleep quality)
- `check_out` — registro noturno (body state score, notas)
- `medication` — doses esperadas hoje por regimen ativo
- `temperature` — medida(s) de temperatura corporal exigida(s)
- `symptoms` — registro opcional (não quebra o dia, mas entra no contrato para rastreio)
- `weight` — pesagem esperada (HC900)
- `garmin` — leitura diária mínima (HRV, sono)

Cada item do protocolo tem:

- `required: boolean` — é obrigatório hoje
- parâmetros específicos (ex.: `expected_doses` para medicação, `min_readings` para temperatura)

Nesta camada, o protocolo vem de um **default frontend** parametrizável. Não há endpoint de protocolo. Quando o backend expuser configuração de protocolo, o default é substituído.

## Definição de blocker

**Blocker** é qualquer condição que impede o usuário de completar um item `required` do protocolo por motivo externo, não por negligência do usuário.

Exemplos:

- HC900 não pareado → `weight` bloqueada.
- Garmin sem sync nas últimas 48h e agente stale → `garmin` bloqueada.
- Source `integration_configured=false` → item dependente bloqueado.

**Não é blocker:**

- Usuário simplesmente ainda não registrou (é `action_needed`, não `blocked`).
- Dado stale mas não obrigatório hoje (é `trust.degraded`, não `blocked`).

Blocker é sempre **auditável** — carrega a causa (`source_unavailable`, `device_not_paired`, `sync_stale`, `no_data`) e a superfície que pode resolver (tipicamente **System**).

## Semântica de `TodaySurfaceState`

Três estados mutuamente exclusivos:

- `ok` — todos os itens `required` do protocolo estão completos (ou `not_applicable`) e não há blocker aberto. Hero é uma **confirmação**.
- `action_needed` — há pelo menos um item actionable pelo usuário hoje. Hero é a **próxima ação prioritária**. Blockers podem coexistir aqui — mas só é `action_needed` se existir alguma ação que o usuário ainda pode executar.
- `blocked` — todos os itens `required` incompletos estão bloqueados por causa externa; não há nada que o usuário possa fazer no Today para avançar. Hero é um **blocker** com rota de resolução.

Regra de decisão:

```
if requiredIncomplete.every(item => item.status === 'blocked'):
    state = 'blocked'
elif requiredIncomplete.length === 0:
    state = 'ok'
else:
    state = 'action_needed'
```

Hero **sempre existe** — nunca é `null`.

## Fronteira arquitetural

```
useTodaySources  →  TodayRawSources  →  deriveTodayViewModel  →  TodayViewModel
     hook             dados crus           função pura            para UI
```

Regras duras:

- `useTodaySources` **só** agrega queries TanStack. Nenhuma interpretação, nenhum default de UX, nenhum fallback semântico. Retorna `{ sources, isLoading, isError }`.
- `TodayRawSources` é um snapshot crú: checkpoints hoje, symptoms hoje, doses de medicação e logs, leituras de temperatura hoje, pesagem mais recente e de hoje, medidas de Garmin de hoje, `SystemStatusResponse`.
- `deriveTodayViewModel(protocol, sources)` é **pura**: mesma entrada → mesma saída. Sem `new Date()`, sem `fetch`, sem `useQuery`. Recebe `now` injetado quando precisar de tempo.
- `TodayViewModel` é o contrato consumido pela UI. Nenhum componente lê `TodayRawSources` diretamente.

Nada nesta pipeline chama backend novo. Nada reabsorve Progress / Record / System.

## Priorização de ações

Ordenação por **regras auditáveis**, sem score numérico ponderado. Ordem de desempate:

1. **Integridade do dia** — item essencial (ex.: check-in matinal antes das 12h).
2. **Sensibilidade temporal** — janela atual aberta (morning window, pre-meal window).
3. **Desbloqueio** — ação que destrava outras.
4. **Confiabilidade** — ação que aumenta trust (ex.: temperatura quando tem sintoma ativo).
5. **Menor custo** — empate final vai para a ação de menor fricção.

Ordenação é **estável** e cada ação expõe `reason: string` explicando por que está naquela posição.

## Fora do escopo desta camada

- `recentCaptures` — não entra no contrato inicial.
- Charts, timelines, analytics.
- UI (componentes React) — esta camada é só tipos + derivação + hook de fontes + testes.
- Roteamento novo — Today v2 não é exposto ainda em `App.tsx`.
- Endpoint de protocolo no backend.
