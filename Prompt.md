# Proyecto: "AutoForm PSV" — app de escritorio para prellenar formularios Enketo desde Excel

## Contexto

App de escritorio (Windows) que prellena el formulario web "Información de Unidades

Productivas y Especies PSV" (Enketo Express: [https://ee.sembrandodatos.com/x/7kMmQETh](https://ee.sembrandodatos.com/x/7kMmQETh)),

un formulario por sembrador.

- Las respuestas generales son FIJAS e IGUALES para todos los sembradores (plantilla única).

- Lo que cambia por sembrador sale de 2 archivos Excel: PADRÓN e INVENTARIO.

- Los obligatorios sin dato quedan PENDIENTES y se reportan; nunca se inventan.

- La app NUNCA presiona "Enviar": solo llena y guarda borrador para revisión humana.

## Stack

Python 3.11+, PySide6, Playwright (Chromium, `launch_persistent_context` con perfil propio

de la app; los borradores de Enketo viven en el IndexedDB de ese perfil), pandas/openpyxl,

YAML para configuración, PyInstaller para el .exe.

## Entrada 1: PADRÓN (una fila = un sembrador)

Columnas: CURP, POLIGONO, Apellido_p, Apellido_m, Nombre, CAC_ID, NOMBRE_CAC,

CENTROIDE_LATITUD, CENTROIDE_LONGITUD, ID_PREDIO ("lat,lon"), TECNICA, CURP de la técnica.

Mapeo en `config/mapeo_padron.yaml`:

- CURP → /curp ; Nombre → /nombre ; Apellido\_p → /aPaterno ; Apellido\_m → /aMaterno

- CAC\_ID → /ID\_de\_la\_CAC ; NOMBRE\_CAC → /Nombre\_de\_la\_CAC

- CURP técnica → /curp\_ingresado (dispara la búsqueda del nombre; esperar a que aparezca)

- ID\_PREDIO → num\_up\_txt

- Lat/Lon → geopoint "Registra\_el\_centroide\_del\_predio" ("lat lon alt precisión") y inputs lat/long

## Entrada 2: INVENTARIO de planta viva (varias filas por sembrador)

Columnas: ID DEL SEMBRADOR, NOMBRE SEMBRADOR, CAC, POLÍGONO, HA, AÑO DE ESTABLECIMIENTO,

NOMBRE COMÚN, NOMBRE CIENTÍFICO, NÚMERO (de plantas), CM DIÁMETRO, M ALTURA.

(El encabezado está en la fila 2; la fila 1 es un título. Detectar el encabezado automáticamente.)

Unión padrón ↔ inventario: por nombre completo normalizado

(Nombre + Apellido_p + Apellido_m vs NOMBRE SEMBRADOR; sin acentos, mayúsculas, espacios

colapsados). Si el padrón trae una columna ID DEL SEMBRADOR, usarla como llave preferente.

Reportar sembradores sin inventario e inventarios sin sembrador.

Limpieza y validación (reportar todo; no corregir en silencio):

- Filas consecutivas idénticas (pasa mucho en el inventario). Regla configurable en

  `config/inventario.yaml`: `duplicados: deduplicar | sumar | mantener`. Por defecto:

  deduplicar y reportar.

- Decimales tipo ".20" → 0.20. Celdas vacías de diámetro/altura → vacío, no 0.

- Altura viene en METROS; el formulario pide cm → multiplicar por 100.

- Nombres científicos con errores (ej. "FFRAXINUS UHDEI") o nombres comunes múltiples

  ("MACUILIS, AMAPA, PALO DE ROSA…"): emparejar contra el catálogo del formulario con fuzzy

  matching (rapidfuzz) y umbral configurable. Debajo del umbral, usar "Otra" + texto y

  reportar. Guardar las correcciones aprobadas en `config/alias_especies.yaml`.

Cómo se vuelca el inventario al formulario:

- "Planta establecida en parcela (especies perennes)": por cada especie (agrupada por

  nombre científico + año), crear una instancia del repeat en la categoría correcta

  (Forestales / Agroindustrial / Frutales / Especias) con nombre común, nombre científico

  (del catálogo), número de individuos y año de establecimiento.

  - La categoría sale de `config/categorias_especies.yaml` (especie → categoría). Prellenar con:

    Frutales = naranja, limón, lima, mandarina, toronja, mango, aguacate, papaya, plátano,

    guayaba, manzana, durazno, nopal tunero ; Forestales = pino, pino ocote, fresno,

    rosa morada/macuilis, guaje/leucaena, guajillo, frijol palo ; Especias = orégano ;

    Agroindustrial = agave/maguey. Si una especie no está en el archivo, se reporta.

  - El inventario no dice si va en SAF o MIAF: regla fija configurable (por defecto SAF).

  - Origen y tasa de supervivencia: valores fijos de la plantilla, o pendientes si no se definen.

- "Cultivos eje" (máx. 3 por categoría frutal / agroindustrial / especia): los 3 con más

  plantas totales. Número de plantas = suma; año → edad promedio = año actual − año

  ponderado; diámetro y altura promedio ponderados por número de plantas (altura en cm).

  El resto de los campos de cultivos eje: plantilla fija o pendiente.

## Entrada 3: PLANTILLA FIJA (`config/plantilla.yaml`) — igual para todos

Clave = ruta del campo o etiqueta; valor = TEXTO visible de la opción (no el value interno).

- Constantes: territorio JALISCO-NAYARIT, ruta 300, "¿La ruta está en la lista?" Sí,

  año de ingreso 2020, número de predios 1, número de UP 1, fecha y hora de inicio

  (configurables en la GUI; formato YYYY-MM-DD)

- Uso de suelo inicial: Cultivo de milpa ; Pendiente: 8° a 20°

- Sistema productivo: SAF y MIAF ; Hectáreas SAF 1 ; MIAF 1.5

- Problemas del suelo: \[Deficiencia de materia orgánica, Poca fertilidad\]

- Altas densidades: No ; Alta mortandad: Sí ; Causas: "Plaga, Hielo" ; Tasa: 60

- Colmenas: No ; Poda frutal: No ; Poda agroindustrial: No ; Bitácora: No

- Fuente de agua: \[Temporal, Río temporal, Manantial\] ; Almacenamiento de agua: No

- Obras de conservación: \[Terrazas, Bordos/muros, Barreras rompevientos/cercos vivos\]

- ¿Las prácticas han mejorado el suelo?: (definir con el jefe; hoy es PENDIENTE)

- % de suelo cubierto por M.O.: 0% ; Raleo: No

- Especies tolerantes: 1) Naranja Valencia, Citrus sinensis, 82, 82%,

  [Heladas, Nortes/Frentes fríos, Lluvias intensas] ; 2) Mandarina, 95, 95%

- Biocultural: Maíz chino, Zea mays, individuos PENDIENTE

- Eventos del año pasado: \[Nortes/Frentes fríos, Heladas, Granizadas\]

- Cómo afectaron: \[Disminución o pérdida de la cosecha, Cambios en la floración,

  Otra afectación] ; Otra: "Secamiento de la planta"

- Plagas: Muy afectada (más del 50 %)

- Matriz CAC/vivero/biofábrica: Huracanes → \[B\] ; Lluvias intensas → \[C, D, E\]

- Matriz de la parcela, matriz de medidas y matriz hogar/comunidad: PENDIENTES

- Labranza cero ; Tractor: Nunca ; Gasto: No gastó nada ; Malezas: Control manual

- Composta 100 kg/año ; Superficie 1 ha ; Procedencia: propia 0, biofábrica 100,

  local 0, regional 0 ; Rastrojo: Sí ; Sistema: MIAF

- Bocashi 1000 kg: sin campo en el formulario → solo en reporte

## Aprendizajes técnicos del formulario (verificados)

1. Identificar campos por `data-name` (o `name`) con la ruta (`/data/.../Labranza`).

   Los radios tienen `name` numérico aleatorio; la ruta real está en `data-name`.

2. Campos no aplicables: ancestro con clase `.disabled`. Llenar EN ORDEN y esperar

   300–1000 ms tras respuestas que muestran campos nuevos (ej. rastrojo Sí → "¿En qué sistema?").

3. Los values internos NO coinciden con el texto: "ninguno" = Granizadas, "ninguno\_1" = Ninguno,

   "quimico" = Control manual, "bioinsumos" = Control mecánico. Los nombres científicos son

   códigos (perenne_525, ANUALES_88). Seleccionar SIEMPRE por texto de la etiqueta.

4. Selects con bootstrap-select: `select.value` + `change` NO actualiza el widget. Hay que

   hacer click en `.bootstrap-select .dropdown-menu input.ignore` cuyo `span.option-label`

   coincida con el texto. Se actualiza de forma asíncrona (1–2 s); verificar después.

5. Text/number: `locator.fill()` o asignar el value y disparar `input` + `change`.

6. Radios y checkboxes: click solo si el estado difiere (idempotente).

7. Matrices: grupos `group_xxx_fila_N` con values sin sentido. Fila = TEXTO del evento;

   columna = POSICIÓN (A = 1.ª casilla). Hay 4 matrices; identificarlas por el título de la pregunta.

8. Repeats: botón "+" / "Agregar otra especie" para crear instancias antes de llenar;

   la instancia nueva aparece al final de su grupo.

9. Al final, listar obligatorios vacíos: visibles, `.required`/asterisco, sin valor

   (o `.invalid-required` tras intentar guardar el borrador).

## Funciones de la app

1. **Descubrimiento**: exporta `form_schema.json` (ruta, tipo, etiqueta, opciones value+texto,

   obligatorio, matriz/repeat, catálogo de especies).

2. **Validación previa**: cruza plantilla + padrón + inventario contra el schema y muestra:

   especies sin match, sin categoría, duplicados, sembradores sin inventario.

3. **Vista previa por sembrador**: tabla con todo lo que se llenará, editable antes de correr.

4. **Llenado por lotes**: elegir padrón e inventario, marcar sembradores y presionar

   "Prellenar". Por cada uno: abrir el formulario, llenar, verificar leyendo de vuelta y

   guardar el borrador "CURP - Nombre". Opción "pausa antes de guardar".

5. **Revisión**: abrir el navegador del perfil para ver o enviar los borradores manualmente.

6. **Reporte** Excel por sembrador: estado, obligatorios pendientes, campos fallidos,

   especies corregidas o como "Otra", log y capturas si hubo error.

## Restricciones

- Prohibido hacer click en "Enviar" (guardia en el código que lance excepción).

- Nada de contraseñas en texto plano; el login se hace manualmente en el navegador persistente.

- Timeouts y reintentos por campo; si un campo falla, continuar y reportar.

- Módulos: excel\_[padron.py](http://padron.py), excel\_[inventario.py](http://inventario.py), [especies.py](http://especies.py) (catálogo, fuzzy, categorías),

  [template.py](http://template.py), form\_[schema.py](http://schema.py), [filler.py](http://filler.py), [matrix.py](http://matrix.py), [repeats.py](http://repeats.py), [report.py](http://report.py), [gui.py](http://gui.py).

- README con instalación (`pip install -r requirements.txt`, `playwright install chromium`).

## Orden de trabajo

1) Modo descubrimiento: muéstrame el `form_schema.json` y el catálogo de especies.

2) Lector de inventario con limpieza y reporte de validación sobre mis archivos.

3) Llenador con 1 sembrador en "pausa antes de guardar".

4) Lote completo + reporte.