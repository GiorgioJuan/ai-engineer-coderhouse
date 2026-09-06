"""Refactorizacion a LCEL asincrono.

El modulo 1 hacia esto a mano: armar el diccionario de mensajes, llamar al SDK con
await, y despues sacar el texto de `res.choices[0].message.content` (o de la lista de
bloques, si era Anthropic). Aca todo eso es una sola linea declarativa:

    cadena = PROMPT | modelo | StrOutputParser()

El parser es el que devuelve texto plano en vez de un objeto AIMessage, y es lo que
permite encadenar el resultado con el paso siguiente sin transformaciones manuales.

Uso:
    python main.py
    python main.py "tu pregunta"
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

PREGUNTA_POR_DEFECTO = "¿Que es la entropia?"


def build_model() -> BaseChatModel:
    """Reemplaza la inicializacion manual del cliente del modulo 1."""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.3,
            max_tokens=300,
        )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # Sin `temperature`: la Messages API actual no la acepta para estos modelos.
        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
            max_tokens=300,
        )
    raise ValueError(f"LLM_PROVIDER invalido: '{provider}'. Usa 'openai' o 'anthropic'.")


# Roles definidos: el mensaje de sistema fija el tono, el humano trae la variable.
PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "Sos un divulgador cientifico. Respondes claro y en dos o tres oraciones."),
        ("human", "{pregunta}"),
    ]
)


def build_chain(modelo: BaseChatModel | None = None) -> Runnable:
    """Prompt -> Modelo -> Parser, compuesto con el operador pipe."""
    return PROMPT | (modelo or build_model()) | StrOutputParser()


async def main() -> None:
    load_dotenv()
    cadena = build_chain()

    pregunta = " ".join(sys.argv[1:]) or PREGUNTA_POR_DEFECTO

    # La clave del diccionario tiene que coincidir con la variable {pregunta} del prompt.
    respuesta = await cadena.ainvoke({"pregunta": pregunta})
    print(f"\n> {pregunta}\n{respuesta}")
    print(f"\n[tipo de la salida: {type(respuesta).__name__}]")

    # La misma cadena, sin cambiarle nada, procesa varias entradas a la vez.
    print("\n--- abatch: dos preguntas en paralelo ---")
    otras = [{"pregunta": "¿Que es un embedding?"}, {"pregunta": "¿Que es el event loop?"}]
    for entrada, salida in zip(otras, await cadena.abatch(otras)):
        print(f"\n> {entrada['pregunta']}\n{salida}")


if __name__ == "__main__":
    asyncio.run(main())
