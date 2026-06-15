from __future__ import annotations

import hashlib
import hmac
import importlib
import os
import sqlite3
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components
from streamlit.errors import StreamlitSecretNotFoundError

import db as db_module

importlib.reload(db_module)

from db import (
    add_order_item,
    as_dict,
    create_order,
    delete_order,
    delete_order_as_admin,
    get_menu_by_category,
    get_order,
    get_order_by_access_key,
    get_order_items,
    get_order_members,
    get_orders,
    get_order_totals_by_product,
    get_or_create_user,
    get_user,
    init_db,
    join_order,
    remove_order_item,
    remove_order_item_as_admin,
    update_order_status,
)


st.set_page_config(page_title="Parrill App", page_icon="🍽️", layout="wide")


APP_TITLE = "Parrill App"
ADMIN_PASSWORD_ENV_VAR = "PARRILL_APP_ADMIN_PASSWORD"
COOKIE_TTL_SECONDS = 60 * 60 * 24 * 30
COOKIE_USER_NAME_KEY = "parrill_app_user_name"
COOKIE_ORDER_ID_KEY = "parrill_app_order_id"
COOKIE_ADMIN_KEY = "parrill_app_admin"


ORDER_STATUS_LABELS = {
    "open": "Abierto",
    "confirmed": "Confirmado",
    "closed": "Cerrado",
}


def get_cookie_value(cookie_key: str) -> str:
    return str(st.context.cookies.get(cookie_key, "") or "").strip()


def set_cookie(cookie_key: str, value: str, max_age_seconds: int = COOKIE_TTL_SECONDS) -> None:
    encoded_value = quote(value, safe="")
    components.html(
        f"""
        <script>
            document.cookie = "{cookie_key}={encoded_value}; path=/; max-age={max_age_seconds}; SameSite=Lax";
        </script>
        """,
        height=0,
    )


def clear_cookie(cookie_key: str) -> None:
    components.html(
        f"""
        <script>
            document.cookie = "{cookie_key}=; path=/; max-age=0; SameSite=Lax";
        </script>
        """,
        height=0,
    )


def build_admin_cookie_token(admin_password: str) -> str:
    return hmac.new(
        key=admin_password.encode("utf-8"),
        msg=b"parrill-app-admin",
        digestmod=hashlib.sha256,
    ).hexdigest()


def restore_session_from_cookies() -> None:
    current_user_id = st.session_state.get("selected_user_id")
    if current_user_id is None:
        cookie_name = get_cookie_value(COOKIE_USER_NAME_KEY)
        if cookie_name:
            try:
                st.session_state["selected_user_id"] = get_or_create_user(cookie_name)
            except ValueError:
                clear_cookie(COOKIE_USER_NAME_KEY)

    current_order_id = st.session_state.get("selected_order_id")
    if current_order_id is None:
        cookie_order_id = get_cookie_value(COOKIE_ORDER_ID_KEY)
        if cookie_order_id.isdigit() and get_order(int(cookie_order_id)) is not None:
            st.session_state["selected_order_id"] = int(cookie_order_id)
        elif cookie_order_id:
            clear_cookie(COOKIE_ORDER_ID_KEY)

    if st.session_state.get("admin_authenticated"):
        return

    admin_password = get_admin_password()
    if not admin_password:
        clear_cookie(COOKIE_ADMIN_KEY)
        return

    cookie_admin_token = get_cookie_value(COOKIE_ADMIN_KEY)
    expected_token = build_admin_cookie_token(admin_password)
    if cookie_admin_token and hmac.compare_digest(cookie_admin_token, expected_token):
        st.session_state["admin_authenticated"] = True


def sync_session_cookies() -> None:
    current_user_id = st.session_state.get("selected_user_id")
    if current_user_id is None:
        clear_cookie(COOKIE_USER_NAME_KEY)
    else:
        user = get_user(int(current_user_id))
        if user is None:
            clear_cookie(COOKIE_USER_NAME_KEY)
        else:
            set_cookie(COOKIE_USER_NAME_KEY, str(user["name"]))

    current_order_id = st.session_state.get("selected_order_id")
    if current_order_id is None:
        clear_cookie(COOKIE_ORDER_ID_KEY)
    else:
        set_cookie(COOKIE_ORDER_ID_KEY, str(int(current_order_id)))

    admin_password = get_admin_password()
    if not st.session_state.get("admin_authenticated") or not admin_password:
        clear_cookie(COOKIE_ADMIN_KEY)
    else:
        set_cookie(COOKIE_ADMIN_KEY, build_admin_cookie_token(admin_password))


def ensure_session_state() -> None:
    st.session_state.setdefault("selected_user_id", None)
    st.session_state.setdefault("selected_order_id", None)
    st.session_state.setdefault("admin_authenticated", False)


def clear_selected_order() -> None:
    st.session_state["selected_order_id"] = None
    for key in ("menu_category", "menu_item", "menu_quantity", "menu_notes"):
        st.session_state.pop(key, None)
    sync_session_cookies()


def logout_user() -> None:
    clear_selected_order()
    st.session_state["selected_user_id"] = None
    st.session_state["admin_authenticated"] = False
    sync_session_cookies()


def get_admin_password() -> str:
    try:
        secret_password = str(st.secrets.get("admin_password", "")).strip()
    except StreamlitSecretNotFoundError:
        secret_password = ""
    if secret_password:
        return secret_password

    return os.getenv(ADMIN_PASSWORD_ENV_VAR, "").strip()


def render_admin_access_panel() -> bool:
    admin_password = get_admin_password()

    with st.sidebar.expander("Administración", expanded=False):
        if not admin_password:
            st.session_state["admin_authenticated"] = False
            sync_session_cookies()
            st.caption(
                "Configurá `admin_password` en Streamlit secrets o la variable de entorno "
                f"`{ADMIN_PASSWORD_ENV_VAR}` para habilitar esta vista."
            )
            return False

        if st.session_state.get("admin_authenticated"):
            st.success("Panel administrativo habilitado.")
            if st.button("Cerrar panel admin", use_container_width=True):
                st.session_state["admin_authenticated"] = False
                sync_session_cookies()
                st.rerun()
            return True

        with st.form("admin_access_form", clear_on_submit=True):
            entered_password = st.text_input("Contraseña de administración", type="password")
            submitted = st.form_submit_button("Abrir panel", use_container_width=True)

        if submitted:
            if entered_password == admin_password:
                st.session_state["admin_authenticated"] = True
                sync_session_cookies()
                st.rerun()

            st.error("La contraseña administrativa es incorrecta.")

    return st.session_state.get("admin_authenticated", False)


def render_admin_orders_panel() -> None:
    st.subheader("Pedidos armados")
    st.caption(
        "Vista administrativa protegida. El borrado elimina el pedido, sus participantes y sus ítems."
    )

    orders = [as_dict(order) for order in get_orders()]
    if not orders:
        st.info("No hay pedidos cargados.")
        return

    open_orders = sum(1 for order in orders if order["status"] == "open")
    closed_orders = sum(1 for order in orders if order["status"] == "closed")
    metrics = st.columns(3)
    metrics[0].metric("Pedidos", len(orders))
    metrics[1].metric("Abiertos", open_orders)
    metrics[2].metric("Cerrados", closed_orders)

    table_rows = []
    order_options: dict[str, dict] = {}
    for order in orders:
        status_label = ORDER_STATUS_LABELS.get(order["status"], order["status"])
        label = (
            f"{order['title']} [{order['order_code']}] | {status_label} | "
            f"{order['created_by_name']}"
        )
        order_options[label] = order
        table_rows.append(
            {
                "Codigo": order["order_code"],
                "Pedido": order["title"],
                "Estado": status_label,
                "Creador": order["created_by_name"],
                "Participantes": order["member_count"],
                "Items": order["total_items"],
                "Actualizado": order["updated_at"],
            }
        )

    st.dataframe(table_rows, hide_index=True, use_container_width=True)

    selected_label = st.selectbox(
        "Pedido a eliminar",
        options=list(order_options.keys()),
        index=None,
        placeholder="Seleccioná un pedido para borrarlo",
    )
    if selected_label is None:
        return

    selected_order = order_options[selected_label]
    st.warning(
        f"Vas a eliminar {selected_order['title']} [{selected_order['order_code']}]. Esta acción no se puede deshacer."
    )

    with st.form(f"admin_delete_order_{selected_order['id']}"):
        confirmation_code = st.text_input(
            "Escribí el código del pedido para confirmar",
            placeholder=str(selected_order["order_code"]),
        )
        submitted = st.form_submit_button(
            "Eliminar pedido definitivamente",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return

    if confirmation_code.strip().upper() != str(selected_order["order_code"]):
        st.error("El código ingresado no coincide. No se eliminó el pedido.")
        return

    try:
        delete_order_as_admin(int(selected_order["id"]))
    except ValueError as error:
        st.error(str(error))
        return

    if st.session_state.get("selected_order_id") == int(selected_order["id"]):
        clear_selected_order()

    st.success("Pedido eliminado.")
    st.rerun()


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
        sync_session_cookies()
        st.rerun()


def render_session_panel(user_name: str) -> None:
    st.sidebar.header("Sesión")
    st.sidebar.success(f"Usuario: {user_name}")
    if st.sidebar.button("Cerrar sesión", use_container_width=True):
        logout_user()
        st.rerun()


def handle_create_order_form(current_user_id: int) -> None:
    with st.form("create_order_form", clear_on_submit=True):
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
        st.error("El pedido necesita un nombre.")
        return

    if not access_key.strip():
        st.error("La palabra clave es obligatoria.")
        return

    try:
        order_id = create_order(title=title, created_by=current_user_id, access_key=access_key)
    except ValueError as error:
        st.error(str(error))
        return
    except sqlite3.IntegrityError:
        st.error("Esa palabra clave ya está en uso. Elegí otra.")
        return

    st.session_state["selected_order_id"] = order_id
    sync_session_cookies()
    st.success("Pedido creado. Compartí la palabra clave para que otros puedan ingresar.")
    st.rerun()


def handle_access_order_form(current_user_id: int) -> None:
    with st.form("access_order_form", clear_on_submit=True):
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
        st.error("Ingresá la palabra clave del pedido.")
        return

    order = get_order_by_access_key(access_key)
    if order is None:
        st.error("No existe un pedido con esa palabra clave.")
        return

    join_order(order["id"], current_user_id)
    st.session_state["selected_order_id"] = int(order["id"])
    sync_session_cookies()
    st.success(f"Ingresaste a {order['title']}.")
    st.rerun()


def render_order_panel(current_user_id: int | None) -> int | None:
    st.sidebar.header("Pedido")
    if current_user_id is None:
        st.sidebar.info("Primero iniciá sesión para crear o acceder a un pedido.")
        return None

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


def render_order_entry_screen(current_user_id: int) -> None:
    st.subheader("Elegí cómo continuar")
    st.caption("Primero creá un pedido o sumate a uno existente con su palabra clave.")

    create_column, join_column = st.columns(2)
    with create_column:
        handle_create_order_form(current_user_id)
    with join_column:
        handle_access_order_form(current_user_id)


def render_order_header(order_data: dict, members: list, current_user_id: int) -> None:
    st.subheader(order_data["title"])
    status_label = ORDER_STATUS_LABELS.get(order_data["status"], order_data["status"])
    details = (
        f"Código: {order_data['order_code']} | Estado: {status_label} | "
        f"Creó: {order_data['created_by_name']}"
    )
    if int(order_data["created_by"]) == int(current_user_id):
        details = f"{details} | Clave: {order_data['access_key']}"
    st.caption(details)

    metrics = st.columns(3)
    metrics[0].metric("Items cargados", order_data["total_items"])
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
    item_names = {int(row["id"]): row["name"] for row in items}
    item_options = [int(row["id"]) for row in items]

    if st.session_state.get("menu_item") not in item_options:
        st.session_state["menu_item"] = item_options[0]

    selected_item_id = st.selectbox(
        "Plato",
        options=item_options,
        format_func=lambda item_id: item_names.get(int(item_id), ""),
        key="menu_item",
    )
    quantity = st.number_input("Cantidad", min_value=1, step=1, value=1, key="menu_quantity")
    notes = st.text_area("Notas", placeholder="Sin cebolla, bien cocido, etc.", key="menu_notes")
    submitted = st.button("Agregar al pedido", use_container_width=True)

    if submitted:
        try:
            add_order_item(
                order_id=order_data["id"],
                user_id=current_user_id,
                menu_item_id=int(selected_item_id),
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


def can_delete_order_item(
    current_user_id: int | None,
    item_user_id: int,
    order_status: str,
    admin_authenticated: bool,
) -> bool:
    return admin_authenticated or (
        current_user_id == item_user_id and order_status != "closed"
    )


def delete_order_item_for_role(order_item_id: int, admin_authenticated: bool) -> None:
    if admin_authenticated:
        remove_order_item_as_admin(order_item_id)
        return
    remove_order_item(order_item_id)


def render_order_items(
    order_id: int,
    current_user_id: int | None,
    order_status: str,
    admin_authenticated: bool,
) -> None:
    st.subheader("Detalle del pedido")
    items = get_order_items(order_id)
    if not items:
        st.caption("Todavía no se cargaron productos.")
        return

    if order_status == "closed" and not admin_authenticated:
        st.info("El pedido está cerrado. Ya no se pueden eliminar productos.")
    elif order_status == "closed" and admin_authenticated:
        st.info("Pedido cerrado: como admin podés eliminar ítems igualmente.")

    for row in items:
        notes_suffix = f" | Nota: {row['notes']}" if row["notes"] else ""
        title = f"{row['user_name']} pidió {row['quantity']} x {row['item_name']}"

        columns = st.columns([7, 2])
        columns[0].write(f"{title}{notes_suffix}")
        can_delete = can_delete_order_item(
            current_user_id=current_user_id,
            item_user_id=int(row["user_id"]),
            order_status=order_status,
            admin_authenticated=admin_authenticated,
        )
        if columns[1].button(
            "Eliminar",
            key=f"delete-item-{row['id']}",
            disabled=not can_delete,
            use_container_width=True,
        ):
            try:
                delete_order_item_for_role(
                    order_item_id=int(row["id"]),
                    admin_authenticated=admin_authenticated,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.rerun()


def render_totals(order_id: int) -> None:
    st.subheader("Totalizado por producto")
    totals = get_order_totals_by_product(order_id)
    if not totals:
        st.caption("Sin totales por mostrar.")
        return

    for row in totals:
        st.write(f"- {row['item_name']}: {row['total_quantity']} unidades")


def main() -> None:
    init_db()
    ensure_session_state()
    restore_session_from_cookies()
    sync_session_cookies()

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
    admin_authenticated = render_admin_access_panel()

    if admin_authenticated:
        render_admin_orders_panel()
        st.divider()

    if current_order_id is None:
        if not admin_authenticated:
            render_order_entry_screen(current_user_id)
        return

    order_data = as_dict(get_order(current_order_id))
    if order_data is None:
        clear_selected_order()
        st.warning("El pedido seleccionado ya no existe.")
        return

    members = get_order_members(current_order_id)
    render_order_header(order_data, members, current_user_id)
    render_order_owner_actions(order_data, current_user_id)

    left_column, right_column = st.columns([1.2, 1])
    with left_column:
        render_menu_form(order_data, current_user_id)
        render_order_items(
            current_order_id,
            current_user_id,
            order_data["status"],
            admin_authenticated,
        )
    with right_column:
        render_members(members)
        render_totals(current_order_id)


if __name__ == "__main__":
    main()