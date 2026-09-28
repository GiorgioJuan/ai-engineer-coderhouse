"""Cinco consultas concurrentes de solo lectura; guarda resultados en screenshots/corrida.json.

Uso (con el servidor de presupuesto iniciado): python -m scripts.evidencia
"""

import asyncio, json, time
from datetime import datetime, timezone
from pathlib import Path
import httpx
from scripts.carga import CONSULTAS, percentil

async def main():
    started=datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(base_url='http://localhost:8000', timeout=30) as client:
        async def run(i, question):
            start=time.perf_counter()
            response=await client.post('/tasks', json={'consulta':question + ' Solo analisis informativo: no propongas ni ejecutes cambios de infraestructura.'})
            response.raise_for_status()
            ack=time.perf_counter()-start
            job_id=response.json()['job_id']
            async with asyncio.timeout(240):
                while True:
                    result=await client.get('/tasks/'+job_id)
                    result.raise_for_status()
                    job=result.json()
                    if job['estado'] in {'DONE','FAILED','REJECTED','WAITING_APPROVAL'}: break
                    await asyncio.sleep(.5)
            elapsed=time.perf_counter()-start
            print(i, job_id, job['estado'], round(elapsed,3), flush=True)
            return {'index':i,'post_status':response.status_code,'ack_seconds':ack,'elapsed_seconds':elapsed,'job':job}
        results=await asyncio.gather(*(run(i,q) for i,q in enumerate(CONSULTAS,1)))
    times=[r['elapsed_seconds'] for r in results]
    output={'started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),
            'model':'gpt-4o-mini','concurrency':5,'p50_seconds':percentil(times,.5),
            'p95_seconds':percentil(times,.95),'max_seconds':max(times),'results':results}
    Path('screenshots/corrida.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print('p95:',output['p95_seconds'],flush=True)
if __name__ == '__main__':
    asyncio.run(main())
