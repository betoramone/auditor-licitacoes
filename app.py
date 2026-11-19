import streamlit as st
from google import genai
from google.genai import types
import streamlit.components.v1 as components
from datetime import date

# Configuração da página
st.set_page_config(page_title="Auditor de Credenciamento", page_icon="⚖️", layout="wide")

st.title("⚖️ Auditor de Documentos para Licitação")
st.markdown("Faça o upload do **Edital** e dos **Documentos da Empresa** para gerar o parecer de habilitação.")

# Barra lateral para a Chave de API (ou configurada nos Secrets da nuvem)
with st.sidebar:
    st.header("Configuração")
    api_key = st.secrets.get("GEMINI_API_KEY", "") or st.text_input("Cole sua API Key do Gemini:", type="password")
    data_referencia = st.date_input("Data base para validar certidões:", value=date.today())

# Área de Upload em duas colunas
col1, col2 = st.columns(2)

with col1:
    edital_pdf = st.file_uploader("1. Suba o Edital da Licitação (PDF)", type=["pdf"])

with col2:
    docs_pdf = st.file_uploader("2. Suba os Documentos da Empresa (PDF)", type=["pdf"])

# Botão de execução
if st.button("🔍 Analisar Documentação e Gerar Parecer", type="primary", use_container_width=True):
    if not api_key:
        st.error("Por favor, insira a chave de API do Google Gemini na barra lateral.")
    elif not edital_pdf or not docs_pdf:
        st.warning("Por favor, anexe tanto o PDF do Edital quanto o PDF dos Documentos da empresa.")
    else:
        with st.spinner("Lendo o edital, conferindo certidões e calculando índices... Aguarde alguns segundos."):
            try:
                client = genai.Client(api_key=api_key)

                prompt = f"""
                Você é um analista sênior de licitações públicas especialista na Lei nº 14.133/2021.
                Data de referência para análise de validade das certidões: {data_referencia.strftime('%d/%m/%Y')}.

                TAREFA:
                Analise o segundo arquivo PDF (Documentos de Habilitação/Credenciamento da empresa) confrontando-o rigorosamente com as exigências do primeiro arquivo PDF (Edital da Licitação).

                INSTRUÇÕES DE AUDITORIA:
                1. Identifique a empresa (Razão Social e CNPJ) e verifique se há consistência em todos os documentos.
                2. Confira cada certidão apresentada (Federal, Estadual, Municipal, FGTS, Trabalhista, Falência/Concordata) verificando data de emissão, prazo de validade e autenticidade formal conforme exigido no edital.
                3. Verifique a habilitação jurídica (Contrato Social/Estatuto e documentos dos sócios).
                4. Caso o edital exija qualificação econômico-financeira, extraia os valores do Balanço Patrimonial e calcule os índices exigidos (ex: Liquidez Corrente, Liquidez Geral, Solvência Geral), informando a fórmula e o resultado.
                5. Verifique a qualificação técnica (atestados) conforme o objeto do edital.

                FORMATO DO PARECER TÉCNICO:
                Organize a saída de forma limpa e formal para impressão:
                - **Cabeçalho do Parecer:** Objeto resumido do edital, Empresa analisada e CNPJ.
                - **Tabela Resumo de Conformidade:** Colunas [Documento / Exigência | Status (CONFORME / IRREGULAR / AUSENTE) | Observação e Validade].
                - **Análise Detalhada e Cálculos:** Detalhamento técnico de cada ponto crítico ou cálculo contábil realizado.
                - **Conclusão / Veredito:** Parecer final claro indicando se a documentação está APTA ou INAPTA para o credenciamento, listando eventuais pendências para diligência.
                """

                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Part.from_bytes(data=edital_pdf.read(), mime_type="application/pdf"),
                        types.Part.from_bytes(data=docs_pdf.read(), mime_type="application/pdf"),
                        prompt
                    ]
                )

                st.session_state["parecer"] = response.text

            except Exception as e:
                st.error(f"Erro ao processar os documentos: {e}")

# Exibição do Parecer e Botão de Impressão
if "parecer" in st.session_state:
    st.divider()
    st.subheader("📄 Parecer Técnico de Habilitação")
    
    # Botão que aciona a janela de impressão do navegador (permite imprimir ou Salvar como PDF)
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

    # Renderiza o parecer limpo na tela
    st.markdown(st.session_state["parecer"])
