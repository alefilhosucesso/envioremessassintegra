# Automação — Envio de Remessas Sintegra (SAT / SEF-SC)

Sucesso Contabilidade — São Bento do Sul (SC)

## Objetivo

Automatizar o envio mensal das remessas Sintegra no portal SAT da SEF/SC e o
arquivamento dos recibos em PDF, hoje feito 100% manualmente, empresa por
empresa.

## Processo manual atual

1. No SAT, tela **"Envio de Remessa - Sintegra - Convênio 57"**: clicar em
   *Procurar*, selecionar o primeiro `.zip` da pasta de remessas, *Abrir*.
2. Clicar em **Enviar Arquivo**.
3. Abre uma janela com o recibo (`Relatorio.aspx`), contendo nº do envio,
   inscrição estadual, CNPJ, razão social, período início/fim, data de envio
   e hash.
4. Clicar em *Imprimir* → conferir se a impressora é **Microsoft Print to PDF**
   → *Imprimir*.
5. No diálogo de salvar, colar `Z:\EMPRESAS\EMPRESAS ATIVAS`, pesquisar o nome
   da empresa, entrar na pasta → `ESCRITA FISCAL` → `Sintegra` → `<ano>`.
6. Salvar com o nome no padrão **`MM AAAA`** (ex.: `07 2026.pdf`).
7. Imprimir de novo e salvar o mesmo PDF em `Z:\DADOS_TAREFFA\FISCAL\Enviar`.
8. Fechar o recibo, voltar ao SAT, apagar o `.zip` já enviado e repetir com o
   próximo.

## Dados de entrada

- Remessas: arquivos `.zip` em
  `Z:\SCAN\AARQUIVOS TRANSITÓRIOS\MAYNARA\SINTEGRA\REMESSAS`.
- Nome do arquivo: `CNPJ_datahora_seq.zip`
  (ex.: `12345678000199_20260817160755_167.zip`, sendo `12345678000199` um
  CNPJ fictício de exemplo).
- Dentro do zip, o **registro 10** (primeira linha, layout Convênio ICMS
  57/95) traz CNPJ, inscrição estadual, razão social, município, UF e o
  período — ou seja, dá para identificar a empresa e a competência **antes**
  de enviar.

## Destinos

| | Caminho |
|---|---|
| 1 | `Z:\EMPRESAS\EMPRESAS ATIVAS\<pasta da empresa>\ESCRITA FISCAL\Sintegra\<ano>\MM AAAA.pdf` |
| 2 | `Z:\DADOS_TAREFFA\FISCAL\Enviar\MM AAAA.pdf` |

## Decisões já tomadas

- **Tecnologia:** Playwright/Selenium controlando o navegador — não pyautogui.
  O processo é web + sistema de arquivos, não tela desktop.
- **PDF:** gerado direto da página do recibo pelo navegador. A caixa
  "Microsoft Print to PDF" e a navegação no Windows Explorer deixam de existir.
- **Navegador/login:** o robô NÃO faz login. O usuário abre o **Edge**
  manualmente, loga no SAT e deixa a janela na tela "Envio de Remessa -
  Sintegra - Convênio 57"; o robô conecta nessa janela já aberta via CDP
  (`playwright.chromium.connect_over_cdp`, Edge é Chromium por baixo) e
  parte dali. Motivo: no dia a dia o usuário usa Firefox, mas o Playwright só
  consegue anexar numa janela já aberta e autenticada no caso de
  navegadores Chromium (CDP) — no Firefox teria que ser um perfil dedicado
  com sessão salva, o que é mais complicado. Usar o Edge só para esta
  automação evita mexer no Firefox do dia a dia e evita ter que programar
  tela de login/captcha.
- **Identificação da empresa:** por **CNPJ**, nunca por busca de nome em tempo
  de execução. As pastas de `EMPRESAS ATIVAS` variam entre razão social, nome
  fantasia e versões encurtadas do nome, então o mapa CNPJ → pasta é montado
  uma vez, conferido à mão, e depois só consultado.
- **Nome do arquivo:** `MM AAAA` derivado do período do registro 10 / recibo.
  Nada de digitar mês.
- **Conferência:** o CNPJ do nome do arquivo tem que bater com o do recibo.
  Se divergir, para.
- **Arquivo enviado:** **mover** para uma subpasta `ENVIADAS\`, não apagar.
- **Remessa rejeitada pelo SAT:** registrar no log, pular e seguir para a
  próxima. Resumo no final com enviados / pulados / motivo.
- **Empresa sem entrada no mapa:** registrar, pular, avisar no resumo.
- **Pasta `Sintegra` (ou o ano) ausente em `ESCRITA FISCAL`:** criar a pasta
  na hora — não pular, não parar. O robô precisa de permissão de escrita
  em `EMPRESAS ATIVAS` para isso.

## Estado atual

- [x] `indexar_empresas_sintegra.py` — lê os zips, extrai o registro 10 e
      sugere a pasta correspondente, gerando `mapa_empresas_sintegra.csv`
      para conferência manual. Rodado em 19/08/2026.
- [x] Rodar o indexador e conferir o CSV (coluna `pasta_confirmada`). Os
      `.zip` da leva atual vieram todos protegidos por senha (ZipCrypto),
      então o script foi ajustado: quando a leitura do zip falha por senha,
      usa o CNPJ do nome do arquivo pra consultar a razão social na
      BrasilAPI (dado público) e faz o fuzzy-match com isso em vez do
      conteúdo do zip. Resultado: 42/43 automáticas (ALTA), 1 pendente de
      conferência manual (empresa que havia mudado de razão social e não
      batia com o nome da pasta — resolvido conferindo à mão).
- [x] ~~Ver a tela de login do SAT (captcha?).~~ Não é mais necessário — ver
      decisão "Navegador/login" acima: o robô conecta numa janela do Edge
      já aberta e logada pelo usuário, não faz login sozinho.
- [x] Escrever o robô de envio (`robo_envio_sintegra.py`). Seletores e
      estrutura do recibo confirmados inspecionando o SAT de verdade via
      CDP em 19/08/2026 (ver detalhes abaixo). Ainda não rodado em lote.
- [x] Teste com uma única remessa antes de rodar em lote (FLOR&SER,
      arquivada manualmente passo a passo pra validar a lógica) e depois
      **lote completo rodado em produção em 19/08/2026**: 41 remessas
      enviadas e arquivadas com sucesso (PDF nos 2 destinos + zip movido
      pra `ENVIADAS`), 1 rejeitada pelo SAT (CNPJ não cadastrado como
      contribuinte de SC — ficou em `REMESSAS`, não mexido), 1 pulada por
      não estar no mapa, ficou em `REMESSAS`. Robô funcionando ponta a
      ponta.

### Notas técnicas do SAT (Envio_Remessa.aspx), confirmadas em 19/08/2026

- Campo de arquivo: `#txtImportarArquivo`. Botão:
  `#Body_Main_Main_pnlEnvioRemessa_btnEnviarArquivo` (dispara `__doPostBack`,
  sem preview antes de enviar).
- Sucesso: abre um **popup** (`Relatorio.aspx?pNomeXls=Recibo_Envio&qh=...`)
  com o recibo. **É obrigatório desativar o bloqueador de pop-up do Edge**
  nesse perfil, senão a janela do recibo se perde e não tem como recuperar
  (reenviar o mesmo zip só dá erro de duplicidade, não reabre o recibo).
- Recibo já enviado / duplicado: não abre popup; aparece um texto inline
  "Erro" + "A remessa com o arquivo <nome> já foi enviada." na própria
  página. O robô trata isso como REJEITADO e segue para a próxima.
- Estrutura do recibo: pares de `<td class="tabela">rótulo</td>` /
  `<td class="dados">valor</td>` dentro de `#lbXmlRelatorio` — Inscrição,
  CNPJ, Razão Social, Período de Início, Período de Fim, Finalidade, Data
  Envio, HASH Arquivo Validado. Nº do envio fica no cabeçalho
  `.subtitulomaior` ("Nº Envio da Remessa <uuid>").
- `page.pdf()` do Playwright funciona normalmente conectado via CDP numa
  janela do Edge **não-headless** (testado e confirmado) — não precisa do
  botão nativo "Imprimir" (`#btnImprimirPDF`) nem da caixa "Microsoft Print
  to PDF".
- Teste real feito com uma remessa de um cliente (competência 07/2026) —
  enviada e aceita pelo SAT de verdade.

## Processo mensal (repetição)

Como os zips já enviados são movidos para `REMESSAS\ENVIADAS` (nunca
apagados), a pasta `REMESSAS` sempre contém só as remessas ainda não
tratadas. Isso significa que o ciclo abaixo é o mesmo todo mês,
independente de quantas empresas houver:

1. Rodar `indexar_empresas_sintegra.py` de novo — ele processa só o que
   está em `REMESSAS` naquele momento (as novas do mês) e gera um
   `mapa_empresas_sintegra.csv` novo.
2. Abrir o CSV e conferir só as linhas `CONFERIR` ou `NAO ENCONTRADA`
   (normalmente poucas — na primeira leva foi 1 em 43). Preencher
   `pasta_confirmada` à mão nelas.
3. Rodar `robo_envio_sintegra.py`. Ele usa a última versão do
   `mapa_empresas_sintegra.csv`.

O esforço manual escala com o número de empresas que caem fora do match
automático, não com o número total de empresas.

## Observações

- O escritório já tem outras automações em Python (lançamento de notas no
  JBCepil com pyautogui, download de SPED no portal IPM com Selenium). Mesmo
  padrão: log detalhado, parar diante de qualquer tela inesperada, resumo no
  final.
- Não apagar nem sobrescrever nada sem confirmação. Remessa não enviada por
  engano é problema fiscal.
