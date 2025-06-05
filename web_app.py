from flask import Flask, render_template, request, jsonify
import os
from PyPDF2 import PdfReader
import re
import unicodedata
from typing import Dict, List, Optional, Tuple
import io
import fitz  # PyMuPDF
import easyocr
import numpy as np
from PIL import Image

app = Flask(__name__, template_folder='templates', static_folder='static')

# Estados del chatbot
ESTADOS = {
    'INICIO': 0,
    'SOLICITAR_CEDULA': 1,
    'FINAL': 2
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

def check_documents(cedula: str, nombre: str) -> Dict[str, bool]:
    """Verifica todos los tipos de documentos para coincidencias"""
    doc_types = ['cedulas', 'actas', 'evaluaciones']
    results = {t: False for t in doc_types}
    
    for doc_type in doc_types:
        dir_path = os.path.join(DOCUMENTOS_PATH, doc_type)
        if not os.path.exists(dir_path):
            print(f"⚠️ Directorio no encontrado: {dir_path}")
            continue
        
        print(f"\n🔍 Buscando en {doc_type}...")
        found = False
        
        for filename in os.listdir(dir_path):
            if filename.lower().endswith('.pdf'):
                file_path = os.path.join(dir_path, filename)
                cedula_found, name_found = search_in_pdf(file_path, cedula, nombre)
                
                if cedula_found or name_found:
                    print(f"✅ Coincidencia encontrada en {filename}:")
                    print(f"   - Cédula: {'✔' if cedula_found else '✖'}")
                    print(f"   - Nombre: {'✔' if name_found else '✖'}")
                    found = True
                    break
        
        results[doc_type] = found
        print(f"📌 Resultado para {doc_type}: {'ENCONTRADO' if found else 'NO ENCONTRADO'}")
    
    return results


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


@app.route('/')
def home():
    return render_template('chatbot.html')


# Modificación en la función procesar()
@app.route('/procesar', methods=['POST'])
def procesar():
    data = request.get_json()
    estado_actual = data.get('estado', ESTADOS['INICIO'])
    mensaje_usuario = data.get('mensaje', '').strip()
    
    respuesta = {}
    database = load_database()
    
    if estado_actual == ESTADOS['INICIO']:
        respuesta = {
            'mensaje': '¡Hola! Soy tu asistente SENA. Por favor ingresa tu número de documento para verificar tu matrícula y documentos:',
            'estado': ESTADOS['SOLICITAR_CEDULA']
        }
    
    elif estado_actual == ESTADOS['SOLICITAR_CEDULA']:
        if not mensaje_usuario.isdigit() or len(mensaje_usuario) < 8 or len(mensaje_usuario) > 10:
            respuesta = {
                'mensaje': 'Documento inválido. Debe tener entre 8 y 10 dígitos. Intenta nuevamente:',
                'estado': ESTADOS['SOLICITAR_CEDULA']
            }
        else:
            estudiante = database.get(mensaje_usuario)
            if estudiante:
                nombre_completo = f"{estudiante['nombres']} {estudiante['apellido1']} {estudiante['apellido2']}"
                print(f"\n🔄 Procesando documentos para {nombre_completo} ({mensaje_usuario})")
                doc_results = check_documents(mensaje_usuario, nombre_completo)
                missing_docs = [k for k, v in doc_results.items() if not v]

                # Construcción del mensaje mejorado
                mensaje = f"¡Bienvenido(a), <b>{nombre_completo}</b>! Estudiante del programa {estudiante['programa']} (Ficha {estudiante['ficha']}).\n\n"

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

                respuesta = {
                    'mensaje': mensaje,
                    'estado': ESTADOS['FINAL'],
                    'encontrado': True
                }
            else:
                respuesta = {
                    'mensaje': '❌ No encontramos tu documento en nuestros registros. ¿Estás seguro de estar matriculado en el SENA?',
                    'estado': ESTADOS['FINAL'],
                    'encontrado': False
                }
    
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
