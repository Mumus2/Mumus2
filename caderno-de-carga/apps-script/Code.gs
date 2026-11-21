/**
 * Caderno de Carga: ponte entre a planilha e o iPhone (Atalhos e Siri).
 *
 * Instalação (detalhes em docs/IOS.md):
 *   1. Na planilha: Extensões > Apps Script. Cole este arquivo em Code.gs e crie Engine.gs
 *      com o conteúdo de apps-script/Engine.gs.
 *   2. Rode configurarToken() uma vez e copie o token do registro de execução.
 *   3. Implantar > Nova implantação > App da Web. Executar como: eu. Quem pode acessar:
 *      qualquer pessoa. Toda chamada precisa do token; sem ele, nada é lido nem gravado.
 *
 * GET  ?token=…&acao=proximo[&local=SJC][&treino=Upper B][&rir=0]  → texto do próximo treino
 * GET  ?token=…&acao=agua                                          → água de hoje
 * POST {token, tipo: 'agua', ml | litros}
 * POST {token, tipo: 'serie', exercicio, carga, reps, [rir, local, treino, serie, unidade, obs]}
 * POST {token, tipo: 'refeicao', refeicao, texto, [kcal, proteina]}
 * POST {token, tipo: 'corpo', [peso, sono]}
 * Todos aceitam `data` (dd/mm/aaaa); sem ela, vale o dia de hoje no fuso da planilha.
 *
 * Derivado do openGym (alexpcosta/opengym), sob a licença AGPL-3.0.
 */

var ABA = { registros: 'Registros', diario: 'Diário', exercicios: 'Exercícios' }
// coluna da refeição na aba Diário (0 = Data)
var REFEICAO = { 'cafe': 2, 'cafe da manha': 2, 'almoco': 3, 'lanche': 4, 'pre-treino': 4, 'pre treino': 4, 'jantar': 5, 'outros': 6, 'ceia': 6 }

/** Gera e guarda um token novo. Rodar de novo troca o token (os atalhos antigos param). */
function configurarToken() {
  var token = Utilities.getUuid().replace(/-/g, '')
  PropertiesService.getScriptProperties().setProperty('TOKEN', token)
  Logger.log('Token do Caderno de Carga: ' + token)
  return token
}

function doGet(e) {
  var p = (e && e.parameter) || {}
  if (!autorizado_(p.token)) return texto_('Erro: token inválido.')
  try {
    var acao = Engine.keyOf(p.acao || 'proximo')
    if (acao === 'proximo') return texto_(resumoProximo_(p))
    if (acao === 'agua') return texto_(resumoAgua_())
    return texto_('Erro: ação desconhecida. Use acao=proximo ou acao=agua.')
  } catch (err) {
    return texto_('Erro: ' + mensagem_(err))
  }
}

function doPost(e) {
  var p = {}
  try { p = JSON.parse((e && e.postData && e.postData.contents) || '{}') } catch (err) { return texto_('Erro: o corpo precisa ser JSON.') }
  var q = (e && e.parameter) || {}
  Object.keys(q).forEach(function (k) { if (p[k] == null) p[k] = q[k] })
  if (!autorizado_(p.token)) return texto_('Erro: token inválido.')
  var lock = LockService.getScriptLock()
  lock.waitLock(10000)
  try {
    var tipo = Engine.keyOf(p.tipo)
    if (tipo === 'agua') return texto_(registrarAgua_(p))
    if (tipo === 'serie') return texto_(registrarSerie_(p))
    if (tipo === 'refeicao') return texto_(registrarRefeicao_(p))
    if (tipo === 'corpo') return texto_(registrarCorpo_(p))
    return texto_('Erro: tipo desconhecido. Use agua, serie, refeicao ou corpo.')
  } catch (err) {
    return texto_('Erro: ' + mensagem_(err))
  } finally {
    lock.releaseLock()
  }
}

// ------------------------------------------------------------------ gravação

function registrarAgua_(p) {
  var litros = Engine.parseNum(p.litros), ml = Engine.parseNum(p.ml)
  if (litros == null && ml != null) litros = ml / 1000
  if (litros != null && litros > 20) litros = litros / 1000   // número grande é ml
  if (!(litros > 0)) throw new Error('informe a água em ml ou litros.')
  var hoje = hoje_()
  aba_(ABA.diario).appendRow([dataDe_(p, hoje), Math.round(litros * 1000) / 1000])
  return 'Ok: ' + Math.round(litros * 1000) + ' ml de água salvos. ' + Engine.fmt(aguaDoDia_(hoje)) + ' L hoje.'
}

function registrarSerie_(p) {
  var d = dados_()
  var carga = Engine.parseNum(p.carga), reps = Engine.parseNum(p.reps)
  if (!p.exercicio || !String(p.exercicio).trim()) throw new Error('informe o exercício.')
  if (carga == null || carga < 0) throw new Error('informe a carga.')
  if (!(reps >= 1)) throw new Error('informe as repetições.')
  var local = localPedido_(p.local, d.sets)
  var row = acharExercicio_(d.plan, p.exercicio, local)
  var nome = row ? row.exercicio : String(p.exercicio).trim()
  var key = Engine.keyOf(nome)
  var plano = Engine.planFor(d.plan, key, local)
  var treino = p.treino ? Engine.normTreino(p.treino) : treinoDeHoje_(d, row)
  var feitas = d.sets.filter(function (s) {
    return s.key === key && s.date === d.hoje && !s.baseline && (s.local === local || plano.local === 'Ambos')
  })
  var serie = Engine.parseNum(p.serie) || feitas.reduce(function (m, s) { return Math.max(m, s.serie || 0) }, feitas.length) + 1
  var unidade = Engine.normUnit(p.unidade) || plano.unidade
  var rir = Engine.parseNum(p.rir)
  aba_(ABA.registros).appendRow([
    dataDe_(p, d.hoje), local, treino, nome, serie, carga, unidade, Math.round(reps),
    rir == null ? '' : rir, p.obs ? String(p.obs) : 'via Atalhos'
  ])
  return 'Ok: série ' + serie + ' de ' + nome + ' salva, ' + Engine.fmt(carga) + ' ' +
    Engine.unitLabel(unidade, carga) + ' × ' + Math.round(reps) + ' em ' + local + '.'
}

function registrarRefeicao_(p) {
  var col = REFEICAO[Engine.keyOf(p.refeicao || 'outros')] || 6
  var texto = p.texto ? String(p.texto).trim() : ''
  var kcal = Engine.parseNum(p.kcal != null ? p.kcal : p.calorias)
  var prot = Engine.parseNum(p.proteina != null ? p.proteina : p.prot)
  if (!texto && kcal == null && prot == null) throw new Error('informe o que comeu, as calorias ou a proteína.')
  var linha = [dataDe_(p, hoje_()), '', '', '', '', '', '', kcal == null ? '' : kcal, prot == null ? '' : prot]
  linha[col] = texto
  aba_(ABA.diario).appendRow(linha)
  return 'Ok: refeição salva.'
}

function registrarCorpo_(p) {
  var peso = Engine.parseNum(p.peso), sono = Engine.parseNum(p.sono)
  if (peso == null && sono == null) throw new Error('informe o peso ou as horas de sono.')
  aba_(ABA.diario).appendRow([dataDe_(p, hoje_()), '', '', '', '', '', '', '', '', peso == null ? '' : peso, sono == null ? '' : sono])
  return 'Ok: salvo.'
}

// ------------------------------------------------------------------ leitura para a Siri

function resumoProximo_(p) {
  var d = dados_()
  var local = localPedido_(p.local, d.sets)
  var treino = p.treino ? Engine.normTreino(p.treino) : treinoDeHoje_(d, null)
  var contarRir = String(p.rir) !== '0'
  var opts = { countRIR: contarRir }
  var rows = Engine.workoutRows(d.plan, treino, local)
  if (!rows.length) return 'Não há exercícios de ' + treino + ' em ' + local + ' na aba Exercícios.'
  var partes = rows.map(function (r, i) {
    var antes = Engine.splitToday(Engine.sessionsFor(d.sets, r, local, opts), d.hoje).before
    var rx = Engine.nextPrescription(antes, r, opts)
    if (rx.carga == null) return (i + 1) + '. ' + r.exercicio + ': carga a definir, umas ' + rx.reps + ' repetições.'
    return (i + 1) + '. ' + r.exercicio + ': ' + falarCarga_(rx.carga, r.unidade) + ', ' + rx.reps + ' repetições' +
      (contarRir && rx.rir > 0 ? ', deixando ' + rx.rir + ' na reserva' : '') + '.'
  })
  return treino + ' em ' + local + '. ' + partes.join(' ')
}

function resumoAgua_() {
  return 'Hoje: ' + Engine.fmt(aguaDoDia_(hoje_())) + ' litros de água.'
}

// ------------------------------------------------------------------ apoio

function autorizado_(token) {
  var certo = PropertiesService.getScriptProperties().getProperty('TOKEN')
  return !!certo && String(token || '') === certo
}
function texto_(s) { return ContentService.createTextOutput(s).setMimeType(ContentService.MimeType.TEXT) }
function mensagem_(err) { return err && err.message ? err.message : String(err) }
function planilha_() { return SpreadsheetApp.getActiveSpreadsheet() }
function aba_(nome) {
  var a = planilha_().getSheetByName(nome)
  if (!a) throw new Error('a aba "' + nome + '" não existe na planilha.')
  return a
}
function valores_(nome) { return aba_(nome).getDataRange().getValues() }
function hoje_() { return Utilities.formatDate(new Date(), planilha_().getSpreadsheetTimeZone(), 'yyyy-MM-dd') }
function dataDe_(p, hoje) { return Engine.toSerial((p.data && Engine.parseDate(p.data)) || hoje) }
function dados_() {
  return {
    sets: Engine.parseRegistros(valores_(ABA.registros)),
    plan: Engine.parseExercicios(valores_(ABA.exercicios)),
    hoje: hoje_()
  }
}
function aguaDoDia_(iso) {
  var total = 0
  Engine.dailyDiary(Engine.parseDiario(valores_(ABA.diario))).forEach(function (d) { if (d.date === iso && d.agua) total = d.agua })
  return total
}
/** O local pedido, senão o do último treino registrado, senão Campinas. */
function localPedido_(valor, sets) {
  var local = Engine.normLocal(valor)
  if (local === 'Campinas' || local === 'SJC') return local
  var ultimo = null
  sets.forEach(function (s) {
    if (s.baseline || !s.local) return
    if (!ultimo || s.date > ultimo.date || (s.date === ultimo.date && s.row >= ultimo.row)) ultimo = s
  })
  return ultimo ? ultimo.local : 'Campinas'
}
/** O treino em andamento hoje, senão o do exercício no plano, senão o próximo da rotação. */
function treinoDeHoje_(d, row) {
  var hoje = d.sets.filter(function (s) { return s.date === d.hoje && !s.baseline && Engine.ROTATION.indexOf(s.treino) >= 0 })
  if (hoje.length) return hoje.reduce(function (a, b) { return b.row >= a.row ? b : a }).treino
  if (row && Engine.ROTATION.indexOf(row.treino) >= 0) return row.treino
  return Engine.nextWorkout(d.sets)
}
/** Nome falado pela Siri → exercício do plano: igual, depois contido, depois todas as palavras. */
function acharExercicio_(plan, nome, local) {
  var k = Engine.keyOf(nome), palavras = k.split(' ')
  var aqui = plan.filter(function (r) { return r.local === local || r.local === 'Ambos' })
  var testes = [
    function (r) { return r.key === k },
    function (r) { return r.key.indexOf(k) >= 0 },
    function (r) { return palavras.every(function (w) { return r.key.indexOf(w) >= 0 }) }
  ]
  for (var i = 0; i < testes.length; i++) {
    var hit = aqui.filter(testes[i])[0] || plan.filter(testes[i])[0]
    if (hit) return hit
  }
  return null
}
function falarCarga_(n, u) {
  var num = Engine.fmt(n)
  if (u === 'placas') return num + (n === 1 ? ' placa' : ' placas')
  if (u === 'kg/lado') return num + ' quilos por lado'
  return num + ' quilos'
}
