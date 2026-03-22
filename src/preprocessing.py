# Todo: implementar código de limpieza de los datos para ingestarlos en el RAG

import pandas as pd
import json
import re
import os

INPUT_FILE = "data/raw/productos_supermercado.json"
OUTPUT_DIR = "data/clean"
OUTPUT_FILE = f"{OUTPUT_DIR}/productos_procesados.csv"

def extraer_numero(texto):
    """Convierte textos como '4,8 g' o '464 kcal' en valores numéricos (float)."""
    if pd.isna(texto) or texto == "" or texto == "Desconocido":
        return 0.0
    texto_str = str(texto).replace(',', '.')
    match = re.search(r'(\d+(?:\.\d+)?)', texto_str)
    if match:
        return float(match.group(1))
    return 0.0

def ejecutar_preprocessing():
    print("\n>>> 🛠️ INICIANDO PIPELINE DE PREPROCESAMIENTO...")
    
    if not os.path.exists(INPUT_FILE):
        print(f"  [!] Error: No se encuentra el archivo {INPUT_FILE}")
        return None
        
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    df = pd.json_normalize(data)
    
    # ==========================================
    # FASE 1: LIMPIEZA
    # ==========================================
    # --- Total JSON original ---
    print(f"  -> Total de productos originales: {len(df)}")

    # 1. RENOMBRAR COLUMNAS
    print("\n--- Fase 1: Limpieza ---")
    columnas_renombrar = {
        'precio_total': 'precio',
        'valores_nutricionales_100_g.Proteinas': 'proteinas',
        'valores_nutricionales_100_g.Hidratos de carbono': 'carbohidratos',
        'valores_nutricionales_100_g.Grasas': 'grasas',
        'valores_nutricionales_100_g.Fibra alimentaria': 'fibra',
        'valores_nutricionales_100_g.Valor energetico': 'calorias'
    }
    # Aplicamos el renombre solo a las columnas que existan
    df = df.rename(columns={k: v for k, v in columnas_renombrar.items() if k in df.columns})
    
    # 2. ELIMINAR DUPLICADOS
    if 'url' in df.columns:
        df = df.drop_duplicates(subset=['url'], keep='first')
    
    if 'precio' in df.columns:
        df['precio'] = pd.to_numeric(df['precio'], errors='coerce')
    
    # 3. ESTANDARIZAR TIPOS DE DATOS (A numéricos)
    columnas_nutricionales = ['proteinas', 'carbohidratos', 'grasas', 'fibra', 'calorias']
    for col in columnas_nutricionales:
        if col in df.columns:
            df[col] = df[col].apply(extraer_numero)
        else:
            df[col] = 0.0 #Por si algún JSON viene sin una de estas columnas
    
    # 4. ELIMINAR FILAS CON VALORES FALTANTES CRÍTICOS        
    campos_criticos = ['titulo', 'precio', 'proteinas', 'carbohidratos', 'grasas', 'fibra', 'calorias']
    #Filtramos para asegurarnos de que la columna existe antes de chequear si está vacía
    campos_existentes = [col for col in campos_criticos if col in df.columns]
    df = df.dropna(subset=campos_existentes)
    # Eliminamos precios que sean 0.0 o nulos
    if 'precio' in df.columns:
        df = df[df['precio'] > 0.0]
        
    print(f"  [✓] Productos limpios y válidos: {len(df)}")

    # --- VISTA PREVIA DE LAS COLUMNAS CRÍTICAS ---
    print(">>> VISTA PREVIA PARA EL RAG (Top 5 productos):")
    df_vista_previa = df[campos_existentes].head(5)
    
    # Imprimimos la tabla formateada sin el índice para que se vea súper limpia
    print(df_vista_previa.to_string(index=False))

    # ==========================================
    # FASE 2: NORMALIZACIÓN
    # ==========================================
    print("\n--- Fase 2: Normalización ---")
    
    # 1. Crear 'texto_busqueda' (Limpiar, rellenar nulos y minusculizar)
    # Como 'descripcion' (del json) ya trae el nombre completo original con marca y tamaño, 
    # concatenarla con 'titulo' y 'marca' es redundante. 
    # Mejor concatenamos la descripción con la categoría para enriquecer el contexto.
    
    if 'descripcion' in df.columns:
        df['descripcion'] = df['descripcion'].fillna('')
    else:
        df['descripcion'] = ''
        
    if 'categorias' in df.columns:
        # Si categorias es una lista, la unimos. Si no, la pasamos a string
        df['cat_str'] = df['categorias'].apply(lambda x: " ".join(x) if isinstance(x, list) else str(x))
    else:
        df['cat_str'] = ''

    # Concatenamos descripcion y categorias, a minúsculas, y quitamos dobles espacios
    df['texto_busqueda'] = (df['descripcion'] + " " + df['cat_str']).astype(str)
    df['texto_busqueda'] = df['texto_busqueda'].str.lower().str.replace(r'\s+', ' ', regex=True).str.strip()
    
    # Limpiamos la columna temporal
    df = df.drop(columns=['cat_str'])
    
    print("  [✓] Columna 'texto_busqueda' creada y normalizada (sin duplicidades).")

    # 2. Normalizar precios (norm_precio) - Inverso: más barato = más cerca de 1
    max_precio = df['precio'].max()
    min_precio = df['precio'].min()
    
    if max_precio > min_precio:
        df['norm_precio'] = (max_precio - df['precio']) / (max_precio - min_precio)
    else:
        df['norm_precio'] = 1.0 # Caso extremo: todos los productos valen lo mismo
        
    # Redondeamos a 4 decimales para que sea manejable
    df['norm_precio'] = df['norm_precio'].round(4)
    print("  [✓] Columna 'norm_precio' calculada (Escala 0-1).")

    # 3. Normalizar valor nutricional (norm_nutri) - Score 0-100 basado en proteínas
    max_prot = df['proteinas'].max()
    
    if max_prot > 0:
        df['norm_nutri'] = (df['proteinas'] / max_prot) * 100.0
    else:
        df['norm_nutri'] = 0.0
        
    # Redondeamos a 2 decimales
    df['norm_nutri'] = df['norm_nutri'].round(2)
    print("  [✓] Columna 'norm_nutri' calculada (Escala 0-100).")

    # --- VISTA PREVIA DE LAS NUEVAS COLUMNAS ---
    print("\n>>> VISTA PREVIA DE FASE 2 (Top 3 productos):")
    columnas_mostrar = ['titulo', 'precio', 'norm_precio', 'proteinas', 'norm_nutri']
    print(df[columnas_mostrar].head(3).to_string(index=False))
    
    print("\n>>> Ejemplo de 'texto_busqueda' (primer producto):")
    print(f"    {df['texto_busqueda'].iloc[0][:500]}...")
    
    # ==========================================
    # FASE 3: ENRIQUECIMIENTO
    # ==========================================
    print("\n--- Fase 3: Enriquecimiento ---")
    
    # Algoritmo de score nutricional
    # Base 50 + (Proteínas * 1.5) + (Fibra * 2) - (Grasas * 0.5) - (Carbohidratos * 0.2)
    df['score_nutricional'] = 50 + (df['proteinas'] * 1.5) + (df['fibra'] * 2) - (df['grasas'] * 0.5) - (df['carbohidratos'] * 0.2)
    
    # Recortar los valores para que el mínimo sea 0 y el máximo 100
    df['score_nutricional'] = df['score_nutricional'].clip(lower=0, upper=100).round(2)
    
    # Limpiar las categorías (Si vienen como lista ['galletas'], pasarlo a texto plano 'galletas')
    if 'categorias' in df.columns:
        df['categorias'] = df['categorias'].apply(lambda x: ", ".join(x) if isinstance(x, list) else str(x))

    print("  [✓] Score nutricional calculado y categorías limpias.")

    # ==========================================
    # 4. EXPORTAR EL OUTPUT ESPERADO
    # ==========================================
    # Seleccionamos ESTRICTAMENTE las columnas de tu rúbrica (más la categoría)
    columnas_finales = [
        'titulo', 'precio', 'proteinas', 'carbohidratos', 'grasas', 'fibra', 'calorias',
        'texto_busqueda', 'norm_precio', 'norm_nutri', 'score_nutricional'
    ]
    
    if 'categorias' in df.columns:
        columnas_finales.append('categorias')
        
    df_final = df[columnas_finales].copy()

    # Guardar en CSV dentro de data/clean
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df_final.to_csv(OUTPUT_FILE, index=False, encoding='utf-8')
    
    print(f"\n✅ PIPELINE COMPLETADO CON ÉXITO.")
    print(f"  -> Archivo final guardado en: {OUTPUT_FILE}")
    
    print("\n>>> 👀 VISTA PREVIA DEL DATAFRAME FINAL (Top 5):")
    columnas_vista = ['titulo', 'precio', 'proteinas', 'norm_precio', 'score_nutricional']
    print(df_final[columnas_vista].head(5).to_string(index=False))
    
    return df_final

if __name__ == "__main__":
    df_procesado = ejecutar_preprocessing()

  
