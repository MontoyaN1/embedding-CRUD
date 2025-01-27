import streamlit as st
from PyPDF2 import PdfReader
from docx import Document
from crud_functions import (
    collection,
    crear_entrada,
    eliminar_registro,
    generar_embedding,
)
import numpy as np


def up_documents():
    uploaded_file = st.file_uploader(
        "Selecciona un archivo",
        type=["txt", "pdf", "docx"],
        accept_multiple_files=False,
    )

    if uploaded_file is not None:
        cargar_documento(uploaded_file)


def cargar_documento(uploaded_file):
    try:
        # Validar nombre y extensión
        if "." not in uploaded_file.name:
            raise ValueError("El archivo no tiene extensión válida")

        file_extension = uploaded_file.name.split(".")[-1].lower()
        if file_extension not in ["txt", "pdf", "docx"]:
            raise ValueError("Formato no soportado")

        # Leer contenido
        content = ""
        if file_extension == "txt":
            content = uploaded_file.read().decode("utf-8", errors="replace")
        elif file_extension == "pdf":
            pdf_reader = PdfReader(uploaded_file)
            content = "\n".join(
                [page.extract_text() or "" for page in pdf_reader.pages]
            )
        elif file_extension == "docx":
            doc = Document(uploaded_file)
            content = "\n".join([p.text for p in doc.paragraphs])

        # Validar contenido no vacío
        if not content.strip():
            raise ValueError("El archivo está vacío o no tiene texto extraíble")

        # Mostrar vista previa
        with st.expander("Vista previa del contenido"):
            st.text(content[:2000] + ("..." if len(content) > 2000 else ""))

        # Botón de carga
        if st.button("Cargar documento", key=f"btn_{uploaded_file.name}"):
            with st.spinner("Procesando..."):
                crear_entrada(content)

    except Exception as e:
        st.error(f"🚨 Error al procesar el archivo: {str(e)}")
        st.stop()  # Detener ejecución para evitar errores en cadena


def view_documents():
    st.title("📚 Documentos Almacenados")

    try:
        # Obtener todos los datos necesarios de ChromaDB
        resultados = collection.get(include=["documents", "metadatas", "embeddings"])

        if not resultados["ids"]:
            st.warning("La base de datos está vacía")
            return

        # Crear tarjetas para cada documento
        mostrar_documentos(resultados)
        # Estadísticas generales
        with st.sidebar:
            st.subheader("Estadísticas")
            st.metric("Total Documentos", len(resultados["ids"]))
            st.metric(
                "Long. Promedio",
                f"{sum(len(d) for d in resultados['documents']) // len(resultados['documents'])} caracteres",
            )

    except Exception as e:
        st.error(f"Error al cargar documentos: {str(e)}")


def mostrar_documentos(resultados):
    for idx, (doc_id, documento, metadata) in enumerate(
        zip(resultados["ids"], resultados["documents"], resultados["metadatas"])
    ):
        titulo = metadata.get("titulo", "Documento sin título")
        descripcion = metadata.get("descripcion", "Sin descripción")
        with st.expander(f"Documento #{idx + 1}", expanded=False):
            st.subheader(metadata.get("titulo", "Sin Título"))
            st.markdown(
                f"**Descripción**: {metadata.get('descripcion', 'Sin descripción disponible')}"
            )

            # Sección de contenido con scroll
            with st.container(height=350):
                st.markdown("**Contenido:**")
                st.text_area(
                    value=documento,
                    label="Contenido del documento (solo lectura)",
                    disabled=True,
                    height=250,
                    key=doc_id,
                )
            # Acciones para cada documento
            with st.container():
                cols = st.columns(2)
                with cols[0]:
                    if st.button("🗑️ Eliminar", key=f"del_{doc_id}"):
                        eliminar_registro(doc_id)
                        st.rerun()  # Fuerza recarga de la vista
                with cols[1]:
                    if st.button("✏️ Editar", key=f"edit_{doc_id}"):
                        edit_documents(doc_id, documento, titulo, descripcion)

            st.markdown("---")


def editar_documento(doc_id, nuevo_texto=None, nuevos_metadatos=None):
    try:
        # Actualizar documento (si se proporciona)
        if nuevo_texto:
            nuevo_embedding = generar_embedding(nuevo_texto)
            collection.update(
                ids=[doc_id], documents=[nuevo_texto], embeddings=[nuevo_embedding]
            )

        # Actualizar metadatos (si se proporcionan)
        if nuevos_metadatos:
            collection.update(ids=[doc_id], metadatas=[nuevos_metadatos])

        st.success("✅ Actualización exitosa")

    except Exception as e:
        st.error(f"🚨 Error al actualizar: {str(e)}")


@st.dialog("Actualizar tareas")
def edit_documents(doc_id, documento, titulo, descripcion):
    with st.form("Actualizar "):
        nuevo_titulo = st.text_input(
            "Nuevo título (opcional)",
            value=titulo,
        )
        nueva_desc = st.text_input(
            "Nueva descripción (opcional)",
            value=descripcion,
        )
        nuevo_texto = st.text_area("Nuevo contenido (opcional)", value=documento)

        if st.form_submit_button("Actualizar"):
            nuevos_metadatos = {"titulo": nuevo_titulo, "descripcion": nueva_desc}
            editar_documento(doc_id, nuevo_texto, nuevos_metadatos)
            st.rerun()


def buscar_tema():
    with st.container():
        st.markdown('<div class="search-box">', unsafe_allow_html=True)
        col1, col2 = st.columns([5, 1])
        with col1:
            query = st.text_input(
                " ",
                placeholder="Busca documentos, artículos o recursos...",
                label_visibility="collapsed",
            )
        with col2:
            search_clicked = st.button("Buscar", use_container_width=True)

    # Lógica de búsqueda
    if search_clicked or query:
        with st.spinner("Analizando documentos..."):
            mostrar_busqueda(query)


def mostrar_busqueda(query):
    try:
        # 1. Generar embedding de la consulta
        query_embedding = generar_embedding(query)
        st.session_state["last_query_embedding"] = query_embedding  # Para debug

        # 2. Buscar en la base vectorial (CON DIAGNÓSTICO)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=10,
            include=["documents", "metadatas", "distances", "embeddings"],
        )

        # 3. Validar resultados
        if not results["ids"][0]:
            st.error("⚠️ No se encontraron coincidencias. Posibles causas:")
            st.markdown("""
                    - **Los documentos no están indexados correctamente**
                    - **El embedding de la consulta es muy diferente a los documentos**
                    - **Umbral de similitud demasiado alto**
                    """)
            return

            # 4. Calcular similitudes detalladas
        doc_embeddings = np.array(results["embeddings"][0])
        query_embedding_np = np.array(query_embedding)

        # Calcular similitud coseno
        similitudes = np.dot(doc_embeddings, query_embedding_np) / (
            np.linalg.norm(doc_embeddings, axis=1) * np.linalg.norm(query_embedding_np)
        )

        # 5. Mostrar resultados con métricas de debug
        st.subheader("Resultados")
        for idx, (doc_id, meta, doc_content, similitud) in enumerate(
            zip(
                results["ids"][0],
                results["metadatas"][0],
                results["documents"][0],
                similitudes,
            )
        ):
            documentos_filtrados = 0

            if similitud >= 0.15:
                documentos_filtrados += 1
                with st.expander(
                    f"{meta.get('titulo', 'Documento sin título')}",
                    expanded=(documentos_filtrados == 1),
                ):
                    st.metric("Similitud", f"{similitud:.2%}")

                    st.write("**Contenido:**")
                    id_unique = doc_id + str(idx)
                    st.text_area(
                        value=doc_content,
                        label="Contenido del documento (solo lectura)",
                        disabled=True,
                        height=250,
                        key=id_unique,
                    )

    except Exception as e:
        st.exception(e)
