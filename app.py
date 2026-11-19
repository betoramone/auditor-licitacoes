import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from google import genai
from google.genai import types
from google.genai.errors import APIError

# Configuração da página
st.set_page_config(page_title="Auditor de Credenciamento", page_icon="⚖️", layout="wide")

st.title("⚖️ Auditor de Documentos para Licitação")
st.markdown("Faça o upload do **Edital** e de **um ou mais PDFs da Empresa** para gerar o parecer de habilitação.")


def obter_api_key() -> str:
    try:
        if "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"]:
            return str(st.secrets["GEMINI_API_KEY"]).strip()
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "").strip()


def eh_cota_diaria_esgotada(erro: APIError) -> bool:
    texto = str(erro).lower()
    return (
        "perday" in texto
        or "requests per day" in texto
        or "per day limit exceeded" in texto
    )


def extrair_tempo_espera(erro: APIError) -> str:
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?[hms]+)", str(erro), re.IGNORECASE)
    return match.group(1) if match else ""


def montar_prompt(data_ref_str: str) -> str:
    return f"""
    Você é um analista sênior de licitações públicas especialista na Lei nº 14.133/2021.
    Data de referência para análise de validade das certidões: {data_ref_str}.

    TAREFA:
    Analise todos os arquivos PDF enviados como "DOCUMENTO DA EMPRESA" confrontando-os rigorosamente com as exigências do "DOCUMENTO DE REFERÊNCIA — EDITAL DA LICITAÇÃO". Considere o conjunto de arquivos da empresa como um único pacote de habilitação/credenciamento, identificando em qual arquivo cada documento/informação se encontra.

    INSTRUÇÕES DE AUDITORIA:
    1. Identifique a empresa (Razão Social e CNPJ) e verifique se há consistência em todos os arquivos enviados.
    2. Confira cada certidão apresentada (Federal, Estadual, Municipal, FGTS, Trabalhista, Falência/Concordata) verificando data de emissão, prazo de validade e conformidade com o edital.
    3. Verifique a habilitação jurídica (Contrato Social/Estatuto, alterações, documentos dos sócios/representantes).
    4. Caso o edital exija qualificação econômico-financeira, extraia os valores do Balanço Patrimonial / demonstrações e calcule os índices exigidos (ex: Liquidez Corrente, Liquidez Geral, Solvência Geral), informando a fórmula e o resultado.
    5. Verifique a qualificação técnica (atestados, declarações, registros) conforme o objeto do edital.

    FORMATO DO PARECER TÉCNICO:
    Organize a saída de forma limpa e formal para impressão:
    - **Cabeçalho do Parecer:** Objeto resumido do edital, Empresa analisada, CNPJ e relação dos arquivos avaliados.
    - **Tabela Resumo de Conformidade:** Colunas [Documento / Exigência | Arquivo de Origem | Status (CONFORME / IRREGULAR / AUSENTE) | Observação e Validade].
    - **Análise Detalhada e Cálculos:** Detalhamento técnico de cada ponto crítico, arquivo avaliado ou cálculo contábil realizado.
    - **Conclusão / Veredito:** Parecer final claro indicando se a documentação está APTA ou INAPTA para o credenciamento, listando eventuais pendências ou diligências.
    """


@st.cache_data(show_spinner=False)
def gerar_parecer_cacheado(
    api_key: str,
    edital_bytes: bytes,
    arquivos_empresa: tuple[tuple[str, bytes], ...],
    data_ref_str: str,
    modelos_prioridade: tuple[str, ...],
) -> tuple[str, str]:
    client = genai.Client(api_key=api_key)

    contents = [
        "DOCUMENTO DE REFERÊNCIA — EDITAL DA LICITAÇÃO:",
        types.Part.from_bytes(data=edital_bytes, mime_type="application/pdf"),
    ]

    for nome_arquivo, dados_bytes in arquivos_empresa:
        contents.append(f"DOCUMENTO DA EMPRESA — ARQUIVO: {nome_arquivo}")
        contents.append(types.Part.from_bytes(data=dados_bytes, mime_type="application/pdf"))

    contents.append(montar_prompt(data_ref_str))

    ultimo_erro = None

    for nome_modelo in modelos_prioridade:
        for tentativa in range(3):
            try:
                response = client.models.generate_content(
                    model=nome_modelo,
                    contents=contents,
                )
                if response.text:
                    return response.text, nome_modelo
                raise RuntimeError(f"O modelo {nome_modelo} retornou uma resposta vazia.")
            except APIError as e:
                ultimo_erro = e
                # Se for cota diária (PerDay) no modelo atual, encerra tentativas deste modelo e passa ao próximo
                if e.code == 429 and eh_cota_diaria_esgotada(e):
                    break
                # Para falhas temporárias (503, 429 por minuto, 500), faz retry curto
                if e.code in (503, 429, 500):
                    time.sleep(2 * (tentativa + 1))
                    continue
                raise

    raise ultimo_erro or RuntimeError("Não foi possível obter resposta em nenhum modelo da lista de prioridade.")


api_key = obter_api_key()

# Barra lateral para data base e lista de fallback
with st.sidebar:
    st.header("Configuração")
    hoje_br = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    data_referencia = st.date_input(
        "Data base para validar certidões:",
        value=hoje_br,
        format="DD/MM/YYYY",
    )

    modelos_padrao = [
        "gemini-3.8-flash",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ]
    modelos_selecionados = st.multiselect(
        "Ordem de prioridade dos modelos (fallback automático):",
        options=modelos_padrao + ["gemma-4-31b-it", "gemma-4-26b-a4b-it"],
        default=modelos_padrao,
        help="Se o primeiro atingir o limite (ex.: 429), o sistema tenta o próximo automaticamente.",
    )

# Formulário para evitar reexecuções indesejadas durante seleção de arquivos
with st.form(key="form_auditoria_licitacao", clear_on_submit=False):
    col1, col2 = st.columns(2)

    with col1:
        edital_pdf = st.file_uploader("1. Suba o Edital da Licitação (PDF)", type=["pdf"])

    with col2:
        docs_pdfs = st.file_uploader(
            "2. Suba os Documentos da Empresa (PDF - pode selecionar vários)",
            type=["pdf"],
            accept_multiple_files=True,
        )

    enviado = st.form_submit_button(
        "🔍 Analisar Documentação e Gerar Parecer",
        type="primary",
        use_container_width=True,
    )

if enviado:
    if not api_key:
        st.error("Chave de API não configurada no servidor (`GEMINI_API_KEY` nos Secrets).")
    elif not edital_pdf or not docs_pdfs:
        st.warning("Por favor, anexe o PDF do Edital e pelo menos um PDF dos Documentos da empresa.")
    elif not modelos_selecionados:
        st.warning("Selecione pelo menos um modelo na barra lateral.")
    else:
        status_box = st.empty()
        progress_bar = st.progress(10, text="Preparando pacotes de PDF para auditoria...")

        try:
            edital_bytes = edital_pdf.getvalue()
            arquivos_tupla = tuple((arq.name, arq.getvalue()) for arq in docs_pdfs)
            data_ref_str = data_referencia.strftime("%d/%m/%Y")
            prioridade_tupla = tuple(modelos_selecionados)

            progress_bar.progress(
                45,
                text=f"Consultando modelos em ordem de prioridade ({', '.join(prioridade_tupla)})...",
            )
            status_box.info(
                f"Iniciando auditoria com fallback automático: **{prioridade_tupla[0]}** → demais modelos configurados."
            )

            parecer_texto, modelo_utilizado = gerar_parecer_cacheado(
                api_key=api_key,
                edital_bytes=edital_bytes,
                arquivos_empresa=arquivos_tupla,
                data_ref_str=data_ref_str,
                modelos_prioridade=prioridade_tupla,
            )

            st.session_state["parecer"] = parecer_texto
            st.session_state["modelo_usado"] = modelo_utilizado
            st.session_state["data_ref_parecer"] = data_ref_str

            progress_bar.progress(100, text=f"Parecer concluído com o modelo: {modelo_utilizado}")
            status_box.empty()

        except APIError as e:
            progress_bar.empty()
            status_box.empty()
            if e.code == 429 and eh_cota_diaria_esgotada(e):
                tempo = extrair_tempo_espera(e)
                aviso_tempo = f" Tempo estimado para reset: **{tempo}**." if tempo else ""
                st.error(
                    f"Limite diário de requisições atingido nos modelos testados.{aviso_tempo}"
                )
            else:
                st.error(f"Erro na API do Gemini ao processar os documentos: {e}")

        except Exception as e:
            progress_bar.empty()
            status_box.empty()
            st.error(f"Erro ao processar os documentos: {e}")

# Exibição do Parecer e Botão de Impressão (imprimindo apenas o relatório)
if "parecer" in st.session_state:
    st.divider()

    if "modelo_usado" in st.session_state:
        st.caption(
            f"Modelo utilizado: **{st.session_state['modelo_usado']}** | "
            f"Data de referência: **{st.session_state.get('data_ref_parecer', '')}**"
        )

    st.iframe(
        html="""
        <script>
        (function() {
            const parentDoc = window.parent.document;
            if (!parentDoc.getElementById("estilo-impressao-relatorio")) {
                const style = parentDoc.createElement("style");
                style.id = "estilo-impressao-relatorio";
                style.innerHTML = `
                    @media print {
                        body * {
                            visibility: hidden !important;
                        }
                        #area-parecer-impressao, #area-parecer-impressao * {
                            visibility: visible !important;
                        }
                        #area-parecer-impressao {
                            position: absolute !important;
                            left: 0 !important;
                            top: 0 !important;
                            width: 100% !important;
                            margin: 0 !important;
                            padding: 16px !important;
                            color: #000000 !important;
                            background: #ffffff !important;
                        }
                        #area-parecer-impressao table {
                            width: 100% !important;
                            border-collapse: collapse !important;
                        }
                        #area-parecer-impressao th, #area-parecer-impressao td {
                            border: 1px solid #666 !important;
                            padding: 6px 8px !important;
                            color: #000000 !important;
                        }
                        .no-print {
                            display: none !important;
                        }
                    }
                `;
                parentDoc.head.appendChild(style);
            }
        })();
        </script>
        <button onclick="window.parent.print()" style="
            background-color: #0e1117;
            color: white;
            border: 1px solid #4a4a4a;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-family: sans-serif;
            font-size: 14px;
            font-weight: bold;">
            🖨️ Imprimir Parecer / Salvar em PDF
        </button>
        """,
        height=55,
    )

    st.markdown('<div id="area-parecer-impressao">', unsafe_allow_html=True)
    st.subheader("📄 Parecer Técnico de Habilitação")
    st.markdown(st.session_state["parecer"])
    st.markdown("</div>", unsafe_allow_html=True)
