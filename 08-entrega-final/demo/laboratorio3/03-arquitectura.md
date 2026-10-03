# Propuesta técnica

## Decisión inicial
Se propone una aplicación web con una API que valide las solicitudes. La comprobación de disponibilidad debe ocurrir en el servidor; una verificación únicamente visual en el calendario no evita solicitudes simultáneas.

## Alternativas
Se consideró conservar la planilla y agregar un formulario. Se descartó como solución final porque mantiene la reconciliación manual de horarios y no impide conflictos concurrentes.

## Estado de implementación
El equipo tiene un prototipo navegable del calendario. La persistencia y el control transaccional de reservas todavía son propuestas; no se han implementado ni probado.

## Próxima validación
Probar con la coordinadora la secuencia consultar disponibilidad, solicitar, revisar y confirmar. Registrar los problemas antes de ampliar el alcance.
