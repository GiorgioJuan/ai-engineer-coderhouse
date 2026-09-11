---
categoria: recuperacion
---

# Embeddings, chunking y bases vectoriales

## Qué es un embedding

Un embedding es la representación de un texto como un vector de números en un espacio de muchas
dimensiones. Textos con significado parecido quedan cerca en ese espacio, aunque no compartan
las mismas palabras. Esa es la propiedad que permite la búsqueda semántica: en lugar de buscar
coincidencias literales, se busca proximidad de significado.

La distancia entre dos vectores solo tiene sentido si ambos fueron generados por el mismo
modelo de embeddings. Indexar los documentos con un modelo y consultar con otro produce
resultados esencialmente aleatorios. Es el error más común al construir un sistema de
recuperación, y el más difícil de detectar, porque el sistema no falla: simplemente devuelve
fragmentos irrelevantes.

## Chunking

Los documentos rara vez se indexan enteros. Se los parte en fragmentos, o chunks, por dos
razones: un fragmento acotado produce un embedding más específico, y el contexto que se le pasa
al modelo tiene un límite de tokens.

RecursiveCharacterTextSplitter es la estrategia por defecto. Intenta cortar primero en los
separadores más naturales, saltos de párrafo, luego saltos de línea, luego oraciones, y solo
recurre a cortar por caracteres si no queda alternativa. Así evita partir una idea al medio.

Dos parámetros gobiernan el resultado. El tamaño de fragmento define cuánto texto entra en cada
chunk. El solapamiento, u overlap, define cuánto texto se repite entre un fragmento y el
siguiente; sirve para que una idea que cae justo en el borde no quede mutilada en ninguno de
los dos. Un punto de partida razonable es un tamaño de quinientos tokens con cincuenta de
solapamiento.

Fragmentos demasiado grandes diluyen el embedding y traen ruido. Fragmentos demasiado chicos
pierden el contexto necesario para que la respuesta tenga sentido.

## Bases vectoriales y persistencia

Una base vectorial almacena los embeddings junto al texto original y sus metadatos, y resuelve
la búsqueda por proximidad de forma eficiente. ChromaDB es una opción liviana que corre en
local y persiste en una carpeta del disco.

La ingesta es cara: cada fragmento requiere una llamada al modelo de embeddings. Por eso el
script de carga debe verificar si la colección ya está poblada antes de volver a indexar. Sin
esa verificación, cada ejecución vuelve a pagar el costo completo.

## Recuperación y el parámetro top_k

El retriever convierte la pregunta del usuario en un embedding, con el mismo modelo usado en la
indexación, y devuelve los fragmentos más cercanos. Cuántos devuelve lo define el parámetro
top_k.

Pasar demasiados fragmentos al modelo es contraproducente. Además del riesgo de superar el
límite de tokens, aparece el fenómeno conocido como Lost in the Middle: los modelos prestan más
atención al principio y al final del contexto que al medio, de modo que la información
sepultada entre muchos fragmentos se pierde. Un valor de entre tres y cinco fragmentos suele
ser el equilibrio adecuado.
