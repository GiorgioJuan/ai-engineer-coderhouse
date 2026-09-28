# 07 — API de producción y monitoreo activo

Pre-entrega 7. El orquestador multi-agente del [módulo 6](../06-orquestador-multiagente/)
expuesto como API REST asíncrona: FastAPI que encola y no bloquea, estado en Redis,
observabilidad con Phoenix y una pausa obligatoria de aprobación humana antes de las acciones
con efectos secundarios.

## Estructura

```
07-api-produccion/
├── app/
│   ├── main.py            # FastAPI: POST /tasks, GET /tasks/{id}, POST /tasks/{id}/approve
│   ├── graph.py           # orquestador del M6 + AsyncRedisSaver + nodo de aprobación
│   ├── agents.py          # los dos especialistas (heredados del M6)
│   ├── hitl.py            # interrupt(), catálogo de acciones y criterio de criticidad
│   ├── worker.py          # ejecución en segundo plano y estados en Redis
│   ├── store.py           # persistencia de jobs
│   ├── observability.py   # instrumentación Phoenix / LangSmith
│   ├── schemas.py         # contratos de la API
│   └── config.py
├── scripts/carga.py       # 5 peticiones concurrentes + p50/p95/max
├── screenshots/           # capturas del dashboard (ver su README)
├── docker-compose.yml     # api + redis + phoenix
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Cómo levantarlo

Requiere **Python 3.12** y Docker (para Redis y Phoenix).

### Con Docker Compose (todo junto)

```bash
cp .env.example .env        # Windows: copy .env.example .env
# poné tu OPENAI_API_KEY en .env
docker compose up --build
```

La API queda en `http://localhost:8000` (docs en `/docs`) y Phoenix en `http://localhost:6006`.

### En local (Redis y Phoenix en Docker, la API a mano)

```bash
python -m venv .venv
.venv\Scripts\activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

docker compose up -d redis phoenix
uvicorn app.main:app --reload
```

Verificá con `curl http://localhost:8000/health` → `{"api":"ok","redis":"ok"}`.

> **Redis Stack, no Redis a secas.** `langgraph-checkpoint-redis` usa el módulo RediSearch
> para indexar los checkpoints. El compose usa `redis/redis-stack-server`; con la imagen
> `redis:alpine` el checkpointer falla al arrancar.

## Los endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/tasks` | Encola la tarea. Devuelve **202** con `job_id` sin esperar al agente. |
| `GET` | `/tasks/{job_id}` | Estado del job. Nunca bloquea. |
| `POST` | `/tasks/{job_id}/approve` | Resuelve una pausa HITL. **409** si el job no está esperando aprobación. |
| `GET` | `/health` | Ping de la API y de Redis. |

### Ciclo de vida de un job

```
PENDING ──> RUNNING ──> DONE
               │  ↑
               │  └──────────────┐
               ├──> WAITING_APPROVAL ──> (approve) ──> DONE
               │                     └──> (reject) ──> REJECTED
               └──> FAILED
```

### Ejemplo completo

```bash
# 1. Encolar
curl -X POST http://localhost:8000/tasks -H "Content-Type: application/json" \
  -d '{"consulta":"Analizá la latencia de nuestros servicios y actuá si hace falta"}'
# -> {"job_id":"a5c4f8dd3e4c","estado":"PENDING","url_estado":"/tasks/a5c4f8dd3e4c"}

# 2. Pollear
curl http://localhost:8000/tasks/a5c4f8dd3e4c
# -> {"estado":"WAITING_APPROVAL","aprobacion_pendiente":{
#      "accion":"escalar_infraestructura","costo_estimado_usd":4800,"critica":true,...}}

# 3. Aprobar (o rechazar con "aprobado": false)
curl -X POST http://localhost:8000/tasks/a5c4f8dd3e4c/approve \
  -H "Content-Type: application/json" -d '{"aprobado":true,"comentario":"dale"}'

# 4. Resultado
curl http://localhost:8000/tasks/a5c4f8dd3e4c
# -> {"estado":"DONE","resultado":"Se escaló la infraestructura..."}
```

## La prueba de carga

```bash
python scripts/carga.py            # 5 peticiones concurrentes
python scripts/carga.py --n 10     # más carga
```

Imprime la latencia end-to-end de cada job y el p50 / p95 / max de la corrida. Ese p95 es el
que hay que cruzar con el del dashboard.

**Capturas completas de una corrida real:** cinco tareas concurrentes en `DONE`, Redis Stack,
Phoenix y OpenAI `gpt-4o-mini`. Las cuatro capturas solicitadas, una captura adicional de
herramientas y el análisis medido están en [`screenshots/README.md`](screenshots/README.md).
El p95 fue de **17,18 s en Phoenix** y **17,65 s desde el cliente**. El costo conservador
acumulado de la verificación inicial y la corrida final fue **USD 0,01526940**, bajo el
presupuesto de USD 1. Para repetir con control de gasto, usar
`python -m scripts.servidor_presupuesto` y `python -m scripts.evidencia`.

## Decisiones de diseño

**El endpoint no espera al agente.** `POST /tasks` escribe el job en Redis, lanza una
`asyncio.Task` y contesta 202. El worker actualiza el estado a medida que avanza y el cliente
pollea. Verificado: el `GET` inmediatamente posterior al `POST` ya devuelve `RUNNING`.

**Ninguna llamada bloqueante dentro de un endpoint.** Redis va por `redis.asyncio`, el grafo
por `ainvoke`, y el checkpointer es `AsyncRedisSaver`. No hace falta `run_in_threadpool` porque
no hay nada síncrono que envolver.

**Las excepciones del background siempre se escriben.** Es la regla que sostiene todo el
polling: si el agente explota, `ejecutar_job` captura la excepción y deja el job en `FAILED`
con el motivo. Sin eso, el cliente pollea para siempre un job que ya murió. Está probado
inyectando un fallo de rate limit.

**Referencias fuertes a las tareas en vuelo.** `worker.lanzar()` guarda la `Task` en un `set`
hasta que termina. `asyncio` sólo mantiene referencias débiles: sin esto, el recolector de
basura puede matar un job a mitad de camino.

**Un job es un hilo de estado.** El `job_id` se usa como `thread_id` del checkpointer, así que
todo el estado del grafo de ese job vive bajo esa clave en Redis.

**La aprobación usa el estado persistido.** El checkpointer guarda el estado del grafo en
Redis. El endpoint `POST /tasks/{job_id}/approve` reanuda la ejecución con el mismo `thread_id`.

**Qué se considera crítico.** Una acción pide aprobación si cuesta más de
`UMBRAL_COSTO_CRITICO` USD **o** si es irreversible. `purgar_cache` cuesta cero pero no se
puede deshacer, así que también frena. Las acciones desconocidas se tratan como críticas por
defecto: es el lado seguro del error.

**La instrumentación no puede tumbar la API.** Si Phoenix no está levantado,
`init_observabilidad()` loguea un warning y sigue. Perder trazas es malo; no arrancar es peor.

**No hace falta decorar nada.** `LangChainInstrumentor` engancha los callbacks de LangChain, y
de ahí salen los spans de cada nodo del grafo, cada llamada al modelo y cada herramienta.
Phoenix deriva el costo por ejecución de los tokens que vienen en esos spans. La exportación
usa OTLP HTTP estándar y un `BatchSpanProcessor`; evita una incompatibilidad de
`phoenix.otel.register` con atributos privados del exporter de OpenTelemetry.

## Pruebas realizadas

Pruebas funcionales controladas sobre la app FastAPI:

| Prueba | Resultado |
|---|---|
| `POST /tasks` | 202 + `job_id`; el `GET` inmediato devuelve `RUNNING` (no bloquea) |
| Ciclo HITL completo | El grafo pausa en `WAITING_APPROVAL` con la acción y su costo de 4800 USD; al aprobar llega a `DONE` |
| Rechazo | Con `aprobado: false` termina en `REJECTED` y la acción no se ejecuta |
| Excepción en background | Ante un error de rate limit simulado, el job termina en `FAILED` con el motivo |
| Códigos de error | 404 job inexistente, 409 approve sobre job terminado, 422 consulta inválida |

**Verificado además con infraestructura real (28/09/2026):** cinco solicitudes concurrentes
con respuesta 202, cinco jobs en `DONE`, cinco checkpoints recuperados desde Redis Stack
después de detener la API, 310 spans recibidos por Phoenix y cuatro capturas del dashboard
más un detalle adicional de herramientas. Ver [evidencia y métricas](screenshots/README.md).
