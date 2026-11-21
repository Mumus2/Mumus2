# Caderno de Carga — design

Aprovado em 21/11/2026.

## Intenção

Acompanhar a evolução das cargas num estilo de treino pesado (5–8 reps perto da falha), saber
o que fazer no próximo treino (carga × reps) e enxergar volume, água e alimentação. O treino
acontece em dois locais com máquinas diferentes: **Campinas** e **São José dos Campos (SJC)**.

## Decisões aprovadas

- Na lista de marcas enviada, valores **entre parênteses = SJC**; os demais = Campinas.
- **Fonte da verdade:** planilha Google "Caderno de Carga" no Drive do usuário, editável também
  pelo app Google Planilhas no iPhone.
- **Painel:** artefato no claude.ai que lê e grava na planilha pelo conector Google Sheets do
  próprio usuário (capability `mcp`: `get_values`, `append_values`).
- **Base:** openGym (alexpcosta/opengym, AGPL-3.0). Reaproveita a lógica (dupla progressão,
  1RM de Epley com teto de reps, deload de 10% após 3 estagnações, RIR por série) e a estrutura
  das telas. O código derivado fica sob AGPL-3.0.
- **Tema:** Ethereal (pedido depois da primeira versão, que usava o visual iOS do openGym): pérola e
  névoa de magnésio, vidro fosco, Cormorant Garamond nos títulos, Manrope no resto; Campinas em
  rosa-aurora e SJC em pervinca, nos dois temas (claro e escuro).
- **iOS:** painel no app do Claude ou no Safari (tela de início) + Siri/Atalhos gravando na
  planilha por um Apps Script. Sem app nativo (exige Mac com Xcode).

## Abordagens consideradas

| Abordagem | Prós | Contras |
|---|---|---|
| **Painel claude.ai + planilha via conector (escolhida)** | Dados ao vivo, nada para hospedar, abre no iPhone | Precisa estar logado no claude.ai |
| PWA hospedado (GitHub Pages) + Apps Script como API | Ícone próprio na tela de início, funciona sem claude.ai | Exige publicar script e hospedagem; fica como caminho opcional pelo mesmo Apps Script |
| Só a planilha, com fórmulas e gráficos nativos | Zero código | Projeção em fórmula é frágil; ruim de usar no celular |

## Planilha

- **Registros** — uma linha por série: `Data | Local | Treino | Exercício | Série | Carga | Unidade | Reps | RIR | Obs`.
- **Diário** — `Data | Água (L) | Café da manhã | Almoço | Lanche | Jantar | Outros | Calorias (kcal) | Proteína (g) | Peso (kg) | Sono (h) | Obs`.
  Várias linhas no mesmo dia são somadas (água, kcal, proteína) — permite registrar aos poucos.
- **Exercícios** — plano e parâmetros: `Treino | Ordem | Exercício | Local | Grupo | Unidade | Incremento | Reps mín | Reps máx | RIR alvo | Séries | Obs`.
  `Local` = Campinas, SJC ou **Ambos** (mesmo equipamento, ex.: halter e barra → histórico compartilhado).
- **Como usar** — instruções.
- Unidades: `kg`, `kg/lado`, `placas`. Locale pt_BR, fuso America/Sao_Paulo. Datas gravadas pelo
  painel como número de série de data (independe do modo de entrada da API).

## Motor de projeção (`engine.js`, funções puras, testado)

- Sessão = (data, local efetivo, exercício). Top set = série de maior e1RM.
- e1RM (Epley): `W·(1 + R/30)`, com `R = reps + RIR` quando "Contar RIR" está ligado (RIR vazio = 0,
  falha). Acima de 15 reps efetivas a estimativa é marcada como pouco confiável.
- Próxima sessão (faixa `[mín, máx]`, RIR alvo `t`, incremento `i`, ganho esperado `g`):
  - `R ≥ máx` → sobe carga. Alvo `W* = E(1+g) / (1 + (mín+1+t)/30)`; passos = `max(1, ⌊(W*−W)/i⌋)`;
    `W' = W + passos·i`; reps previstas = `clamp(⌊30(E(1+g)/W' − 1)⌋ − t, mín, máx)`.
    Se as reps previstas ficarem abaixo de `mín` (incremento grande demais, comum em placas),
    mantém `W` e pede `R+1` (até `máx+2`).
  - `mín ≤ R < máx` → mantém `W`, reps = `clamp(R + 1 − t, mín, máx)`.
  - `R < mín` → mantém `W`, reps = `mín`.
  - 3 sessões seguidas sem superar o melhor e1RM → deload de 10% (no mínimo 1 passo).
  - Sem histórico no local → "primeira vez: esta sessão vira a base".
  - Back-off (se séries ≥ 2): `W'·0,9` mirando reps + 2.
  - Toda sugestão traz o motivo em texto.
- Projeção futura: simula a regra por 6 sessões; `g` = tendência do histórico limitada a
  0,25–2,5% por sessão (padrão 1%).
- Volume semanal: séries duras (RIR ≤ 3) por grupo muscular; tonelagem por exercício na própria unidade.

## Painel

- Cabeçalho: seletor **Campinas | SJC** (troca a cor de destaque), interruptor **Contar RIR**,
  status da sincronização e link para a planilha.
- **Treino:** próximo treino pela rotação Upper A → Lower A → Upper B → Lower B. Cada exercício mostra
  última marca, sugestão com motivo, mini-gráfico e formulário de registro (grava na planilha).
- **Evolução:** gráfico de e1RM com projeção tracejada e tabela das próximas sessões.
- **Volume:** barras semanais de séries duras por grupo.
- **Diário:** água vs meta, proteína, peso, refeições; botões +250/+500 ml.
- Falhas do conector tratadas por código; sem conector, mostra o instantâneo inicial identificado como tal.

## Não-objetivos

- App nativo iOS; integração com Apple Saúde além da automação de água por Atalhos;
  cálculo automático de calorias das refeições.

## Deixado para o construtor

- Incrementos de cada máquina (palpites editáveis na aba Exercícios), séries planejadas (padrão 2),
  RIR alvo (0 em todos, combinando com treino até a falha; 1–2 fica disponível por exercício na planilha), cores e layout fino.
