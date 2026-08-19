"""
Indexador de empresas - Sintegra
Sucesso Contabilidade

Objetivo: montar UMA VEZ o mapa CNPJ -> pasta da empresa, para que o robô
de envio nunca precise "procurar pelo nome" em tempo de execução.

O que ele faz:
  1. Abre cada .zip da pasta de remessas e lê o REGISTRO 10 (primeira linha),
     de onde tira CNPJ, inscrição estadual, razão social e período.
  2. Lista as pastas de Z:\\EMPRESAS\\EMPRESAS ATIVAS.
  3. Sugere, para cada CNPJ, a pasta mais parecida, com um grau de confiança.
  4. Gera um CSV para você CONFERIR e corrigir à mão.

O CSV conferido vira o mapa definitivo usado pelo robô.
Nada é enviado, movido ou apagado por este script - ele só lê.

Uso:
    python indexar_empresas_sintegra.py
"""

import csv
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from difflib import SequenceMatcher

# ---------------------------------------------------------------- configuração

PASTA_REMESSAS = r"Z:\SCAN\AARQUIVOS TRANSITÓRIOS\MAYNARA\SINTEGRA\REMESSAS"
PASTA_EMPRESAS = r"Z:\EMPRESAS\EMPRESAS ATIVAS"
SAIDA_CSV = r"mapa_empresas_sintegra.csv"

# a partir de que semelhança a sugestão é considerada confiável
LIMITE_ALTA = 0.88
LIMITE_MEDIA = 0.70

# palavras que não ajudam a diferenciar uma empresa da outra
RUIDO = {
    "ltda", "me", "epp", "eireli", "sa", "s a", "s/a", "cia", "comercio",
    "comercial", "industria", "industrial", "servicos", "servico", "e",
    "de", "da", "do", "das", "dos", "em", "the", "&", "-",
}

# --------------------------------------------------------------------- helpers


def normalizar(texto: str) -> str:
    """Tira acento, pontuação, sufixos societários e espaços sobrando."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    palavras = [p for p in texto.split() if p not in RUIDO]
    return " ".join(palavras)


def semelhanca(a: str, b: str) -> float:
    """Compara dois nomes já normalizados, com bônus para prefixo em comum.

    O bônus existe porque as pastas costumam ser versões ENCURTADAS do nome
    ('DELICIAS DE MARIA' para 'DELICIAS DE MARIA LTDA'), e nesses casos a
    comparação bruta pune o texto que sobra.
    """
    if not a or not b:
        return 0.0
    base = SequenceMatcher(None, a, b).ratio()
    if a.startswith(b) or b.startswith(a):
        base = max(base, 0.90)
    # nome fantasia costuma ser a primeira palavra da razão social
    pa, pb = a.split(), b.split()
    if pa and pb and pa[0] == pb[0] and len(pa[0]) >= 4:
        base += 0.05
    return min(base, 1.0)


def ler_registro_10(caminho_zip: str) -> dict | None:
    """Lê o registro 10 do arquivo Sintegra dentro do .zip.

    Layout do Convênio ICMS 57/95 (posições 1-based):
      01-02 tipo (10)      03-16 CNPJ          17-30 inscrição estadual
      31-65 nome           66-95 município     96-97 UF
      108-115 data inicial 116-123 data final
    """
    try:
        with zipfile.ZipFile(caminho_zip) as z:
            internos = [n for n in z.namelist() if not n.endswith("/")]
            if not internos:
                return None
            with z.open(internos[0]) as f:
                linha = f.readline().decode("latin-1")
    except Exception as e:
        return {"erro": f"{type(e).__name__}: {e}"}

    if not linha.startswith("10"):
        return {"erro": f"primeira linha não é registro 10: {linha[:20]!r}"}

    return {
        "cnpj": linha[2:16].strip(),
        "ie": linha[16:30].strip(),
        "razao_social": linha[30:65].strip(),
        "municipio": linha[65:95].strip(),
        "uf": linha[95:97].strip(),
        "data_inicial": linha[107:115].strip(),
        "data_final": linha[115:123].strip(),
    }


def consultar_cnpj_publico(cnpj: str) -> dict | None:
    """Consulta a razão social de um CNPJ na BrasilAPI (dado público).

    Usado como alternativa quando o .zip da remessa vem protegido por senha
    e não dá pra ler o registro 10 direto (caso de toda a leva atual). O CNPJ
    já vem do nome do arquivo, então não depende do conteúdo do zip.
    """
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                dados = json.load(r)
            return {
                "razao_social": dados.get("razao_social", ""),
                "nome_fantasia": dados.get("nome_fantasia", ""),
            }
        except urllib.error.HTTPError as e:
            if e.code == 429 and tentativa < 2:
                time.sleep(3)
                continue
            return None
        except Exception:
            return None
    return None


def competencia(data_final: str) -> str:
    """20260731 -> '07 2026' (padrão de nome de arquivo usado no escritório)."""
    if len(data_final) == 8:
        return f"{data_final[4:6]} {data_final[0:4]}"
    return ""


# ------------------------------------------------------------------ processo


def main() -> None:
    if not os.path.isdir(PASTA_REMESSAS):
        raise SystemExit(f"Pasta de remessas não encontrada: {PASTA_REMESSAS}")
    if not os.path.isdir(PASTA_EMPRESAS):
        raise SystemExit(f"Pasta de empresas não encontrada: {PASTA_EMPRESAS}")

    pastas = [d for d in os.listdir(PASTA_EMPRESAS)
              if os.path.isdir(os.path.join(PASTA_EMPRESAS, d))]
    pastas_norm = [(p, normalizar(p)) for p in pastas]
    print(f"{len(pastas)} pastas encontradas em EMPRESAS ATIVAS")

    zips = sorted(f for f in os.listdir(PASTA_REMESSAS) if f.lower().endswith(".zip"))
    print(f"{len(zips)} remessas encontradas\n")

    def melhor_pasta(razao_social: str):
        alvo = normalizar(razao_social)
        melhor, melhor_score = "", 0.0
        for pasta, pasta_norm in pastas_norm:
            s = semelhanca(alvo, pasta_norm)
            if s > melhor_score:
                melhor, melhor_score = pasta, s
        return melhor, melhor_score

    linhas = []
    for nome_zip in zips:
        dados = ler_registro_10(os.path.join(PASTA_REMESSAS, nome_zip))
        cnpj_nome_m = re.match(r"(\d{14})", nome_zip)
        cnpj_nome = cnpj_nome_m.group(1) if cnpj_nome_m else ""

        erro = (dados or {}).get("erro", "") if dados is not None else "zip vazio"
        protegido = "encrypted" in erro.lower() or "password" in erro.lower()

        if dados is not None and not erro:
            # leitura normal do registro 10 (zip não protegido)
            divergente = bool(cnpj_nome) and cnpj_nome != dados["cnpj"]
            melhor, melhor_score = melhor_pasta(dados["razao_social"])
            cnpj = dados["cnpj"]
            razao_social = dados["razao_social"]
            comp = competencia(dados["data_final"])
            origem = "zip"
        elif protegido and cnpj_nome:
            # zip protegido por senha: usa o CNPJ do nome do arquivo e busca
            # a razão social numa fonte pública (CNPJ é dado cadastral público)
            info = consultar_cnpj_publico(cnpj_nome)
            time.sleep(1.2)  # não martelar a API pública
            if info is None or not info.get("razao_social"):
                print(f"[ERRO ] {nome_zip}: zip protegido e consulta pública de "
                      f"CNPJ falhou/CNPJ não encontrado")
                linhas.append({
                    "arquivo": nome_zip, "cnpj": cnpj_nome, "razao_social": "",
                    "competencia": "", "pasta_sugerida": "", "confianca": "",
                    "situacao": "ERRO NA CONSULTA CNPJ", "pasta_confirmada": "",
                })
                continue
            divergente = False
            melhor, melhor_score = melhor_pasta(info["razao_social"])
            cnpj = cnpj_nome
            razao_social = info["razao_social"]
            comp = ""  # não temos o período sem abrir o zip; vem do recibo no envio
            origem = "consulta pública (zip protegido)"
        else:
            print(f"[ERRO ] {nome_zip}: {erro}")
            linhas.append({
                "arquivo": nome_zip, "cnpj": cnpj_nome, "razao_social": "",
                "competencia": "", "pasta_sugerida": "", "confianca": "",
                "situacao": "ERRO NA LEITURA", "pasta_confirmada": "",
            })
            continue

        if divergente:
            situacao = "CNPJ DIVERGE DO NOME DO ARQUIVO"
        elif melhor_score >= LIMITE_ALTA:
            situacao = "ALTA"
        elif melhor_score >= LIMITE_MEDIA:
            situacao = "CONFERIR"
        else:
            situacao = "NAO ENCONTRADA"

        print(f"[{situacao:<8}] ({origem}) {razao_social[:32]:<32} -> "
              f"{melhor[:32]:<32} ({melhor_score:.2f})")

        linhas.append({
            "arquivo": nome_zip,
            "cnpj": cnpj,
            "razao_social": razao_social,
            "competencia": comp,
            "pasta_sugerida": melhor if melhor_score >= LIMITE_MEDIA else "",
            "confianca": f"{melhor_score:.2f}",
            "situacao": situacao,
            # coluna que VOCÊ preenche quando a sugestão estiver errada ou vazia
            "pasta_confirmada": melhor if situacao == "ALTA" else "",
        })

    with open(SAIDA_CSV, "w", newline="", encoding="utf-8-sig") as f:
        campos = ["arquivo", "cnpj", "razao_social", "competencia",
                  "pasta_sugerida", "confianca", "situacao", "pasta_confirmada"]
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        w.writeheader()
        w.writerows(linhas)

    alta = sum(1 for l in linhas if l["situacao"] == "ALTA")
    conferir = sum(1 for l in linhas if l["situacao"] == "CONFERIR")
    nao_encontrada = sum(1 for l in linhas if l["situacao"] == "NAO ENCONTRADA")
    divergente = sum(1 for l in linhas if l["situacao"] == "CNPJ DIVERGE DO NOME DO ARQUIVO")
    erros = len(linhas) - alta - conferir - nao_encontrada - divergente

    print(f"\nResumo: {alta} automáticas | {conferir} para conferir | "
          f"{nao_encontrada} não encontradas | {divergente} CNPJ divergente | "
          f"{erros} erros de leitura/consulta")
    print(f"Arquivo gerado: {os.path.abspath(SAIDA_CSV)}")
    print("\nAbra no Excel e preencha a coluna 'pasta_confirmada' onde estiver vazia.")
    print("Esse arquivo conferido vira o mapa oficial do robô de envio.")


if __name__ == "__main__":
    main()
