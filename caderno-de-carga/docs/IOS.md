# Caderno de Carga no iPhone

Há três formas de usar no iPhone. A primeira não exige nada; as outras duas levam uns 10 minutos, uma vez só.

| Forma | Para quê | Configuração |
|---|---|---|
| Painel no app do Claude ou no Safari | Ver a sugestão do dia, gráficos e registrar séries com a carga já preenchida | Nenhuma |
| App Google Planilhas | Corrigir ou digitar linhas direto na planilha | Nenhuma |
| Atalhos e Siri | "E aí Siri, registrar água", "registrar série", "próximo treino" | Apps Script + atalhos (abaixo) |

Um app nativo (como o build iOS do openGym com Capacitor) exige um Mac com Xcode, por isso não faz parte deste projeto.

## 1. Painel na tela de início

1. No iPhone, abra o link do painel no Safari, já logado no claude.ai.
2. Toque em Compartilhar e depois em **Adicionar à Tela de Início**.

O painel também aparece no app do Claude. Se lá ele mostrar "Sem acesso à planilha nesta tela", use o Safari: o painel lê a planilha pelo conector Google Sheets da sua conta no claude.ai.

## 2. Ligar a planilha aos Atalhos (uma vez, pelo computador)

1. Abra a planilha **Caderno de Carga** e vá em **Extensões > Apps Script**.
2. Apague o conteúdo de `Code.gs` e cole o arquivo [`apps-script/Code.gs`](../apps-script/Code.gs).
3. Clique em **+ > Script**, dê o nome `Engine` e cole [`apps-script/Engine.gs`](../apps-script/Engine.gs) inteiro. É o mesmo motor de cálculo do painel.
4. Salve. No menu de funções, escolha `configurarToken` e clique em **Executar**. Autorize com a sua conta do Google.
5. Abra o **Registro de execução** e copie o token (uma sequência de 32 letras e números).
6. Clique em **Implantar > Nova implantação**, tipo **App da Web**:
   - Executar como: **Eu**
   - Quem pode acessar: **Qualquer pessoa**
7. Clique em **Implantar** e copie a **URL do app da Web** (termina em `/exec`).

"Qualquer pessoa" é necessário para os Atalhos chamarem o script sem login do Google. O que protege a planilha é o token: sem ele o script responde "token inválido" e não lê nem grava nada. Guarde a URL e o token só nos seus atalhos. Para trocar o token, rode `configurarToken` de novo e atualize os atalhos.

Quando atualizar `Code.gs` ou `Engine.gs`, use **Implantar > Gerenciar implantações > editar > Nova versão** para manter a mesma URL.

## 3. Atalhos

No app **Atalhos**, crie um atalho novo para cada item abaixo. O nome do atalho é o que você fala para a Siri. Em **Obter Conteúdo da URL**, toque em "Mostrar Mais", escolha o método e, para POST, **Corpo da Solicitação: JSON**.

### Registrar água

1. **Pedir Entrada**, tipo Número, pergunta "Quantos ml?".
2. **Obter Conteúdo da URL**: a sua URL `/exec`, método **POST**, corpo JSON com os campos:
   - `token` (Texto): o seu token
   - `tipo` (Texto): `agua`
   - `ml` (Número): Entrada Fornecida
3. **Mostrar Notificação** com o Conteúdo da URL. A resposta é algo como "Ok: 500 ml de água salvos. 2,5 L hoje."

### Registrar série

1. **Escolher do Menu** com as opções `Campinas` e `SJC` (ou fixe o local em um atalho por academia).
2. **Pedir Entrada**, Texto: "Exercício?". Pode falar só parte do nome, como "supino inclinado": o script procura no plano.
3. **Pedir Entrada**, Número: "Carga?". Depois "Reps?" e, se quiser, "RIR?".
4. **Obter Conteúdo da URL**, método **POST**, corpo JSON:
   - `token`, `tipo` = `serie`
   - `local`, `exercicio`, `carga`, `reps`, `rir` com as respostas acima
5. **Mostrar Notificação** com o Conteúdo da URL.

O script completa o resto: data de hoje, treino do dia, número da série e unidade do plano.

### Próximo treino (a Siri lê)

1. **Texto**: `SUA_URL?token=SEU_TOKEN&acao=proximo&local=Campinas`
2. **Obter Conteúdo da URL** (método GET) com esse texto.
3. **Falar Texto** com o Conteúdo da URL.

A Siri lê algo como "Upper A em Campinas. 1. Supino inclinado com halter: 32 quilos, 7 repetições…". Opções: `&treino=Upper%20B` escolhe o treino e `&rir=0` ignora o RIR nos cálculos.

### Refeição, peso e sono

Mesmo formato do atalho de água, com `tipo` e os campos:

- `refeicao`: `refeicao` (cafe, almoco, lanche, jantar ou outros), `texto` e, se quiser, `kcal` e `proteina`
- `corpo`: `peso` e/ou `sono`

### Água do app Saúde (automação)

Se você já registra água no app Saúde, ele pode mandar o total do dia para a planilha:

1. Em **Automação**, crie uma automação pessoal de **Hora do Dia**, por exemplo 22:30, para rodar sem perguntar.
2. **Encontrar Amostras de Saúde** onde o tipo é Água e a data de início é hoje.
3. **Calcular Estatísticas**: Soma das amostras, em ml.
4. **Obter Conteúdo da URL**, POST com `token`, `tipo` = `agua` e `ml` = a soma.

Use uma fonte só para a água (Saúde ou os botões do painel), senão o dia conta em dobro.
