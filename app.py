import os
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


api_key = obter_api_key()

# Barra lateral para data base
with st.sidebar:
    st.header("Configuração")
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

# Botão de execução
if st.button("🔍 Analisar Documentação e Gerar Parecer", type="primary", use_container_width=True):
    if not api_key:
        st.error("Chave de API não configurada no servidor (`GEMINI_API_KEY` nos Secrets).")
    elif not edital_pdf or not docs_pdfs:
        st.warning("Por favor, anexe o PDF do Edital e pelo menos um PDF dos Documentos da empresa.")
    else:
        status_box = st.empty()
        progress_bar = st.progress(0, text="Preparando documentos para auditoria...")

        try:
            progress_bar.progress(15, text="Carregando edital e documentos da empresa...")
            client = genai.Client(api_key=api_key)

            # Monta a lista de conteúdos: primeiro o edital, depois cada documento da empresa
            contents = [
                "DOCUMENTO DE REFERÊNCIA — EDITAL DA LICITAÇÃO:",
                types.Part.from_bytes(data=edital_pdf.getvalue(), mime_type="application/pdf"),
            ]

            total_docs = len(docs_pdfs)
            for idx, arquivo in enumerate(docs_pdfs, start=1):
                contents.append(f"DOCUMENTO DA EMPRESA — ARQUIVO: {arquivo.name}")
                contents.append(
                    types.Part.from_bytes(data=arquivo.getvalue(), mime_type="application/pdf")
                )
                pct_docs = 15 + int((idx / max(total_docs, 1)) * 20)
                progress_bar.progress(
                    min(pct_docs, 35),
                    text=f"Anexando documento {idx} de {total_docs}: {arquivo.name}..."
                )

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

            contents.append(prompt)

            modelo_ativo = "gemini-3.8-flash"
            response = None
            ultimo_erro = None
            max_tentativas = 3

            for tentativa in range(max_tentativas):
                progresso_tentativa = 40 + (tentativa * 15)
                try:
                    progress_bar.progress(
                        min(progresso_tentativa, 85),
                        text=f"Analisando documentação com {modelo_ativo} (tentativa {tentativa + 1} de {max_tentativas})..."
                    )
                    status_box.info(
                        f"Consultando {modelo_ativo} (tentativa {tentativa + 1} de {max_tentativas})..."
                    )
                    response = client.models.generate_content(
                        model=modelo_ativo,
                        contents=contents
                    )
                    if response.text:
                        break
                    raise RuntimeError("A resposta veio vazia.")
                except APIError as e:
                    ultimo_erro = e
                    if e.code in (503, 429, 500):
                        espera = 3 * (tentativa + 1)
                        progress_bar.progress(
                            min(progresso_tentativa, 85),
                            text=f"Sobrecarga temporária ({e.code}). Aguardando {espera}s para nova tentativa..."
                        )
                        status_box.warning(
                            f"Instabilidade/sobrecarga no {modelo_ativo} (código {e.code}). "
                            f"Tentando novamente em {espera}s..."
                        )
                        time.sleep(espera)
                        continue
                    raise

            if response is None or not response.text:
                raise ultimo_erro or RuntimeError("Não foi possível obter resposta após as tentativas.")

            progress_bar.progress(100, text="Parecer técnico gerado com sucesso!")
            status_box.empty()
            st.session_state["parecer"] = response.text

        except Exception as e:
            progress_bar.empty()
            status_box.empty()
            st.error(f"Erro ao processar os documentos: {e}")

# Exibição do Parecer e Botão de Impressão (imprimindo apenas o relatório)
if "parecer" in st.session_state:
    st.divider()

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
        height=55
    )

    st.markdown('<div id="area-parecer-impressao">', unsafe_allow_html=True)
    st.subheader("📄 Parecer Técnico de Habilitação")
    st.markdown(st.session_state["parecer"])
    st.markdown("</div>", unsafe_allow_html=True)
