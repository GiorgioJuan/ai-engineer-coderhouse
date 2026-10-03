# Modo live: usar un modelo real

Por defecto PanelLab corre en modo demo. El modo live usa un proveedor compatible con OpenAI para
las decisiones del supervisor, las preguntas de los evaluadores, las valoraciones y los embeddings.

## Activación

1. En `08-entrega-final/`, crear `.env` a partir de `.env.example` y completar
   `PANEL_OPENAI_API_KEY`. La clave sólo la leen API y worker; nunca llega al frontend, a los
   documentos ni a las trazas.
2. Levantar con la base live:

```sh
docker compose -f compose.yaml -f compose.live.yaml up --build -d
```

3. Abrir http://127.0.0.1:8080. La etiqueta de la cabecera indica **IA en vivo**.

El override usa un Redis distinto (`redis-live`, con su propio volumen): las fuentes se indexan con
embeddings reales y no se mezclan con los vectores demo. Los proyectos demo siguen en su volumen y
reaparecen al volver a `docker compose up -d`. El botón de carga automática del ejemplo sólo existe
en demo; en live se pueden subir a mano los archivos de `demo/laboratorio3/`.

## Modelos

| Variable | Valor por defecto | Notas |
| --- | --- | --- |
| `PANEL_CHAT_MODEL` | `gpt-6-luna` | También admite `gpt-4o-mini`. Otro modelo requiere agregar su tarifa en `CHAT_MODELS` (`backend/app/llm.py`). |
| `PANEL_REASONING_EFFORT` | `low` | Sólo para modelos con razonamiento. |
| `PANEL_MAX_OUTPUT_TOKENS` | `4000` | Incluye tokens de razonamiento y respuesta. |
| `PANEL_EMBEDDING_MODEL` | `text-embedding-3-small` | Dimensión `PANEL_EMBEDDING_DIMENSIONS` (1536). |
| `PANEL_LLM_BASE_URL` | `https://api.openai.com/v1` | Cualquier API compatible (chat/completions + embeddings). |

Tarifas verificadas el 28/09/2026 en la documentación oficial: `gpt-6-luna` USD 0,10 / 0,50 por
millón de tokens de entrada / salida; `gpt-4o-mini` USD 0,15 / 0,60; `text-embedding-3-small`
USD 0,02. Phoenix trae las mismas tarifas y calcula el costo de cada llamada a partir de los tokens.
El adaptador rechaza prompts que excedan el tramo de precio estándar del modelo.

## Presupuesto

Antes de cada llamada se reserva en Redis el costo máximo posible y después se liquida con el uso
real que informa el proveedor. Las reservas son atómicas, así que llamadas concurrentes no pueden
superar el techo `PANEL_BUDGET_CAP_USD` (USD 0,95 por defecto). `PANEL_BUDGET_PRIOR_USD` permite
descontar un gasto previo. Una llamada que el proveedor rechaza (por ejemplo, clave inválida o falta
de crédito) libera su reserva; una que falla después de llegar al proveedor la conserva, porque pudo
haber tenido costo. El ledger vive en el volumen de `redis-live`: borrarlo reinicia el control, que
sólo conoce el consumo registrado por esta instalación.

## Errores del proveedor

`/api/health/ready` confirma la infraestructura, no la validez de la clave ni el saldo. Un problema
del proveedor aparece en el trabajo con un código claro (`ProviderHTTP401` para clave inválida,
`ProviderQuotaExceeded` para falta de crédito) y la interfaz lo explica en lenguaje simple. Esos
errores no se ofrecen como reintentables: hay que corregir la causa. Los transitorios (429 por
velocidad, 5xx, red) se reintentan una vez automáticamente y, si persisten, se pueden reintentar
desde la interfaz.

## Evidencia

La batería de cinco escenarios se ejecutó con `gpt-6-luna`: ver [evidence/README.md](../evidence/README.md).
