# Canal "Clipou!": identidade e passo a passo

| Arquivo | Uso | Tamanho |
|---|---|---|
| `banner.png` | Banner do canal | 2560x1440. O texto fica na área segura de 1546x423, que é a única parte visível no celular |
| `avatar.png` | Foto de perfil | 800x800, com o desenho centralizado para o recorte redondo |
| `watermark.png` | Marca d'água nos vídeos (botão de inscrever) | 150x150, fundo transparente |
| `canal.yaml` | Nome, @, descrição e palavras-chave | — |
| `*.html` + `render.js` | Fontes das artes. Para editar: mude o HTML e rode `node branding/render.js` | — |

Fontes: Anton e Bebas Neue, licença OFL (uso comercial livre). Todas as artes são originais.
Não usei o logo, a fonte nem as artes oficiais do GTA 6. Usar isso no canal é pedir problema
com a Rockstar/Take-Two.

## Por que esse nome e esse visual

Os canais de cortes grandes do Brasil seguem alguns padrões:
- **Nome curto, falado e fácil de lembrar.** "Clipou!" é o que o chat grita quando acontece algo.
- **Um @ que não depende de um jogo só.** `@ClipouBR` continua servindo depois da fase do GTA 6
  (dá para cobrir outros jogos e streamers). Só o nome de exibição cita GTA 6, e ele muda quando você quiser.
- **Visual de alto contraste, reconhecível em miniatura.** A estética neon/pôr do sol combina com o
  clima de Miami/Vice City do jogo sem copiar nenhuma marca.
- **Crédito sempre visível.** Nome do streamer e `twitch.tv/canal` em todo vídeo. É isso que faz
  streamer apoiar o canal em vez de derrubar.

Outros nomes, caso o @ esteja ocupado: **Corte Seco BR**, **Plantão dos Cortes**,
**Leonida Cortes**, **Vice Cortes BR**. Confira a disponibilidade quando for criar o @.

## Passo a passo: conta, canal e integração

Essa parte precisa ser feita por você. Criar a conta exige verificação por telefone, e a conta
(com a senha e o 2FA) tem que ser sua: é para ela que o dinheiro do canal vai.

1. **Conta Google nova** em <https://accounts.google.com/signup>, só para o canal.
   Ative a **verificação em 2 etapas** logo de cara: o Programa de Parcerias exige.
2. **Canal**: entre em <https://youtube.com>, clique na foto → **Criar um canal** e use o nome
   `Clipou! • Cortes de GTA 6`. Se quiser adicionar editores depois, crie como *conta de marca*
   ("usar um nome personalizado").
3. **Verifique o telefone** em <https://www.youtube.com/verify>. Isso libera miniaturas
   personalizadas e vídeos com mais de 15 min (as compilações).
4. **YouTube Studio → Personalização**:
   - *Marca*: foto = `avatar.png`, banner = `banner.png`, marca d'água = `watermark.png`
   - *Informações básicas*: identificador `@ClipouBR`. A descrição e os links o robô aplica no passo 6.
5. **Integração com o robô**: siga a seção "Credenciais do YouTube" do README principal
   (projeto no Google Cloud **logado nessa mesma conta**, depois `python -m clipador youtube-auth`).
   Se você já tinha autorizado antes, rode de novo: agora o robô também pede permissão para editar o canal.
6. `python -m clipador brand`: aplica descrição, palavras-chave, país (Brasil), idioma e banner.
7. Troque `COLOQUE-SEU-EMAIL-DE-CONTATO` no `canal.yaml` por um e-mail de contato real antes do passo 6.

## Monetização: o que o canal precisa

Os requisitos abaixo são os que eu conheço. Confira os valores atuais em
**YouTube Studio → Ganhar dinheiro**, porque o YouTube muda isso de tempos em tempos.

- **Para entrar no Programa de Parcerias (receita de anúncios)**: 1.000 inscritos e
  **4.000 horas assistidas em vídeos longos nos últimos 12 meses** ou **10 milhões de
  visualizações de Shorts nos últimos 90 dias**. Também precisa de 2FA ativado, AdSense,
  nenhum aviso ativo e morar em país elegível (o Brasil é).
- **As visualizações de Shorts não contam como horas assistidas.** As compilações diárias
  (vídeos longos) são o que soma horas. Por isso o robô já faz uma por dia.

**O maior risco é a política de "conteúdo reutilizado".** Na revisão, um canal que só reposta
lives de outras pessoas, mesmo com legenda e crédito, costuma ser recusado. O que ajuda a passar:
1. **Autorização dos streamers por escrito** (um e-mail já serve). Guarde as respostas.
   Muitos streamers grandes têm programa oficial de cortes, alguns com divisão de receita.
2. **Conteúdo seu por cima**: narração nas compilações, "TOP 10 da semana" com comentário,
   títulos e miniaturas próprios. Faça pelo menos 1 vídeo assim por semana.
3. **Cuidado com música**: o rádio do GTA toca músicas licenciadas. Clipe com música
   reconhecível leva reivindicação de Content ID (a receita vai para a gravadora ou o vídeo é
   bloqueado). Rejeite esses no painel. A Twitch também muta trechos dos VODs com música, então
   alguns clipes detectados pelo chat podem vir sem som.
4. **Nunca ignore uma reclamação de streamer.** Tire o vídeo do ar. Três avisos de direitos
   autorais apagam o canal.
