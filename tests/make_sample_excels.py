"""Genera Excel de ejemplo (datos ficticios) con los problemas tipicos del inventario."""
from pathlib import Path
from openpyxl import Workbook

OUT = Path(__file__).parent / "datos"
OUT.mkdir(exist_ok=True)

wb = Workbook(); ws = wb.active; ws.title = "PADRON"
ws.append(["CURP", "POLIGONO", "Apellido_p", "Apellido_m", "Nombre", "CAC_ID", "NOMBRE_CAC",
           "CENTROIDE_LATITUD", "CENTROIDE_LONGITUD", "ID_PREDIO", "TECNICA", "CURP de la técnica"])
ws.append(["PEGJ800101HNTRRN01", "P-01", "Pérez", "García", "Juan", "CAC-101", "LOS PINOS", 21.5123, -104.8941,
           "21.5123,-104.8941", "TECNICA DEMO", "TEDE850101MNTRRR05"])
ws.append(["LOMM750505MNTPRR02", "P-02", "López", "Martínez", "María", "CAC-101", "LOS PINOS", None, None,
           "21.4801,-104.9012", "TECNICA DEMO", "TEDE850101MNTRRR05"])
ws.append(["RAHP900909HJCMRD03", "P-03", "Ramírez", "Hernández", "Pedro", "CAC-102", "EL ROBLE", 21.33, -104.77,
           "21.33,-104.77", "TECNICA DEMO", ""])
wb.save(OUT / "padron_ejemplo.xlsx")

wb = Workbook(); ws = wb.active; ws.title = "INVENTARIO"
ws.append(["INVENTARIO DE PLANTA VIVA 2026"])
ws.append(["ID DEL SEMBRADOR", "NOMBRE SEMBRADOR", "CAC", "POLÍGONO", "HA", "AÑO DE ESTABLECIMIENTO",
           "NOMBRE COMÚN", "NOMBRE CIENTÍFICO", "NÚMERO", "CM DIÁMETRO", "M ALTURA"])
rows = [
    ["", "JUAN PEREZ GARCIA", "LOS PINOS", "P-01", 2.5, 2021, "NARANJA", "CITRUS SINENSIS", 40, 3.5, 1.2],
    ["", "JUAN PEREZ GARCIA", "LOS PINOS", "P-01", 2.5, 2021, "NARANJA", "CITRUS SINENSIS", 40, 3.5, 1.2],   # duplicado
    ["", "JUAN PEREZ GARCIA", "LOS PINOS", "P-01", 2.5, 2022, "NARANJA", "CITRUS SINENSIS", 20, 2, ".80"],
    ["", "JUAN PEREZ GARCIA", "LOS PINOS", "P-01", 2.5, 2021, "MANGO", "MANGIFERA INDICA", 15, None, ".20"],
    ["", "JUAN PEREZ GARCIA", "LOS PINOS", "P-01", 2.5, 2021, "FRESNO", "FFRAXINUS UHDEI", 30, 5, 2.1],
    ["", "JUAN PEREZ GARCIA", "LOS PINOS", "P-01", 2.5, 2020, "MACUILIS, AMAPA, PALO DE ROSA", "TABEBUIA ROSEA", 12, 6, 2.5],
    ["", "JUAN PEREZ GARCIA", "LOS PINOS", "P-01", 2.5, 2022, "OREGANO", "LIPPIA GRAVEOLENS", 50, None, None],
    ["", "JUAN PEREZ GARCIA", "LOS PINOS", "P-01", 2.5, 2021, "AGAVE", "AGAVE TEQUILANA", 25, None, ".5"],
    ["", "JUAN PEREZ GARCIA", "LOS PINOS", "P-01", 2.5, 2021, "ZAPOTE RARO", "POUTERIA INVENTADA", 3, None, None],
    ["", "MARIA LOPEZ MARTINEZ", "LOS PINOS", "P-02", 1.0, 2021, "LIMON", "CITRUS LATIFOLIA", 60, 2.5, 1.0],
    ["", "MARIA LOPEZ MARTINEZ", "LOS PINOS", "P-02", 1.0, 2021, "PINO OCOTE", "PINUS OOCARPA", 35, 4, 1.8],
    ["", "SEMBRADOR FANTASMA", "EL ROBLE", "P-09", 1.0, 2021, "MANGO", "MANGIFERA INDICA", 5, None, None],
]
for r in rows:
    ws.append(r)
wb.save(OUT / "inventario_ejemplo.xlsx")
print("ok", OUT)
