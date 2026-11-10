# Claves derivadas de relaciones del diagrama

`app/services/relationship_keys.py` sincroniza los atributos del JSON del
diagrama después de guardar clases, relaciones o contenido completo.
No crea tablas ni aplica migraciones en Neon.

- Asociación, agregación y composición 1:N: PK del lado 1 como FK no primaria
  en el lado N. La PK propia del lado N se conserva. La FK admite null si
  la multiplicidad del extremo referenciado es 0..1.
- Clase de asociación: PK conocidas de ambos participantes como PK compuesta
  y FK en la intermedia; atributos propios conservados. Una PK sustituta de
  esa clase deja de ser primaria mientras se usa esta política compuesta.
- Generalización: JOINED por defecto, igual que el generador actual. La PK
  de la hija referencia a la PK del padre. `inheritanceStrategy=SINGLE_TABLE`
  o `TABLE_PER_CLASS` en los datos de la relación desactiva esa derivación
  del diagrama; el generador actual de Java sigue implementando JOINED.
- Realización y plantillas no propagan claves. 1:1 necesita definir propiedad
  y unicidad de la FK; N:M sin clase intermedia no inventa una tabla puente.

Los atributos derivados guardan `_relationshipKey` con procedencia y datos
originales para recalcularlos sin duplicados, y retirarlos al quitar o reasignar
una relación. Los atributos manuales preexistentes se restauran. Los tipos
proceden de las PK de origen; sin una PK conocida no se inventa una referencia.

El generador Spring usa esas referencias para ubicar JoinColumn/JoinColumns
sin generar también una columna escalar duplicada para la FK derivada normal.
