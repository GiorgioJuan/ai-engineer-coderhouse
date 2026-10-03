# Cinco perspectivas para defender una presentación

El catálogo inicial contiene cinco personajes ficticios. Sus nombres, identificadores y voces pertenecen al simulador; no incluyen biografías, instituciones, empleadores, fotografías, citas personales ni enlaces que identifiquen a personas reales.

| Personaje | Perspectiva | Pregunta que ayuda a resolver |
| --- | --- | --- |
| Bruno | Ejecución y compromisos | ¿Qué se entrega y cómo se comprueba? |
| Inés | Evidencia y experimentación | ¿Qué respalda la afirmación y qué podría refutarla? |
| Lucía | Diseño y robustez | ¿Por qué encajan las piezas y qué pasa cuando algo falla? |
| Santiago | Valor y adopción | ¿A quién le sirve y qué necesita para usarlo? |
| Elena | Comprensión y defensa de decisiones | ¿Se puede explicar el razonamiento con un ejemplo completo? |

## Diseño de las voces

Las cinco voces son personajes ficticios diseñados para el simulador. Cada Markdown define
prioridades, forma de preguntar, repreguntas según la respuesta, señales de una respuesta
convincente y límites. No representan a personas reales.

## Editar y usar

Los archivos están en `config/profiles/`. Se pueden importar, editar y versionar desde **Panel y criterios**. Una sesión convoca de uno a cinco evaluadores del catálogo, con tres a cinco preguntas; el supervisor elige quién interviene según el criterio y la evidencia disponible. Se reserva al menos una pregunta por evaluador seleccionado antes de repetir; con cinco evaluadores se configuran cinco preguntas. Podés cerrar la sesión antes si lo necesitás.

`focus` debe usar IDs de la rúbrica del proyecto. Las perspectivas no agregan criterios de calificación: cambian cómo se examinan los criterios existentes. Los cinco enfoques sirven también para presentaciones sin software ni fines comerciales.

El catálogo se actualiza al consultar los perfiles de un proyecto existente. Los ocho perfiles iniciales retirados ya no pueden seleccionarse para nuevas sesiones; los perfiles personalizados del usuario se conservan. Las versiones de una conversación siguen siendo resolubles para mantener el historial.

En **demo**, las preguntas son deterministas y permiten verificar el circuito. En **live**, el evaluador recibe su Markdown como dato de personalidad y formula las preguntas con esa voz.
