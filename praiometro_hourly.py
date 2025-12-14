import json
import re
import sys
import datetime
import time
import requests
import pdfplumber
import schedule
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

CAMINHO_PONTOS = "pontos.json"          # arquivo de pontos estáticos
CAMINHO_PDF = "niteroi_historico.pdf"  # PDF com histórico de balneabilidade

MAPA_STATUS = {
    "Própria": True,
    "Imprópria": False
}

def criar_sessao_com_retries(retries=5, backoff_factor=1.0, status_forcelist=(500, 502, 503, 504)):
    sessao = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry)
    sessao.mount("http://", adapter)
    sessao.mount("https://", adapter)
    return sessao

# Carrega pontos estáticos (nomes, coordenadas e histórico de balneabilidade)
def carregar_pontos(caminho=CAMINHO_PONTOS):
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Erro ao carregar pontos: {e}")
        sys.exit(1)

def baixar_relatorio_inea(caminho_pdf=CAMINHO_PDF):
    url_pagina = "https://www.inea.rj.gov.br/niteroi/"
    sessao = criar_sessao_com_retries()
    sessao.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    try:
        resposta = sessao.get(url_pagina, timeout=30)
        resposta.raise_for_status()
        soup = BeautifulSoup(resposta.text, "html.parser")

        # Tenta encontrar links que são apenas anos (ex: "2024", "2025") e pega o maior
        link = None
        anos_encontrados = []
        for a_tag in soup.find_all("a", href=True):
            texto = a_tag.get_text(" ", strip=True)
            # Verifica se o texto é exatamente um ano (4 dígitos)
            if re.match(r'^\d{4}$', texto):
                try:
                    ano = int(texto)
                    anos_encontrados.append((ano, a_tag))
                except ValueError:
                    pass
        
        if anos_encontrados:
            # Ordena pelo ano decrescente (maior primeiro)
            anos_encontrados.sort(key=lambda x: x[0], reverse=True)
            link = anos_encontrados[0][1]
            print(f"Link selecionado pelo ano mais recente: {anos_encontrados[0][0]}")
        
        # Se não encontrar ano, tenta "último boletim"
        if not link:
            for a_tag in soup.find_all("a", href=True):
                if "último boletim" in a_tag.get_text(" ", strip=True).lower():
                    link = a_tag
                    break
        
        if not link:
            # Fallback: heurística genérica
            print("Links específicos não encontrados. Tentando heurística...")
            for a_tag in soup.find_all("a", href=True):
                texto = a_tag.get_text(" ", strip=True).lower()
                href = a_tag['href'].lower()
                if "boletim" in texto and ".pdf" in href:
                    link = a_tag
                    break

        if not link:
            print("Link do boletim não encontrado.")
            return
        
        url_pdf = link.get("href")
        print(f"URL do boletim mais recente: {url_pdf}")

        # baixar PDF
        for tentativa in range(5):
            try:
                resposta_pdf = sessao.get(url_pdf, timeout=10)
                resposta_pdf.raise_for_status()
                with open(caminho_pdf, "wb") as f:
                    f.write(resposta_pdf.content)
                print(f"Boletim salvo como {caminho_pdf}")
                return
            except Exception as e:
                print(f"Tentativa {tentativa+1} falhou: {e}")
                time.sleep(2 * (tentativa + 1))
        print("Falha ao baixar boletim após 5 tentativas.")

    except Exception as e:
        print(f"Erro ao acessar a página do INEA: {e}")

# Extrai status de balneabilidade mais recente do PDF
def extrair_balneabilidade(caminho_pdf=CAMINHO_PDF):
    resultado = {}
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            for pagina in pdf.pages:
                for tabela in pagina.extract_tables():
                    for linha in tabela:
                        if not linha or len(linha) < 4:
                            continue
                        codigo = (linha[1] or '').strip()
                        if not codigo:
                            continue
                        medicoes = [m for m in linha[3:] if m]
                        if not medicoes:
                            continue
                        ultimo = medicoes[-1].strip()
                        resultado[codigo] = MAPA_STATUS.get(ultimo)
    except FileNotFoundError:
        print(f"Aviso: PDF '{caminho_pdf}' não encontrado.")
    except Exception as e:
        print(f"Erro ao processar PDF: {e}")
    print(resultado)
    return resultado

# Função que busca dados meteorológicos e marinhos para uma coordenada
def buscar_dados(lat, lon):
    br_timezone = datetime.timezone(datetime.timedelta(hours=-3))
    agora = datetime.datetime.now(br_timezone)
    ts_hour = agora.replace(minute=0, second=0, microsecond=0)
    date_start = ts_hour.strftime("%Y-%m-%d")
    date_end = (ts_hour + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    # parâmetros adicionais
    met_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "temperature_2m",
            "precipitation",
            "precipitation_probability",
            "rain",
            "relative_humidity_2m",
            "apparent_temperature",
            "wind_speed_10m",
            "wind_direction_10m",
            "uv_index",
            "weather_code"
        ]),
        "timezone": "auto",
        "start_date": date_start,
        "end_date": date_end
    }
    marine_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wave_height,wave_period",
        "timezone": "auto",
        "start_date": date_start,
        "end_date": date_end
    }
    sessao = criar_sessao_com_retries()
    # requisição metereológica
    try:
        r_met = sessao.get("https://api.open-meteo.com/v1/forecast", params=met_params, timeout=10)
        data_met = r_met.json().get("hourly", {})
    except Exception as e:
        print(f"Erro API meteo: {e}")
        data_met = {}
    # requisição marinha
    try:
        r_mar = sessao.get("https://marine-api.open-meteo.com/v1/marine", params=marine_params, timeout=10)
        data_mar = r_mar.json().get("hourly", {})
    except Exception as e:
        print(f"Erro API marinha: {e}")
        data_mar = {}


    # busca índice do timestamp
    time_list = data_met.get("time", [])
    key = ts_hour.strftime("%Y-%m-%dT%H:%M")
    if key in time_list:
        idx = time_list.index(key)
        # verifica se choveu nas últimas 8 horas
        choveu_8_horas = False
        if "precipitation" in data_met and "time" in data_met:
            now_idx = None
            for i, t in enumerate(data_met["time"]):
                if t == key:
                    now_idx = i
                    break
            if now_idx is not None and now_idx >= 8:
                ult_precip = data_met["precipitation"][now_idx-8:now_idx]
                choveu_8_horas = any(p > 0 for p in ult_precip)
        
        # Extrai previsão das próximas 24 horas
        previsao_24h = []
        temps = data_met.get("temperature_2m", [])
        probs = data_met.get("precipitation_probability", [])
        codes = data_met.get("weather_code", [])
        
        for i in range(24):
            hora_idx = idx + i
            if hora_idx < len(time_list):
                previsao_24h.append({
                    "hora": time_list[hora_idx],
                    "temperatura": temps[hora_idx] if hora_idx < len(temps) else None,
                    "precipitacao_prob": probs[hora_idx] if hora_idx < len(probs) else None,
                    "weather_code": codes[hora_idx] if hora_idx < len(codes) else None
                })
        
        # coleta valores
        return {
            "timestamp": key,
            "temperature_2m": data_met.get("temperature_2m", [None])[idx],
            "precipitation": data_met.get("precipitation", [None])[idx],
            "precipitation_probability": data_met.get("precipitation_probability", [None])[idx],
            "rain": data_met.get("rain", [None])[idx],
            "relative_humidity_2m": data_met.get("relative_humidity_2m", [None])[idx],
            "apparent_temperature": data_met.get("apparent_temperature", [None])[idx],
            "wind_speed_10m": data_met.get("wind_speed_10m", [None])[idx],
            "wind_direction_10m": data_met.get("wind_direction_10m", [None])[idx],
            "uv_index": data_met.get("uv_index", [None])[idx],
            "wave_height": data_mar.get("wave_height", [None])[idx],
            "wave_period": data_mar.get("wave_period", [None])[idx],
            "weather_code": data_met.get("weather_code", [None])[idx],
            "choveu_8_horas": choveu_8_horas,
            "previsao_24h": previsao_24h
        }
    else:
        print(f"Hora {key} não encontrada nos dados.")
        return {"timestamp": key, "previsao_24h": []}

def atualizar():
    # carrega pontos estáticos e balneabilidade
    pontos = carregar_pontos()
    baixar_relatorio_inea()
    bal = extrair_balneabilidade()

    # carrega pontos antigos para fallback
    try:
        with open(CAMINHO_PONTOS, "r", encoding="utf-8") as f:
            pontos_anteriores = json.load(f)
    except Exception:
        pontos_anteriores = {}

    # prepara saída
    out = {}
    for codigo, info in pontos.items():
        lat, lon = info.get("coordenadas_decimais", [None, None])
        leitura = buscar_dados(lat, lon)

        # checar se a leitura falhou: pode usar uma métrica como `temperature_2m is None`
        if leitura.get("temperature_2m") is None:
            print(f"Falha na leitura para {codigo}, mantendo dados anteriores.")
            if codigo in pontos_anteriores:
                out[codigo] = pontos_anteriores[codigo]
            else:
                # se não houver anterior, salva com leitura mínima
                leitura["balneabilidade"] = bal.get(codigo)
                out[codigo] = {
                    **info,
                    "leitura_atual": leitura
                }
        else:
            leitura["balneabilidade"] = bal.get(codigo)
            out[codigo] = {
                **info,
                "leitura_atual": leitura
            }

    # salva resultado
    with open(CAMINHO_PONTOS, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=4)

    br_timezone = datetime.timezone(datetime.timedelta(hours=-3))
    print(f"Atualização realizada em {datetime.datetime.now(br_timezone).isoformat()}")

    # notificar API após atualização do pontos.json
    try:
        resposta = requests.post("http://localhost:8000/notificar-atualizacao")  # Altere se necessário
        print("Notificação enviada:", resposta.json())
    except Exception as e:
        print("Erro ao notificar API:", e)


# Executa atualização imediata ao iniciar
atualizar()

if len(sys.argv) > 1 and sys.argv[1] == "once":
    print("Modo 'once': encerrando após primeira atualização.")
    sys.exit(0)

# configura agendamento a cada hora
schedule.every().hour.at(":00").do(atualizar)

print("Iniciando praiômetro programado. Pressione Ctrl+C para sair.")
# execução contínua
while True:
    schedule.run_pending()
    time.sleep(30)