from __future__ import annotations

import importlib
import sqlite3

import streamlit as st

import db as db_module

importlib.reload(db_module)

from db import (
    add_order_item,
    as_dict,
    create_order,
    delete_order,
    format_currency,
    get_menu_by_category,
    get_order,
    get_order_by_access_key,
    get_order_items,
    get_order_members,
    get_order_totals_by_user,
    get_or_create_user,
    get_user,
    init_db,
    join_order,
    remove_order_item,
    update_order_status,
)


st.set_page_config(page_title="Parrill App", page_icon="🍽️", layout="wide")


APP_TITLE = "Parrill App"


ORDER_STATUS_LABELS = {
    "open": "Abierto",
    "confirmed": "Confirmado",
    "closed": "Cerrado",
}


def ensure_session_state() -> None:
    st.session_state.setdefault("selected_user_id", None)
    st.session_state.setdefault("selected_order_id", None)


def clear_selected_order() -> None:
    st.session_state["selected_order_id"] = None
    for key in ("menu_category", "menu_item", "menu_quantity", "menu_notes"):
        st.session_state.pop(key, None)


def logout_user() -> None:
    clear_selected_order()
    st.session_state["selected_user_id"] = None


def render_login_screen() -> None:
    st.title(APP_TITLE)
    st.write(
        "Ingresá tu nombre para continuar. Después vas a poder crear un pedido nuevo o entrar a uno existente con su palabra clave."
    )

    _, center_column, _ = st.columns([1, 1.3, 1])
    with center_column:
        with st.form("login_form"):
            name = st.text_input("Nombre", placeholder="Ej: Juan Perez")
            submitted = st.form_submit_button("Ingresar", use_container_width=True)

        if not submitted:
            return

        if not name.strip():
            st.error("El nombre es obligatorio.")
            return

        user_id = get_or_create_user(name)
        st.session_state["selected_user_id"] = user_id
        clear_selected_order()
        st.rerun()


def render_session_panel(user_name: str) -> None:
    st.sidebar.header("Sesión")
    st.sidebar.success(f"Usuario: {user_name}")
    if st.sidebar.button("Cerrar sesión", use_container_width=True):
        logout_user()
        st.rerun()


def handle_create_order_form(current_user_id: int) -> None:
    with st.sidebar.form("create_order_form", clear_on_submit=True):
        st.write("Crear pedido compartido")
        title = st.text_input("Nombre del pedido", placeholder="Ej: Mesa viernes")
        access_key = st.text_input(
            "Palabra clave",
            type="password",
            placeholder="Definí una clave para compartir",
        )
        submitted = st.form_submit_button(
            "Crear pedido",
            use_container_width=True,
        )

    if not submitted:
        return

    if not title.strip():
        st.sidebar.error("El pedido necesita un nombre.")
        return

    if not access_key.strip():
        st.sidebar.error("La palabra clave es obligatoria.")
        return

    try:
        order_id = create_order(title=title, created_by=current_user_id, access_key=access_key)
    except ValueError as error:
        st.sidebar.error(str(error))
        return
    except sqlite3.IntegrityError:
        st.sidebar.error("Esa palabra clave ya está en uso. Elegí otra.")
        return

    st.session_state["selected_order_id"] = order_id
    st.sidebar.success("Pedido creado. Compartí la palabra clave para que otros puedan ingresar.")
    st.rerun()


def handle_access_order_form(current_user_id: int) -> None:
    with st.sidebar.form("access_order_form", clear_on_submit=True):
        st.write("Entrar a un pedido")
        access_key = st.text_input(
            "Palabra clave del pedido",
            type="password",
            placeholder="Ingresá la clave compartida",
        )
        submitted = st.form_submit_button("Acceder", use_container_width=True)

    if not submitted:
        return

    if not access_key.strip():
        st.sidebar.error("Ingresá la palabra clave del pedido.")
        return

    order = get_order_by_access_key(access_key)
    if order is None:
        st.sidebar.error("No existe un pedido con esa palabra clave.")
        return

    join_order(order["id"], current_user_id)
    st.session_state["selected_order_id"] = int(order["id"])
    st.sidebar.success(f"Ingresaste a {order['title']}.")
    st.rerun()


def render_order_panel(current_user_id: int | None) -> int | None:
    st.sidebar.header("Pedido")
    if current_user_id is None:
        st.sidebar.info("Primero iniciá sesión para crear o acceder a un pedido.")
        return None

    handle_create_order_form(current_user_id)
    st.sidebar.divider()
    handle_access_order_form(current_user_id)

    selected_order_id = st.session_state.get("selected_order_id")
    if selected_order_id is not None:
        order = get_order(selected_order_id)
        if order is None:
            clear_selected_order()
            st.sidebar.warning("El pedido activo ya no existe.")
            return None

        st.sidebar.caption(f"Pedido activo: {order['title']} [{order['order_code']}]")
        if st.sidebar.button("Salir del pedido actual", use_container_width=True):
            clear_selected_order()
            st.rerun()

    return st.session_state.get("selected_order_id")


def render_order_header(order_data: dict, members: list) -> None:
    st.subheader(order_data["title"])
    status_label = ORDER_STATUS_LABELS.get(order_data["status"], order_data["status"])
    st.caption(
        f"Código: {order_data['order_code']} | Estado: {status_label} | Creó: {order_data['created_by_name']} | Clave: {order_data['access_key']}"
    )

    metrics = st.columns(3)
    metrics[0].metric("Total", format_currency(order_data["total_amount"]))
    metrics[1].metric("Participantes", len(members))
    metrics[2].metric("Actualizado", order_data["updated_at"])


def render_order_owner_actions(order_data: dict, current_user_id: int) -> None:
    if int(order_data["created_by"]) != int(current_user_id):
        return

    with st.expander("Administrar pedido", expanded=False):
        if order_data["status"] != "closed":
            if st.button("Cerrar pedido", use_container_width=True):
                try:
                    update_order_status(order_data["id"], "closed", current_user_id)
                except (PermissionError, ValueError) as error:
                    st.error(str(error))
                else:
                    st.success("Pedido cerrado.")
                    st.rerun()
        else:
            st.info("El pedido ya está cerrado.")

        st.divider()
        confirm_delete = st.checkbox(
            "Confirmo que quiero eliminar este pedido y todos sus ítems",
            key=f"confirm-delete-{order_data['id']}",
        )
        delete_disabled = not confirm_delete
        if st.button(
            "Eliminar pedido",
            type="primary",
            disabled=delete_disabled,
            use_container_width=True,
        ):
            try:
                delete_order(order_data["id"], current_user_id)
            except (PermissionError, ValueError) as error:
                st.error(str(error))
            else:
                clear_selected_order()
                st.success("Pedido eliminado.")
                st.rerun()


def render_menu_form(order_data: dict, current_user_id: int | None) -> None:
    st.subheader("Agregar ítems")
    if current_user_id is None:
        st.info("Seleccioná o creá un usuario para sumar productos al pedido.")
        return

    if order_data["status"] == "closed":
        st.info("El pedido está cerrado. Ya no se pueden agregar productos.")
        return

    if st.session_state.pop("reset_menu_form", False):
        st.session_state["menu_quantity"] = 1
        st.session_state["menu_notes"] = ""

    menu_by_category = get_menu_by_category()
    categories = list(menu_by_category.keys())
    if not categories:
        st.warning("No hay platos cargados en la carta.")
        return

    if st.session_state.get("menu_category") not in categories:
        st.session_state["menu_category"] = categories[0]

    selected_category = st.selectbox("Categoría", options=categories, key="menu_category")
    items = menu_by_category[selected_category]
    item_labels = {
        f"{row['name']} - {format_currency(row['price'])}": row["id"] for row in items
    }
    item_options = list(item_labels.keys())

    if st.session_state.get("menu_item") not in item_options:
        st.session_state["menu_item"] = item_options[0]

    selected_item_label = st.selectbox("Plato", options=item_options, key="menu_item")
    quantity = st.number_input("Cantidad", min_value=1, step=1, value=1, key="menu_quantity")
    notes = st.text_area("Notas", placeholder="Sin cebolla, bien cocido, etc.", key="menu_notes")
    submitted = st.button("Agregar al pedido", use_container_width=True)

    if submitted:
        try:
            add_order_item(
                order_id=order_data["id"],
                user_id=current_user_id,
                menu_item_id=item_labels[selected_item_label],
                quantity=int(quantity),
                notes=notes,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state["reset_menu_form"] = True
            st.rerun()


def render_members(members: list) -> None:
    st.subheader("Participantes")
    if not members:
        st.caption("Todavía no hay participantes en este pedido.")
        return

    for member in members:
        st.write(f"- {member['name']}")


def render_order_items(order_id: int, current_user_id: int | None, order_status: str) -> None:
    st.subheader("Detalle del pedido")
    items = get_order_items(order_id)
    if not items:
        st.caption("Todavía no se cargaron productos.")
        return

    if order_status == "closed":
        st.info("El pedido está cerrado. Ya no se pueden eliminar productos.")

    for row in items:
        subtotal = format_currency(row["subtotal"])
        notes_suffix = f" | Nota: {row['notes']}" if row["notes"] else ""
        title = f"{row['user_name']} pidió {row['quantity']} x {row['item_name']} ({subtotal})"

        columns = st.columns([7, 2])
        columns[0].write(f"{title}{notes_suffix}")
        can_delete = current_user_id == row["user_id"] and order_status != "closed"
        if columns[1].button(
            "Eliminar",
            key=f"delete-item-{row['id']}",
            disabled=not can_delete,
            use_container_width=True,
        ):
            try:
                remove_order_item(row["id"])
            except ValueError as error:
                st.error(str(error))
            else:
                st.rerun()


def render_totals(order_id: int) -> None:
    st.subheader("Totales por persona")
    totals = get_order_totals_by_user(order_id)
    if not totals:
        st.caption("Sin totales por mostrar.")
        return

    for row in totals:
        st.write(
            f"- {row['user_name']}: {row['total_items']} ítems | {format_currency(row['total_amount'])}"
        )


def main() -> None:
    init_db()
    ensure_session_state()

    current_user_id = st.session_state.get("selected_user_id")
    if current_user_id is None:
        render_login_screen()
        return

    current_user = get_user(current_user_id)
    if current_user is None:
        logout_user()
        render_login_screen()
        return

    st.title(APP_TITLE)
    st.write(
        "Gestioná pedidos compartidos de SisOp en la app de la parri de Campus"
    )

    render_session_panel(current_user["name"])
    current_order_id = render_order_panel(current_user_id)

    if current_order_id is None:
        st.info("Creá un pedido nuevo o ingresá la palabra clave de uno existente desde la barra lateral.")
        return

    order_data = as_dict(get_order(current_order_id))
    if order_data is None:
        clear_selected_order()
        st.warning("El pedido seleccionado ya no existe.")
        return

    members = get_order_members(current_order_id)
    render_order_header(order_data, members)
    render_order_owner_actions(order_data, current_user_id)

    left_column, right_column = st.columns([1.2, 1])
    with left_column:
        render_menu_form(order_data, current_user_id)
        render_order_items(current_order_id, current_user_id, order_data["status"])
    with right_column:
        render_members(members)
        render_totals(current_order_id)


if __name__ == "__main__":
    main()