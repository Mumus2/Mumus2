import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'

const root = new URL('..', import.meta.url).pathname

test('build injects the engine, sheet id and snapshot into the page', () => {
  const dir = mkdtempSync(join(tmpdir(), 'cdc-'))
  const config = join(dir, 'local.json')
  writeFileSync(config, JSON.stringify({
    sheetId: 'SHEET123', seedDate: '2026-11-21',
    marks: [['SJC', 'Lower B', 'Hip thrust', 40, 'kg', 10, 3, 'bem de boa']]
  }))
  const out = join(dir, 'page.html')
  const gs = join(dir, 'Engine.gs')
  execFileSync('node', [join(root, 'scripts/build.mjs'), '--config', config, '--out', out, '--gs', gs])
  const html = readFileSync(out, 'utf8')
  assert.match(html, /<title>Caderno de Carga<\/title>/)
  assert.match(html, /parseRegistros/)
  assert.match(html, /SHEET123/)
  assert.doesNotMatch(html, /__SHEET_ID__/)
  assert.doesNotMatch(html, /\/\*@ENGINE\*\//)
  assert.doesNotMatch(html, /<html|<body|<!doctype/i)
  const snap = JSON.parse(html.match(/const SNAPSHOT = (.*?);\n/)[1])
  assert.equal(snap.date, '2026-11-21')
  assert.equal(snap.registros.length, 2)
  assert.deepEqual(snap.registros[1].slice(1, 4), ['SJC', 'Lower B', 'Hip thrust'])
  assert.equal(snap.registros[1][9], 'marca inicial · bem de boa')
  assert.ok(snap.exercicios.length > 40)
  const engine = readFileSync(join(root, 'src/engine.js'), 'utf8')
  const gsText = readFileSync(gs, 'utf8')
  assert.ok(gsText.endsWith(engine))
  assert.match(gsText, /^\/\/ Gerado por scripts\/build\.mjs/)
})

test('build without marks still produces a page with an empty snapshot log', () => {
  const dir = mkdtempSync(join(tmpdir(), 'cdc-'))
  const config = join(dir, 'local.json')
  writeFileSync(config, JSON.stringify({ sheetId: '' }))
  const out = join(dir, 'page.html')
  execFileSync('node', [join(root, 'scripts/build.mjs'), '--config', config, '--out', out, '--gs', join(dir, 'E.gs')])
  const snap = JSON.parse(readFileSync(out, 'utf8').match(/const SNAPSHOT = (.*?);\n/)[1])
  assert.equal(snap.registros.length, 1)
})
