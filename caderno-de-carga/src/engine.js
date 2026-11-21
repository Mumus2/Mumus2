/*
 * Caderno de Carga — motor de progressão e projeção.
 *
 * Funções puras: tudo é derivado das linhas da planilha cada vez que é preciso, nada é
 * guardado. Corrigir uma linha na planilha corrige a próxima sugestão na hora.
 *
 * A lógica segue o openGym (alexpcosta/opengym, AGPL-3.0): dupla progressão, 1RM por Epley,
 * deload de 10% após 3 sessões sem progresso e RIR por série. Este arquivo é derivado dele e
 * é distribuído sob a mesma licença (AGPL-3.0-or-later).
 *
 * Roda em três lugares sem mudança: inline na página do artefato (window.Engine), no Node
 * para os testes (module.exports) e no Google Apps Script (Engine global). Por isso evita
 * sintaxe recente demais (?. ?? Array#at).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory()
  else root.Engine = factory()
})(this, function () {
  'use strict'

  // ------------------------------------------------------------------ schema

  var SCHEMA = {
    registros: ['Data', 'Local', 'Treino', 'Exercício', 'Série', 'Carga', 'Unidade', 'Reps', 'RIR', 'Obs'],
    diario: ['Data', 'Água (L)', 'Café da manhã', 'Almoço', 'Lanche', 'Jantar', 'Outros',
      'Calorias (kcal)', 'Proteína (g)', 'Peso (kg)', 'Sono (h)', 'Obs'],
    exercicios: ['Treino', 'Ordem', 'Exercício', 'Local', 'Grupo', 'Unidade', 'Incremento',
      'Reps mín', 'Reps máx', 'RIR alvo', 'Séries', 'Obs']
  }

  // Field names per tab, in the same order as SCHEMA (used when a tab has no header row),
  // each with the header spellings it answers to after normalization.
  var FIELDS = {
    registros: [
      ['date', ['data', 'dia', 'date']],
      ['local', ['local', 'academia', 'cidade', 'gym']],
      ['treino', ['treino', 'divisao', 'workout']],
      ['exercicio', ['exercicio', 'exercise', 'movimento']],
      ['serie', ['serie', 'set']],
      ['carga', ['carga', 'peso', 'load']],
      ['unidade', ['unidade', 'unid', 'unit']],
      ['reps', ['reps', 'repeticoes', 'rep']],
      ['rir', ['rir', 'reserva', 'reps em reserva']],
      ['obs', ['obs', 'observacao', 'observacoes', 'notas', 'nota']]
    ],
    diario: [
      ['date', ['data', 'dia']],
      ['agua', ['agua', 'water']],
      ['cafe', ['cafe da manha', 'cafe']],
      ['almoco', ['almoco']],
      ['lanche', ['lanche', 'pre-treino', 'pre treino']],
      ['jantar', ['jantar']],
      ['outros', ['outros', 'ceia', 'extras']],
      ['kcal', ['calorias', 'kcal']],
      ['prot', ['proteina', 'prot']],
      ['peso', ['peso', 'peso corporal']],
      ['sono', ['sono']],
      ['obs', ['obs', 'observacao', 'observacoes', 'notas']]
    ],
    exercicios: [
      ['treino', ['treino']],
      ['ordem', ['ordem', '#']],
      ['exercicio', ['exercicio']],
      ['local', ['local']],
      ['grupo', ['grupo', 'grupo muscular', 'musculo']],
      ['unidade', ['unidade', 'unid']],
      ['inc', ['incremento', 'inc', 'passo']],
      ['repsMin', ['reps min', 'reps minimas', 'min']],
      ['repsMax', ['reps max', 'reps maximas', 'max']],
      ['rirAlvo', ['rir alvo', 'rir']],
      ['series', ['series', 'sets']],
      ['obs', ['obs', 'observacao', 'observacoes', 'notas']]
    ]
  }

  var ROTATION = ['Upper A', 'Lower A', 'Upper B', 'Lower B']

  // ------------------------------------------------------------------ text

  function strip(s) { return String(s).normalize('NFD').replace(/[̀-ͯ]/g, '') }

  /** Matching key for names typed by hand: no case, accents or repeated spaces. */
  function keyOf(name) {
    return strip(name == null ? '' : name).toLowerCase().replace(/\s+/g, ' ').trim()
  }
  function headerKey(h) { return keyOf(String(h == null ? '' : h).replace(/\(.*?\)/g, ' ')) }
  function text(v) { return v == null ? '' : String(v).trim() }

  // ------------------------------------------------------------------ numbers & dates

  /**
   * Numbers as the sheet shows them in pt-BR ("102,5", "1.234,5") or as plain numbers.
   * Letters are dropped, so "32kg" or "6 rep" still read.
   */
  function parseNum(v) {
    if (v == null) return null
    if (typeof v === 'number') return isFinite(v) ? v : null
    var s = String(v).replace(/\s/g, '').replace(/[^\d,.\-]/g, '')
    if (!/\d/.test(s)) return null
    var comma = s.lastIndexOf(','), dot = s.lastIndexOf('.')
    if (comma >= 0 && dot >= 0) {
      // whichever separator comes last is the decimal one
      s = comma > dot ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '')
    } else if (comma >= 0) {
      s = s.replace(',', '.')
    }
    var n = Number(s)
    return isFinite(n) ? n : null
  }

  var EPOCH = Date.UTC(1899, 11, 30)   // Google Sheets day 0
  var DAY = 86400000
  function pad(n) { return (n < 10 ? '0' : '') + n }
  function isoOf(y, m, d) { return y + '-' + pad(m) + '-' + pad(d) }
  function validYMD(y, m, d) {
    var dt = new Date(Date.UTC(y, m - 1, d))
    return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d
  }
  function fromSerial(n) {
    var dt = new Date(EPOCH + Math.floor(n) * DAY)
    return isoOf(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate())
  }
  function toSerial(iso) {
    var p = String(iso).split('-')
    return Math.round((Date.UTC(+p[0], +p[1] - 1, +p[2]) - EPOCH) / DAY)
  }

  /** dd/mm/aaaa, dd/mm/aa, dd/mm (ano atual), aaaa-mm-dd, número de série ou Date → ISO. */
  function parseDate(v) {
    if (v == null || v === '') return null
    if (Object.prototype.toString.call(v) === '[object Date]') {
      return isNaN(v) ? null : isoOf(v.getFullYear(), v.getMonth() + 1, v.getDate())
    }
    if (typeof v === 'number') return v > 20000 && v < 100000 ? fromSerial(v) : null
    var s = String(v).trim(), m, y, mo, d
    if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/))) { y = +m[1]; mo = +m[2]; d = +m[3] }
    else if ((m = s.match(/^(\d{1,2})\/(\d{1,2})(?:\/(\d{2}|\d{4}))?$/))) {
      d = +m[1]; mo = +m[2]
      y = m[3] ? +m[3] : new Date().getFullYear()
      if (y < 100) y += 2000
    }
    else if (/^\d{5}(\.\d+)?$/.test(s)) return fromSerial(+s)
    else return null
    return validYMD(y, mo, d) ? isoOf(y, mo, d) : null
  }

  // ------------------------------------------------------------------ vocab

  function normLocal(v) {
    var k = keyOf(v).replace(/\./g, '')
    if (!k) return null
    if (k === 'sjc' || k === 'sj' || k.indexOf('sao jose') === 0) return 'SJC'
    if (k.indexOf('campinas') === 0 || k === 'cps') return 'Campinas'
    if (k === 'ambos' || k === 'os dois' || k === 'todos') return 'Ambos'
    return null
  }

  function normUnit(v) {
    var k = keyOf(v)
    if (!k) return null
    if (/^pl/.test(k)) return 'placas'
    if (/lado|side/.test(k)) return 'kg/lado'
    if (/^(kg|quilo|kilo)/.test(k)) return 'kg'
    return null
  }

  function normTreino(v) {
    var k = keyOf(v), m = k.match(/^(upper|lower)\s*([ab])$/)
    if (m) return (m[1] === 'upper' ? 'Upper ' : 'Lower ') + m[2].toUpperCase()
    return text(v)
  }

  // ------------------------------------------------------------------ tables

  /**
   * Rows of a tab as objects keyed by field name. Columns are found by header text, so the
   * user can reorder or add columns; a tab without a recognisable header row is read in the
   * default column order. `row` is the 1-based sheet row (the range is read from A1).
   */
  function readTable(values, table) {
    var fields = FIELDS[table]
    var rows = values || []
    var head = (rows[0] || []).map(headerKey)
    var idx = {}, used = {}, hits = 0
    // exact header matches first, then prefixes, never giving one column to two fields
    fields.forEach(function (f) {
      for (var i = 0; i < head.length; i++) {
        if (!used[i] && f[1].indexOf(head[i]) >= 0) { idx[f[0]] = i; used[i] = true; hits++; return }
      }
    })
    fields.forEach(function (f) {
      if (idx[f[0]] != null) return
      for (var i = 0; i < head.length; i++) {
        if (used[i] || !head[i]) continue
        for (var j = 0; j < f[1].length; j++) {
          if (f[1][j].length >= 3 && head[i].indexOf(f[1][j]) === 0) { idx[f[0]] = i; used[i] = true; return }
        }
      }
    })
    var hasHeader = hits >= 2
    if (!hasHeader) { idx = {}; fields.forEach(function (f, i) { idx[f[0]] = i }) }
    var out = []
    for (var r = hasHeader ? 1 : 0; r < rows.length; r++) {
      var src = rows[r] || [], o = { row: r + 1 }
      fields.forEach(function (f) { o[f[0]] = idx[f[0]] == null ? '' : src[idx[f[0]]] })
      out.push(o)
    }
    return out
  }

  /** Registros: one logged set per row. Rows missing a date, exercise, load or reps are skipped. */
  function parseRegistros(values) {
    var out = []
    readTable(values, 'registros').forEach(function (r) {
      var exercicio = text(r.exercicio), reps = parseNum(r.reps), carga = parseNum(r.carga)
      var date = parseDate(r.date)
      if (!exercicio || !date || carga == null || reps == null || reps < 1) return
      var obs = text(r.obs)
      out.push({
        row: r.row, date: date, local: normLocal(r.local), treino: normTreino(r.treino),
        exercicio: exercicio, key: keyOf(exercicio), serie: parseNum(r.serie),
        carga: carga, unidade: normUnit(r.unidade), reps: reps, rir: parseNum(r.rir),
        obs: obs, baseline: /marca inicial/i.test(obs)
      })
    })
    return out
  }

  var DEFAULTS = { repsMin: 5, repsMax: 8, rirAlvo: 0, series: 2, grupo: 'Outros', unidade: 'kg' }

  function defaultInc(unidade, exercicio) {
    if (unidade === 'placas') return 1
    if (unidade === 'kg' && /halter/.test(keyOf(exercicio))) return 2
    return 2.5
  }

  /** Exercícios: the plan, one row per (treino, exercício, local), with defaults filled in. */
  function parseExercicios(values) {
    var out = []
    readTable(values, 'exercicios').forEach(function (r) {
      var exercicio = text(r.exercicio)
      if (!exercicio) return
      var unidade = normUnit(r.unidade) || DEFAULTS.unidade
      var lo = parseNum(r.repsMin), hi = parseNum(r.repsMax)
      if (lo == null) lo = DEFAULTS.repsMin
      if (hi == null) hi = Math.max(lo, DEFAULTS.repsMax)
      if (lo > hi) { var tmp = lo; lo = hi; hi = tmp }
      var inc = parseNum(r.inc)
      var rir = parseNum(r.rirAlvo), series = parseNum(r.series)
      out.push({
        row: r.row, treino: normTreino(r.treino), ordem: parseNum(r.ordem),
        exercicio: exercicio, key: keyOf(exercicio), local: normLocal(r.local) || 'Ambos',
        grupo: text(r.grupo) || DEFAULTS.grupo, unidade: unidade,
        inc: inc > 0 ? inc : defaultInc(unidade, exercicio),
        repsMin: lo, repsMax: hi, rirAlvo: rir == null ? DEFAULTS.rirAlvo : rir,
        series: series > 0 ? series : DEFAULTS.series, obs: text(r.obs)
      })
    })
    return out
  }

  /** Diário: water, meals and body data. Water above 20 is read as millilitres. */
  function parseDiario(values) {
    var out = []
    readTable(values, 'diario').forEach(function (r) {
      var date = parseDate(r.date)
      if (!date) return
      var agua = parseNum(r.agua)
      if (agua != null && agua > 20) agua = agua / 1000
      out.push({
        row: r.row, date: date, agua: agua,
        cafe: text(r.cafe), almoco: text(r.almoco), lanche: text(r.lanche),
        jantar: text(r.jantar), outros: text(r.outros),
        kcal: parseNum(r.kcal), prot: parseNum(r.prot), peso: parseNum(r.peso),
        sono: parseNum(r.sono), obs: text(r.obs)
      })
    })
    return out
  }

  return {
    SCHEMA: SCHEMA, ROTATION: ROTATION, DEFAULTS: DEFAULTS,
    keyOf: keyOf, parseNum: parseNum, parseDate: parseDate, toSerial: toSerial, fromSerial: fromSerial,
    normLocal: normLocal, normUnit: normUnit, normTreino: normTreino, defaultInc: defaultInc,
    readTable: readTable, parseRegistros: parseRegistros, parseExercicios: parseExercicios,
    parseDiario: parseDiario
  }
})
