import { test } from 'node:test'
import assert from 'node:assert/strict'
import Engine from '../src/engine.js'

// ---------------------------------------------------------------- Task 1: parsing

test('parseNum reads pt-BR and plain numbers', () => {
  assert.equal(Engine.parseNum('102,5'), 102.5)
  assert.equal(Engine.parseNum('1.234,5'), 1234.5)
  assert.equal(Engine.parseNum('32'), 32)
  assert.equal(Engine.parseNum(32), 32)
  assert.equal(Engine.parseNum(' 2.5 '), 2.5)
  assert.equal(Engine.parseNum(''), null)
  assert.equal(Engine.parseNum(null), null)
  assert.equal(Engine.parseNum('abc'), null)
})

test('parseDate accepts dd/mm/yyyy, dd/mm/yy, ISO and serial numbers', () => {
  for (const v of ['21/11/2026', '21/11/26', '2026-11-21', 46347, '46347'])
    assert.equal(Engine.parseDate(v), '2026-11-21', String(v))
  assert.equal(Engine.parseDate('3/2/2026'), '2026-02-03')
  assert.equal(Engine.parseDate(''), null)
  assert.equal(Engine.parseDate('ontem'), null)
})

test('toSerial and fromSerial round-trip Google Sheets day numbers', () => {
  assert.equal(Engine.toSerial('2026-11-21'), 46347)
  assert.equal(Engine.fromSerial(46347), '2026-11-21')
})

test('normLocal maps the ways people write the two gyms', () => {
  assert.equal(Engine.normLocal('sjc'), 'SJC')
  assert.equal(Engine.normLocal('São José dos Campos'), 'SJC')
  assert.equal(Engine.normLocal(' campinas '), 'Campinas')
  assert.equal(Engine.normLocal('ambos'), 'Ambos')
  assert.equal(Engine.normLocal('Rio'), null)
})

test('normUnit maps plate and per-side spellings', () => {
  assert.equal(Engine.normUnit('plaquinhas'), 'placas')
  assert.equal(Engine.normUnit('placa'), 'placas')
  assert.equal(Engine.normUnit('kg cada lado'), 'kg/lado')
  assert.equal(Engine.normUnit('KG/LADO'), 'kg/lado')
  assert.equal(Engine.normUnit('kg'), 'kg')
  assert.equal(Engine.normUnit(''), null)
})

test('keyOf ignores case, accents and extra spaces', () => {
  assert.equal(Engine.keyOf(' Supino  Inclinado com HALTER '), Engine.keyOf('supino inclinado com halter'))
  assert.equal(Engine.keyOf('Elevação lateral'), Engine.keyOf('elevacao lateral'))
})

test('parseRegistros finds columns by header name, not position', () => {
  const values = [
    ['Exercício', 'Data', 'Reps', 'Extra', 'Carga', 'Local', 'RIR', 'Treino', 'Unidade', 'Série', 'Obs'],
    ['Supino inclinado com halter', '21/11/2026', '6', 'x', '32', 'Campinas', '', 'Upper A', 'kg', '1', 'marca inicial'],
    ['Remada baixa', '22/11/2026', '5', '', '50', 'sjc', '2', 'Upper B', 'kg', '1', '']
  ]
  const sets = Engine.parseRegistros(values)
  assert.equal(sets.length, 2)
  assert.equal(sets[0].exercicio, 'Supino inclinado com halter')
  assert.equal(sets[0].date, '2026-11-21')
  assert.equal(sets[0].carga, 32)
  assert.equal(sets[0].reps, 6)
  assert.equal(sets[0].rir, null)
  assert.equal(sets[0].local, 'Campinas')
  assert.equal(sets[0].baseline, true)
  assert.equal(sets[1].local, 'SJC')
  assert.equal(sets[1].rir, 2)
  assert.equal(sets[1].baseline, false)
  assert.equal(sets[1].row, 3)
})

test('parseRegistros drops rows without reps, load or exercise', () => {
  const values = [
    Engine.SCHEMA.registros,
    ['21/11/2026', 'Campinas', 'Upper A', 'Rosca com halter', 1, 18, 'kg', '', '', ''],
    ['21/11/2026', 'Campinas', 'Upper A', '', 1, 18, 'kg', 7, '', ''],
    ['21/11/2026', 'Campinas', 'Upper A', 'Rosca com halter', 1, '', 'kg', 7, '', ''],
    ['21/11/2026', 'Campinas', 'Upper A', 'Rosca com halter', 1, 18, 'kg', 7, '', '']
  ]
  assert.equal(Engine.parseRegistros(values).length, 1)
})

test('parseRegistros falls back to the default column order without a header', () => {
  const values = [['21/11/2026', 'SJC', 'Lower B', 'Hip thrust', 1, 40, 'kg', 10, 3, 'bem de boa']]
  const [s] = Engine.parseRegistros(values)
  assert.equal(s.exercicio, 'Hip thrust')
  assert.equal(s.rir, 3)
  assert.equal(s.row, 1)
})

test('parseExercicios reads plan rows with numeric parameters', () => {
  const values = [
    Engine.SCHEMA.exercicios,
    ['Upper A', 1, 'Supino inclinado com halter', 'Ambos', 'Peito', 'kg', 2, 5, 8, 0, 2, ''],
    ['Upper B', 2, 'Pulldown unilateral', 'SJC', 'Costas', 'kg', '2,5', 5, 8, 0, 2, '']
  ]
  const plan = Engine.parseExercicios(values)
  assert.equal(plan.length, 2)
  assert.equal(plan[0].local, 'Ambos')
  assert.equal(plan[0].inc, 2)
  assert.equal(plan[1].inc, 2.5)
  assert.equal(plan[1].repsMin, 5)
  assert.equal(plan[1].key, Engine.keyOf('pulldown unilateral'))
})

test('parseDiario reads water and meals, tolerating unit suffixes in headers', () => {
  const values = [
    Engine.SCHEMA.diario,
    ['21/11/2026', '1,5', 'ovos', '', '', '', '', '', '40', '82,3', '7', '']
  ]
  const [d] = Engine.parseDiario(values)
  assert.equal(d.date, '2026-11-21')
  assert.equal(d.agua, 1.5)
  assert.equal(d.cafe, 'ovos')
  assert.equal(d.prot, 40)
  assert.equal(d.peso, 82.3)
  assert.equal(d.sono, 7)
  assert.equal(d.kcal, null)
})

test('parseDiario reads water typed in millilitres as litres', () => {
  const [d] = Engine.parseDiario([Engine.SCHEMA.diario, ['21/11/2026', '500']])
  assert.equal(d.agua, 0.5)
})

test('parseDate accepts Date objects (Apps Script getValues)', () => {
  assert.equal(Engine.parseDate(new Date(2026, 10, 21, 0, 0, 0)), '2026-11-21')
})

test('normTreino canonicalises the four workouts', () => {
  assert.equal(Engine.normTreino(' upper a'), 'Upper A')
  assert.equal(Engine.normTreino('LOWER B'), 'Lower B')
  assert.equal(Engine.normTreino('Full body'), 'Full body')
})

// ---------------------------------------------------------------- Task 2: progression

const set = (date, local, exercicio, carga, reps, rir = null, extra = {}) => ({
  row: extra.row || 0, date, local, treino: extra.treino || 'Upper A', exercicio,
  key: Engine.keyOf(exercicio), serie: 1, carga, unidade: extra.unidade || 'kg', reps, rir,
  obs: extra.baseline ? 'marca inicial' : '', baseline: !!extra.baseline
})
const planRow = (over = {}) => ({
  treino: 'Upper A', ordem: 1, exercicio: 'Supino inclinado com halter',
  key: Engine.keyOf(over.exercicio || 'Supino inclinado com halter'), local: 'Campinas',
  grupo: 'Peito', unidade: 'kg', inc: 2.5, repsMin: 5, repsMax: 8, rirAlvo: 0, series: 2, obs: '', ...over
})
const ON = { countRIR: true }, OFF = { countRIR: false }
const rxFor = (marks, row, opts = ON, local = 'Campinas') => {
  const sets = marks.map(([d, w, r, rir], i) => set(d, local, row.exercicio, w, r, rir, { unidade: row.unidade, row: i + 2 }))
  return Engine.nextPrescription(Engine.sessionsFor(sets, row, local, opts), row, opts)
}

test('e1rm uses Epley and adds RIR only when counting it', () => {
  assert.deepEqual(Engine.e1rm(32, 6, null, true), { est: 38.4, R: 6, reliable: true })
  assert.equal(Engine.e1rm(40, 10, 3, true).R, 13)
  assert.equal(Engine.e1rm(40, 10, 3, false).R, 10)
  assert.equal(Engine.e1rm(30, 12, 4, true).reliable, false)
  assert.equal(Engine.e1rm(100, 1, null, false).est, 100)
  assert.equal(Engine.e1rm(0, 8, 0, true), null)
  assert.equal(Engine.e1rm(50, 0, 0, true), null)
})

test('planFor prefers the exact gym, then Ambos, then defaults by unit', () => {
  const plan = [
    planRow({ exercicio: 'Remada baixa', key: Engine.keyOf('Remada baixa'), local: 'Campinas', unidade: 'placas', inc: 1 }),
    planRow({ exercicio: 'Remada baixa', key: Engine.keyOf('Remada baixa'), local: 'SJC', unidade: 'kg', inc: 2.5 }),
    planRow({ exercicio: 'Rosca com halter', key: Engine.keyOf('Rosca com halter'), local: 'Ambos', inc: 2 })
  ]
  assert.equal(Engine.planFor(plan, Engine.keyOf('remada baixa'), 'SJC').unidade, 'kg')
  assert.equal(Engine.planFor(plan, Engine.keyOf('Rosca com halter'), 'SJC').local, 'Ambos')
  const unknown = Engine.planFor(plan, Engine.keyOf('Voador'), 'SJC', 'placas')
  assert.equal(unknown.inc, 1)
  assert.equal(unknown.repsMin, 5)
  assert.equal(unknown.repsMax, 8)
  assert.equal(unknown.local, 'SJC')
})

test('sessionsFor merges both gyms only for Ambos exercises', () => {
  const sets = [set('2026-11-21', 'Campinas', 'Rosca com halter', 18, 7), set('2026-11-24', 'SJC', 'Rosca com halter', 18, 8)]
  const shared = planRow({ exercicio: 'Rosca com halter', key: Engine.keyOf('Rosca com halter'), local: 'Ambos' })
  assert.equal(Engine.sessionsFor(sets, shared, 'SJC', ON).length, 2)
  const own = { ...shared, local: 'Campinas' }
  assert.equal(Engine.sessionsFor(sets, own, 'Campinas', ON).length, 1)
})

test('sessionsFor groups a day into one session whose top set has the best e1RM', () => {
  const sets = [set('2026-11-21', 'Campinas', 'Supino inclinado com halter', 32, 6), set('2026-11-21', 'Campinas', 'Supino inclinado com halter', 28, 9)]
  const [s] = Engine.sessionsFor(sets, planRow(), 'Campinas', ON)
  assert.equal(s.sets.length, 2)
  assert.equal(s.top.carga, 32)
  assert.equal(s.tonnage, 32 * 6 + 28 * 9)
})

test('no history at this gym means the session sets the baseline', () => {
  assert.equal(Engine.nextPrescription([], planRow(), ON).kind, 'first')
})

test('inside the range: same load, one more rep', () => {
  const rx = rxFor([['2026-11-21', 32, 6, null]], planRow({ inc: 2 }))
  assert.equal(rx.kind, 'hold')
  assert.equal(rx.carga, 32)
  assert.equal(rx.reps, 7)
})

test('reps in reserve count toward the next target only when RIR is on', () => {
  assert.equal(rxFor([['2026-11-21', 32, 6, 1]], planRow({ inc: 2 }), ON).reps, 8)
  assert.equal(rxFor([['2026-11-21', 32, 6, 1]], planRow({ inc: 2 }), OFF).reps, 7)
})

test('target RIR applies only when the last set logged its RIR', () => {
  const stiff = planRow({ exercicio: 'Stiff', unidade: 'kg/lado', rirAlvo: 1 })
  assert.equal(rxFor([['2026-11-21', 35, 6, null]], stiff).reps, 7)
})

test('an easy top set jumps the load using e1RM', () => {
  const hip = planRow({ exercicio: 'Hip thrust', inc: 5, rirAlvo: 1, grupo: 'Glúteos' })
  const rx = rxFor([['2026-11-21', 40, 10, 3]], hip, ON, 'SJC')
  assert.equal(rx.kind, 'up')
  assert.equal(rx.carga, 45)
  assert.equal(rx.reps, 7)
  assert.equal(rx.rir, 1)
  assert.match(rx.why, /\+5 kg/)
})

test('per-side loads step by the per-side increment and say so in pt-BR', () => {
  const calf = planRow({ exercicio: 'Panturrilha sentada', unidade: 'kg/lado', inc: 2.5 })
  const rx = rxFor([['2026-11-21', 30, 10, null]], calf, ON, 'SJC')
  assert.equal(rx.kind, 'up')
  assert.equal(rx.carga, 32.5)
  assert.equal(rx.reps, 7)
  assert.match(rx.why, /\+2,5 kg\/lado/)
})

test('coarse plate steps progress by reps before adding a plate', () => {
  const cross = planRow({ exercicio: 'Cross alto na polia', unidade: 'placas', inc: 1 })
  const rx = rxFor([['2026-11-21', 3, 8, null]], cross)
  assert.equal(rx.kind, 'reps')
  assert.equal(rx.carga, 3)
  assert.equal(rx.reps, 9)
})

test('coarse plate steps eventually go up with rest-pause instead of 0 reps', () => {
  const cross = planRow({ exercicio: 'Cross alto na polia', unidade: 'placas', inc: 1 })
  const rx = rxFor([['2026-11-21', 3, 11, null]], cross)
  assert.equal(rx.kind, 'up')
  assert.equal(rx.carga, 4)
  assert.equal(rx.reps, 5)
  assert.match(rx.why, /rest-pause/)
})

test('below the range: same load, aim for the bottom of the range', () => {
  const rx = rxFor([['2026-11-21', 60, 4, null]], planRow({ exercicio: 'Remada Tbar' }))
  assert.equal(rx.kind, 'hold')
  assert.equal(rx.carga, 60)
  assert.equal(rx.reps, 5)
})

test('three sessions without progress trigger a 10% deload', () => {
  const row = planRow({ exercicio: 'Remada Tbar' })
  const marks = [['2026-11-01', 60, 6, null], ['2026-11-05', 60, 6, null], ['2026-11-09', 60, 5, null], ['2026-11-13', 60, 6, null]]
  const sets = marks.map(([d, w, r]) => set(d, 'Campinas', 'Remada Tbar', w, r))
  const sessions = Engine.sessionsFor(sets, row, 'Campinas', ON)
  assert.equal(Engine.stallCount(sessions), 3)
  const rx = Engine.nextPrescription(sessions, row, ON)
  assert.equal(rx.kind, 'deload')
  assert.equal(rx.carga, 55)
})

test('stallCount resets on more reps or on a deliberate load drop', () => {
  const row = planRow({ exercicio: 'Remada Tbar' })
  const count = marks => Engine.stallCount(Engine.sessionsFor(
    marks.map(([d, w, r]) => set(d, 'Campinas', 'Remada Tbar', w, r)), row, 'Campinas', ON))
  assert.equal(count([['2026-11-01', 60, 6], ['2026-11-05', 60, 7]]), 0)
  assert.equal(count([['2026-11-01', 60, 6], ['2026-11-05', 60, 6]]), 1)
  assert.equal(count([['2026-11-01', 60, 6], ['2026-11-05', 60, 6], ['2026-11-09', 55, 8]]), 0)
})

test('a back-off set is suggested when the plan has two or more sets', () => {
  const rx = rxFor([['2026-11-21', 32, 6, null]], planRow({ inc: 2, series: 2 }))
  assert.deepEqual(rx.backoff, { carga: 28, reps: 9 })
  assert.equal(rxFor([['2026-11-21', 32, 6, null]], planRow({ inc: 2, series: 1 })).backoff, null)
})

test('trendGain defaults to 1% and stays within 0.25–2.5%', () => {
  const row = planRow({ inc: 2 })
  const sess = marks => Engine.sessionsFor(marks.map(([d, w, r]) => set(d, 'Campinas', row.exercicio, w, r)), row, 'Campinas', ON)
  assert.equal(Engine.trendGain(sess([['2026-11-01', 32, 6]])), 0.01)
  const g = Engine.trendGain(sess([['2026-11-01', 30, 6], ['2026-11-05', 30, 8], ['2026-11-09', 32, 7], ['2026-11-13', 34, 6]]))
  assert.ok(g >= 0.0025 && g <= 0.025, String(g))
  const flat = Engine.trendGain(sess([['2026-11-01', 40, 6], ['2026-11-05', 38, 6], ['2026-11-09', 36, 6]]))
  assert.equal(flat, 0.0025)
})

test('simulate projects six sessions of the rule, ending above today', () => {
  const row = planRow({ inc: 2 })
  const sessions = Engine.sessionsFor([set('2026-11-21', 'Campinas', row.exercicio, 32, 6)], row, 'Campinas', ON)
  const sim = Engine.simulate(sessions, row, ON, 6)
  assert.equal(sim.length, 6)
  assert.deepEqual(sim.slice(0, 3).map(s => [s.carga, s.reps]), [[32, 7], [32, 8], [34, 6]])
  assert.ok(sim[5].est > sessions[0].top.est)
})

test('nextWorkout follows the rotation from the latest logged day', () => {
  assert.equal(Engine.nextWorkout([]), 'Upper A')
  assert.equal(Engine.nextWorkout([set('2026-11-21', 'Campinas', 'Mesa flexora', 10, 5, null, { treino: 'Lower A' })]), 'Upper B')
  assert.equal(Engine.nextWorkout([set('2026-11-21', 'SJC', 'Stiff', 35, 6, null, { treino: 'Lower B' })]), 'Upper A')
  const sets = [
    set('2026-11-22', 'SJC', 'Remada baixa', 50, 5, null, { treino: 'Upper B', row: 5 }),
    set('2026-11-21', 'Campinas', 'Mesa flexora', 10, 5, null, { treino: 'Lower A', row: 9 })
  ]
  assert.equal(Engine.nextWorkout(sets), 'Lower B')
})

test('weeklyVolume counts hard sets per group, per gym, without baseline marks', () => {
  const plan = [
    planRow(),
    planRow({ exercicio: 'Crucifixo máquina', key: Engine.keyOf('Crucifixo máquina'), unidade: 'placas' }),
    planRow({ exercicio: 'Rosca com halter', key: Engine.keyOf('Rosca com halter'), grupo: 'Bíceps', local: 'Ambos' })
  ]
  const sets = [
    set('2026-11-17', 'Campinas', 'Supino inclinado com halter', 32, 6),
    set('2026-11-18', 'Campinas', 'Crucifixo máquina', 14, 6, 1),
    set('2026-11-19', 'Campinas', 'Rosca com halter', 18, 7, 4),
    set('2026-11-19', 'SJC', 'Supino inclinado com halter', 32, 7),
    set('2026-11-21', 'Campinas', 'Supino inclinado com halter', 32, 6, null, { baseline: true })
  ]
  const on = Engine.weeklyVolume(sets, plan, 'Campinas', { countRIR: true, today: '2026-11-21' }, 8)
  assert.equal(on.length, 8)
  const wk = on[on.length - 1]
  assert.equal(wk.start, '2026-11-16')
  assert.equal(wk.byGroup['Peito'], 2)
  assert.equal(wk.byGroup['Bíceps'] || 0, 0)
  assert.equal(wk.total, 2)
  const off = Engine.weeklyVolume(sets, plan, 'Campinas', { countRIR: false, today: '2026-11-21' }, 8)
  assert.equal(off[off.length - 1].byGroup['Bíceps'], 1)
})

test('dailyDiary sums the day and joins the meals', () => {
  const rows = Engine.parseDiario([
    Engine.SCHEMA.diario,
    ['21/11/2026', '0,5', 'ovos', '', '', '', '', '', '30', '', '', ''],
    ['21/11/2026', '1', '', 'arroz e frango', '', '', '', '', '50', '82', '', ''],
    ['20/11/2026', '3', '', '', '', '', '', '', '', '', '', '']
  ])
  const days = Engine.dailyDiary(rows)
  assert.equal(days.length, 2)
  assert.equal(days[0].date, '2026-11-20')
  const d = days[1]
  assert.equal(d.agua, 1.5)
  assert.equal(d.prot, 80)
  assert.equal(d.kcal, null)
  assert.equal(d.peso, 82)
  assert.equal(d.meals.cafe, 'ovos')
  assert.equal(d.meals.almoco, 'arroz e frango')
})

test('status flags new, PR and stalled exercises', () => {
  const row = planRow({ exercicio: 'Remada Tbar' })
  const st = marks => Engine.status(Engine.sessionsFor(marks.map(([d, w, r]) => set(d, 'Campinas', 'Remada Tbar', w, r)), row, 'Campinas', ON))
  assert.equal(st([]), 'new')
  assert.equal(st([['2026-11-01', 60, 6]]), 'new')
  assert.equal(st([['2026-11-01', 60, 6], ['2026-11-05', 60, 7]]), 'pr')
  assert.equal(st([['2026-11-01', 60, 6], ['2026-11-05', 60, 6], ['2026-11-09', 60, 5]]), 'stalled')
})

test('simulate keeps target RIR off when the real sets do not log RIR', () => {
  const stiff = planRow({ exercicio: 'Stiff', unidade: 'kg/lado', rirAlvo: 1 })
  const sessions = Engine.sessionsFor([set('2026-11-21', 'Campinas', 'Stiff', 35, 6)], stiff, 'Campinas', ON)
  const sim = Engine.simulate(sessions, stiff, ON, 2)
  assert.deepEqual(sim.map(s => [s.carga, s.reps]), [[35, 7], [35, 8]])
})

test('simulate applies target RIR when the real sets log RIR', () => {
  const stiff = planRow({ exercicio: 'Stiff', unidade: 'kg/lado', rirAlvo: 1 })
  const sessions = Engine.sessionsFor([set('2026-11-21', 'Campinas', 'Stiff', 35, 6, 1)], stiff, 'Campinas', ON)
  const [first] = Engine.simulate(sessions, stiff, ON, 1)
  assert.deepEqual([first.carga, first.reps, first.rir], [35, 7, 1])
})

test('reads rows exactly as the Sheets connector returns them (strings, pt-BR, short rows)', () => {
  const payload = {
    range: 'Registros!A1:J3',
    values: [
      ['Data', 'Local', 'Treino', 'Exercício', 'Série', 'Carga', 'Unidade', 'Reps', 'RIR', 'Obs'],
      ['21/11/2026', 'SJC', 'Upper B', 'Supino reto (máquina ou Smith)', '1', '102,5', 'kg', '7', '', 'marca inicial'],
      ['22/11/2026', 'Campinas', 'Upper A', 'Remada Tbar', '1', '60', 'kg', '7']
    ]
  }
  const sets = Engine.parseRegistros(payload.values)
  assert.equal(sets.length, 2)
  assert.equal(sets[0].carga, 102.5)
  assert.equal(sets[1].rir, null)
  assert.equal(sets[1].obs, '')
  const plan = Engine.parseExercicios([
    ['Treino', 'Ordem', 'Exercício', 'Local', 'Grupo', 'Unidade', 'Incremento', 'Reps mín', 'Reps máx', 'RIR alvo', 'Séries', 'Obs'],
    ['Upper A', '2', 'Remada Tbar', 'Campinas', 'Costas', 'kg', '2,5', '5', '8', '1', '2']
  ])
  assert.equal(plan[0].inc, 2.5)
  assert.equal(plan[0].rirAlvo, 1)
  assert.equal(plan[0].obs, '')
})

test('nextWorkout ignores the initial marks: the rotation starts at Upper A', () => {
  const marks = [set('2026-11-20', 'Campinas', 'Supino inclinado com halter', 32, 6, null, { treino: 'Upper A', baseline: true })]
  assert.equal(Engine.nextWorkout(marks), 'Upper A')
  const withReal = marks.concat([set('2026-11-21', 'Campinas', 'Mesa flexora', 10, 6, null, { treino: 'Lower A' })])
  assert.equal(Engine.nextWorkout(withReal), 'Upper B')
})

test('workoutRows lists one workout at one gym in plan order, shared rows included, without repeats', () => {
  const plan = Engine.parseExercicios([Engine.SCHEMA.exercicios,
    ['Upper A', 2, 'Remada Tbar', 'Campinas', 'Costas', 'kg', 2.5, 5, 8, 0, 2, ''],
    ['Upper A', 2, 'Remada Tbar', 'SJC', 'Costas', 'kg', 2.5, 5, 8, 0, 2, ''],
    ['Upper A', 1, 'Supino inclinado com halter', 'Ambos', 'Peito', 'kg', 2, 5, 8, 0, 2, ''],
    ['Upper A', 1, 'Supino inclinado com halter', 'Ambos', 'Peito', 'kg', 2, 5, 8, 0, 2, 'repetida'],
    ['Lower A', 1, 'Mesa flexora', 'Campinas', 'Posterior', 'placas', 1, 5, 8, 0, 2, '']
  ])
  const rows = Engine.workoutRows(plan, 'Upper A', 'SJC')
  assert.deepEqual(rows.map(r => r.exercicio + '@' + r.local), ['Supino inclinado com halter@Ambos', 'Remada Tbar@SJC'])
})

test('splitToday separates a real session done today from the history behind it', () => {
  const row = planRow({ inc: 2 })
  const sets = [
    set('2026-11-20', 'Campinas', row.exercicio, 32, 6, null, { baseline: true }),
    set('2026-11-21', 'Campinas', row.exercicio, 32, 7, 0)
  ]
  const sessions = Engine.sessionsFor(sets, row, 'Campinas', ON)
  const { before, doneToday } = Engine.splitToday(sessions, '2026-11-21')
  assert.equal(before.length, 1)
  assert.equal(doneToday.top.reps, 7)
  const onlyMarks = Engine.splitToday(Engine.sessionsFor(sets.slice(0, 1), row, 'Campinas', ON), '2026-11-20')
  assert.equal(onlyMarks.doneToday, null)
  assert.equal(onlyMarks.before.length, 1)
})
