import streamlit as st
from views import up_documents, view_documents, buscar_tema


def main():
    st.set_page_config(
        page_title="Administrar Documentos", page_icon="📄", layout="centered"
    )

    st.title("Análisis de documentos")

    st.text("Mira, carga, actualiza, elimina y busca temas en tus documentos")

    listar, agregar, buscar = st.tabs(
        ["Ver Documentos", "Agregar Documentos", "Buscar por tema"]
    )

    with listar:
        view_documents()

    with agregar:
        st.header("📄 Cargar Documentos (TXT, PDF, DOCX)")
        up_documents()
    with buscar:
        st.header("Busca documentos relacionados con un tema de interes")
        buscar_tema()


if __name__ == "__main__":
    main()
