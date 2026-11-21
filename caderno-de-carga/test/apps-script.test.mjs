// Apps Script bridge (apps-script/Code.gs + Engine.gs) run in a VM with Google's services mocked.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const root = new URL('..', import.meta.url).pathname
const plano = JSON.parse(readFileSync(root + 'src/plano.json', 'utf8'))

function sandbox({ today = '2026-11-22', registros = [] } = {}) {
  const sheets = {
    Registros: [['Data', 'Local', 'Treino', 'Exercício', 'Série', 'Carga', 'Unidade', 'Reps', 'RIR', 'Obs'], ...registros],
    'Diário': [['Data', 'Água (L)', 'Café da manhã', 'Almoço', 'Lanche', 'Jantar', 'Outros', 'Calorias (kcal)', 'Proteína (g)', 'Peso (kg)', 'Sono (h)', 'Obs']],
    'Exercícios': [['Treino', 'Ordem', 'Exercício', 'Local', 'Grupo', 'Unidade', 'Incremento', 'Reps mín', 'Reps máx', 'RIR alvo', 'Séries', 'Obs'], ...plano]
  }
  const sheet = name => ({
    getDataRange: () => ({ getValues: () => sheets[name].map(r => r.slice()) }),
    appendRow: row => { sheets[name].push(row) }
  })
  const props = { TOKEN: 'segredo' }
  const ctx = {
    SpreadsheetApp: { getActiveSpreadsheet: () => ({ getSheetByName: n => (sheets[n] ? sheet(n) : null), getSpreadsheetTimeZone: () => 'America/Sao_Paulo' }) },
    PropertiesService: { getScriptProperties: () => ({ getProperty: k => props[k], setProperty: (k, v) => { props[k] = v } }) },
    Utilities: { formatDate: () => today, getUuid: () => '1234abcd-5678-90ef-1234-567890abcdef' },
    ContentService: { MimeType: { TEXT: 'text', JSON: 'json' }, createTextOutput: s => ({ content: s, setMimeType(m) { this.mime = m; return this } }) },
    LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
    Logger: { log() {} }
  }
  vm.createContext(ctx)
  vm.runInContext(readFileSync(root + 'apps-script/Engine.gs', 'utf8'), ctx)
  vm.runInContext(readFileSync(root + 'apps-script/Code.gs', 'utf8'), ctx)
  return { ctx, sheets, props }
}
const post = (ctx, body) => ctx.doPost({ parameter: {}, postData: { contents: JSON.stringify(body) } }).content
const get = (ctx, parameter) => ctx.doGet({ parameter }).content
const baseline = [new Date(2026, 10, 20), 'Campinas', 'Upper A', 'Supino inclinado com halter', 1, 32, 'kg', 6, '', 'marca inicial']

test('rejects calls without the right token', () => {
  const { ctx, sheets } = sandbox()
  assert.match(post(ctx, { token: 'errado', tipo: 'agua', ml: 500 }), /^Erro: token/)
  assert.match(get(ctx, { acao: 'proximo' }), /^Erro: token/)
  assert.equal(sheets['Diário'].length, 1)
})

test('water in ml is saved in litres on today\'s date', () => {
  const { ctx, sheets } = sandbox()
  const out = post(ctx, { token: 'segredo', tipo: 'agua', ml: '500' })
  const row = sheets['Diário'][1]
  assert.equal(row[0], 46348)               // 22/11/2026 as a Sheets date number
  assert.equal(row[1], 0.5)
  assert.match(out, /^Ok: 500 ml/)
  assert.match(out, /0,5 L hoje/)
})

test('a spoken, partial exercise name is matched to the plan and the row is completed', () => {
  const { ctx, sheets } = sandbox({ registros: [baseline] })
  const out = post(ctx, { token: 'segredo', tipo: 'serie', exercicio: 'supino inclinado', carga: '32,5', reps: 7, rir: 1 })
  const row = sheets.Registros[2]
  assert.deepEqual([...row], [46348, 'Campinas', 'Upper A', 'Supino inclinado com halter', 1, 32.5, 'kg', 7, 1, 'via Atalhos'])   // copied out of the VM realm
  assert.match(out, /^Ok: série 1 de Supino inclinado com halter/)
})

test('the next set number counts sets already logged today', () => {
  const { ctx, sheets } = sandbox({ registros: [baseline, [new Date(2026, 10, 22), 'SJC', 'Upper B', 'Remada baixa', 1, 50, 'kg', 6, '', '']] })
  post(ctx, { token: 'segredo', tipo: 'serie', local: 'sjc', exercicio: 'remada baixa', carga: 50, reps: 5 })
  const row = sheets.Registros[3]
  assert.equal(row[1], 'SJC')
  assert.equal(row[2], 'Upper B')
  assert.equal(row[4], 2)
})

test('a set without load or reps is refused', () => {
  const { ctx, sheets } = sandbox()
  assert.match(post(ctx, { token: 'segredo', tipo: 'serie', exercicio: 'Stiff', reps: 6 }), /^Erro: /)
  assert.equal(sheets.Registros.length, 1)
})

test('meals and body data go to the right Diário columns', () => {
  const { ctx, sheets } = sandbox()
  post(ctx, { token: 'segredo', tipo: 'refeicao', refeicao: 'almoço', texto: 'arroz e frango', proteina: '45' })
  post(ctx, { token: 'segredo', tipo: 'corpo', peso: '82,4', sono: 7 })
  assert.equal(sheets['Diário'][1][3], 'arroz e frango')
  assert.equal(sheets['Diário'][1][8], 45)
  assert.equal(sheets['Diário'][2][9], 82.4)
  assert.equal(sheets['Diário'][2][10], 7)
})

test('Siri reads the next workout with loads and reps in words', () => {
  const { ctx } = sandbox({ registros: [baseline] })
  const text = get(ctx, { token: 'segredo', acao: 'proximo', local: 'Campinas' })
  assert.match(text, /^Upper A em Campinas\./)
  assert.match(text, /Supino inclinado com halter: 32 quilos, 7 repetições/)
  assert.match(text, /Remada Tbar: carga a definir/)
})

test('configurarToken stores a new token', () => {
  const { ctx, props } = sandbox()
  const t = ctx.configurarToken()
  assert.equal(props.TOKEN, t)
  assert.ok(t.length >= 20)
})

test('Engine.gs is the current src/engine.js (run the build after changing the engine)', () => {
  const gs = readFileSync(root + 'apps-script/Engine.gs', 'utf8')
  assert.ok(gs.endsWith(readFileSync(root + 'src/engine.js', 'utf8')))
})
