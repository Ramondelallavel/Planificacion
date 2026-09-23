# Ficheros de prueba

Los tests `test_pdf_real.py` usan el PDF real de la tanda 2210 que HIDRAL proporcionó como ejemplo:

    tests/fixtures/07_Tanda_EH-2210_OrdenesFab.pdf

El fichero **no se versiona** (contiene datos de clientes y contactos). Cópielo en esta carpeta
o indique su ruta con la variable `HIDRAL_PDF_EJEMPLO`. Si no está, esos tests se omiten; el
resto usa PDF sintéticos generados por `tests/generador_pdf.py`.
