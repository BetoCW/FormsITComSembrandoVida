# Campos del formulario "Información de Unidades Productivas y Especies PSV"

Generado desde la definición del formulario (Enketo `7kMmQETh`, versión del md5:2e980c48…).

- **649** campos · **40** marcados como obligatorios · 14 repeats · 5 matrices.
- "Obligatorio" = el formulario lo exige **solo cuando la pregunta está visible** (columna *Visible si*).

## Lo que cambia por sembrador (~6 datos + inventario)

| Dato | Campo del formulario | De dónde sale |
|---|---|---|
| CURP del sembrador | group_eq6af71/curp | Padrón: CURP |
| Nombre(s), apellido paterno, apellido materno | group_eq6af71/nombre, aPaterno, aMaterno | Padrón |
| ID y nombre de la CAC | group_eq6af71/ID_de_la_CAC, Nombre_de_la_CAC | Padrón: CAC_ID, NOMBRE_CAC |
| ID del predio | up/num_up_txt | Padrón: ID_PREDIO |
| Centroide del predio (**obligatorio**) | up/Registra_el_centroide_del_predio | Padrón: CENTROIDE_LATITUD / LONGITUD |
| CURP del técnico | datos_curp/curp_ingresado | Padrón: CURP de la técnica (o el de "Hoy") |
| Planta establecida y cultivos eje | repeats SAF/MIAF y cultivos eje | Inventario de planta viva |

## Lo que se captura una vez al día

| Dato | Obligatorio |
|---|---|
| Fecha de la entrevista | no |
| Hora de inicio | no |
| Hora de término | **sí** |
| Calidad de la entrevista | **sí** |

## Los 40 obligatorios

| # | Pregunta | Ruta | Visible si | Cómo lo llena la app |
|---|---|---|---|---|
| 1 | Territorio | `group_eq6af71/territorios` | `siempre` | FIJO (plantilla) = JALISCO-NAYARIT |
| 2 | Predio ID | `up/num_up` | `false()` | no aplica con la plantilla actual |
| 3 | Registra el centroide del predio | `up/Registra_el_centroide_del_predio` | `siempre` | POR SEMBRADOR (padrón) |
| 4 | Sistema productivo | `up/sistema` | `siempre` | FIJO (plantilla) = SAF y MIAF |
| 5 | ¿Cuántas? | `up/Cuantas_colmenas` | `../_Tiene_colmenas_en_la_UP  = 's'` | no aplica con la plantilla actual |
| 6 | ¿Requiere poda del arbolado frutal? | `up/poda_001` | `siempre` | FIJO (plantilla) = No |
| 7 | Especie | `up/cultivo_frutales_001` | `false()` | no aplica con la plantilla actual |
| 8 | Especies | `up/Esps_poda_frut` | `../poda_001  = 'si'` | no aplica con la plantilla actual |
| 9 | Número de individuos | `up/num_poda_002` | `../poda_001  = 'si'` | no aplica con la plantilla actual |
| 10 | Especie | `up/cultivo_agro_001` | `false()` | no aplica con la plantilla actual |
| 11 | Especies | `up/Especies` | `../_Requiere_poda_del_arbolado_ag  = 's'` | no aplica con la plantilla actual |
| 12 | Número de individuos | `up/num_poda_002_001` | `../_Requiere_poda_del_arbolado_ag  = 's'` | no aplica con la plantilla actual |
| 13 | Principal fuente de agua | `up/disp_agua` | `siempre` | FIJO (plantilla) = ['Temporal de lluvia', 'Río/Arroyo/Laguna temporal', 'Manantial'] |
| 14 | ¿Cuál? | `up/almacenar_agua` | `../_Existe_alg_n_m_todo_para_alma  = 's'` | no aplica con la plantilla actual |
| 15 | El año pasado ¿cuáles fueron los meses con disponibilidad de agua | `up/El_a_o_pasado_cu_le_sponibilidad_de_agua` | `../_Existe_alg_n_m_todo_para_alma  = 's'` | no aplica con la plantilla actual |
| 16 | Presencia de obras de conservación en la UP | `up/Presencia_de_obras_de_conserva` | `siempre` | FIJO (plantilla) = ['Terraza tabla, Terrazas individuales', 'Bordos, Muros con piedra acomodada', 'Barreras rompevientos, Cercos vivos'] |
| 17 | km de brechas | `up/km_de_brechas` | `selected( ../Tipo_de_obras_de_prevenci_n_de , 'brechas_cortafuego')` | no aplica con la plantilla actual |
| 18 | km de chaponeo | `up/km_de_chaponeo` | `selected( ../Tipo_de_obras_de_prevenci_n_de , 'chaponeo')` | no aplica con la plantilla actual |
| 19 | Número de individuos | `up/N_mero_de_individuos_002` | `selected( ../Tipo_de_obras_de_prevenci_n_de , 'levantamiento_de_fuste')` | no aplica con la plantilla actual |
| 20 | El año pasado ¿cómo controló las malezas en su parcela? | `up/arv_manejo_up` | `siempre` | FIJO (plantilla) = Control manual (deshierbe con machete, azadón u otras herramientas) |
| 21 | Unidad de medida | `group_vj6ie64/forestales_001/Unidad_de_medida_002` | `siempre` | FIJO (plantilla cultivos_eje) — PENDIENTE |
| 22 | Nombre científico | `group_bn3nt58/group_bi0cl57/esp_anual1` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 23 | Variedad (Si no tiene variedad, escribir: NINGUNA) | `group_bn3nt58/group_bi0cl57/Variedad_Si_no_tien_d_escribir_NINGUNA` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 24 | Volumen de producción (t) | `group_bn3nt58/group_bi0cl57/Volumen_de_producci_n_t_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 25 | Costo riego (ha/año) | `group_bn3nt58/group_bi0cl57/costo_frutales_riego_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 26 | Costo fertilización (ha/año) | `group_bn3nt58/group_bi0cl57/costo_frutales_fertilizacion_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 27 | Costo control de plagas y enfermedades (ha/año) | `group_bn3nt58/group_bi0cl57/costo_frutales_control_plagas_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 28 | Costo arvenses (ha/año) | `group_bn3nt58/group_bi0cl57/costo_frutales_arvenses_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 29 | Costo podas y mantenimiento (ha/año) | `group_bn3nt58/group_bi0cl57/costo_frutales_podas_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 30 | Costo tractores y otra maquinaria (ha/año) | `group_bn3nt58/group_bi0cl57/Costo_tractores_y_ot_a_maquinaria_ha_a_o` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 31 | Costo herramientas (ha/año) | `group_bn3nt58/group_bi0cl57/Costo_herramientas_ha_a_o` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 32 | Costo pago a jornales (ha/año) | `group_bn3nt58/group_bi0cl57/Costo_pago_a_jornales_ha_a_o` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 33 | % de destino de la producción de Autoconsumo | `group_bn3nt58/group_bi0cl57/_de_destino_de_la_p_cci_n_de_Autoconsumo_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 34 | % de destino de la producción de venta local | `group_bn3nt58/group_bi0cl57/_de_destino_de_la_p_cci_n_de_venta_local_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 35 | % de destino de la producción de venta regional | `group_bn3nt58/group_bi0cl57/_de_destino_de_la_p_n_de_venta_regional_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 36 | % de destino de la producción de venta nacional | `group_bn3nt58/group_bi0cl57/_de_destino_de_la_p_n_de_venta_nacional_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 37 | % de destino de la producción de venta exportación | `group_bn3nt58/group_bi0cl57/_de_destino_de_la_p_de_venta_exportaci_n_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 38 | % de destino de la producción en transformación | `group_bn3nt58/group_bi0cl57/_de_destino_de_la_p_n_en_transformaci_n_003` | `siempre` | FIJO (plantilla) — PENDIENTE |
| 39 | Calidad de la entrevista | `Calidad_de_la_entrevista` | `siempre` | DEL DÍA |
| 40 | Hora de término de la entrevista | `Hora_de_t_rmino_de_la_entrevista` | `siempre` | DEL DÍA |

### Notas

- `Predio ID`, `Especie` (poda frutal/agro) tienen *Visible si* = `false()`: nunca se muestran, el formulario no los exige.
- Poda, colmenas, almacenamiento de agua y obras contra incendios solo son obligatorios si se contesta "Sí"; la plantilla contesta "No", así que no aplican.
- **Cultivo anual 1** (17 obligatorios, siempre visibles) y **Unidad de medida** del cultivo eje de especia no venían en la plantilla original: quedan PENDIENTES hasta que se definan una vez en *Plantilla fija*.
- Matrices: el valor interno de cada casilla no tiene sentido (fila_1, opci_n_2, disminucion…). La app elige por **posición** (A = 1.ª casilla) y por el **texto** de la fila.