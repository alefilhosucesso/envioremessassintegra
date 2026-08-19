"""
Robô de envio - Sintegra (SAT / SEF-SC)
Sucesso Contabilidade

Pré-requisito: o usuário abre o Edge manualmente, com depuração remota:
    msedge.exe --remote-debugging-port=9222 --user-data-dir="C:\\SAT_ROBO_PROFILE"
loga no SAT e deixa a janela na tela "Envio de Remessa - Sintegra -
Convênio 57". O robô NUNCA faz login sozinho - ver decisão em CLAUDE.md.

O que ele faz, para cada .zip em PASTA_REMESSAS que tenha pasta_confirmada
no mapa_empresas_sintegra.csv:
  1. Seleciona o arquivo no campo de upload e clica "Enviar Arquivo".
  2. Se o SAT rejeitar (duplicado, arquivo inválido etc.), registra o
     motivo, pula e segue para o próximo.
  3. Se aceitar, abre a janela de recibo. Confere se o CNPJ do recibo bate
     com o CNPJ do nome do arquivo - se divergir, PARA (problema fiscal).
  4. Gera o PDF do recibo direto da página (Playwright page.pdf()).
  5. Salva o PDF nos dois destinos definidos em CLAUDE.md, criando as
     pastas Sintegra/<ano> se necessário.
  6. Move o .zip enviado para PASTA_REMESSAS\\ENVIADAS (nunca apaga).
  7. No final, imprime um resumo: enviados / pulados / motivo.

Empresa sem pasta_confirmada no mapa: registra, pula, avisa no resumo -
não tenta adivinhar.
"""

import csv
import os
import re
import shutil
import sys
import time

from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------- configuração

CDP_URL = "http://localhost:9222"

PASTA_REMESSAS = r"Z:\SCAN\AARQUIVOS TRANSITÓRIOS\MAYNARA\SINTEGRA\REMESSAS"
PASTA_ENVIADAS = os.path.join(PASTA_REMESSAS, "ENVIADAS")
PASTA_EMPRESAS = r"Z:\EMPRESAS\EMPRESAS ATIVAS"
DESTINO_ENVIAR = r"Z:\DADOS_TAREFFA\FISCAL\Enviar"
MAPA_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "mapa_empresas_sintegra.csv")

URL_ENVIO = "Envio_Remessa.aspx"
SEL_INPUT_ARQUIVO = "#txtImportarArquivo"
SEL_BOTAO_ENVIAR = "#Body_Main_Main_pnlEnvioRemessa_btnEnviarArquivo"

TIMEOUT_POPUP_MS = 15000

# --------------------------------------------------------------------- helpers


def ler_mapa() -> dict:
    """arquivo (nome do zip) -> linha do CSV conferido."""
    if not os.path.isfile(MAPA_CSV):
        raise SystemExit(
            f"Mapa não encontrado: {MAPA_CSV}\n"
            "Rode indexar_empresas_sintegra.py e confira o CSV primeiro."
        )
    mapa = {}
    with open(MAPA_CSV, newline="", encoding="utf-8-sig") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            mapa[linha["arquivo"]] = linha
    return mapa


def conectar_pagina_envio():
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp(CDP_URL)
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if URL_ENVIO in pg.url:
                return p, browser, ctx, pg
    raise SystemExit(
        "Não achei nenhuma aba do Edge na tela de Envio de Remessa. "
        "Abra o Edge com --remote-debugging-port=9222, faça login no SAT "
        "e deixe a janela na tela 'Envio de Remessa - Sintegra - Convênio 57'."
    )


def competencia(periodo_fim: str) -> str:
    """'31/07/2026' -> '07 2026'."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", periodo_fim)
    return f"{m.group(2)} {m.group(3)}" if m else ""


def extrair_recibo(pagina_recibo) -> dict:
    labels = pagina_recibo.locator(".tabela")
    valores = pagina_recibo.locator(".dados")
    dados = {}
    for i in range(labels.count()):
        chave = labels.nth(i).inner_text().strip()
        valor = valores.nth(i).inner_text().strip()
        dados[chave] = valor

    cabecalho = pagina_recibo.locator(".subtitulomaior").inner_text()
    m = re.search(r"Envio da Remessa\s+(\S+)", cabecalho)
    dados["nº_envio"] = m.group(1) if m else ""
    return dados


def enviar_um_arquivo(page, ctx, caminho_zip: str):
    """Seleciona o zip e clica Enviar Arquivo.

    Retorna ("sucesso", pagina_recibo) | ("erro", motivo) | ("indefinido", texto)
    """
    page.set_input_files(SEL_INPUT_ARQUIVO, caminho_zip)

    try:
        with ctx.expect_page(timeout=TIMEOUT_POPUP_MS) as popup_info:
            page.click(SEL_BOTAO_ENVIAR)
        recibo = popup_info.value
        recibo.wait_for_load_state()
        return "sucesso", recibo
    except Exception:
        pass

    # não abriu popup: pode ser mensagem de erro (ex.: duplicado) inline
    page.wait_for_load_state("networkidle", timeout=20000)
    texto = page.locator("body").inner_text()
    m = re.search(r"Erro\s*\n(.+)", texto)
    if m:
        return "erro", m.group(1).strip()
    return "indefinido", texto[-500:]


def garantir_pasta(caminho: str):
    os.makedirs(caminho, exist_ok=True)


def processar_remessa(page, ctx, nome_zip: str, linha_mapa: dict, log: list):
    caminho_zip = os.path.join(PASTA_REMESSAS, nome_zip)
    pasta_empresa = linha_mapa.get("pasta_confirmada", "").strip()

    if not pasta_empresa:
        print(f"[PULADO ] {nome_zip}: sem pasta_confirmada no mapa")
        log.append((nome_zip, "PULADO", "sem pasta_confirmada no mapa"))
        return

    cnpj_nome_m = re.match(r"(\d{14})", nome_zip)
    cnpj_nome = cnpj_nome_m.group(1) if cnpj_nome_m else ""

    resultado, valor = enviar_um_arquivo(page, ctx, caminho_zip)

    if resultado == "erro":
        print(f"[REJEITADO] {nome_zip}: {valor}")
        log.append((nome_zip, "REJEITADO", valor))
        return

    if resultado == "indefinido":
        raise SystemExit(
            f"Tela inesperada depois de enviar {nome_zip}. Parando para "
            f"conferência manual.\nTrecho da página:\n{valor}"
        )

    # resultado == "sucesso"
    recibo = valor
    dados = extrair_recibo(recibo)

    cnpj_recibo = dados.get("CNPJ", "")
    if cnpj_nome and cnpj_recibo and cnpj_nome != cnpj_recibo:
        raise SystemExit(
            f"CNPJ do nome do arquivo ({cnpj_nome}) diverge do CNPJ do "
            f"recibo ({cnpj_recibo}) para {nome_zip}. Parando."
        )

    comp = competencia(dados.get("Período de Fim", ""))
    if not comp:
        raise SystemExit(
            f"Não consegui calcular a competência (MM AAAA) para {nome_zip} "
            f"a partir do recibo. Parando.\nDados do recibo: {dados}"
        )
    mes, ano = comp.split()

    pasta_sintegra_ano = os.path.join(
        PASTA_EMPRESAS, pasta_empresa, "ESCRITA FISCAL", "Sintegra", ano
    )
    garantir_pasta(pasta_sintegra_ano)
    destino1 = os.path.join(pasta_sintegra_ano, f"{comp}.pdf")
    garantir_pasta(DESTINO_ENVIAR)
    destino2 = os.path.join(DESTINO_ENVIAR, f"{comp}.pdf")

    recibo.pdf(path=destino1)
    shutil.copyfile(destino1, destino2)
    recibo.close()

    garantir_pasta(PASTA_ENVIADAS)
    shutil.move(caminho_zip, os.path.join(PASTA_ENVIADAS, nome_zip))

    print(f"[ENVIADO] {nome_zip}: {dados.get('Razão Social', '')} -> "
          f"{destino1}")
    log.append((nome_zip, "ENVIADO", f"{dados.get('Razão Social', '')} | {comp}"))


# ------------------------------------------------------------------ processo


def main():
    if not os.path.isdir(PASTA_REMESSAS):
        raise SystemExit(f"Pasta de remessas não encontrada: {PASTA_REMESSAS}")

    mapa = ler_mapa()
    zips = sorted(f for f in os.listdir(PASTA_REMESSAS) if f.lower().endswith(".zip"))
    print(f"{len(zips)} remessas encontradas em {PASTA_REMESSAS}\n")

    p, browser, ctx, page = conectar_pagina_envio()

    log = []
    try:
        for nome_zip in zips:
            linha_mapa = mapa.get(nome_zip)
            if linha_mapa is None:
                print(f"[PULADO ] {nome_zip}: não está no mapa_empresas_sintegra.csv")
                log.append((nome_zip, "PULADO", "não está no mapa"))
                continue
            processar_remessa(page, ctx, nome_zip, linha_mapa, log)
            time.sleep(1)
    finally:
        p.stop()

    enviados = sum(1 for _, s, _ in log if s == "ENVIADO")
    rejeitados = sum(1 for _, s, _ in log if s == "REJEITADO")
    pulados = sum(1 for _, s, _ in log if s == "PULADO")

    print(f"\nResumo: {enviados} enviados | {rejeitados} rejeitados pelo SAT | "
          f"{pulados} pulados (sem mapa)")
    for nome_zip, situacao, motivo in log:
        if situacao != "ENVIADO":
            print(f"  - {situacao}: {nome_zip} ({motivo})")


if __name__ == "__main__":
    main()
