---
categoria: recuperacion
---

# Pinecone y búsqueda híbrida

## Índices serverless

Un índice serverless de Pinecone no requiere aprovisionar pods ni elegir un tamaño de máquina:
el servicio escala solo y se cobra por uso. Al crearlo hay que declarar tres cosas: la
dimensión de los vectores, la métrica de distancia y la región donde vive.

La dimensión debe coincidir exactamente con la del modelo de embeddings. El modelo
text-embedding-3-small de OpenAI produce vectores de 1536 dimensiones; text-embedding-3-large
produce 3072. Intentar insertar vectores de 1536 en un índice creado con 768 falla, y es uno de
los errores más frecuentes al montar la infraestructura. Conviene verificar la dimensión del
índice existente antes de escribir, en lugar de asumirla.

La métrica habitual para embeddings de texto es la similitud coseno.

## Namespaces

Un namespace es una partición lógica dentro del mismo índice. Los vectores de un namespace no
se mezclan con los de otro durante la búsqueda.

Sirven para separar inquilinos en una aplicación multi-tenant, para aislar entornos de
desarrollo y producción, o para dividir tipos de datos distintos dentro del mismo proyecto.
Ignorarlos hace que todas las consultas recorran el conjunto completo, lo que vuelve la
búsqueda más ruidosa y más lenta de lo necesario.

## Metadatos

Pinecone guarda, junto a cada vector, un diccionario de metadatos. La práctica recomendada es
almacenar ahí el texto original del fragmento, además de su origen, sección y etiquetas de
categoría.

El motivo es evitar una segunda consulta a una base de datos relacional para recuperar el texto
después de la búsqueda vectorial. Con el texto en los metadatos, una sola llamada devuelve todo
lo necesario para armar el contexto.

Los metadatos también habilitan el filtrado previo: se puede restringir la búsqueda a una
categoría o a un rango de fechas antes de calcular distancias, lo que mejora la precisión y
reduce el trabajo.

## Búsqueda léxica y BM25

La búsqueda vectorial encuentra significado parecido, pero tiene un punto ciego: los términos
exactos. Nombres propios, identificadores de error, versiones y nombres de función suelen
quedar diluidos en el embedding, porque el modelo los representa por su contexto y no por su
forma literal.

BM25 es un algoritmo de recuperación léxica clásico. Puntúa un documento según la frecuencia de
los términos de la consulta dentro de él, ajustada por la frecuencia de esos términos en toda
la colección y por la longitud del documento. Un término raro que aparece varias veces en un
documento pesa mucho; un término común pesa poco.

BM25 no entiende sinónimos ni paráfrasis, pero acierta cuando la consulta contiene el término
exacto.

## Recuperación híbrida

La recuperación híbrida combina ambas señales: la semántica del vector y la literal de BM25.
Cada recuperador produce su propio ranking y los rankings se fusionan.

La técnica de fusión más usada es Reciprocal Rank Fusion. En lugar de comparar puntajes, que
viven en escalas distintas y no son comparables, usa la posición de cada documento en cada
ranking: un documento que aparece alto en varias listas sube, y uno que aparece alto en una
sola lista sube menos. Eso evita tener que normalizar puntajes heterogéneos.

Los pesos relativos de cada recuperador se ajustan según el dominio. En documentación técnica,
con muchos nombres propios e identificadores, conviene darle más peso a la parte léxica que en
un corpus de prosa general.

## Evaluación de la recuperación

Un sistema de recuperación se mide antes de mirar la respuesta final del modelo. Si los
fragmentos correctos no llegan, ningún prompt los va a salvar.

Recall@k mide si el documento relevante aparece entre los k primeros resultados. Responde a la
pregunta de si el sistema encuentra lo que hay que encontrar.

Precision@k mide qué proporción de los k resultados devueltos es efectivamente relevante.
Responde a la pregunta de cuánto ruido acompaña a lo bueno.

Ambas se calculan contra un conjunto de referencia, o golden set: un puñado de preguntas para
las que se conoce de antemano cuál es el documento fuente correcto. No hace falta que sea
grande para ser útil; con unas pocas preguntas bien elegidas ya se detecta una regresión.
