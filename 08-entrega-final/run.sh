#!/usr/bin/env bash
# Atajos para levantar y verificar PanelLab. Uso: ./run.sh <comando>
set -euo pipefail
cd "$(dirname "$0")"

LIVE=(-f compose.yaml -f compose.live.yaml)

case "${1:-up}" in
  up)         # stack completo en modo demo (sin clave ni costo)
    docker compose up --build -d
    echo "Web: http://127.0.0.1:8080 · API: http://127.0.0.1:8080/api/docs · Phoenix: http://127.0.0.1:6007" ;;
  live)       # modo live: requiere PANEL_OPENAI_API_KEY en .env
    docker compose "${LIVE[@]}" up --build -d ;;
  test)       # tests backend (con Redis desechable), estilo y reglas ASYNC
    docker compose --profile test up -d --wait redis-test
    docker compose exec -T -e PANEL_TEST_REDIS_URL=redis://redis-test:6379/0 api python -m pytest -q
    docker compose exec -T api ruff check .
    docker compose exec -T api ruff format --check .
    docker compose --profile test stop redis-test ;;
  smoke)      # recorrido completo contra la API real en modo demo
    docker compose exec -T api python -m scripts.smoke --url http://localhost:8000 ;;
  scenarios)  # los cinco escenarios end-to-end (requiere Python con httpx en el host)
    python backend/scripts/scenarios.py "${@:2}" ;;
  graph)      # regenera el diagrama Mermaid del grafo
    docker compose exec -T api python -m scripts.export_graph ;;
  logs)       docker compose logs -f api worker ;;
  down)       docker compose down ;;
  *) echo "Comandos: up | live | test | smoke | scenarios | graph | logs | down"; exit 1 ;;
esac
