---
categoria: orquestacion
---

# LangChain Expression Language (LCEL)

## El problema de la orquestación manual

Con los SDKs base de los proveedores, cada paso de la lógica se maneja a mano: formatear las
variables dentro de un string, hacer la llamada al modelo, gestionar reintentos y sesiones, y
convertir el string de respuesta en algo útil. Cuando se agregan streaming, ejecución en
paralelo y trazado de errores, el código crece de forma desproporcionada y se vuelve difícil
de testear.

LCEL es un lenguaje declarativo para componer cadenas. Su idea central es que cada componente
es un bloque con una interfaz estándar, y que esos bloques se conectan con el operador pipe.

## El protocolo Runnable

Casi todos los objetos de LangChain, modelos, prompts, parsers y herramientas, heredan de la
clase base Runnable. Eso garantiza que todos expongan los mismos métodos.

El método invoke llama al componente con una entrada única de forma síncrona. El método ainvoke
es su versión asíncrona. El método batch procesa una lista de entradas optimizando la latencia,
y abatch es su equivalente asíncrono. El método stream devuelve fragmentos de la respuesta a
medida que se generan.

La analogía útil es una línea de montaje: cada estación recibe piezas y entrega un componente
más complejo. No importa qué haga la estación, todas aceptan entrada por la cinta y entregan
salida a la siguiente. El operador pipe es esa cinta transportadora.

## Composición con el operador pipe

La salida del componente de la izquierda se convierte en la entrada del de la derecha. El flujo
típico de una cadena de IA es: PromptTemplate, luego ChatModel, luego OutputParser.

El PromptTemplate toma un diccionario de variables y genera el mensaje formateado. El ChatModel
recibe ese mensaje y devuelve un objeto de mensaje. El OutputParser toma la respuesta cruda y
extrae el contenido limpio, por ejemplo un string o un objeto Pydantic.

ChatPromptTemplate permite definir roles: system, human y ai. Esto es importante en los modelos
modernos, que dependen del mensaje de sistema para seguir instrucciones de formato y seguridad.

## Paralelismo y lotes

RunnableParallel ejecuta varias sub-cadenas al mismo tiempo sobre la misma entrada y devuelve
un diccionario con los resultados de cada rama. El tiempo total pasa a ser el de la rama más
lenta en lugar de la suma de todas. Es el patrón para analizar una misma entrada desde varias
perspectivas independientes.

Un detalle clave: las claves del diccionario que produce RunnableParallel deben coincidir con
los nombres de las variables del prompt siguiente. Si no coinciden, la cadena falla.

Para muchas entradas, abatch es preferible a un bucle con ainvoke, porque optimiza
internamente las llamadas al proveedor.

LCEL también convierte automáticamente cualquier función en un Runnable. Eso permite intercalar
una lambda para adaptar la forma de los datos entre dos pasos, por ejemplo envolver un string
en el diccionario que espera el prompt siguiente.

## Buenas prácticas

En aplicaciones web conviene usar siempre los métodos asíncronos, para no bloquear el event
loop mientras se espera la respuesta del proveedor. Y conviene no saltearse el OutputParser:
sin él, la cadena devuelve un objeto de mensaje en lugar de texto limpio, y el siguiente paso
recibe un tipo que no espera.
