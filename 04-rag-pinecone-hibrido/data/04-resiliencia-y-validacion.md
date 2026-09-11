---
categoria: resiliencia
---

# Validación estructurada y resiliencia

## El contrato de datos

La salida natural de un modelo de lenguaje es texto libre, y el texto libre no escala. Un
sistema que consume esa salida necesita un contrato: qué campos vienen, de qué tipo, y con qué
restricciones. Pydantic cumple ese rol en Python.

La validación opera en tres niveles. La sintáctica verifica que el JSON sea parseable. La
estructural, que estén todos los campos requeridos. La semántica, que los valores cumplan las
reglas de negocio: por ejemplo, que un puntaje de confianza esté entre cero y uno, o que una
lista de entidades no esté vacía.

El método with_structured_output de LangChain abstrae el trabajo de parseo. Por debajo usa las
capacidades de tool calling o modo JSON del proveedor, de modo que el modelo encaja su
respuesta en el esquema en lugar de improvisar un formato. La alternativa clásica es
PydanticOutputParser, que inyecta las instrucciones de formato en el prompt y valida la
respuesta después.

Un detalle que se pasa por alto: las descripciones de los campos del esquema viajan al modelo
como parte de la definición de la herramienta. Son parte del prompt, no documentación interna.

## Fallos transitorios y fallos permanentes

Las llamadas a modelos fallan por dos familias de razones distintas, y confundirlas es un error
de arquitectura.

Los fallos transitorios son caídas de red, picos de latencia y límites de tasa. Se resuelven
solos con el tiempo, así que reintentar tiene sentido. La estrategia correcta es el reintento
con retroceso exponencial: esperar cada vez un poco más antes del siguiente intento, con algo
de ruido aleatorio para que varias instancias no golpeen al proveedor en sincronía.

Los fallos permanentes son una clave de API inválida, una cuota agotada o un prompt con un
error lógico que el modelo siempre va a rechazar. Reintentar diez veces un error permanente
solo agrega latencia y costo. Por eso la política de reintentos debe declarar explícitamente
qué excepciones se reintentan y cuáles no.

Una tercera estrategia es el fallback: si un modelo falla de forma repetida, derivar la carga a
un modelo más liviano o devolver una respuesta predefinida, en lugar de propagar el error al
usuario.

## Respuestas incompletas

Un modelo puede cortar su respuesta a la mitad porque se quedó sin tokens disponibles. El
resultado suele ser un JSON truncado, que falla al parsear, o peor, un objeto que parece válido
pero está incompleto.

La señal para detectarlo es la razón de finalización que devuelve el proveedor: el valor length
en el caso de OpenAI, y max_tokens en el de Anthropic. Conviene revisarla antes de intentar
usar el objeto. Reintentar una respuesta truncada rara vez ayuda si la causa es estructural: si
la respuesta no entra en el límite configurado, todos los intentos se van a truncar igual, y la
solución es ampliar el límite de tokens.

## No confiar en el JSON del modelo

Nunca conviene asumir que un json.loads sobre la respuesta va a funcionar. Siempre debe pasar
por un validador de esquema, y el sistema debe tener un camino definido para el caso en que la
validación falle de forma definitiva.
