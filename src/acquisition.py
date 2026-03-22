# Todo: implementar código de adquisición de datos (crawler, scraper...)
# Deberán tener una estructura similar a la del json de ejemplo (ver data/ejemplo.json)

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time
import json
import os
import re

OUTPUT_FILE = "data/raw/productos_supermercado.json"

def parse_dia_product(html, url, cat_name):
    """Extrae la información leyendo el texto de la web línea por línea."""
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Extracción del texto principal
    titulo_tag = soup.find("h1")
    texto_original_web = titulo_tag.get_text(strip=True) if titulo_tag else "N/A"
    
    # --- CAZADOR DE MARCAS Y LIMPIEZA DE TÍTULO ---
    # Lista de las marcas más comunes + marcas blancas de Dia. 
    # El orden importa: ponemos las marcas blancas específicas de Dia primero.
    marcas_conocidas = [
        "Danone", "Nestlé", "Nestle", "Nocilla", "Nutella", "Dr. Oetker", "Nesquik", "Azucarera", "Campofrío", "Campofrio", "ElPozo", "Gallo",
        "Dekora", "La piara","Artiach", "Milka", "Valor", "Gullón", "Gullon", "Fidias", "Mari Marinera", "Vegecampo",
        "El Molino", "Albea", "Naturmundo", "Pascual", "Asturiana", "President",
        "Bimbo", "Oreo", "Fontaneda", "Cuétara", "Cuetara", "Knorr", "Gallina Blanca",
        "Heinz", "Orlando", "Hero", "Litoral", "Alpro", "Oatly", "Vivesoy", "Puleva",
        "Activia", "Actimel", "Oikos", "Reina", "Royal", "Tarradellas", "Navidul",
        "Revilla", "Argal", "Ferrero", "Lindt", "Central Lechera Asturiana", "Gatorade",
        "Coca-Cola", "Pepsi", "Fanta", "Aquarius", "Nestea", "Red Bull", "Monster",
        "Lays", "Ruffles", "Doritos", "Cheetos", "Pringles", "Grefusa", "Facundo", "DiaCol",
        "Dia" # Dia va al final como "red de seguridad"
    ]
    
    marca_detectada = "Desconocida"
    titulo_limpio = texto_original_web
    
    for marca in marcas_conocidas:
        # Buscamos la marca en el texto como palabra exacta
        if re.search(r'\b' + re.escape(marca) + r'\b', texto_original_web, re.IGNORECASE):
            marca_detectada = marca
            # Cortamos el título justo antes de donde empieza la marca
            match = re.search(r'\b' + re.escape(marca) + r'\b', texto_original_web, re.IGNORECASE)
            titulo_limpio = texto_original_web[:match.start()].strip()
            break
            
    # Si no detecta ninguna de la lista, cortamos los gramos/packs del título para dejarlo limpio
    if marca_detectada == "Desconocida":
        titulo_limpio = re.sub(r'\bpack\s+\d+\s*[xX]\s*\d+.*$', '', titulo_limpio, flags=re.IGNORECASE)
        titulo_limpio = re.sub(r'\b\d+(?:,\d+)?\s*(g|kg|ml|l|cl)\b.*$', '', titulo_limpio, flags=re.IGNORECASE)
        titulo_limpio = titulo_limpio.strip()
    
    # Capitalizamos la marca para que quede bonita (ej: danone -> Danone)
    if marca_detectada != "Desconocida":
        marca_detectada = marca_detectada.title() if marca_detectada.lower() != "dia" else "Dia"

    # --- CALCULADORA DE UNIDADES Y PESOS (Usando el texto original) ---
    unidades = 1
    peso_por_unidad = "Desconocido"
    peso_total = "Desconocido"

    pack_match = re.search(r'(\d+)\s*[xX]\s*(\d+(?:,\d+)?)\s*(g|kg|ml|l|cl)', texto_original_web, re.IGNORECASE)
    if pack_match:
        unidades = int(pack_match.group(1))
        peso_val = float(pack_match.group(2).replace(',', '.')) 
        medida = pack_match.group(3).lower()
        
        peso_por_unidad = f"{peso_val:g} {medida}"
        peso_total = f"{unidades * peso_val:g} {medida}"
    else:
        single_match = re.search(r'(\d+(?:,\d+)?)\s*(g|kg|ml|l|cl)', texto_original_web, re.IGNORECASE)
        if single_match:
            peso_val = float(single_match.group(1).replace(',', '.'))
            medida = single_match.group(2).lower()
            peso_por_unidad = f"{peso_val:g} {medida}"
            peso_total = peso_por_unidad
            
    # 2. Precio
    precio_total = 0.0
    precio_tag = soup.select_one('.buy-box__active-price') or soup.select_one('.buy-box__price') or soup.select_one('.price')
    if precio_tag:
        p_raw = precio_tag.get_text(strip=True)
        m = re.search(r'(\d+[.,]\d{2})', p_raw)
        if m: precio_total = float(m.group(1).replace(",", "."))

    if precio_total == 0.0:
        texto_completo = soup.get_text(separator=" ", strip=True)
        match_precio = re.search(r'(\d+[.,]\d{2})\s*€', texto_completo)
        if match_precio: precio_total = float(match_precio.group(1).replace(",", "."))

    # 3. Extractor Avanzado de Texto
    text_lines = soup.get_text(separator="\n", strip=True).split('\n')
    
    nutricion = {
        "Grasas": "0 g",
        "Saturadas": "0 g",
        "Hidratos de carbono": "0 g",
        "Azucares": "0 g",
        "Fibra alimentaria": "0 g",
        "Proteínas": "0 g",
        "Sal": "0 g",
        "Valor energetico": "0 kcal",
        "Valor energetico en KJ": "0 kJ"
    }

    # Cazador en bloque de 5 líneas
    def extract_g(index, lines):
        chunk = " ".join(lines[index:min(index+5, len(lines))])
        m = re.search(r'(\d+(?:,\d+)?)\s*g', chunk, re.IGNORECASE)
        if m: return m.group(1).replace(" ", "") + " g"
        return "0 g"

    for i, line in enumerate(text_lines):
        line_lower = line.lower().strip()
                    
        # ENERGÍA
        if "valor energético" in line_lower or "valor energetico" in line_lower:
            val_str = " ".join(text_lines[i:min(i+6, len(text_lines))])
            match_kj = re.search(r'(\d+(?:,\d+)?)\s*kJ', val_str, re.IGNORECASE)
            match_kcal = re.search(r'(\d+(?:,\d+)?)\s*kcal', val_str, re.IGNORECASE)
            if match_kj: nutricion["Valor energetico en KJ"] = match_kj.group(1).replace(" ", "") + " kJ"
            if match_kcal: nutricion["Valor energetico"] = match_kcal.group(1).replace(" ", "") + " kcal"
            
        # MACRONUTRIENTES
        elif line_lower.startswith("grasas"):
            nutricion["Grasas"] = extract_g(i, text_lines)
        elif "cuales saturadas" in line_lower:
            nutricion["Saturadas"] = extract_g(i, text_lines)
        elif line_lower.startswith("hidratos de carbono"):
            nutricion["Hidratos de carbono"] = extract_g(i, text_lines)
        elif "cuales azúcares" in line_lower or "cuales azucares" in line_lower:
            nutricion["Azucares"] = extract_g(i, text_lines)
        elif line_lower.startswith("fibra"):
            nutricion["Fibra alimentaria"] = extract_g(i, text_lines)
        elif line_lower.startswith("proteínas") or line_lower.startswith("proteinas"):
            nutricion["Proteinas"] = extract_g(i, text_lines)
        elif line_lower.startswith("sal"):
            nutricion["Sal"] = extract_g(i, text_lines)

    # 4. Construcción Final del Diccionario (NUEVA ESTRUCTURA)
    return {
        "url": url,
        "titulo": titulo_limpio,                     # Ejemplo: "Yogur sabor coco, fresa, frutos del bosque y macedonia"
        "marca": marca_detectada,                    # Ejemplo: "Danone"
        "valores_nutricionales_100_g": nutricion,
        "descripcion": texto_original_web,           # Ejemplo: "Yogur sabor coco... Danone pack 8 x 120 g"
        "categorias": [cat_name],
        "precio_total": precio_total,
        "unidades": unidades,
        "peso_por_unidad": peso_por_unidad,
        "peso_total": peso_total,
        "origen": "dia_directo",
        "direccion_manufactura": []
    }

def run_acquisition():
    busquedas = {
        "yogures_y_postres": "https://www.dia.es/yogures-y-postres/c/L113",
        "azucar_y_chocolates": "https://www.dia.es/azucar-chocolates-y-caramelos/c/L110",
        "charcuteria_y_quesos": "https://www.dia.es/charcuteria-y-quesos/c/L101",
        "galletas": "https://www.dia.es/galletas-bollos-y-cereales/galletas/c/L2065",
        "conservas_y_caldos": "https://www.dia.es/conservas-caldos-y-cremas/c/L114",
        "pastas_y_arroces": "https://www.dia.es/compra-online/search?q=macarrones",
        "platos_preparados": "https://www.dia.es/platos-preparados-y-pizzas/c/L116"
    }
    
    final_data = []
    MAX_POR_CATEGORIA = 40 

    with sync_playwright() as p:
        print("\n>>> Arrancando navegador para extraer 6 categorías de Dia.es...")
        browser = p.chromium.launch(headless=False) 
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for cat_name, url_search in busquedas.items():
            print(f"\n>>> Entrando en categoría: {cat_name}")
            try:
                page.goto(url_search, timeout=60000, wait_until="domcontentloaded")
                time.sleep(4)
                
                print("  -> Haciendo scroll profundo...")
                for _ in range(5): 
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2) 
                
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                
                links = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/p/" in href:
                        full_url = href if href.startswith("http") else "https://www.dia.es" + href
                        if full_url not in links: links.append(full_url)
                        
                print(f"  -> ¡Éxito! Encontrados {len(links)} productos. Extrayendo un máximo de {MAX_POR_CATEGORIA}...")

                productos_extraidos = 0

                for link in links:
                    if productos_extraidos >= MAX_POR_CATEGORIA:
                        print(f"  -> Límite alcanzado para {cat_name}. Pasando a la siguiente...")
                        break
                    
                    try:
                        page.goto(link, timeout=45000, wait_until="domcontentloaded")
                        time.sleep(2.5) 
                        
                        p_html = page.content()
                        data = parse_dia_product(p_html, link, cat_name)
                        
                        final_data.append(data)
                        productos_extraidos += 1
                        
                        print(f"    [✓] Extraído ({len(final_data)}/240): {data['marca']} | {data['titulo']}")
                        
                    except Exception as e:
                        print(f"    [x] Error cargando producto, saltando...")
                        
            except Exception as e:
                print(f"  [!] Error en la categoría: {e}")

        browser.close()

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ MISIÓN CUMPLIDA. Ahora los nombres de marca se extraen correctamente y los títulos están súper limpios.")

if __name__ == "__main__":
    run_acquisition()