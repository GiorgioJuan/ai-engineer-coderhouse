# 02 — Pipeline de extracción de entidades técnicas (LCEL + validación)

Pre-entrega 2. Un pipeline que recibe texto crudo (un log de error, una descripción de
arquitectura, un ticket) y devuelve un objeto Pydantic validado. Construido con LCEL, con
salida estructurada y reintentos ante JSON mal formado o respuestas cortadas.

## Archivos

| Archivo | Contenido |
|---|---|
| `schemas.py` | Contrato de datos: `ExtraccionTecnica` (`tecnologias`, `nivel_de_criticidad`, `resumen_tecnico`) y el enum `NivelCriticidad`. |
| `chain.py` | Modelo (OpenAI o Anthropic), `ChatPromptTemplate`, la cadena LCEL con `.with_structured_output()` + `.with_retry()`, y `process_text()`. |
| `main.py` | Mini-script de prueba asíncrono: tres textos, incluido uno ambiguo. |
| `.env.example` | Variables de entorno. |

## Cómo correrlo

Requiere **Python 3.12**.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
python main.py
```

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `LLM_PROVIDER` | no | `openai` o `anthropic`. Default: `openai`. |
| `OPENAI_API_KEY` | sí, si usás OpenAI | Clave de OpenAI. |
| `ANTHROPIC_API_KEY` | sí, si usás Anthropic | Clave de Anthropic. |
| `OPENAI_MODEL` / `ANTHROPIC_MODEL` | no | Defaults: `gpt-4o-mini` / `claude-sonnet-5`. |
| `MAX_TOKENS` | no | Default `512`. Bajalo mucho para ver el pipeline detectar `finish_reason=length` y reintentar. |

## Salida esperada

```json
{
  "tecnologias": ["FastAPI", "Redis", "PostgreSQL"],
  "nivel_de_criticidad": "alta",
  "resumen_tecnico": "API con caché en Redis y persistencia en PostgreSQL; el pool de conexiones se agotó y se perdieron peticiones."
}
```

Con los logs en INFO se ve el proceso completo:

```
INFO     pipeline | Procesando texto (243 caracteres)
WARNING  pipeline | JSON invalido o incompleto: Expecting ',' delimiter
INFO     pipeline | Validacion OK: 3 tecnologias, criticidad=alta
INFO     pipeline | Listo: API con caché en Redis y persistencia en PostgreSQL...
```

## Cómo está armada la cadena

```python
cadena = PROMPT | model.with_structured_output(ExtraccionTecnica, include_raw=True) | RunnableLambda(_validar)
cadena.with_retry(
    retry_if_exception_type=(SalidaInvalida, RespuestaIncompleta, ValidationError),
    wait_exponential_jitter=True,
    stop_after_attempt=3,
)
```

**Por qué `include_raw=True`.** Sin eso, LangChain devuelve el objeto parseado y punto: si
el modelo cortó la respuesta a mitad de camino, te enterás tarde o nunca. Con el mensaje
crudo a mano, `_validar()` revisa el `finish_reason` **antes** de intentar usar el objeto y
distingue tres fallas: respuesta truncada, JSON inválido, y respuesta vacía. Cada una lanza
una excepción propia, que es lo que dispara el reintento.

**Qué se reintenta y qué no.** `retry_if_exception_type` lista solo errores recuperables
(formato, truncamiento, validación de Pydantic). Un 401 por API key inválida o un error de
cuota es permanente: reintentarlo tres veces solo suma latencia y gasto. Esos caen al
`except` general de `process_text()`, que loguea y devuelve `None`.

**El backoff.** `wait_exponential_jitter=True` espera cada vez un poco más, con ruido
aleatorio, para no golpear al proveedor en sincronía si hay varias instancias corriendo.

**Límite conocido del reintento.** Con `temperature=0` el modelo tiende a repetir la misma
salida, así que reintentar sirve para fallas transitorias, no para una causa estructural. El
caso típico es `finish_reason=length`: si la respuesta no entra en `MAX_TOKENS`, los tres
intentos se van a truncar igual. Por eso el log distingue esa falla por separado — cuando la
ves repetida, la solución es subir `MAX_TOKENS`, no insistir.

**Dónde están las instrucciones de formato.** No hay una variable `{format_instructions}`
en el prompt a propósito: con `.with_structured_output()` el esquema viaja al proveedor como
definición de tool, que es un contrato más fuerte que pedirlo en texto. Los
`Field(description=...)` de `schemas.py` son los que le dicen al modelo que use nombres
canónicos y no invente tecnologías. El `ChatPromptTemplate` queda modular con una sola
variable de entrada, `{texto}`.

**Nada de f-strings.** El texto de entrada entra como variable `{texto}` del
`ChatPromptTemplate`, así LangChain gestiona el escapado y la cadena queda reutilizable.

## Sobre la prueba de estrés

El tercer texto de `main.py` es ambiguo a propósito ("Ayer estuvo raro todo, medio lento...")
y **no menciona ninguna tecnología**. Ahí chocan dos reglas: el esquema exige al menos una
tecnología (`min_length=1`) y el prompt prohíbe inventar. El resultado esperado es que el
modelo no logre producir un objeto válido, se agoten los tres intentos y `process_text()`
devuelva `None` con un log de error.

Eso es el comportamiento correcto, no una falla: para un texto sin contenido técnico, un
`None` explícito es mejor que un objeto con tecnologías alucinadas. Si tu caso de uso
prefiere lo contrario, sacá el `min_length=1` de `tecnologias` y el pipeline devolverá una
lista vacía.

## Nota sobre Anthropic

`ChatAnthropic` se construye sin `temperature`: la Messages API actual no la acepta para
estos modelos y LangChain emite un warning si se la pasás. Para OpenAI sí se usa
`temperature=0`, porque en extracción querés determinismo.
