# Envio de Remessas Sintegra (SAT / SEF-SC)

Automação do envio mensal de remessas Sintegra pelo portal SAT da SEF/SC
(Santa Catarina) e do arquivamento dos recibos em PDF — processo que
antes era feito manualmente, empresa por empresa.

## O que faz

1. **`indexar_empresas_sintegra.py`** — lê os `.zip` de remessa (nome no
   padrão `CNPJ_datahora_seq.zip`), identifica o CNPJ e tenta casar cada
   remessa com a pasta correspondente da empresa no sistema de arquivos,
   usando fuzzy-match de nome. Quando o `.zip` vem protegido por senha (o
   que impede ler o conteúdo), busca a razão social por consulta pública
   de CNPJ (BrasilAPI) como alternativa. Gera um CSV para conferência
   manual das poucas remessas sem match automático de alta confiança.
2. **`robo_envio_sintegra.py`** — usando o CSV já conferido, conecta numa
   janela do navegador já aberta e autenticada no SAT (via CDP), envia
   cada remessa, lê o recibo retornado, gera o PDF do recibo e o arquiva
   na pasta da empresa, movendo o `.zip` já enviado para uma subpasta
   `ENVIADAS`.
   puladas e registradas no resumo final, nunca travam o lote inteiro.

3. **`enviar_recibos_tareffa.py`** — copia os recibos já arquivados para
   a fila de outro sistema interno, um por vez, com intervalo e
   confirmando que a fila consumiu o anterior antes de mandar o próximo.
   Existe porque todos os recibos de um mês têm o mesmo nome (a
   competência): mandados em rajada, um sobrescreve o outro. Este script
   não interage com o portal — só copia PDF que já existe, então pode ser
   repetido sem risco.

O robô **não faz login sozinho** — o usuário loga manualmente no SAT numa
janela do navegador aberta com depuração remota habilitada, e o robô
assume dali em diante. Nada é enviado, movido ou apagado sem que a lógica
de conferência (CNPJ do arquivo == CNPJ do recibo) seja respeitada.

## Requisitos

- Python 3.12+
- `pip install playwright`
- Microsoft Edge, aberto com depuração remota:
  ```
  msedge.exe --remote-debugging-port=9222 --user-data-dir="<perfil dedicado>"
  ```
  logado no SAT, na tela **Envio de Remessa - Sintegra - Convênio 57**,
  com o bloqueador de pop-up desativado nesse perfil.

## Uso mensal

1. `python indexar_empresas_sintegra.py` — processa as remessas pendentes
   e gera/atualiza `mapa_empresas_sintegra.csv`.
2. Abrir o CSV e preencher a coluna `pasta_confirmada` nas linhas que
   ficaram como `CONFERIR` ou `NAO ENCONTRADA`.
3. `python robo_envio_sintegra.py` — envia o que está confirmado no mapa.
4. `python enviar_recibos_tareffa.py` — alimenta a fila do outro sistema
   (um recibo a cada 25s; apagar `recibos_enviados_tareffa.txt` a cada
   novo mês).

Detalhes de decisões de arquitetura, descobertas sobre a estrutura do SAT
e histórico do projeto estão em [`CLAUDE.md`](CLAUDE.md).

## O que não vai pro repositório

`mapa_empresas_sintegra.csv` e `Sintegra.docx` ficam de fora
(`.gitignore`) por conterem dados de clientes (CNPJ, razão social) e por
mudarem a cada ciclo mensal — não fazem sentido versionados.
