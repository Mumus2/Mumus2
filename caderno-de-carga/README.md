# Caderno de Carga

Caderno de treino pesado (5–8 reps perto da falha) ligado a uma planilha do Google. Ele mostra a carga e as reps sugeridas para o próximo treino, a evolução do 1RM estimado com projeção, o volume semanal e o diário de água e alimentação. Cada academia tem a sua progressão (Campinas e São José dos Campos), porque as máquinas são diferentes.

Feito com base no [openGym](https://github.com/alexpcosta/opengym), de onde vêm a lógica de dupla progressão, o 1RM de Epley, o deload após estagnação, o RIR por série e a estrutura das telas. O visual é o tema Ethereal: fundo pérola com névoa de magnésio (pêssego, lavanda e verde-água; aurora violeta à noite), cartões de vidro fosco, títulos em Cormorant Garamond e números em Manrope. Por isso o código desta pasta é distribuído sob a mesma licença, AGPL-3.0 (veja [LICENSE](LICENSE)).

## Como funciona

```
 iPhone / computador
   ├─ Painel (artefato no claude.ai) ──conector Google Sheets──┐
   ├─ App Google Planilhas ────────────────────────────────────┤
   └─ Atalhos / Siri ──── Apps Script (Code.gs + Engine.gs) ───┤
                                                               ▼
                                      Planilha "Caderno de Carga"
                                      Registros · Diário · Exercícios · Como usar
```

- **A planilha é a fonte da verdade.** Uma linha por série em Registros; água, refeições, peso e sono em Diário; o plano e as regras de cada exercício em Exercícios.
- **O painel** (`src/app.html`) lê e grava na planilha com o conector Google Sheets da sua conta no claude.ai. Nada fica guardado no painel.
- **O motor** (`src/engine.js`) faz todas as contas e é o mesmo arquivo no painel, nos testes e no Apps Script.

## A regra de progressão

Para cada exercício em cada local:

1. **1RM estimado (Epley):** `1RM = carga × (1 + R/30)`, com `R = reps + RIR` quando "Contar RIR" está ligado. RIR vazio conta como 0 (falha).
2. **Dentro da faixa** (padrão 5 a 8): mesma carga, `R + 1 − RIR alvo` reps.
3. **No topo da faixa:** a carga sobe. O alvo vem do 1RM com um ganho esperado `g` por sessão:
   `carga* = 1RM·(1+g) / (1 + (mín + 1 + RIR alvo)/30)`. A carga sobe pelo menos um incremento, contado a partir da carga atual.
   As reps previstas na carga nova são `⌊30·(1RM·(1+g)/carga − 1)⌋ − RIR alvo`.
4. **Incremento grande demais** (comum em placas: 3 → 4 placas é +33%): se as reps previstas ficam abaixo do mínimo, primeiro soma reps até `máx + 3` e só então sobe, com rest-pause.
5. **Três sessões seguidas sem progresso** (sem mais reps na mesma carga): deload de 10%, no mínimo um incremento.
6. **Ganho esperado `g`:** a inclinação da reta dos últimos 6 1RMs dividida pela média, limitada a 0,25%–2,5% por sessão. Com menos de 3 sessões, 1%.
7. **Projeção:** a regra é repetida por 6 sessões, supondo que cada alvo é cumprido.

Exemplo: 40 kg × 10 com RIR 3 e faixa 5–8 dá `R = 13` e 1RM ≈ 57,3 kg. A sugestão sobe para 45 kg × 8.

## Estrutura

| Caminho | O que é |
|---|---|
| `src/engine.js` | Motor: leitura da planilha (pt-BR), sessões, 1RM, sugestão, projeção, volume, diário |
| `src/app.html` | Página do painel (sem `<html>`/`<body>`; o claude.ai monta o resto) |
| `src/plano.json` | Plano padrão por treino e local, sem cargas |
| `scripts/build.mjs` | Injeta o motor, o ID da planilha e o instantâneo inicial na página; gera `apps-script/Engine.gs` |
| `apps-script/Code.gs` | Ponte para Atalhos e Siri (água, série, refeição, próximo treino) |
| `docs/IOS.md` | Passo a passo do iPhone |
| `test/` | Testes do motor, do build e do Apps Script (`node --test`) |

## Desenvolvimento

Precisa de Node 20 ou mais novo, sem dependências.

```bash
npm test
```

```bash
node scripts/build.mjs --config local.json --out dist/caderno-de-carga.html
```

`local.json` fica fora do git, porque tem as suas marcas:

```json
{
  "sheetId": "ID da planilha (o trecho entre /d/ e /edit no link)",
  "seedDate": "2026-11-20",
  "marks": [["Campinas", "Upper A", "Supino inclinado com halter", 32, "kg", 6, ""]]
}
```

Cada marca é `[local, treino, exercício, carga, unidade, reps, RIR, nota]`. Elas viram o instantâneo que o painel mostra enquanto a planilha não responde. Depois de mudar `src/engine.js`, rode o build de novo para atualizar `apps-script/Engine.gs` (um teste avisa se esquecer).

## Licença

AGPL-3.0-or-later. Derivado do openGym, © 2026 Duarte Santos, na versão de alexpcosta/opengym.
