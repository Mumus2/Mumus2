#!/usr/bin/env node
// Monta a página publicada a partir de src/app.html:
//   /*@ENGINE*/          → src/engine.js inteiro
//   __SHEET_ID__         → ID da planilha (de local.json)
//   /*@SNAPSHOT*/null    → instantâneo inicial (plano + marcas), usado até a planilha responder
// e gera apps-script/Engine.gs, o mesmo motor para colar no Apps Script.
//
// Uso: node scripts/build.mjs --config local.json --out dist/caderno-de-carga.html [--gs apps-script/Engine.gs]
// local.json fica fora do git (as marcas são dados pessoais); veja README.md.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const args = {}
process.argv.slice(2).forEach((a, i, all) => { if (a.startsWith('--')) args[a.slice(2)] = all[i + 1] })

const config = args.config ? JSON.parse(readFileSync(resolve(args.config), 'utf8')) : {}
const out = resolve(args.out || join(root, 'dist/caderno-de-carga.html'))
const gsOut = resolve(args.gs || join(root, 'apps-script/Engine.gs'))

const Engine = createRequire(import.meta.url)(join(root, 'src/engine.js'))
const engineSrc = readFileSync(join(root, 'src/engine.js'), 'utf8')
const plano = JSON.parse(readFileSync(join(root, 'src/plano.json'), 'utf8'))

const date = config.seedDate || Engine.todayISO()
const serial = Engine.toSerial(date)
// a mark is [local, treino, exercício, carga, unidade, reps, rir?, nota?]
const marks = (config.marks || []).map(m => [
  serial, m[0], m[1], m[2], 1, m[3], m[4], m[5], m[6] == null ? '' : m[6],
  m[7] ? 'marca inicial · ' + m[7] : 'marca inicial'
])
const snapshot = {
  date,
  registros: [Engine.SCHEMA.registros, ...marks],
  exercicios: [Engine.SCHEMA.exercicios, ...plano],
  diario: [Engine.SCHEMA.diario]
}

const page = readFileSync(join(root, 'src/app.html'), 'utf8')
  .replace('/*@ENGINE*/', () => engineSrc)
  .replace(/__SHEET_ID__/g, () => config.sheetId || '')
  .replace('/*@SNAPSHOT*/null', () => JSON.stringify(snapshot))

mkdirSync(dirname(out), { recursive: true })
writeFileSync(out, page)
mkdirSync(dirname(gsOut), { recursive: true })
writeFileSync(gsOut, '// Gerado por scripts/build.mjs a partir de src/engine.js. Não edite aqui: ' +
  'cole este arquivo inteiro no Apps Script.\n' + engineSrc)
console.log('página:', out, '(' + Math.round(page.length / 1024) + ' KB) · Engine.gs:', gsOut)
