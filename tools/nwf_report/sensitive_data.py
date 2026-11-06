"""Usuwanie danych uwierzytelniających z modelu używanego do generowania raportów."""
from __future__ import annotations

from copy import deepcopy
import re
from xml.etree import ElementTree as ET


REDACTED = "<pominięto dane uwierzytelniające>"
_SENSITIVE_NAMES = {
    "apikey", "authorization", "clientsecret", "connectionstring", "credentials",
    "password", "pwd", "secret", "token", "uid", "userid", "username",
}
_SENSITIVE_SUFFIXES = (
    "apikey", "authorization", "clientsecret", "connectionstring", "credentials",
    "password", "passwd", "pwd", "secret", "accesstoken", "refreshtoken", "userid", "username",
)
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:connection\s*string|password|passwd|pwd|user\s*id|uid|user\s*name|"
    r"client\s*secret|access\s*token)\s*=",
    re.IGNORECASE,
)


def is_sensitive_name(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
    return normalized in _SENSITIVE_NAMES or normalized.endswith(_SENSITIVE_SUFFIXES)


def contains_credential_assignment(value: str) -> bool:
    return bool(_CREDENTIAL_ASSIGNMENT_RE.search(value))


def sanitize_action_xml(action: ET.Element) -> tuple[ET.Element, dict[int, list[str]]]:
    root = deepcopy(action)
    redactions: dict[int, list[str]] = {}

    def sanitize_action(current: ET.Element) -> None:
        redacted: set[str] = set()

        def walk(element: ET.Element, sensitive: bool = False, label: str = "wartość akcji") -> None:
            if element.tag == "ChildActivities":
                for child in element.findall("NWActionConfig"):
                    sanitize_action(child)
                return
            if element.tag == "Parameter":
                name = element.get("Name", "")
                label = f"parametr {name}" if name and not contains_credential_assignment(name) else "parametr"
                sensitive = sensitive or is_sensitive_name(name)
            elif element.tag == "FieldReference":
                name = element.get("Value") or element.get("Name", "")
                label = f"pole {name}" if name and not contains_credential_assignment(name) else "pole"
                sensitive = sensitive or is_sensitive_name(name)

            for key, value in list(element.attrib.items()):
                is_field_name = element.tag == "FieldReference" and key == "Value"
                sensitive_value = sensitive and key == "Value" and not is_field_name
                sensitive_attribute = key != "Name" and is_sensitive_name(key)
                if value and (sensitive_value or sensitive_attribute or contains_credential_assignment(value)):
                    element.set(key, REDACTED)
                    redacted.add(label)
            if element.text and element.text.strip() and (sensitive or contains_credential_assignment(element.text)):
                element.text = REDACTED
                redacted.add(label)
            if element.tail and element.tail.strip() and (sensitive or contains_credential_assignment(element.tail)):
                element.tail = REDACTED
                redacted.add(label)
            for child in element:
                walk(child, sensitive, label)

        for child in current:
            walk(child)
        redactions[id(current)] = sorted(redacted)

    sanitize_action(root)
    return root, redactions
