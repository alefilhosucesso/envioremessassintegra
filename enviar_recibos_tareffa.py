"""
Envio dos recibos Sintegra para a fila do TAREFFA
Sucesso Contabilidade

Copia, um de cada vez, o PDF do recibo que já está arquivado na pasta da
empresa para Z:\\DADOS_TAREFFA\\FISCAL\\Enviar.

Por que existe: todos os recibos do mês têm o mesmo nome ("MM AAAA.pdf"),
porque é a competência. Se o robô de envio joga os 300+ na fila em poucos
minutos, um sobrescreve o outro antes de o TAREFFA consumir, e recibo se
perde. Aqui vai um por vez, com uma pausa entre eles, e só continua depois
de confirmar que o anterior foi consumido.

NÃO fala com o SAT. Não envia remessa, não move nem apaga zip. Só copia PDF
que já existe. Rodar isto nunca reenvia nada para a Receita.

Uso:
    python enviar_recibos_tareffa.py                      # todas do mapa
    python enviar_recibos_tareffa.py Faltantes.csv        # só as da lista
    python enviar_recibos_tareffa.py Faltantes.csv 25     # intervalo de 25s

A lista pode ser um CSV com a coluna "Nome Empresa" (o formato que o TAREFFA
exporta) ou um txt com um nome de empresa por linha. O casamento com a pasta
da empresa usa o mesmo fuzzy-match do indexador.
"""

import csv
import os
import shutil
import sys
import time

import indexar_empresas_sintegra as ix

# ---------------------------------------------------------------- configuração

PASTA_EMPRESAS = ix.PASTA_EMPRESAS
DESTINO_ENVIAR = r"Z:\DADOS_TAREFFA\FISCAL\Enviar"
MAPA_CSV = ix.SAIDA_CSV

INTERVALO_PADRAO = 25          # segundos entre um recibo e o próximo
LIMITE_SEMELHANCA = 0.80       # abaixo disso, considera que não é a empresa

# guarda o que já foi copiado, para poder repetir a execução sem duplicar
AQUI = os.path.dirname(os.path.abspath(__file__))
LOG_FEITOS = os.path.join(AQUI, "recibos_enviados_tareffa.txt")

INTERVALO_ATUAL = [INTERVALO_PADRAO]   # definido em main(), lido pela barra


# --------------------------------------------------------------------- helpers


def ler_lista(caminho: str) -> list:
    """Nomes de empresa de um CSV com coluna 'Nome Empresa' ou de um txt."""
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        inicio = f.read(400)
        f.seek(0)
        if "Nome Empresa" in inicio:
            return [l["Nome Empresa"].strip()
                    for l in csv.DictReader(f, delimiter=";")
                    if l.get("Nome Empresa", "").strip()]
        return [linha.strip() for linha in f if linha.strip()]


def carregar_mapa() -> list:
    """Linhas do mapa que têm pasta confirmada."""
    with open(MAPA_CSV, newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f, delimiter=";")
                if r.get("pasta_confirmada", "").strip()]


def casar(nome: str, mapa: list):
    """Acha a linha do mapa que corresponde a este nome de empresa."""
    alvo = ix.normalizar(nome)
    melhor, melhor_score = None, 0.0
    for r in mapa:
        s = max(ix.semelhanca(alvo, ix.normalizar(r["razao_social"])),
                ix.semelhanca(alvo, ix.normalizar(r["pasta_confirmada"])))
        if s > melhor_score:
            melhor, melhor_score = r, s
    if melhor_score >= LIMITE_SEMELHANCA:
        return melhor, melhor_score
    return None, melhor_score


def recibo_da_empresa(pasta_empresa: str):
    """Caminho do PDF de recibo mais recente da empresa, ou None."""
    base = os.path.join(PASTA_EMPRESAS, pasta_empresa, "ESCRITA FISCAL", "Sintegra")
    if not os.path.isdir(base):
        return None
    candidatos = []
    for ano in os.listdir(base):
        pasta_ano = os.path.join(base, ano)
        if not os.path.isdir(pasta_ano):
            continue
        for nome in os.listdir(pasta_ano):
            if nome.lower().endswith(".pdf"):
                caminho = os.path.join(pasta_ano, nome)
                candidatos.append((os.path.getmtime(caminho), caminho))
    if not candidatos:
        return None
    return max(candidatos)[1]


def ja_feitos() -> set:
    if not os.path.isfile(LOG_FEITOS):
        return set()
    with open(LOG_FEITOS, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


def formatar_tempo(segundos: int) -> str:
    if segundos >= 3600:
        return "{}h{:02d}m".format(segundos // 3600, (segundos % 3600) // 60)
    return "{}m{:02d}s".format(segundos // 60, segundos % 60)


def barra(feitos: int, total: int, espera: int = -1) -> None:
    """Desenha a barra de progresso, sempre na mesma linha do terminal.

    espera = -1 desenha só o andamento (usado na fase de casamento, onde não
    há tempo de espera a prever).
    """
    largura = 30
    cheio = int(largura * feitos / total) if total else largura
    pct = 100.0 * feitos / total if total else 100.0
    sys.stdout.write("\r[{}{}] {}/{} ({:4.1f}%)".format(
        "#" * cheio, "." * (largura - cheio), feitos, total, pct))
    if espera >= 0:
        # o que falta são os recibos ainda não copiados, mais o que resta da
        # espera atual - assim o tempo só diminui, nunca pula para trás
        falta = (total - feitos) * INTERVALO_ATUAL[0] + espera
        prox = " - proximo em {:2d}s".format(espera) if espera else ""
        sys.stdout.write(" restam {}{}{}".format(
            formatar_tempo(falta), prox, " " * 19))
    sys.stdout.flush()


def esperar_fila(nome_arquivo: str, espera: int, feitos: int, total: int) -> bool:
    """Conta o intervalo mostrando a barra e confirma que a fila esvaziou.

    Devolve False se, passado o intervalo, o arquivo anterior ainda está lá -
    sinal de que o TAREFFA não consumiu e copiar de novo apagaria um recibo.
    """
    destino = os.path.join(DESTINO_ENVIAR, nome_arquivo)
    for restante in range(espera, 0, -1):
        if not os.path.exists(destino):
            # fila já livre: ainda assim respeita o intervalo pedido
            barra(feitos, total, restante)
            time.sleep(1)
            continue
        barra(feitos, total, restante)
        time.sleep(1)
    return not os.path.exists(destino)


# ------------------------------------------------------------------ processo


def main() -> None:
    lista_arq = sys.argv[1] if len(sys.argv) > 1 else ""
    intervalo = int(sys.argv[2]) if len(sys.argv) > 2 else INTERVALO_PADRAO
    INTERVALO_ATUAL[0] = intervalo

    if not os.path.isdir(DESTINO_ENVIAR):
        raise SystemExit("Pasta de destino não encontrada: " + DESTINO_ENVIAR)

    mapa = carregar_mapa()
    print("{} empresas com pasta confirmada no mapa".format(len(mapa)))

    if lista_arq:
        nomes = ler_lista(lista_arq)
        print("{} nomes na lista {}".format(len(nomes), lista_arq))
    else:
        nomes = [r["razao_social"] for r in mapa]
        print("sem lista: usando todas as empresas do mapa")

    # monta a fila de trabalho antes de copiar qualquer coisa, para poder
    # mostrar o que vai acontecer e não descobrir problema no meio do caminho
    print("casando nomes com as pastas das empresas...")
    feitos_antes = ja_feitos()
    trabalho, ignorados, repetidos = [], [], []
    vistos = set()
    for i, nome in enumerate(nomes, 1):
        barra(i, len(nomes))
        linha, score = casar(nome, mapa)
        if linha is None:
            ignorados.append((nome, "sem empresa correspondente ({:.2f})".format(score)))
            continue
        pasta = linha["pasta_confirmada"]
        if pasta in vistos:
            repetidos.append(nome)
            continue
        vistos.add(pasta)
        if pasta in feitos_antes:
            repetidos.append(nome + " (já enviado em execução anterior)")
            continue
        pdf = recibo_da_empresa(pasta)
        if pdf is None:
            ignorados.append((nome, "sem recibo em ESCRITA FISCAL/Sintegra"))
            continue
        trabalho.append((pasta, pdf))
    print()

    print("\n{} recibos a enviar | {} ignorados (sem recibo/sem match) | "
          "{} repetidos na lista".format(len(trabalho), len(ignorados),
                                         len(repetidos)))
    for nome, motivo in ignorados:
        print("  [IGNORADO] {}: {}".format(nome, motivo))

    if not trabalho:
        print("\nNada a fazer.")
        return

    total = len(trabalho)
    print("\nIntervalo: {}s. Tempo estimado: {}".format(
        intervalo, formatar_tempo(total * intervalo)))
    print("Destino: {}\n".format(DESTINO_ENVIAR))

    # a fila tem que estar vazia antes de começar, senão a primeira cópia já
    # apagaria um recibo que o TAREFFA ainda não processou
    primeiro = os.path.basename(trabalho[0][1])
    if os.path.exists(os.path.join(DESTINO_ENVIAR, primeiro)):
        raise SystemExit(
            "Já existe '{}' na fila do TAREFFA. Espere o sistema consumir "
            "antes de rodar, para não sobrescrever um recibo.".format(primeiro)
        )

    enviados = 0
    for i, (pasta, pdf) in enumerate(trabalho, 1):
        nome_arquivo = os.path.basename(pdf)

        shutil.copyfile(pdf, os.path.join(DESTINO_ENVIAR, nome_arquivo))
        with open(LOG_FEITOS, "a", encoding="utf-8") as f:
            f.write(pasta + "\n")
        enviados += 1

        if i < total:
            # esperar_fila já redesenha a barra a cada segundo
            if not esperar_fila(nome_arquivo, intervalo, enviados, total):
                print("\n\n[PARADA] '{}' continua na fila depois de {}s - o "
                      "TAREFFA não consumiu o anterior.".format(
                          nome_arquivo, intervalo))
                print("Parando para não sobrescrever recibo. Rode de novo "
                      "quando a fila estiver vazia; os já enviados serão "
                      "pulados.")
                break
        else:
            barra(enviados, total, 0)

    print("\n\nResumo: {} recibos copiados para a fila do TAREFFA.".format(enviados))
    print("Registro do que foi enviado: {}".format(LOG_FEITOS))
    print("Apague esse arquivo antes de começar um novo mês.")


if __name__ == "__main__":
    main()
