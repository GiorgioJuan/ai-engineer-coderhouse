"""Configuracion de la API."""

import os

from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JOB_TTL = int(os.getenv("JOB_TTL", "3600"))  # segundos que sobrevive un job en Redis

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

MAX_PASOS = int(os.getenv("MAX_PASOS", "6"))
RECURSION_LIMIT = int(os.getenv("RECURSION_LIMIT", "25"))

# Observabilidad: 'phoenix', 'langsmith' o 'none'
OBSERVABILIDAD = os.getenv("OBSERVABILIDAD", "phoenix").lower()
PHOENIX_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
PROJECT_NAME = os.getenv("PHOENIX_PROJECT_NAME", "orquestador-multiagente")

# Una accion se considera critica (y pide aprobacion humana) por encima de este costo.
UMBRAL_COSTO_CRITICO = float(os.getenv("UMBRAL_COSTO_CRITICO", "1000"))
