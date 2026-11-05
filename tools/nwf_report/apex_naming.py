"""Wspolne konwencje nazewnicze dla kodu Oracle APEX Workflow / LCDT.SHP_API."""
from __future__ import annotations

import re
import unicodedata

SHP_API = "LCDT.SHP_API"

# Zmienne standardowego procesu APEX (kroki 2-3: Retrieve Payload + Invoke API).
V_ITEM_ID = "V_ITEM_ID"
V_SITE_URL = "V_SITE_URL"
V_LIST_TITLE = "V_LIST_TITLE"
V_EDITOR = "V_EDITOR"
V_SHP_ANSWER = "V_SHP_ANSWER"
P_PAYLOAD_BODY = "P_PAYLOAD_BODY"

LOOKUP_TYPES = {"lookup", "lookupmulti"}
USER_TYPES = {"user", "usermulti"}
MULTI_TYPES = {"lookupmulti", "usermulti", "multichoice", "taxonomyfieldtypemulti"}


def identifier(value: str, prefix: str = "", max_length: int = 120) -> str:
    # NFKD nie rozklada polskiego "ł" - mapujemy go jawnie.
    value = value.replace("ł", "l").replace("Ł", "L")
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    clean = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value).strip("_").upper()
    clean = re.sub(r"_+", "_", clean)
    if not clean:
        clean = "WORKFLOW"
    if clean[0].isdigit():
        clean = f"_{clean}"
    return f"{prefix}{clean}"[:max_length]


def field_variable(internal_name: str, suffix: str = "") -> str:
    """Static ID zmiennej APEX z wartoscia pola SharePoint, np. SP_STATUS / SP_EDITOR_EMAIL."""
    return identifier(internal_name, "SP_") + (f"_{suffix}" if suffix else "")


def variable_static_id(name: str) -> str:
    return identifier(name)


def workflow_static_id(title: str) -> str:
    return identifier(title, "WF_", 120)


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def is_lookup(field_type: str) -> bool:
    return (field_type or "").lower() in LOOKUP_TYPES


def is_user(field_type: str) -> bool:
    return (field_type or "").lower() in USER_TYPES


def is_multi(field_type: str) -> bool:
    return (field_type or "").lower() in MULTI_TYPES


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
P_EMAIL_FROM = "P_EMAIL_FROM"


def email_param(email: str) -> str:
    """Alias parametru konfiguracyjnego (NINTEX_PARAMS) dla stalego adresu e-mail."""
    return identifier(email.split("@", 1)[0], "P_EMAIL_", 30)
