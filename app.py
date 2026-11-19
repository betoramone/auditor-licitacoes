import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types
from google.genai.errors import APIError as GeminiAPIError

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


api_key = obter_api_key()

# Barra lateral apenas com modelo e data base
with st.sidebar:
    st.header("Configuração")

    modelos_gemini = ["gemini-3.8-flash", "gemini-2.5-flash"]
    modelo = st.selectbox(
        "Modelo Gemini principal:",
        options=modelos_gemini
    )

    hoje_br = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    data_referencia = st.date_input(
        "Data base para validar certidões:",
        value=hoje_br,
        format="DD/MM/YYYY"
    )

# Área de Upload em duas colunas
col1, col2 = st.columns(2)

with col1:
    edital_pdf = st.file_uploader("1. Suba o Edital da Licitação (PDF)", type=["pdf"])

with col2:
    docs_pdfs = st.file_uploader(
        "2. Suba os Documentos da Empresa (PDF - pode selecionar vários)",
        type=["pdf"],
        accept_multiple_files=True
    )


def analisar_com_gemini(
    chave_api: str,
    modelo_principal: str,
    edital_bytes: bytes,
    arquivos_empresa: list[tuple[str, bytes]],
    prompt: str,
    status_placeholder
) -> str:
    client = genai.Client(api_key=chave_api)

    contents = [
        "DOCUMENTO DE REFERÊNCIA — EDITAL DA LICITAÇÃO:",
        types.Part.from_bytes(data=edital_bytes, mime_type="application/pdf"),
    ]

    for nome_arquivo, dados_bytes in arquivos_empresa:
        contents.append(f"DOCUMENTO DA EMPRESA — ARQUIVO: {nome_arquivo}")
        contents.append(types.Part.from_bytes(data=dados_bytes, mime_type="application/pdf"))

    contents.append(prompt)

    ordem_modelos = [modelo_principal]
    for m in ["gemini-3.8-flash", "gemini-2.5-flash"]:
        if m not in ordem_modelos:
            ordem_modelos.append(m)

    ultimo_erro = None
    for idx_m, nome_modelo in enumerate(ordem_modelos):
        for tentativa in range(3):
            try:
                status_placeholder.info(
                    f"Consultando Google Gemini ({nome_modelo}) — tentativa {tentativa + 1} de 3..."
                )
                response = client.models.generate_content(
                    model=nome_modelo,
                    contents=contents
                )
                if response.text:
                    return response.text
                raise RuntimeError("O modelo retornou uma resposta vazia.")
            except GeminiAPIError as e:
                ultimo_erro = e
                if e.code in (503, 429, 500):
                    espera = 3 * (tentativa + 1)
                    status_placeholder.warning(
                        f"Modelo {nome_modelo} instável/ocupado (código {e.code}). "
                        f"Nova tentativa em {espera}s..."
                    )
                    time.sleep(espera)
                    continue
                raise

        if idx_m < len(ordem_modelos) - 1:
            status_placeholder.warning(
                f"Sem resposta após tentativas no {nome_modelo}. Tentando modelo alternativo..."
            )

    raise ultimo_erro or RuntimeError("Não foi possível obter resposta do Google Gemini após tentativas.")


# Botão de execução
if st.button("🔍 Analisar Documentação e Gerar Parecer", type="primary", use_container_width=True):
    if not api_key:
        st.error("Chave de API não configurada no servidor (`GEMINI_API_KEY` nos Secrets).")
    elif not edital_pdf or not docs_pdfs:
        st.warning("Por favor, anexe o PDF do Edital e pelo menos um PDF dos Documentos da empresa.")
    else:
        status_placeholder = st.empty()
        with st.spinner("Processando documentos e gerando parecer..."):
            try:
                edital_bytes = edital_pdf.getvalue()
                arquivos_empresa = [(arq.name, arq.getvalue()) for arq in docs_pdfs]

                prompt = f"""
                Você é um analista sênior de licitações públicas especialista na Lei nº 14.133/2021.
                Data de referência para análise de validade das certidões: {data_referencia.strftime('%d/%m/%Y')}.

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

                parecer_texto = analisar_com_gemini(
                    api_key, modelo, edital_bytes, arquivos_empresa, prompt, status_placeholder
                )

                status_placeholder.empty()
                st.session_state["parecer"] = parecer_texto

            except Exception as e:
                status_placeholder.empty()
                st.error(f"Erro ao processar os documentos: {e}")

# Exibição do Parecer e Botão de Impressão
if "parecer" in st.session_state:
    st.divider()
    st.subheader("📄 Parecer Técnico de Habilitação")

    components.html(
        """
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
        height=55
    )

    st.markdown(st.session_state["parecer"])
