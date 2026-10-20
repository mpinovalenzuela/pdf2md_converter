# pdf2md-converter

Convierte PDFs de modelos de datos (exportados desde **Oracle Data Modeler**) a
**Markdown estructurado**, **CSV por tabla** y **JSON de metadatos**, usando
[PyMuPDF](https://pymupdf.readthedocs.io/) (detección de líneas de grilla) como
motor de extracción de tablas — el `.md`, los `.csv` y el `.json` se generan
todos a partir de las mismas tablas ya extraídas, clasificadas y fusionadas,
para que queden consistentes entre sí. [Docling](https://github.com/DS4SD/docling)
se usa solo como respaldo, para páginas sin ninguna tabla detectada (ver
[Rendimiento en documentos grandes](#rendimiento-en-documentos-grandes)).

Pensado para alimentar un pipeline de **RAG (Retrieval Augmented Generation)**
en **Copilot Studio**: la calidad de la extracción de tablas (columnas, PKs,
FKs, tipos de dato) es el objetivo principal del proyecto.

## Características

- Conversión de PDF a Markdown preservando la jerarquía de encabezados.
- Extracción de cada tabla detectada a un CSV independiente, clasificada
  automáticamente como tabla de **columnas**, de **foreign keys** o genérica.
- JSON de metadatos por documento: páginas, tablas, columnas detectadas,
  relaciones FK y advertencias.
- Post-procesamiento del Markdown: separadores entre tablas, encabezados de
  sección normalizados, eliminación de artefactos de paginación, listas
  normalizadas, bloques de código preservados.
- CLI con [Typer](https://typer.tiangolo.com/) + salida enriquecida con
  [rich](https://github.com/Textualize/rich).
- Logging estructurado con [loguru](https://github.com/Delgan/loguru) a
  consola y archivo.
- Configuración vía archivo YAML/JSON validado con
  [Pydantic](https://docs.pydantic.dev/).
- Conversión en lote de carpetas completas de PDFs.
- Manejo de errores por archivo: un PDF corrupto no detiene el lote.

## Instalación

Requiere **Python 3.11+**.

### Con `uv` (recomendado)

```bash
uv venv
uv pip install -e ".[dev]"
```

### Con `pip`

```bash
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Con `poetry`

```bash
poetry install
```

## Uso básico

```bash
# Convertir un PDF (genera .md, .csv por tabla y .json)
pdf2md convert input/Commissions_Data_Model.pdf -o output/ -v

# Convertir todos los PDFs de una carpeta
pdf2md convert-all input/ -o output/ -f md,csv,json

# Inspeccionar un PDF sin escribir nada a disco
pdf2md inspect input/Commissions_Data_Model.pdf

# Comparar dos carpetas de vistas exportadas (detecta nuevas, eliminadas y modificadas)
pdf2md views-diff output/v1/views output/v2/views -o output/views_diff.md

# Ver la versión instalada
pdf2md --version
```

### Opciones del comando `convert`

| Opción             | Alias | Descripción                                              | Default        |
|--------------------|-------|-----------------------------------------------------------|----------------|
| `--output-dir`     | `-o`  | Carpeta de salida                                          | `output/`      |
| `--formats`        | `-f`  | Formatos a generar: `md`, `csv`, `json` (separados por coma) | `md,csv,json`  |
| `--no-tables-csv`  |       | No extraer tablas individuales a CSV                        | `false`        |
| `--verbose`        | `-v`  | Logging detallado (`DEBUG`)                                 | `false`        |
| `--config`         |       | Ruta a archivo de configuración YAML/JSON                   | ninguno        |
| `--fast`           |       | Modo `fast` de Docling para el `.md` (ya es el default)      | `false`        |
| `--accurate`       |       | Modo `accurate` de Docling para el `.md` (ver abajo)         | `false`        |
| `--ocr`            |       | Habilita OCR (solo para PDFs escaneados)                    | `false`        |

`convert-all` acepta las mismas opciones, recibiendo una carpeta en lugar de
un archivo.

### Rendimiento en documentos grandes

Las tablas — tanto las de `.csv`/`.json` como las que aparecen dentro del
`.md` — **se extraen con PyMuPDF**, no con Docling: por eso son rápidas
(segundos, no minutos) y no dependen de ningún modelo neuronal. Docling solo
se usa como respaldo para páginas donde PyMuPDF no detectó ninguna tabla
(por ejemplo, un PDF puramente narrativo). El `table_mode` de Docling
(`fast`/`accurate`) solo afecta la calidad de ese Markdown de respaldo — no
afecta en nada al contenido normal de `.csv`, `.json` ni al `.md` de un PDF
con tablas.

- **`fast` (default):** recomendado para la gran mayoría de casos.
- **`--accurate`:** usa el modelo TableFormer completo de Docling para el
  Markdown de respaldo, más lento (es normal ver un aluvión de warnings
  `MatchingPostProcessor ... Orphan pdf_cell ...` en la consola mientras
  esto ocurre; son parte del proceso normal, no errores).

**OCR va desactivado por defecto** (`ocr: false`): los PDFs exportados por
Data Modeler ya son nativos de texto, así que el OCR no aporta calidad y
solo agrega tiempo de arranque. Actívalo (`--ocr`) únicamente si algún PDF
de origen es en realidad una imagen escaneada.

Estas opciones también se pueden fijar de forma permanente en
`config.yaml` bajo `conversion.ocr` y `conversion.table_mode` (`"fast"` o
`"accurate"`).

### Códigos de salida

| Código | Significado                                   |
|--------|-------------------------------------------------|
| `0`    | Éxito, sin advertencias                          |
| `1`    | Error (PDF no encontrado, corrupto o Docling falló) |
| `2`    | Éxito con advertencias (ej. tabla omitida)       |

### Comparación de vistas (`views-diff`)

El comando `views-diff` compara dos carpetas de vistas exportadas (`.md`
generados por el comando `views`) y genera un reporte Markdown con:

- **Vistas nuevas:** presentes solo en la carpeta nueva.
- **Vistas eliminadas:** presentes solo en la carpeta anterior.
- **Vistas modificadas:** presentes en ambas pero con SQL distinto (incluye
  un diff unificado del SQL).
- **Detalle por vista:** tabla con *todas* las vistas de ambas carpetas y su
  estado (🆕 Nueva, 🗑️ Eliminada, ✏️ Modificada, ✅ Sin cambios). Para las
  modificadas indica brevemente el tipo de cambio:
  - `+ / − columnas salida: ...` — columnas de salida agregadas o quitadas
    (o `orden de columnas salida` si solo cambió el orden).
  - `+ / − tablas origen: ...` — tablas `FROM`/`JOIN` agregadas o quitadas.
  - `filtro WHERE agregado / eliminado / modificado`.
  - `solo comentarios/formato` — el SQL es equivalente ignorando
    comentarios, espacios y mayúsculas.
  - `lógica SQL (SELECT/JOIN/expresiones)` — cualquier otro cambio.

  Además muestra cuántas líneas se agregaron/quitaron en el diff.

```bash
# Comparar la exportación del 30/09 contra la del 19/10
pdf2md views-diff output/v1/views output/v2/views

# Especificar la ruta del reporte de salida
pdf2md views-diff output/v1/views output/v2/views -o output/views_diff_report.md
```

| Opción         | Alias | Descripción                                         | Default                          |
|----------------|-------|------------------------------------------------------|----------------------------------|
| `--out`        | `-o`  | Ruta del reporte Markdown a escribir                  | `{after_dir}/views_diff_report.md` |
| `--verbose`    | `-v`  | Logging detallado (`DEBUG`)                           | `false`                          |

## Estructura de archivos generados

Para un PDF `Commissions_Data_Model.pdf`, `pdf2md convert` genera en la
carpeta de salida:

```
output/
├── Commissions_Data_Model.md
├── Commissions_Data_Model_metadata.json
├── Commissions_Data_Model_tabla_1_columns.csv
├── Commissions_Data_Model_tabla_2_columns.csv
├── Commissions_Data_Model_tabla_3_fk.csv
└── ...
```

- **`.md`**: Markdown con encabezados normalizados, separadores `---` entre
  tablas y secciones, y artefactos de PDF (números de página, headers
  repetidos) eliminados.
- **`_tabla_N_columns.csv`**: tabla de columnas de una entidad (nombre,
  tipo de dato, PK/FK, dominio, etc.).
- **`_tabla_N_fk.csv`**: tabla de foreign keys ("referring to" / "referred
  from").
- **`_metadata.json`**: resumen estructurado del documento — ver esquema
  abajo.

### Esquema del JSON de metadatos

```json
{
  "source_file": "Commissions_Data_Model.pdf",
  "converted_at": "2026-04-29T10:30:00+00:00",
  "docling_version": "2.x.x",
  "total_pages": 199,
  "total_tables": 45,
  "total_tables_columns": 30,
  "total_tables_fk": 15,
  "tables": [
    {
      "index": 1,
      "page": 2,
      "type": "columns",
      "table_name": "INSIS_COMMISSIONS.AC_ANNEX",
      "row_count": 6,
      "column_count": 10,
      "csv_file": "Commissions_Data_Model_tabla_1_columns.csv",
      "columns_detected": ["POLICY_ID", "ANNEX_ID", "CR_TYPE"]
    }
  ],
  "relationships": [
    {
      "source_table_index": 3,
      "fk_name": "FK_ANNEX_POLICY",
      "related_table": "AC_POLICY",
      "related_column": "POLICY_ID"
    }
  ],
  "warnings": [
    "Página 46: tabla sin encabezado detectada, se omitió"
  ]
}
```

## Configuración avanzada

Se puede pasar un archivo `config.yaml` (o `.json`) con `--config`:

```yaml
conversion:
  engine: docling
  preserve_tables: true
  extract_csv: true
  extract_json: true
  pages_to_skip: []
  ocr: false          # activar solo si el PDF de origen es una imagen escaneada
  table_mode: fast  # "fast" (default) o "accurate" (más lento, solo afecta el .md)
output:
  base_dir: ./output
  markdown_filename_pattern: "{stem}.md"
  csv_filename_pattern: "{stem}_tabla_{n}_{type}.csv"
  json_filename_pattern: "{stem}_metadata.json"
logging:
  level: INFO
  file: ./logs/{date}.log
  console: true
postprocessing:
  normalize_headers: true
  remove_page_artifacts: true
  clean_empty_cells: true
```

Todos los campos son opcionales; los valores no especificados usan los
defaults de arriba. Ver [`src/pdf2md_converter/config.py`](src/pdf2md_converter/config.py)
para el detalle de validación (Pydantic).

## Integración con Copilot Studio

1. Ejecuta `pdf2md convert-all` sobre la carpeta de PDFs de tus modelos de
   datos, generando `.md` por documento.
2. Sube los `.md` resultantes como fuente de conocimiento (Knowledge Source)
   en Copilot Studio, o indexa el contenido en tu base vectorial de RAG.
3. Usa los `.csv` por tabla para **validar manualmente** que la extracción de
   columnas/PK/FK sea correcta antes de indexar — son el punto de control de
   calidad recomendado antes de confiar en el `.md` para producción.
4. Usa el `.json` de metadatos para poblar filtros de búsqueda (por tabla,
   por página, por tipo) o para construir un grafo de relaciones FK entre
   entidades que enriquezca las respuestas del agente.

## Desarrollo

```bash
# Tests con cobertura
pytest

# Lint
ruff check .

# Formato
black .
isort .
```

### Estructura del proyecto

```
pdf2md_converter/
├── src/pdf2md_converter/
│   ├── main.py            # Entry point CLI
│   ├── cli.py             # Comandos Typer + orquestación del pipeline
│   ├── config.py          # Configuración Pydantic
│   ├── converter.py       # Wrapper sobre Docling (páginas, Markdown de respaldo)
│   ├── extractors/        # Tablas (PyMuPDF), metadatos, relaciones FK
│   ├── writers/           # Markdown (generado desde las tablas), CSV, JSON
│   ├── postprocessors/    # Limpieza de tablas y de Markdown
│   └── utils/             # Logging y utilidades de archivos
└── tests/
```

## Licencia

MIT. Ver [LICENSE](LICENSE).
