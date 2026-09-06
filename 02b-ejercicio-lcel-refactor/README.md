# 02b — Ejercicio: refactorización a LCEL asíncrono

Ejercicio opcional de la unidad *Arquitectura de cadenas con LCEL y Runnables*. Toma la lógica
imperativa del [módulo 1](../01-cliente-llm-async/) y la reescribe como una cadena declarativa.

## Cómo correrlo

Requiere **Python 3.12**.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
python main.py
python main.py "¿Que es un event loop?"
```

Variables de entorno: `LLM_PROVIDER` (`openai` o `anthropic`), la API key del proveedor
elegido, y opcionalmente `OPENAI_MODEL` / `ANTHROPIC_MODEL`.

## El refactor

**Antes** — módulo 1, con el SDK crudo. El formateo, la llamada y la extracción del texto son
tres pasos manuales, y cada proveedor devuelve el texto en un lugar distinto:

```python
res = await client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "system", "content": "..."}, {"role": "user", "content": pregunta}],
)
texto = res.choices[0].message.content        # y en Anthropic: res.content[0].text
```

**Después** — la misma lógica como cadena:

```python
PROMPT = ChatPromptTemplate.from_messages([
    ("system", "Sos un divulgador científico..."),
    ("human", "{pregunta}"),
])

cadena = PROMPT | modelo | StrOutputParser()
respuesta = await cadena.ainvoke({"pregunta": "¿Qué es la entropía?"})
```

Lo que cambia no es solo la cantidad de líneas. Cambiar de OpenAI a Anthropic ahora es
reemplazar el objeto `modelo`: el `StrOutputParser` devuelve texto plano en los dos casos, así
que nada del código de alrededor se entera.

## Criterios de aceptación

| Criterio | Cómo se cumple |
|---|---|
| Flujo principal solo con LCEL (`\|`) | `PROMPT \| modelo \| StrOutputParser()` |
| Ejecución asíncrona con `await chain.ainvoke(...)` | En `main()` |
| Salida en texto plano, no un `BaseMessage` | `StrOutputParser`; el script imprime el tipo para que se vea |
| `ChatPromptTemplate` con roles System/Human | `from_messages([("system", ...), ("human", "{pregunta}")])` |

## Detalles que vale la pena notar

**El parser es lo que hace encadenable la cadena.** Sin él, el resultado es un `AIMessage` y el
paso siguiente recibe un tipo que no espera. Lo verifiqué: la misma cadena sin
`StrOutputParser` devuelve `AIMessage`; con él, `str`. Por eso `main.py` imprime el tipo de la
salida.

**Las claves tienen que coincidir.** El diccionario que se le pasa a `ainvoke` debe usar
exactamente los nombres de las variables del prompt. Pasar `{"question": ...}` cuando el prompt
espera `{pregunta}` levanta un `KeyError`.

**`abatch` sale gratis.** La misma cadena, sin tocarle nada, procesa varias entradas a la vez.
`main.py` lo muestra al final con dos preguntas. Para muchas entradas es bastante más eficiente
que un bucle con `ainvoke`.

**Sobre `temperature` en Anthropic.** Se configura solo para OpenAI: la Messages API actual no
acepta `temperature` para estos modelos y LangChain emite un warning si se la pasás.
