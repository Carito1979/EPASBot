import os
import re
import random
import unicodedata
from typing import Dict, List, Optional, Tuple
from flask import Flask, render_template, request, jsonify
from PyPDF2 import PdfReader
import fitz  # PyMuPDF
import easyocr
import numpy as np
from PIL import Image
import io

app = Flask(__name__, template_folder='templates', static_folder='static')

# Estados del chatbot
ESTADOS = {
    'INICIO': 0,
    'SOLICITAR_CEDULA': 1,
    'FINAL': 2,
    'PREGUNTAS_FRECUENTES': 3,
    'MENU_PRINCIPAL': 4  
}

PREGUNTAS_FRECUENTES = {
    "documentos": {
        "pregunta": "¿Qué documentos necesito para la etapa productiva?",
        "respuesta": "Los documentos requeridos son:<br>1. Documento de identidad<br>2. Formato F-023 (Acta de inicio)<br>3. Evaluación de etapa productiva"
    },
    "fechas": {
        "pregunta": "¿Cuáles son las fechas importantes?",
        "respuesta": "Las fechas clave son:<br>- Inicio etapa productiva: 15 de julio<br>- Entrega evaluaciones: 30 de noviembre<br>- Finalización: 15 de diciembre"
    },
    "horas": {
        "pregunta": "¿Cuántas horas debe tener la etapa productiva?",
        "respuesta": "La etapa productiva debe tener mínimo 880 horas según el programa de formación."
    }
}

# Configuración de paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'database.txt')
DOCUMENTOS_PATH = os.path.join(BASE_DIR, 'documentos')

# Inicializar EasyOCR
reader = easyocr.Reader(['es'], gpu=False)

def normalize_text(text: str) -> str:
    """Normaliza el texto para búsquedas más confiables"""
    if not text:
        return ""
    
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII').lower()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def load_database() -> Dict[str, dict]:
    """Carga la base de datos de usuarios en memoria con la nueva estructura"""
    database = {}
    try:
        with open(DATABASE_PATH, 'r', encoding='utf-8') as file:
            # Saltar la primera línea de encabezados si existe
            headers = file.readline().strip().split('|')
            
            for line in file:
                parts = line.strip().split('|')
                if len(parts) >= 10:  # Asegurar que tenemos todos los campos
                    documento = parts[1].strip()  # Usar NumeroDocumento como clave
                    database[documento] = {
                        'tipo_documento': parts[0].strip(),
                        'nombres': to_capital_case(parts[2].strip()),
                        'apellido1': to_capital_case(parts[3].strip()),
                        'apellido2': to_capital_case(parts[4].strip()),
                        'ficha': parts[5].strip(),
                        'codigo': parts[6].strip(),
                        'version_programa': parts[7].strip(),
                        'programa': to_capital_case(parts[8].strip()),
                        'nivel_formacion': to_capital_case(parts[9].strip())
                    }
    except FileNotFoundError:
        print(f"⚠️ Archivo de base de datos no encontrado en {DATABASE_PATH}")
    return database

def detectar_intencion(texto: str) -> str:
    """Detecta la intención del usuario basado en su mensaje"""
    texto = texto.lower().strip()
    
    # Saludos
    saludos = ['hola', 'hi', 'buenos días', 'buenas tardes', 'buenas noches']
    if any(s in texto for s in saludos):
        return 'saludo'
    
    # Preguntas frecuentes
    if 'documento' in texto or 'requisito' in texto or 'necesito' in texto:
        return 'documentos'
    if 'fecha' in texto or 'cuándo' in texto or 'día' in texto:
        return 'fechas'
    if 'hora' in texto or 'dura' in texto or 'tiempo' in texto:
        return 'horas'
    if 'ayuda' in texto or 'pregunta' in texto or 'frecuente' in texto:
        return 'ayuda'
    
    # Consulta estado
    if any(palabra in texto for palabra in ['estado', 'documento', 'cedula', 'cédula', 'identificación']):
        return 'consulta'
    
    return 'desconocido'

def extract_text_with_easyocr(image: Image.Image) -> str:
    """Extrae texto de una imagen usando EasyOCR"""
    try:
        img_array = np.array(image)
        results = reader.readtext(img_array, paragraph=True)
        full_text = "\n".join([result[1] for result in results])
        return full_text
    except Exception as e:
        print(f"⚠️ Error en EasyOCR: {str(e)}")
        return ""

def pdf_to_images(pdf_path: str) -> List[Image.Image]:
    """Convierte PDF a imágenes usando PyMuPDF"""
    images = []
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
        return images
    except Exception as e:
        print(f"⚠️ Error al convertir PDF a imágenes: {str(e)}")
        return []

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extrae texto de un PDF usando PyPDF2 + EasyOCR (con PyMuPDF para imágenes)"""
    try:
        # Extraer texto directo con PyPDF2
        reader_pdf = PdfReader(pdf_path)
        full_text = ""
        for page in reader_pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"
        
        # Si hay poco texto, usar OCR en imágenes generadas con PyMuPDF
        if len(full_text.strip()) < 100:
            print(f"🔍 Usando EasyOCR para {pdf_path}")
            images = pdf_to_images(pdf_path)
            for image in images:
                ocr_text = extract_text_with_easyocr(image)
                if ocr_text:
                    full_text += "\n" + ocr_text
        
        return full_text
    except Exception as e:
        print(f"⚠️ Error procesando PDF {pdf_path}: {str(e)}")
        return ""
    
def to_capital_case(text: str) -> str:
    """Convierte un texto a Capital Case (primera letra mayúscula, resto minúsculas)"""
    if not text:
        return text
    return ' '.join(word.capitalize() for word in text.split())

def search_in_pdf(file_path: str, cedula: str, nombre: str) -> Tuple[bool, bool]:
    """Busca cédula y nombre en un archivo PDF"""
    try:
        full_text = extract_text_from_pdf(file_path)
        
        if not full_text:
            return (False, False)
        
        norm_text = normalize_text(full_text)
        norm_cedula = normalize_text(cedula)
        norm_nombre = normalize_text(nombre)
        
        # Búsqueda de cédula
        cedula_found = False
        if norm_cedula:
            clean_cedula = re.sub(r'\D', '', norm_cedula)
            clean_text_cedula = re.sub(r'\D', '', norm_text)
            cedula_found = clean_cedula in clean_text_cedula
            
            if not cedula_found and len(clean_cedula) >= 4:
                last_digits = clean_cedula[-4:]
                patterns = [
                    rf'cc\D*{last_digits}',
                    rf'c[ée]dula\D*{last_digits}',
                    rf'documento\D*{last_digits}',
                    rf'identificaci[óo]n\D*{last_digits}'
                ]
                for pattern in patterns:
                    if re.search(pattern, norm_text, re.IGNORECASE):
                        cedula_found = True
                        break
        
        # Búsqueda de nombre
        name_found = False
        if norm_nombre:
            name_parts = norm_nombre.split()
            if len(name_parts) >= 2:
                matches = sum(1 for part in name_parts if re.search(r'\b' + re.escape(part) + r'\b', norm_text))
                name_found = matches >= 2
                
                if not name_found:
                    name_pattern = r'\b' + r'\s+'.join([re.escape(part) for part in name_parts]) + r'\b'
                    name_found = bool(re.search(name_pattern, norm_text))
        
        return (cedula_found, name_found)
    except Exception as e:
        print(f"⚠️ Error procesando {file_path}: {str(e)}")
        return (False, False)

def check_documents(cedula: str, nombre: str) -> Tuple[Dict[str, bool], List[str]]:
    """Verifica todos los tipos de documentos para coincidencias y devuelve pasos del proceso"""
    doc_types = ['cedulas', 'actas', 'evaluaciones']
    results = {t: False for t in doc_types}
    proceso = []
    
    for doc_type in doc_types:
        dir_path = os.path.join(DOCUMENTOS_PATH, doc_type)
        if not os.path.exists(dir_path):
            proceso.append(f"⚠️ Directorio no encontrado: {doc_type}")
            continue
        
        proceso.append(f"🔍 Buscando en {doc_type}...")
        found = False
        
        for filename in os.listdir(dir_path):
            if filename.lower().endswith('.pdf'):
                file_path = os.path.join(dir_path, filename)
                proceso.append(f"   Procesando archivo: {filename}")
                
                # Extraer texto del PDF
                proceso.append("   Extrayendo texto del PDF...")
                full_text = extract_text_from_pdf(file_path)
                
                if not full_text:
                    proceso.append("   No se pudo extraer texto, usando OCR...")
                
                # Buscar coincidencias
                proceso.append("   Buscando coincidencias...")
                cedula_found, name_found = search_in_pdf(file_path, cedula, nombre)
                
                if cedula_found or name_found:
                    proceso.append(f"   ✅ Coincidencia encontrada en {filename}")
                    found = True
                    break
        
        results[doc_type] = found
        proceso.append(f"📌 Resultado para {doc_type}: {'ENCONTRADO' if found else 'NO ENCONTRADO'}")
    
    return results, proceso

def buscar_estudiante(database, criterio, valor):
    """
    Busca estudiantes según diferentes criterios
    :param criterio: 'documento', 'nombre', 'codigo'
    :param valor: valor a buscar
    :return: lista de (documento, datos_estudiante)
    """
    resultados = []
    for doc, datos in database.items():
        if criterio == 'documento' and doc == valor:
            return [(doc, datos)]  # Retorna inmediato para documento
        
        if criterio == 'nombre':
            nombre_completo = f"{datos['nombres']} {datos['apellido1']} {datos['apellido2']}"
            if valor.lower() in nombre_completo.lower():
                resultados.append((doc, datos))
        
        if criterio == 'codigo' and datos['codigo'] == valor:
            resultados.append((doc, datos))
    
    return resultados

def procesar_inicio(intencion, contexto):
    """Maneja el estado inicial con saludo personalizado"""
    if intencion == 'saludo':
        # Saludo aleatorio para hacerlo más natural
        saludos = [
            "¡Hola! Soy EPASBot, tu asistente para la Etapa Productiva. 😊",
            "¡Hola! ¿En qué puedo ayudarte hoy con tu etapa productiva?",
            "¡Buen día! Soy tu asistente virtual del SENA. ¿Cómo estás?"
        ]
        saludo = random.choice(saludos)
        
        return {
            'mensaje': f"{saludo}<br><br>Por favor selecciona una opción:<br>"
                      "1. 📄 Consultar estado de documentos<br>"
                      "2. ❓ Preguntas frecuentes<br>"
                      "3. ℹ️ Información sobre etapa productiva",
            'estado': ESTADOS['MENU_PRINCIPAL'],
            'mostrar_reinicio': False,
            'contexto': {'ultimo_saludo': saludo}
        }
    
    # Si no es un saludo, ofrecer ayuda
    return {
        'mensaje': "¡Bienvenido a EPASBot! 🤖<br><br>"
                  "Puedo ayudarte con:<br>"
                  "1. 📄 Consultar estado de documentos<br>"
                  "2. ❓ Preguntas frecuentes<br>"
                  "3. ℹ️ Información sobre etapa productiva<br><br>"
                  "¿Qué necesitas? (1-3)",
        'estado': ESTADOS['MENU_PRINCIPAL'],
        'mostrar_reinicio': False
    }

def procesar_menu_principal(mensaje_usuario, contexto):
    """Maneja el menú principal con opciones interactivas"""
    mensaje = mensaje_usuario.lower().strip()
    
    # Opción 1: Consultar documentos
    if '1' in mensaje or 'documento' in mensaje or 'estado' in mensaje:
        return {
            'mensaje': "Por favor ingresa tu número de documento (cédula) para verificar tu matrícula y documentos:",
            'estado': ESTADOS['SOLICITAR_CEDULA'],
            'mostrar_reinicio': False,
            'contexto': {'opcion_elegida': 'documentos'}
        }
    
    # Opción 2: Preguntas frecuentes
    elif '2' in mensaje or 'pregunta' in mensaje or 'frecuente' in mensaje:
        opciones = "<br>".join([
            f"{i+1}. {v['pregunta']}" 
            for i, (k, v) in enumerate(PREGUNTAS_FRECUENTES.items())
        ])
        return {
            'mensaje': f'Estas son nuestras preguntas frecuentes:<br>{opciones}<br><br>¿Cuál deseas consultar? (1-{len(PREGUNTAS_FRECUENTES)})',
            'estado': ESTADOS['PREGUNTAS_FRECUENTES'],
            'mostrar_reinicio': False,
            'contexto': {'opcion_elegida': 'preguntas_frecuentes'}
        }
    
    # Opción 3: Información etapa productiva
    elif '3' in mensaje or 'información' in mensaje or 'etapa' in mensaje:
        info_etapa = (
            "La <b>Etapa Productiva</b> es el espacio donde aplicas tus conocimientos:<br><br>"
            "📅 <b>Duración:</b> 880 horas mínimo<br>"
            "📝 <b>Requisitos:</b><br>"
            "   - Documento de identidad<br>"
            "   - Formato F-023 (Acta de inicio)<br>"
            "   - Evaluación de etapa productiva<br><br>"
            "¿Te gustaría saber algo más específico?"
        )
        return {
            'mensaje': info_etapa,
            'estado': ESTADOS['MENU_PRINCIPAL'],
            'mostrar_reinicio': False,
            'contexto': {'opcion_elegida': 'info_etapa'}
        }
    
    # Si no se reconoce la opción
    return {
        'mensaje': "No entendí tu selección. Por favor elige:<br>"
                  "1. 📄 Consultar documentos<br>"
                  "2. ❓ Preguntas frecuentes<br>"
                  "3. ℹ️ Información etapa productiva",
        'estado': ESTADOS['MENU_PRINCIPAL'],
        'mostrar_reinicio': False
    }

def procesar_preguntas_frecuentes(mensaje_usuario, contexto):
    """Procesa las preguntas frecuentes seleccionadas por el usuario"""
    if mensaje_usuario.isdigit() and 1 <= int(mensaje_usuario) <= len(PREGUNTAS_FRECUENTES):
        clave = list(PREGUNTAS_FRECUENTES.keys())[int(mensaje_usuario)-1]
        return {
            'mensaje': f"<b>{PREGUNTAS_FRECUENTES[clave]['pregunta']}</b><br><br>{PREGUNTAS_FRECUENTES[clave]['respuesta']}<br><br>¿Necesitas algo más? (sí/no)",
            'estado': ESTADOS['FINAL'],
            'mostrar_reinicio': True,
            'contexto': contexto
        }
    
    opciones = "<br>".join([f"{i+1}. {v['pregunta']}" for i, (k, v) in enumerate(PREGUNTAS_FRECUENTES.items())])
    return {
        'mensaje': f'Opción no válida. Estas son nuestras preguntas frecuentes:<br>{opciones}<br><br>¿Cuál deseas consultar? (1-{len(PREGUNTAS_FRECUENTES)})',
        'estado': ESTADOS['PREGUNTAS_FRECUENTES'],
        'mostrar_reinicio': False,
        'contexto': contexto
    }

def procesar_cedula(mensaje_usuario, database, contexto):
    """Procesa el número de cédula ingresado por el usuario"""
    if not mensaje_usuario.isdigit() or len(mensaje_usuario) < 8 or len(mensaje_usuario) > 10:
        return {
            'mensaje': 'Documento inválido. Debe tener entre 8 y 10 dígitos. Intenta nuevamente:',
            'estado': ESTADOS['SOLICITAR_CEDULA'],
            'mostrar_reinicio': False,
            'proceso': ["Validación de documento fallida"],
            'contexto': contexto
        }
    
    estudiante = database.get(mensaje_usuario)
    if not estudiante:
        return {
            'mensaje': '❌ No encontramos tu documento en nuestros registros. ¿Estás seguro de estar matriculado en el SENA?',
            'estado': ESTADOS['FINAL'],
            'mostrar_reinicio': True,
            'encontrado': False,
            'proceso': ["Búsqueda en base de datos completada", "Documento no encontrado"],
            'contexto': contexto
        }
    
    nombre_completo = f"{estudiante['nombres']} {estudiante['apellido1']} {estudiante['apellido2']}"
    doc_results, proceso = check_documents(mensaje_usuario, nombre_completo)
    missing_docs = [k for k, v in doc_results.items() if not v]

    mensaje = f"¡Bienvenido(a), <b>{nombre_completo}</b>! Estudiante del programa {estudiante['programa']} (Ficha {estudiante['ficha']}).<br><br>"

    if not missing_docs:
        mensaje += "✅ ¡Felicidades! Tienes TODOS tus documentos al día:<br>"
        mensaje += "• Documento de Identidad<br>• Formato F-023 <br>• Evaluación Etapa Productiva."
    else:
        mensaje += "❌ Documentos faltantes:<br>"
        if 'cedulas' in missing_docs:
            mensaje += f"• Documento ({estudiante['tipo_documento']}): No encontrado en nuestros registros<br>"
        if 'actas' in missing_docs:
            mensaje += "• F-023: No encontrada en formatos de curso<br>"
        if 'evaluaciones' in missing_docs:
            mensaje += "• Evaluación: No encontrada en evaluación etapa productiva<br>"
        mensaje += "<br>Por favor entrega los documentos faltantes a coordinación."

    return {
        'mensaje': mensaje,
        'estado': ESTADOS['FINAL'],
        'mostrar_reinicio': True,
        'encontrado': True,
        'proceso': proceso,
        'contexto': contexto
    }

def procesar_final(mensaje_usuario, contexto):
    """Procesa la respuesta final del usuario (si quiere continuar o no)"""
    mensaje = mensaje_usuario.lower()
    if mensaje in ['sí', 'si', 'yes', 's', '1']:
        return {
            'mensaje': '¡Perfecto! ¿Cómo puedo ayudarte?<br>'
                      '1. Consultar estado de documentos<br>'
                      '2. Preguntas frecuentes<br>'
                      '3. Información sobre etapa productiva',
            'estado': ESTADOS['MENU_PRINCIPAL'],
            'mostrar_reinicio': False,
            'contexto': contexto
        }
    elif mensaje in ['no', 'n', '2']:
        return {
            'mensaje': '¡Gracias por usar nuestro servicio! Si necesitas más ayuda, no dudes en volver.',
            'estado': ESTADOS['INICIO'],
            'mostrar_reinicio': True,
            'contexto': contexto
        }
    return {
        'mensaje': '¿Necesitas realizar otra consulta? (sí/no)',
        'estado': ESTADOS['FINAL'],
        'mostrar_reinicio': True,
        'contexto': contexto
    }

@app.route('/')
def home():
    """Ruta principal que renderiza la interfaz del chatbot"""
    return render_template('chatbot.html')

@app.route('/procesar', methods=['POST'])
def procesar():
    """Procesa los mensajes del usuario y devuelve respuestas del chatbot"""
    data = request.get_json()
    estado_actual = data.get('estado', ESTADOS['INICIO'])
    mensaje_usuario = data.get('mensaje', '').strip()
    es_consulta_proceso = data.get('proceso', False)
    contexto = data.get('contexto', {})
    
    respuesta = {
        'mensaje': '',
        'estado': estado_actual,
        'mostrar_reinicio': False,
        'encontrado': None,
        'proceso': [],
        'contexto': contexto
    }
    
    database = load_database()
    intencion = detectar_intencion(mensaje_usuario)

    # Manejo de estados
    if estado_actual == ESTADOS['INICIO']:
        respuesta.update(procesar_inicio(intencion, contexto))
    
    elif estado_actual == ESTADOS['MENU_PRINCIPAL']:
        respuesta.update(procesar_menu_principal(mensaje_usuario, contexto))
    
    elif estado_actual == ESTADOS['PREGUNTAS_FRECUENTES']:
        respuesta.update(procesar_preguntas_frecuentes(mensaje_usuario, contexto))
    
    elif estado_actual == ESTADOS['SOLICITAR_CEDULA']:
        if es_consulta_proceso:
            # Simular progreso de búsqueda
            respuesta['proceso'] = [
                "🔍 Buscando en base de datos...",
                "✓ Datos del estudiante encontrados",
                "📁 Abriendo archivos PDF..."
            ]
        else:
            respuesta.update(procesar_cedula(mensaje_usuario, database, contexto))
    
    elif estado_actual == ESTADOS['FINAL']:
        respuesta.update(procesar_final(mensaje_usuario, contexto))
    
    return jsonify(respuesta)

def initialize_application():
    """Inicializa archivos y directorios requeridos con la nueva estructura"""
    if not os.path.exists(DATABASE_PATH):
        with open(DATABASE_PATH, 'w', encoding='utf-8') as file:
            file.write("TipoDocumento|NumeroDocumento|Nombres|Apellido1|Apellido2|Ficha|Codigo|VersionPrograma|Programa|NivelFormacion\n")
            file.write("CC|1032508266|NICOLLE ALEJANDRA|GONZALEZ|RODRIGUEZ|2944777|233108|1|SISTEMAS TELEINFORMÁTICOS|TÉCNICO\n")
            file.write("CC|1233506810|JULIAN|ALDANA|MAZO|2944777|233108|1|SISTEMAS TELEINFORMÁTICOS|TÉCNICO\n")
            file.write("CC|1022922610|NICOLE VANESSA|AGUIRRE|LATORRE|2944777|233108|1|SISTEMAS TELEINFORMÁTICOS|TÉCNICO\n")
            file.write("CC|1023019031|BELLANIRA|ALDANA|ARANGO|2944777|233108|1|SISTEMAS TELEINFORMÁTICOS|TÉCNICO\n")
            file.write("TI|1021805727|BRAHIAN|BERMUDEZ|TORRES|2944777|233108|1|SISTEMAS TELEINFORMÁTICOS|TÉCNICO\n")
    
    os.makedirs(os.path.join(DOCUMENTOS_PATH, 'cedulas'), exist_ok=True)
    os.makedirs(os.path.join(DOCUMENTOS_PATH, 'actas'), exist_ok=True)
    os.makedirs(os.path.join(DOCUMENTOS_PATH, 'evaluaciones'), exist_ok=True)
    
    print("\n" + "="*50)
    print("📂 Aplicación Inicializada:")
    print(f"- Base de datos: {DATABASE_PATH}")
    print(f"- Directorio de documentos: {DOCUMENTOS_PATH}")
    print("="*50 + "\n")

if __name__ == '__main__':
    initialize_application()
    app.run(debug=True, port=5000)


