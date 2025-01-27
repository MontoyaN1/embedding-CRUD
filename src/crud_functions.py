import chromadb
import uuid
import requests
import streamlit as st
import time
import re
import logging
from huggingface_hub import InferenceClient

# Inicilizamos ChromaDb y nuestra API KEY
client = chromadb.EphemeralClient()
collection = client.get_or_create_collection(name="hf_text_collection")
API_KEY = "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"
_client = None


def extraer_titulo(texto):
    """Extrae el título de las primeras líneas del documento"""
    # Buscar hasta el primer salto de línea o punto seguido de espacio
    titulo_match = re.search(
        r"(?:^[\s\r\n]*)(.+?)(?=\s*[\r\n]|$)", texto, flags=re.DOTALL | re.MULTILINE
    )

    if titulo_match:
        titulo = titulo_match.group(1)
        # Limpieza avanzada
        titulo_limpio = re.sub(r"[\s\r\n]+", " ", titulo).strip()

        if titulo_limpio:
            # Acortar manteniendo palabras completas
            if len(titulo_limpio) > 100:
                return titulo_limpio[:100].rsplit(" ", 1)[0] + "..."
            return titulo_limpio

    # Fallback mejorado: primeras palabras clave no vacías
    palabras = [p for p in re.split(r"\s+", texto.strip()) if p][:8]
    return " ".join(palabras) if palabras else "Documento sin título"


def get_client():
    global _client
    if _client is None:
        _client = InferenceClient(api_key=API_KEY)
    return _client


def generar_resumen(texto: str) -> str:
    client = InferenceClient(api_key=API_KEY)  # Sin parámetro provider

    # Optimización del prompt y longitud
    prompt = f"""Genera una descripción del siguiente texto:
    {texto[:200]}  
    
    """

    try:
        response = client.text_generation(
            prompt=prompt,
            model="deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
            max_new_tokens=150,  # Reducido para mejor coherencia
            temperature=0.3,
            repetition_penalty=1.2,
        )

        # Post-procesamiento para limpiar la respuesta
        return response.split("\n")[0].strip().replace("**Resumen:**", "")

    except TimeoutError as e:
        logging.warning(f"Error recuperable: {e}")
        raise  # Para reintentos
    except Exception as e:
        logging.error(f"Error crítico: {e}")
        raise RuntimeError(f"Fallo en generación: {str(e)}") from e


def procesar_documento(texto):
    """Pipeline completo de procesamiento"""
    return {"titulo": extraer_titulo(texto), "descripcion": generar_resumen(texto)}


def generar_embedding(texto):
    API_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
    headers = {"Authorization": f"Bearer {API_KEY}"}

    try:
        # Limpiar y truncar texto (máximo 512 tokens)
        texto_limpio = texto[:4000].replace("\n", " ").strip()
        if not texto_limpio:
            raise ValueError("Texto vacío")

        # Enviar solicitud con formato correcto
        response = requests.post(
            API_URL,
            headers=headers,
            json={"inputs": [texto_limpio]},  # ¡Lista de textos!
        )

        # Verificar errores HTTP y de modelo
        if response.status_code != 200:
            error_msg = response.json().get("error", "Error desconocido")
            raise ValueError(f"API Error: {error_msg}")

        # Extraer embedding correctamente
        embeddings = response.json()
        if not isinstance(embeddings, list) or len(embeddings) == 0:
            raise ValueError("Respuesta inválida de la API")

        embedding = embeddings[0]  # Primer texto enviado → primer embedding
        if len(embedding) != 384:  # Tamaño esperado del modelo
            raise ValueError(f"Tamaño de embedding incorrecto: {len(embedding)}")

        return embedding

    except Exception as e:
        st.error(f"🚨 Error en generar_embedding: {str(e)}")
        return None


def crear_entrada(texto):
    try:
        # Paso 1: Generar embedding
        embedding = generar_embedding(texto)
        if embedding is None:
            st.error("No se pudo generar el embedding")
            return

        # Paso 2: Generar metadatos con reintentos
        metadata = procesar_documento(texto)

        # Paso 3: Insertar en ChromaDB
        doc_id = str(uuid.uuid4())
        collection.add(
            documents=[texto],
            metadatas=[metadata],
            ids=[doc_id],
            embeddings=[embedding],
        )

        st.toast("Documento guardado correctamente", icon="✅")
        st.session_state.ultima_actualizacion = time.time()
        st.rerun()

    except Exception as e:
        st.error(f"Error crítico al guardar: {str(e)}")
        raise  # Propagar el error para debug


def leer_vector(id):
    try:
        results = collection.get(ids=[id], include=["metadatas", "documents"])
        if not results["documents"]:
            st.warning(f"⚠️ No se encontró la entrada con ID: {id}")
            return None

        st.success("✅ Entrada encontrada")
        return {
            "id": id,
            "documento": results["documents"][0],
            "metadata": results["metadatas"][0],
        }
    except Exception as e:
        st.error(f"🚨 Error al leer: {str(e)}")
        return None


def actualizar_registro(id, new_texto):
    try:
        # Regenerar embedding y metadatos
        new_embedding = generar_embedding(new_texto)
        new_metadata = procesar_documento(new_texto)

        # Actualizar directamente en ChromaDB
        collection.update(
            ids=[id],
            documents=[new_texto],
            metadatas=[new_metadata],
            embeddings=[new_embedding],
        )
        st.success(f"✅ Entrada {id} actualizada")
    except Exception as e:
        st.error(f"🚨 Error al actualizar: {str(e)}")


def eliminar_registro(doc_id):
    try:
        # Verificar existencia antes de eliminar
        if not collection.get(ids=[doc_id])["ids"]:
            st.error("⚠️ El documento no existe")
            return

        # Eliminar y confirmar
        collection.delete(ids=[doc_id])
        st.toast(f"Documento {doc_id[:8]} eliminado", icon="✅")
        st.session_state.ultima_eliminacion = time.time()

    except Exception as e:
        st.error(f"Error al eliminar: {str(e)}")
        raise


def buscar_entradas(consulta):
    try:
        query_embedding = generar_embedding(consulta)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=3,
            include=["documents", "metadatas", "distances"],
        )

        formatted_results = []
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            formatted_results.append(
                {
                    "titulo": meta.get("titulo", "Sin título"),
                    "descripcion": meta.get("descripcion", ""),
                    "similitud": f"{1 - dist:.2f}",  # Convertir distancia a similitud
                    "contenido": doc,
                }
            )

        return formatted_results

    except Exception as e:
        logging.critical(f"Error inesperado: {e}")
        raise
