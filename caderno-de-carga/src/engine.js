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

  // ------------------------------------------------------------------ helpers

  var HARD_RIR = 3       // openGym: at or below this a set counts as hard
  var REL_CAP = 15       // above this many effective reps an e1RM says more about endurance
  var DELOAD_AFTER = 3   // openGym's double-progression deload trigger
  var DELOAD = 0.1

  function round2(x) { return Math.round(x * 100) / 100 }
  function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)) }
  /** pt-BR number for copy: 2.5 → "2,5". */
  function fmt(n) { return String(round2(n)).replace('.', ',') }
  function unitLabel(u, n) { return u === 'placas' ? (n === 1 ? 'placa' : 'placas') : u }
  function plus(n, u) { return '+' + fmt(n) + ' ' + unitLabel(u, n) }
  function todayISO() { var d = new Date(); return isoOf(d.getFullYear(), d.getMonth() + 1, d.getDate()) }
  function addDays(iso, n) { return fromSerial(toSerial(iso) + n) }
  function mondayOf(iso) {
    var p = iso.split('-'), d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]))
    return addDays(iso, -((d.getUTCDay() + 6) % 7))
  }
  function isHard(s, countRIR) { return !countRIR || s.rir == null || s.rir <= HARD_RIR }

  // ------------------------------------------------------------------ e1RM & plan

  /** Epley. R = reps até a falha: reps + RIR, só quando o RIR conta. */
  function e1rm(carga, reps, rir, countRIR) {
    if (!(carga > 0) || !(reps >= 1)) return null
    var R = reps + (countRIR && rir > 0 ? rir : 0)
    return { est: round2(R === 1 ? carga : carga * (1 + R / 30)), R: R, reliable: R <= REL_CAP }
  }

  /**
   * The plan row for an exercise at a gym: that gym's own row, else the shared (Ambos) row,
   * else defaults. Equipment differs between the gyms, so another gym's row is never
   * borrowed — only its name and muscle group.
   */
  function planFor(plan, key, local, unitHint) {
    var rows = (plan || []).filter(function (p) { return p.key === key })
    var own = rows.filter(function (p) { return p.local === local })[0]
    var shared = rows.filter(function (p) { return p.local === 'Ambos' })[0]
    if (own || shared) return own || shared
    var unidade = unitHint || DEFAULTS.unidade, any = rows[0]
    var name = any ? any.exercicio : key
    return {
      treino: any ? any.treino : '', ordem: null, exercicio: name, key: key, local: local,
      grupo: any ? any.grupo : DEFAULTS.grupo, unidade: unidade, inc: defaultInc(unidade, name),
      repsMin: DEFAULTS.repsMin, repsMax: DEFAULTS.repsMax, rirAlvo: DEFAULTS.rirAlvo,
      series: DEFAULTS.series, obs: '', synthetic: true
    }
  }

  // ------------------------------------------------------------------ sessions

  function betterTop(a, b) {
    if (a.est != null && b.est != null) return a.est > b.est
    if (a.est != null || b.est != null) return a.est != null
    return a.reps > b.reps
  }

  /**
   * Sessions of one exercise at one gym, oldest first: the day's sets with the top set (best
   * e1RM). An exercise planned as Ambos pools both gyms, since the load means the same there.
   */
  function sessionsFor(sets, row, local, opts) {
    var countRIR = !!(opts && opts.countRIR), shared = row.local === 'Ambos'
    var by = {}, order = []
    ;(sets || []).forEach(function (s) {
      if (s.key !== row.key || (!shared && s.local !== local)) return
      var k = shared ? s.date : s.date + '|' + s.local
      if (!by[k]) { by[k] = { date: s.date, local: s.local, sets: [] }; order.push(k) }
      by[k].sets.push(s)
    })
    var out = order.map(function (k) {
      var g = by[k], top = null, tonnage = 0, hard = 0
      g.sets.forEach(function (s) {
        var e = e1rm(s.carga, s.reps, s.rir, countRIR)
        var cand = {
          carga: s.carga, reps: s.reps, rir: s.rir, row: s.row,
          R: e ? e.R : s.reps, est: e ? e.est : null, reliable: e ? e.reliable : true
        }
        if (!top || betterTop(cand, top)) top = cand
        tonnage += s.carga * s.reps
        if (isHard(s, countRIR)) hard++
      })
      return {
        date: g.date, local: g.local, sets: g.sets, top: top, tonnage: round2(tonnage), hardSets: hard,
        baseline: g.sets.every(function (s) { return s.baseline })
      }
    })
    out.sort(function (a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : (a.top.row || 0) - (b.top.row || 0)
    })
    return out
  }

  /**
   * Sessions in a row without progress, counted back from the latest. Progress is more
   * effective reps at the same load; any load change (up, or a deliberate drop) starts over.
   */
  function stallCount(sessions) {
    var n = 0, load = null, best = null
    ;(sessions || []).forEach(function (s, i) {
      var t = s.top
      if (i === 0 || t.carga !== load) { load = t.carga; best = t.R; n = 0; return }
      if (t.R > best) { best = t.R; n = 0 } else n++
    })
    return n
  }

  /** Expected e1RM gain per session from the recent trend, kept within 0.25–2.5%. */
  function trendGain(sessions) {
    var pts = (sessions || []).filter(function (s) { return s.top && s.top.est != null }).slice(-6)
    if (pts.length < 3) return 0.01
    var n = pts.length, sx = 0, sy = 0, sxy = 0, sxx = 0
    pts.forEach(function (s, i) { var y = s.top.est; sx += i; sy += y; sxy += i * y; sxx += i * i })
    var g = ((n * sxy - sx * sy) / (n * sxx - sx * sx)) / (sy / n)
    return clamp(isFinite(g) ? g : 0.01, 0.0025, 0.025)
  }

  // ------------------------------------------------------------------ prescription

  function rx(kind, carga, reps, rir, row, why, jumpPct) {
    var out = { kind: kind, carga: carga, reps: reps, rir: rir, why: why, jumpPct: jumpPct || 0, backoff: null }
    if (row.series >= 2 && carga > 0 && kind !== 'first' && kind !== 'deload') {
      var cut = Math.max(1, Math.round(carga * DELOAD / row.inc))
      out.backoff = { carga: round2(Math.max(row.inc, carga - cut * row.inc)), reps: Math.min(reps + 2, row.repsMax + 2) }
    }
    return out
  }

  /**
   * Next session for one exercise (heavy double progression, RIR-aware). Load steps are
   * counted from the current load, never snapped to a grid, so odd loads like 33 kg/lado or
   * 102,5 kg stay loadable. Every answer carries `why` in plain Portuguese.
   */
  function nextPrescription(sessions, row, opts) {
    opts = opts || {}
    var countRIR = !!opts.countRIR
    var min = row.repsMin, max = row.repsMax, inc = row.inc, u = row.unidade
    if (!sessions || !sessions.length) {
      return rx('first', null, min + 1, 0, row,
        'Primeira vez aqui: escolha uma carga para ~' + (min + 1) + ' reps. Esta sessão vira a base.')
    }
    var last = sessions[sessions.length - 1].top
    var W = last.carga, R = last.R
    // a target RIR only makes sense where RIR is being logged
    var t = countRIR && last.rir != null ? (row.rirAlvo || 0) : 0
    if (!(W > 0)) return rx('reps', 0, R + 1, t, row, 'Sem carga externa: busque ' + (R + 1) + ' reps.')

    if (R >= max) {
      var g = opts.gain != null ? opts.gain : trendGain(sessions)
      var Eg = last.est * (1 + g)
      var target = Eg / (1 + (min + 1 + t) / 30)
      var W2 = round2(W + Math.max(1, Math.floor((target - W) / inc + 1e-9)) * inc)
      var p = Math.floor(30 * (Eg / W2 - 1) + 1e-9) - t
      var pct = Math.round((W2 - W) / W * 100)
      var top = R > max ? 'Passou do topo da faixa (' + R + ' reps)' : 'Bateu o topo da faixa (' + max + ' reps)'
      if (p >= min) return rx('up', W2, clamp(p, min, max), t, row, top + ' → ' + plus(W2 - W, u) + '.', pct)
      if (R - t < max + 3) {
        return rx('reps', W, R + 1 - t, t, row, 'Subir ' + plus(inc, u) + ' seria +' + pct +
          '% de uma vez: some reps antes e suba ao chegar em ' + (max + 3) + '.', pct)
      }
      return rx('up', W2, min, t, row, top + ' → ' + plus(W2 - W, u) + ' (+' + pct +
        '%). Use rest-pause para fechar ' + min + ' reps.', pct)
    }
    var stalls = stallCount(sessions)
    if (stalls >= DELOAD_AFTER) {
      var Wd = round2(Math.max(inc, W - Math.max(1, Math.round(W * DELOAD / inc)) * inc))
      var pd = clamp(Math.floor(30 * (last.est / Wd - 1) + 1e-9) - t, min, max)
      return rx('deload', Wd, pd, t, row, stalls + ' sessões sem progresso → deload de ' +
        Math.round((W - Wd) / W * 100) + '% e reconstrua a partir daqui.')
    }
    if (R >= min) return rx('hold', W, clamp(R + 1 - t, min, max), t, row, 'Dentro da faixa: mesma carga, +1 rep.')
    return rx('hold', W, min, t, row, 'Abaixo da faixa (' + R + ' reps): mesma carga, busque ' + min + '.')
  }

  /** The rule played forward n sessions, assuming each target is met at the target RIR. */
  function simulate(sessions, row, opts, n) {
    opts = opts || {}
    var countRIR = !!opts.countRIR
    var g = opts.gain != null ? opts.gain : trendGain(sessions)
    var virt = (sessions || []).slice(), out = []
    // projected sessions log RIR only if the real ones do, so the target RIR stays consistent
    var logsRir = countRIR && virt.length > 0 && virt[virt.length - 1].top.rir != null
    for (var i = 1; i <= (n || 6); i++) {
      var r = nextPrescription(virt, row, { countRIR: countRIR, gain: g })
      if (r.kind === 'first' || !(r.carga > 0)) break
      var rir = logsRir ? r.rir : null
      var e = e1rm(r.carga, r.reps, rir, countRIR)
      virt.push({ date: null, local: row.local, sets: [], virtual: true,
        top: { carga: r.carga, reps: r.reps, rir: rir, R: e.R, est: e.est, reliable: e.reliable } })
      out.push({ step: i, kind: r.kind, carga: r.carga, reps: r.reps, rir: rir, est: e.est })
    }
    return out
  }

  function status(sessions) {
    if (!sessions || sessions.length < 2) return 'new'
    var last = sessions[sessions.length - 1].top, best = -Infinity
    for (var i = 0; i < sessions.length - 1; i++) {
      var e = sessions[i].top.est
      if (e != null && e > best) best = e
    }
    if (last.est != null && last.est > best) return 'pr'
    return stallCount(sessions) >= 2 ? 'stalled' : 'ok'
  }

  // ------------------------------------------------------------------ calendar views

  /** Next workout in the rotation after the latest logged day (any gym). */
  function nextWorkout(sets) {
    var last = null
    ;(sets || []).forEach(function (s) {
      if (ROTATION.indexOf(s.treino) < 0) return
      if (!last || s.date > last.date || (s.date === last.date && (s.row || 0) >= (last.row || 0))) last = s
    })
    return last ? ROTATION[(ROTATION.indexOf(last.treino) + 1) % ROTATION.length] : ROTATION[0]
  }

  /**
   * Hard sets per muscle group per week (Monday start), for one gym, newest week last.
   * "Marca inicial" rows are reference points, not training, so they are left out.
   */
  function weeklyVolume(sets, plan, local, opts, weeks) {
    opts = opts || {}
    weeks = weeks || 8
    var countRIR = !!opts.countRIR, end = mondayOf(opts.today || todayISO())
    var list = [], idx = {}
    for (var i = weeks - 1; i >= 0; i--) {
      var start = addDays(end, -7 * i)
      idx[start] = { week: start, start: start, byGroup: {}, total: 0, sets: 0 }
      list.push(idx[start])
    }
    ;(sets || []).forEach(function (s) {
      if (s.baseline || (local && s.local !== local)) return
      var w = idx[mondayOf(s.date)]
      if (!w) return
      w.sets++
      if (!isHard(s, countRIR)) return
      var grupo = planFor(plan, s.key, s.local, s.unidade).grupo || DEFAULTS.grupo
      w.byGroup[grupo] = (w.byGroup[grupo] || 0) + 1
      w.total++
    })
    return list
  }

  var MEALS = ['cafe', 'almoco', 'lanche', 'jantar', 'outros']

  /** One entry per day: water, kcal and protein summed; weight and sleep from the last row. */
  function dailyDiary(rows) {
    var by = {}, keys = []
    ;(rows || []).forEach(function (r) {
      var d = by[r.date]
      if (!d) {
        d = by[r.date] = { date: r.date, agua: null, kcal: null, prot: null, peso: null, sono: null, meals: {}, obs: '' }
        MEALS.forEach(function (m) { d.meals[m] = '' })
        keys.push(r.date)
      }
      if (r.agua != null) d.agua = round2((d.agua || 0) + r.agua)
      if (r.kcal != null) d.kcal = round2((d.kcal || 0) + r.kcal)
      if (r.prot != null) d.prot = round2((d.prot || 0) + r.prot)
      if (r.peso != null) d.peso = r.peso
      if (r.sono != null) d.sono = r.sono
      MEALS.forEach(function (m) { if (r[m]) d.meals[m] = d.meals[m] ? d.meals[m] + ' · ' + r[m] : r[m] })
      if (r.obs) d.obs = d.obs ? d.obs + ' · ' + r.obs : r.obs
    })
    keys.sort()
    return keys.map(function (k) { return by[k] })
  }

  return {
    SCHEMA: SCHEMA, ROTATION: ROTATION, DEFAULTS: DEFAULTS, HARD_RIR: HARD_RIR, MEALS: MEALS,
    keyOf: keyOf, parseNum: parseNum, parseDate: parseDate, toSerial: toSerial, fromSerial: fromSerial,
    normLocal: normLocal, normUnit: normUnit, normTreino: normTreino, defaultInc: defaultInc,
    readTable: readTable, parseRegistros: parseRegistros, parseExercicios: parseExercicios,
    parseDiario: parseDiario,
    e1rm: e1rm, planFor: planFor, sessionsFor: sessionsFor, stallCount: stallCount,
    trendGain: trendGain, nextPrescription: nextPrescription, simulate: simulate, status: status,
    nextWorkout: nextWorkout, weeklyVolume: weeklyVolume, dailyDiary: dailyDiary,
    fmt: fmt, unitLabel: unitLabel, todayISO: todayISO, addDays: addDays, mondayOf: mondayOf
  }
})
