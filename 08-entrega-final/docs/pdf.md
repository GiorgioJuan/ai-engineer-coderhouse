# Materiales PDF

En **Materiales → Agregar material**, arrastrar o elegir un `.pdf`. PanelLab extrae el texto localmente y muestra una vista previa editable con encabezados `## Página N`. Revisar especialmente tablas, columnas y saltos de línea antes de **Guardar material**. Se guarda el texto revisado como una versión documental; el archivo PDF original no se almacena.

La extracción no llama al modelo ni genera embeddings. En modo live, guardar sí inicia la indexación con el presupuesto compartido habitual. Cancelar la vista previa no crea documentos ni trabajos.

Límites: 10 MiB de archivo, 50 páginas y 200.000 bytes UTF-8 de texto extraído. El proyecto mantiene sus límites de 30 documentos y 1 MB de fuentes actuales. Los PDF deben contener texto seleccionable; para escaneos, aplicar OCR antes de importarlos. Los protegidos deben exportarse sin contraseña. Los documentos mixtos avisan qué páginas no aportaron texto, para evitar omisiones silenciosas.

## API

`POST /api/projects/{project_id}/documents/extract?filename=brief.pdf`, cuerpo binario `application/pdf`. Respuesta validada: `title`, `text`, `page_count`, `warnings`. No requiere clave de idempotencia porque no persiste recursos. El guardado posterior usa `POST /documents` con la clave habitual.

Los errores indican cómo recuperarse: PDF inválido/protegido/sin texto (422), archivo/páginas/texto excesivos (413). La lectura de la petición está acotada y el parser corre separado del event loop. Las citas nuevas respetan límites entre páginas y se validan contra el texto guardado.

La extracción usa [pypdf](https://pypdf.readthedocs.io/en/stable/user/extract-text.html). El orden visual de tablas y columnas no siempre se traduce fielmente a texto; la vista previa permite corregirlo antes de incluirlo como evidencia.
