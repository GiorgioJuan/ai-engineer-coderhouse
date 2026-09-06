# 01 — Cliente de LLM robusto y asíncrono

Pre-entrega 1 del curso. Un **Unified Async LLM Client**: una sola interfaz para hablar con
OpenAI y Anthropic, totalmente asíncrona, con streaming, validación con Pydantic y errores
controlados en lugar de crashes.

## Archivos

| Archivo | Contenido |
|---|---|
| `schemas.py` | Modelos Pydantic: `Provider`, `ChatMessage`, `ModelParams` (temperatura 0–2, `max_tokens`, `timeout`), `LLMConfig` (claves como `SecretStr`) y `ModelResponse` normalizada. |
| `clients.py` | `BaseLLMClient` (ABC), `OpenAIClient`, `AnthropicClient` y `AsyncLLMManager` (factory que elige el cliente según la config). |
| `main.py` | Script de validación: misma pregunta en modo normal y en streaming. |
| `async_patterns.py` | Demo autocontenida de `asyncio.gather` + `Semaphore` + `timeout` (batch de embeddings simulado). Corre sin API keys. |
| `.env.example` | Variables de entorno necesarias. |

## Cómo correrlo

Requiere **Python 3.12**.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
```

Editá `.env` con tus claves y después:

```bash
python main.py                    # usa LLM_PROVIDER del .env
python main.py anthropic          # fuerza un proveedor
python main.py openai anthropic   # ambos: las respuestas completas salen con gather
python async_patterns.py          # demo de concurrencia, no necesita claves
```

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `LLM_PROVIDER` | no | `openai` o `anthropic`. Default: `openai`. |
| `OPENAI_API_KEY` | sí, si usás OpenAI | Clave de OpenAI. |
| `ANTHROPIC_API_KEY` | sí, si usás Anthropic | Clave de Anthropic. |
| `OPENAI_MODEL` / `ANTHROPIC_MODEL` | no | Modelo a usar. Defaults: `gpt-4o-mini` / `claude-sonnet-5`. |
| `TEMPERATURE` | no | 0 a 2. Default `0.7`. Solo aplica a OpenAI (ver nota abajo). |
| `MAX_TOKENS` | no | Default `512`. |
| `TIMEOUT` | no | Segundos por llamada. Default `30`. |

`LLMConfig` valida que exista la clave del proveedor elegido y falla con un mensaje claro
si falta, antes de tocar la red.

## Decisiones de diseño

**Interfaz común sobre SDKs distintos.** OpenAI devuelve el texto en
`choices[0].message.content`; Anthropic devuelve una lista de bloques en `content` y recibe el
system prompt como parámetro aparte. Ambas diferencias quedan encerradas en cada cliente: el
resto de la app siempre recibe un `ModelResponse`.

**`temperature` es un parámetro de OpenAI.** El SDK `anthropic` 1.x removió `temperature`
de la Messages API (el control de sampling pasó a `output_config.effort`), así que
`AnthropicClient` no lo envía. El campo sigue validado en `ModelParams` porque lo pide la
consigna y porque OpenAI sí lo usa.

**Todo no bloqueante.** Se usan `AsyncOpenAI` y `AsyncAnthropic` con `await`. Usar la versión
síncrona dentro de una corrutina congelaría el event loop y, con él, a todos los usuarios.

**Streaming como generador asíncrono.** `stream()` hace `yield` de cada fragmento dentro de un
`async for` sobre el stream del SDK, así el primer token llega al usuario sin esperar los 500
restantes (baja el *time to first token*).

**Errores controlados, no excepciones sueltas.** Rate limits, claves inválidas, timeouts y
caídas de red se traducen a `ModelResponse(ok=False, error=...)`. El loop principal nunca se
rompe por un fallo del proveedor.

**Secretos fuera de los logs.** Las claves viven en `SecretStr`, así que no se filtran si un
traceback imprime la configuración.
