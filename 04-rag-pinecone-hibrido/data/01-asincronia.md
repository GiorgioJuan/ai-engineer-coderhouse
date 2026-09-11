---
categoria: concurrencia
---

# Asincronía en sistemas de IA

## Por qué importa

En una aplicación que consume modelos de lenguaje, el tiempo no se gasta calculando: se gasta
esperando. El cálculo ocurre en los servidores del proveedor. Lo que hace nuestro proceso es
esperar a que el prompt viaje por la red, a que el modelo genere, y a que los tokens vuelvan.

Un modelo síncrono detiene el proceso completo durante esa espera. Si una llamada tarda dos
segundos y hacemos tres en secuencia, el usuario espera seis segundos y el servidor no puede
atender a nadie más mientras tanto. La asincronía convierte esa espera pasiva en una
oportunidad de ejecución.

Asyncio no es paralelismo real: es concurrencia cooperativa. Mientras una tarea espera datos
de la red, cede el control para que otra avance sobre el mismo hilo.

## Corrutinas, event loop y tareas

Una corrutina es una función declarada con `async def` que puede pausar su ejecución en cada
`await`. El event loop es el coordinador que decide qué corrutina avanza en cada momento. Una
Task es una corrutina ya programada para ejecutarse: a diferencia de una corrutina suelta, que
no hace nada hasta que la esperás, una Task corre en segundo plano.

El punto de entrada estándar es `asyncio.run(main())`. Se encarga de crear el loop, ejecutar la
corrutina principal y cerrar todo limpiamente al terminar.

## Patrones de concurrencia

`asyncio.gather` dispara varias corrutinas a la vez y espera a que todas terminen. Es el patrón
para comparar respuestas de varios modelos sobre el mismo prompt, o para buscar en una base
vectorial y en una API externa al mismo tiempo. El argumento `return_exceptions=True` evita que
el fallo de una rama tumbe todo el conjunto.

`asyncio.timeout` es un gestor de contexto que cancela la operación si tarda más de lo
permitido. Nunca hay que dejar una llamada a un modelo abierta indefinidamente: un modelo lento
o una API caída bloquean recursos sin límite.

`asyncio.Semaphore` limita cuántas tareas pueden estar activas al mismo tiempo. Es la
herramienta para respetar los límites de tasa del proveedor. Disparar mil llamadas simultáneas
garantiza un error 429 Too Many Requests; con un semáforo de cinco, las mil llamadas se encolan
y solo cinco corren a la vez.

## Errores frecuentes

El primero es creer que asyncio acelera el cálculo. No lo hace. Para tareas que consumen CPU
—limpieza de datos con Pandas, inferencia local en PyTorch— la herramienta es multiprocessing.
Asyncio sirve para tareas limitadas por entrada y salida: red, bases de datos, APIs.

El segundo, y más peligroso, es bloquear el event loop. Llamar a una función síncrona lenta
dentro de una corrutina —por ejemplo `time.sleep(5)` en lugar de `await asyncio.sleep(5)`—
congela a todos los usuarios a la vez. Si hay que usar una librería que no es asíncrona, la
salida es `asyncio.to_thread(funcion_bloqueante, datos)`, que la ejecuta en un hilo aparte.

## Streaming de tokens

El streaming es la aplicación más visible de la asincronía en productos de IA. En lugar de
esperar a que se generen los quinientos tokens de una respuesta para enviarla completa, se
procesa cada token a medida que llega de la red y se lo envía al frontend. Esto reduce el
Time To First Token, una de las métricas de experiencia de usuario más importantes. Se
implementa con generadores asíncronos: un bucle `async for` sobre el stream del SDK que hace
`yield` de cada fragmento.
