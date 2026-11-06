# Painel de Projetos de Lei · Célio Studart

Página online que mostra os projetos do deputado (PL, PLP, PEC e PDL, de autoria e coautoria) com a situação atual, a última movimentação e o histórico recente de cada um. Os dados vêm da API de Dados Abertos da Câmara dos Deputados e são atualizados sozinhos a cada 3 horas.

## Como funciona

- `docs/index.html` é a página.
- `docs/dados.json` é o arquivo com os dados (criado e atualizado pelo robô).
- `scripts/atualizar.py` é o robô que consulta a Câmara.
- `.github/workflows/atualizar.yml` é o agendamento: roda o robô a cada 3 horas e publica a página.

Tudo roda de graça no GitHub. Não precisa de servidor nem de instalar nada no computador.

## Publicar (uma vez só, uns 10 minutos)

1. Crie uma conta gratuita em https://github.com (se ainda não tiver).
2. Clique em **New repository** (botão verde). Dê um nome, por exemplo `painel-celio`, marque **Public** e clique em **Create repository**.
3. Na página do repositório, clique em **uploading an existing file**. Arraste a pasta `docs` e a pasta `scripts` (as duas de uma vez) e clique em **Commit changes**.
4. Crie o arquivo do agendamento (no Mac e no Windows a pasta `.github` costuma ficar oculta, por isso é melhor criar pelo site):
   - clique em **Add file > Create new file**;
   - no nome, digite exatamente `.github/workflows/atualizar.yml`;
   - cole o conteúdo do arquivo `atualizar.yml` que está nesta pasta e clique em **Commit changes**.
5. Vá em **Settings > Pages**. Em **Source**, escolha **GitHub Actions**.
6. Vá na aba **Actions**, clique em **Atualizar painel** (à esquerda), depois em **Run workflow > Run workflow**. A primeira vez demora uns 5 a 15 minutos, porque busca todas as proposições.
7. Quando aparecer o sinal verde, o endereço da página fica em **Settings > Pages** (algo como `https://seu-usuario.github.io/painel-celio/`). É esse link que você abre e compartilha.

A partir daí não precisa fazer mais nada: o robô roda sozinho a cada 3 horas, e aos domingos faz uma revisão completa de todas as proposições.

## Ajustes simples

Todos ficam no arquivo `.github/workflows/atualizar.yml`, na parte `env:`:

- **Outro deputado:** troque `DEPUTADO_ID` (o número que aparece no endereço do perfil na Câmara, por exemplo `camara.leg.br/deputados/204488`).
- **Outros tipos de proposição:** edite `TIPOS`, por exemplo `PL,PLP,PEC,PDL,REQ,INC`.
- **Frequência:** a linha `cron: "17 */3 * * *"` significa a cada 3 horas. Para de hora em hora, use `"17 * * * *"`.

Para forçar uma atualização na hora: aba **Actions > Atualizar painel > Run workflow** (marque "Atualização completa" se quiser reconsultar tudo).

## Observações

- Se o repositório ficar 60 dias sem nenhuma alteração, o GitHub pausa o agendamento e manda um e-mail; basta clicar em reativar. Na prática isso não deve acontecer, porque cada movimentação nova gera uma alteração.
- A categoria de cada projeto (em tramitação, aprovada na Câmara, virou lei, arquivada/encerrada) é calculada a partir da situação informada pela Câmara.
