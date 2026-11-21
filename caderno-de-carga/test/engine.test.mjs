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
