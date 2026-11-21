# Caderno de Carga Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Painel de treino (artefato claude.ai) ligado a uma planilha Google, com progressão/projeção de cargas por local, RIR opcional, volume, diário de água/alimentação e integração iOS por Atalhos.

**Architecture:** Um motor puro (`engine.js`, UMD) faz todo o cálculo e é testado no Node; o mesmo arquivo roda inline no artefato e como `Engine.gs` no Apps Script. A página (`app.html`) lê/grava a planilha pela capability `mcp` (conector "Google Sheets": `get_values`, `append_values`). Um script de build injeta o motor, o ID da planilha e o instantâneo inicial na página publicada.

**Tech Stack:** HTML/CSS/JS sem framework (SVG próprio para gráficos), Node 20+ `node:test`, Google Apps Script V8, Google Sheets API via conector.

**Spec:** `docs/superpowers/specs/2026-11-21-caderno-de-carga-design.md`

## Global Constraints

- Idioma da interface e da planilha: português do Brasil; locale `pt_BR`, fuso `America/Sao_Paulo`.
- Locais: exatamente `Campinas` e `SJC`; Local de exercício pode ser `Ambos` (histórico compartilhado).
- Unidades: `kg`, `kg/lado`, `placas`. Rotação: `Upper A → Lower A → Upper B → Lower B`.
- Padrões: faixa 5–8 reps; RIR alvo 0 em todos; séries 2; incremento padrão kg 2,5 · kg/lado 2,5 · placas 1 · halter 2.
- e1RM Epley `W·(1+R/30)`, `R = reps + RIR` só com "Contar RIR" ligado; RIR vazio = 0; `R > 15` = estimativa pouco confiável.
- Deload: 3 sessões seguidas sem superar o melhor e1RM → −10% (mínimo 1 passo). Ganho por sessão `g` = tendência limitada a 0,25–2,5%, padrão 1%.
- Datas gravadas pelo painel como número de série (dias desde 30/12/1899).
- Os números reais do usuário não vão para o repositório (público): ficam na planilha e no instantâneo da página publicada.
- Código derivado do openGym → pasta sob AGPL-3.0, com atribuição.
- Páginas de artefato: sem `<html>/<head>/<body>`, scripts só de CDNs permitidos (aqui: nenhum), tema claro/escuro por tokens, funciona a 400 px.

## Review Focus

1. Valores formatados em pt-BR vindos da planilha (`"102,5"`, `"1.234,5"`, `"21/11/2026"`, `"21/11/26"`, número de série) → devem virar número/data corretos.
2. Cabeçalho reordenado ou com colunas extras pelo usuário → colunas encontradas pelo nome, não pela posição.
3. Nome de exercício digitado com caixa/acentos/espaços diferentes → mesmo histórico.
4. Linhas incompletas (sem reps ou sem carga, RIR vazio) → ignoradas ou RIR = 0, sem quebrar o painel.
5. Incremento grosso (placas: +1 placa > 15%) → progride por reps antes de subir carga, sem sugerir "4 placas × 0".

---

## File Structure

```
caderno-de-carga/
  README.md            o que é, como usar, como publicar (Task 6)
  LICENSE              AGPL-3.0 (cópia do openGym) (Task 6)
  package.json         "test": "node --test test/" (Task 1)
  .gitignore           dist/, local.json (Task 1)
  src/engine.js        motor puro, UMD → window.Engine / module.exports / Apps Script (Tasks 1–2)
  src/plano.json       plano padrão sem cargas (Task 1)
  src/app.html         página do artefato (Tasks 4–5)
  scripts/build.mjs    gera dist/caderno-de-carga.html e apps-script/Engine.gs (Task 4)
  test/engine.test.mjs testes do motor (Tasks 1–2)
  test/build.test.mjs  teste do build (Task 4)
  apps-script/Code.gs  doGet/doPost para Atalhos e modo app (Task 6)
  apps-script/Engine.gs gerado pelo build (Task 4)
  docs/IOS.md          Siri/Atalhos/Saúde/Tela de Início (Task 6)
```

### Task 1: Parsing and table reading

**Files:** Create `caderno-de-carga/src/engine.js`, `caderno-de-carga/src/plano.json`, `caderno-de-carga/package.json`, `caderno-de-carga/.gitignore`, `caderno-de-carga/test/engine.test.mjs`

**Interfaces — Produces (all on `Engine`):**
- `parseNum(v: any) → number|null`
- `parseDate(v: any) → 'YYYY-MM-DD'|null`; `toSerial(iso) → number`; `fromSerial(n) → iso`
- `normLocal(v) → 'Campinas'|'SJC'|'Ambos'|null`; `normUnit(v) → 'kg'|'kg/lado'|'placas'|null`; `keyOf(name) → string`
- `parseRegistros(values: any[][]) → Set[]` — `{row, date, local, treino, exercicio, key, serie, carga, unidade, reps, rir}`
- `parseExercicios(values) → PlanRow[]` — `{treino, ordem, exercicio, key, local, grupo, unidade, inc, repsMin, repsMax, rirAlvo, series, obs}`
- `parseDiario(values) → DiaryRow[]` — `{date, agua, cafe, almoco, lanche, jantar, outros, kcal, prot, peso, sono, obs}`
- `SCHEMA` — header lists for the three tabs (used by sheet seeding and Apps Script).

- [ ] **Step 1: Write failing tests** `parseNum`: `"102,5"→102.5`, `"1.234,5"→1234.5`, `"32"→32`, `32→32`, `""→null`, `"abc"→null`. `parseDate`: `"21/11/2026"`, `"21/11/26"`, `"2026-11-21"`, `46347` and `"46347"` all → `"2026-11-21"`; `toSerial("2026-11-21") === 46347`. `normLocal`: `"sjc"`, `"São José dos Campos"` → `"SJC"`; `" campinas "` → `"Campinas"`. `normUnit`: `"plaquinhas"`, `"placa"` → `"placas"`; `"kg cada lado"` → `"kg/lado"`. `keyOf(" Supino  Inclinado com HALTER ") === keyOf("supino inclinado com halter")`. `parseRegistros` with headers reordered (`Exercício, Data, Reps, Carga, Local`) and an extra column still maps fields; a row without reps is dropped; blank RIR → `null`.
- [ ] **Step 2: Run** `cd caderno-de-carga && npm test` → FAIL (`Engine` functions missing).
- [ ] **Step 3: Implement** in `engine.js`. Header match: normalize (lowercase, strip accents, drop `(...)`, collapse spaces), exact alias first, then prefix; fall back to `SCHEMA` position when a header is missing.
- [ ] **Step 4: Run** `npm test` → PASS.
- [ ] **Step 5: Commit** `feat(caderno): parsing de planilha pt-BR`.

### Task 2: Progression engine

**Files:** Modify `caderno-de-carga/src/engine.js`; Test `caderno-de-carga/test/engine.test.mjs`

**Interfaces — Consumes:** Task 1 types. **Produces:**
- `e1rm(carga, reps, rir, countRIR) → {est, R, reliable}|null`
- `planFor(plan: PlanRow[], key, local) → PlanRow` (exact local → `Ambos` → same key elsewhere → `DEFAULTS` + unit default inc)
- `sessionsFor(sets, planRow, local, opts) → Session[]` — `{date, local, sets, top:{carga, reps, rir, R, est, reliable}, tonnage, hardSets}`; `Ambos` merges both locals
- `stallCount(sessions) → number`; `trendGain(sessions) → number`
- `nextPrescription(sessions, planRow, opts:{countRIR, gain?}) → Rx` — `{kind:'first'|'up'|'hold'|'reps'|'deload', carga, reps, rir, backoff:{carga,reps}|null, why, jumpPct}`
- `simulate(sessions, planRow, opts, n=6) → [{step, carga, reps, est}]`
- `nextWorkout(sets) → 'Upper A'|'Lower A'|'Upper B'|'Lower B'`
- `weeklyVolume(sets, plan, local, opts, weeks=8) → [{week, start, byGroup, total}]`
- `dailyDiary(rows) → [{date, agua, kcal, prot, peso, sono, meals, obs}]`
- `status(sessions) → 'pr'|'ok'|'stalled'|'new'`

- [ ] **Step 1: Write failing tests** (range 5–8, t=0 unless noted):
  - `e1rm(32,6,null,true).est === 38.4`; `e1rm(40,10,3,true).R === 13`; `e1rm(40,10,3,false).R === 10`; `e1rm(30,12,4,true).reliable === false`.
  - Hold: last `32×6`, inc 2 → `{kind:'hold', carga:32, reps:7}`; with RIR 1 counted → reps 8.
  - Up: last `40×10 RIR3` (Hip thrust, inc 5, t=1) counted → `kind:'up'`, `carga ≥ 45`, `reps` within 5–8.
  - Coarse: last `3 placas×8` inc 1 → `kind:'reps'`, `carga:3`, `reps:9`; last `3×11` → `kind:'up'`, `carga:4`, `reps:5`, `why` mentions rest-pause.
  - Below range: last `60×4` → `{kind:'hold', carga:60, reps:5}`.
  - Deload: four sessions `60×6, 60×6, 60×5, 60×6` → `stallCount ≥ 3`, `kind:'deload'`, `carga:55` (inc 2,5 → −10% = 6 → 2 passos = 5).
  - First: no sessions → `kind:'first'`.
  - Shared: plan row `Local: Ambos` merges a Campinas set and an SJC set into 2 sessions; a `Campinas` row ignores SJC sets.
  - Backoff: `series 2` → `backoff.carga < carga`.
  - `simulate(...,6)` returns 6 steps with non-decreasing `est`.
  - `nextWorkout` after a `Lower A` set → `'Upper B'`; after `Lower B` → `'Upper A'`; empty → `'Upper A'`.
  - `weeklyVolume`: two sets in ISO week 2026-W47 for group Peito → `byGroup.Peito === 2`; RIR 4 set counted only when `countRIR` false.
  - `dailyDiary`: two rows on the same date with Água 0,5 and 1 → `agua === 1.5`.
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement** following the spec rules; load steps are relative to the current load (`W + k·inc`), never snapped to an absolute grid. Big-jump rule: if predicted reps at `W'` < `mín` and `R − t < máx + 3` → `kind:'reps'` (`reps = R+1−t`); else `kind:'up'` with `reps = mín` and rest-pause in `why`. `why` strings in pt-BR.
- [ ] **Step 4: Run** `npm test` → PASS.
- [ ] **Step 5: Commit** `feat(caderno): motor de progressão e projeção`.

### Task 3: Google Sheet

**Files:** none in repo (operations through the Google Drive/Sheets connector). Seed values come from the user's marks (Campinas = main values, SJC = parentheses) and `plano.json`; a local `local.json` (git-ignored) keeps `{sheetId, seedDate}`.

- [ ] **Step 1:** Create spreadsheet "Caderno de Carga" (`application/vnd.google-apps.spreadsheet`); read sheet ids.
- [ ] **Step 2:** One `update_spreadsheet` batch: locale/timezone; tabs `Registros`, `Diário`, `Exercícios`, `Como usar`; frozen header; header style; widths; date format `dd/mm/yyyy` on Data columns; dropdowns (Local, Treino, Unidade, Local do plano with `Ambos`), RIR 0–10.
- [ ] **Step 3:** Write headers (`Engine.SCHEMA`), plan rows, seed marks (one set each, Obs "marca inicial"; Hip thrust RIR 3 from "bem de boa"), `Como usar` text.
- [ ] **Step 4: Verify** `get_values` of each tab; run the parsed values through `parseRegistros`/`parseExercicios` in Node → expected counts (sets = number of marks, plan rows > 0, every set matches a plan row).

### Task 4: Page shell, build, Sheets adapter

**Files:** Create `caderno-de-carga/src/app.html`, `caderno-de-carga/scripts/build.mjs`, `caderno-de-carga/test/build.test.mjs`, generated `caderno-de-carga/apps-script/Engine.gs`

**Interfaces — Consumes:** `Engine.*`. **Produces:** `node scripts/build.mjs --config local.json --out <file>` writes the page with `/*@ENGINE*/`, `"__SHEET_ID__"`, `/*@SNAPSHOT*/null` replaced; also writes `apps-script/Engine.gs`.

- [ ] **Step 1: Write failing test** `build.test.mjs`: build with a temp config → output contains `Engine.parseNum`, the sheet id, no `__SHEET_ID__`, no `<html`; `Engine.gs` equals engine source with a "gerado" header.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** build + page shell: tokens (openGym iOS palette, light/dark, accent per local: Campinas orange, SJC blue), header with Local segmented control, "Contar RIR" switch (localStorage), sync status and sheet link; data layer `load()` via `watchTool("Google Sheets","get_values",…)` for the three ranges + `callTool("Google Sheets","append_values",…)` for writes, error states by code (`needs_reauth`, `server_not_connected`, `not_in_manifest`/`approval_required` with a button, `server_unavailable` keeping stale data, `tool_error` showing message), snapshot fallback labeled with its date.
- [ ] **Step 4: Run** `npm test` → PASS. **Step 5: Commit** `feat(caderno): página, build e conexão com a planilha`.

### Task 5: Views and charts

**Files:** Modify `caderno-de-carga/src/app.html`

- [ ] **Step 1:** Treino view: workout chips (suggested by `nextWorkout`), per exercise: last mark, `Rx` (big load × reps, why chip, back-off), sparkline, log form prefilled with `Rx` (Carga, Reps, RIR shown only with Contar RIR, Série auto-increment) → append row `[serial, local, treino, exercício, série, carga, unidade, reps, rir|'', obs]`, then `invalidate` + refresh.
- [ ] **Step 2:** Evolução view: exercise picker, SVG line (e1RM history solid, `simulate` dashed with widening band, last point emphasized), table of next sessions, PR/stall pill.
- [ ] **Step 3:** Volume view: stacked weekly bars by group (8 weeks), legend, totals.
- [ ] **Step 4:** Diário view: water bars vs goal (default 4 L, editable), +250/+500/+1000 ml buttons and meal form (append to Diário), protein/kcal/peso/sono summaries, recent meals list; designed empty states.
- [ ] **Step 5: Verify** build, one Playwright screenshot at 400 px and desktop of the snapshot mode (no console errors). **Commit** `feat(caderno): telas de treino, evolução, volume e diário`.

### Task 6: Publish, iOS, docs

**Files:** Create `caderno-de-carga/apps-script/Code.gs`, `caderno-de-carga/docs/IOS.md`, `caderno-de-carga/README.md`, `caderno-de-carga/LICENSE`

- [ ] **Step 1:** Publish the built page as an artifact with `capabilities: {mcp: {servers: [{server: "Google Sheets", tools: ["get_values", "append_values"]}]}}`; one preview look; one read-back of the sheet.
- [ ] **Step 2:** `Code.gs`: `doGet(e)` — `acao=dados` returns the three tabs as JSON, `acao=proximo&local=SJC` returns spoken text of the next workout (via `Engine`); `doPost(e)` — `tipo: 'serie'|'agua'|'diario'` appends rows; all calls require `token` = Script Property `TOKEN` (set by `configurarToken()`).
- [ ] **Step 3:** `IOS.md`: deploy steps, Atalhos "Registrar água", "Registrar série", "Próximo treino", automação Saúde → água, Tela de Início.
- [ ] **Step 4:** README + LICENSE + attribution; `npm test` PASS; commit and push to `claude/fervent-lamport-rm3gol`.
