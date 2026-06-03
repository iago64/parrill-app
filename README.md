# Parrill App

Aplicación en Python + Streamlit para cargar una carta desde `carta.csv`, persistir usuarios y gestionar pedidos compartidos usando SQLite local.

## Qué incluye

- Base de datos local `parrilla.db` con tablas para usuarios, carta, pedidos, participantes e ítems.
- Seed automático de la carta a partir del CSV al iniciar la app por primera vez.
- Login inicial sólo con nombre; si el usuario ya existe, se reutiliza.
- Pedidos compartidos con estado (`Abierto`, `Confirmado`, `Cerrado`) y palabra clave de acceso.
- Quien crea el pedido puede cerrarlo y eliminarlo.
- Totales por persona y total general del pedido.

## Flujo de acceso

1. El usuario entra con su nombre en la primera pantalla.
2. Puede crear un pedido nuevo definiendo una palabra clave.
3. Para entrar a un pedido existente, debe ingresar esa palabra clave.

## Cómo correrla

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Estructura de datos

La app usa SQLite local mediante el módulo estándar `sqlite3`. Si más adelante necesitás moverla a otra base, la capa de acceso está concentrada en `db.py`.

## Notas

- `parrilla.db` se crea automáticamente en la raíz del proyecto.
- Si querés reinicializar la carta desde cero, borrá `parrilla.db` y volvé a ejecutar la app.