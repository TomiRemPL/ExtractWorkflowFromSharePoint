"""Parser plikow .nwf (eksport konfiguracji Nintex Workflow z SharePoint 2019).

Format pliku:
  <ExportedWorkflowWithListMetdata>
      <ExportedWorkflowSeralized>  -- string z escapowanym (HTML-entity) XML-em <ExportedWorkflow>
      <IsSourceList>, <ContentTypes>, <Fields> -- metadane listy zrodlowej (opcjonalne)

Wewnatrz <ExportedWorkflow>:
  <Title>, <Description>
  <Configurations><ActionConfigs><NWActionConfig> ... </NWActionConfig> ...

Kazdy <NWActionConfig> opisuje jedna akcje workflow: Type (klasa .NET), Enabled,
ConditionUse, Parameters/Parameter[@Name] i wlasne FieldReferences.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass
class FieldRef:
    name: str  # nazwa wyswietlana uzyta w danym kontekscie (moze byc pusta)
    internal_name: str  # InternalName / StaticName pola w SharePoint
    field_type: str = ""


@dataclass
class ActionNode:
    type: str
    enabled: bool = True
    condition_use: str = "None"
    params: dict[str, str] = field(default_factory=dict)
    param_elements: dict[str, ET.Element] = field(default_factory=dict)
    field_refs: list[FieldRef] = field(default_factory=list)
    children: list["ActionNode"] = field(default_factory=list)
    branch_label: str = ""  # np. "Tak" / "Nie" gdy dziecko warunku
    # Etykiety nadane w projektancie Nintex - czesto najlepszy opis "po ludzku".
    t_label: str = ""  # tytul/naglowek akcji (gorna etykieta)
    b_label: str = ""  # dolna etykieta (np. nazwa zmiennej)
    l_label: str = ""  # lewa etykieta galezi warunku
    r_label: str = ""  # prawa etykieta galezi warunku
    condition_el: ET.Element | None = None  # surowy XML <Condition> (dla akcji warunkowych)


@dataclass
class ListReference:
    list_name: str
    list_id: str
    is_source_list: bool
    fields: list[FieldRef]  # slownik pol tej listy (z metadanych wbudowanych w .nwf)


@dataclass
class WorkflowModel:
    title: str
    description: str
    list_references: list[ListReference]  # listy uzyte przez workflow + ich slownik pol
    actions: list[ActionNode]
    source_path: Path

    @property
    def source_list(self) -> "ListReference | None":
        return next((lr for lr in self.list_references if lr.is_source_list), None)


def _text(el: ET.Element | None) -> str:
    return el.text if el is not None and el.text is not None else ""


def _parse_parameters(action_el: ET.Element) -> dict[str, str]:
    params: dict[str, str] = {}
    params_el = action_el.find("Parameters")
    if params_el is None:
        return params
    for param_el in params_el.findall("Parameter"):
        name = param_el.get("Name", "")
        value_el = param_el.find("PrimitiveValue")
        value = value_el.get("Value", "") if value_el is not None else _text(param_el)
        params[name] = value
    return params


def _parse_param_elements(action_el: ET.Element) -> dict[str, ET.Element]:
    """Zwraca surowy element wartosci kazdego parametru (PrimitiveValue/Variable/ListLookup/...).

    Uzupelnienie do _parse_parameters: niektore parametry (np. Value w SPSetVariableAdapter)
    trzymaja zlozone struktury, ktore trzeba renderowac generycznie (patrz action_catalog).
    """
    elements: dict[str, ET.Element] = {}
    params_el = action_el.find("Parameters")
    if params_el is None:
        return elements
    for param_el in params_el.findall("Parameter"):
        name = param_el.get("Name", "")
        child = next(iter(param_el), None)
        if child is not None:
            elements[name] = child
    return elements
    return params


def _parse_field_refs(action_el: ET.Element) -> list[FieldRef]:
    refs: list[FieldRef] = []
    refs_el = action_el.find("FieldReferences")
    if refs_el is None:
        return refs
    for ref_el in refs_el.findall("FieldReference"):
        refs.append(
            FieldRef(
                name=ref_el.get("Name", ""),
                internal_name=ref_el.get("Value", ""),
                field_type=ref_el.get("Type", ""),
            )
        )
    return refs


def _parse_action(action_el: ET.Element, branch_label: str = "") -> ActionNode:
    node = ActionNode(
        type=_text(action_el.find("Type")),
        enabled=_text(action_el.find("Enabled")).lower() == "true",
        condition_use=_text(action_el.find("ConditionUse")) or "None",
        params=_parse_parameters(action_el),
        param_elements=_parse_param_elements(action_el),
        field_refs=_parse_field_refs(action_el),
        branch_label=branch_label,
        t_label=_text(action_el.find("TLabel")),
        b_label=_text(action_el.find("BLabel")),
        l_label=_text(action_el.find("LLabel")),
        r_label=_text(action_el.find("RLabel")),
        condition_el=action_el.find("Condition"),
    )
    # Zagniezdzone akcje (warunki, petle, action sety) zawsze siedza pod
    # bezposrednim elementem <ChildActivities><NWActionConfig>...</NWActionConfig></ChildActivities>.
    child_activities_el = action_el.find("ChildActivities")
    if child_activities_el is not None:
        child_els = child_activities_el.findall("NWActionConfig")
        labels = _branch_labels(node.type, action_el, len(child_els))
        for child_el, label in zip(child_els, labels):
            node.children.append(_parse_action(child_el, branch_label=label))
    return node


def _branch_labels(action_type: str, action_el: ET.Element, count: int) -> list[str]:
    """Zwraca etykiety galezi (np. Tak/Nie) dla akcji warunkowych typu WFIfElseAdapter."""
    if action_type.endswith("WFIfElseAdapter") and count == 2:
        left_label = _text(action_el.find("LLabel")) or "Nie"
        right_label = _text(action_el.find("RLabel")) or "Tak"
        return [left_label, right_label]
    return [""] * count


def _parse_list_references(outer_root: ET.Element) -> list[ListReference]:
    refs: list[ListReference] = []
    list_refs_el = outer_root.find("ListReferences")
    if list_refs_el is None:
        return refs
    for ref_el in list_refs_el.findall("ListReference"):
        fields: list[FieldRef] = []
        fields_el = ref_el.find("Fields")
        if fields_el is not None:
            for field_el in fields_el.findall("FieldReference"):
                fields.append(
                    FieldRef(
                        name=_text(field_el.find("DisplayName")),
                        internal_name=_text(field_el.find("InternalName")),
                        field_type=_text(field_el.find("FieldType")),
                    )
                )
        refs.append(
            ListReference(
                list_name=_text(ref_el.find("ListName")),
                list_id=_text(ref_el.find("ListId")),
                is_source_list=_text(ref_el.find("IsSourceList")).lower() == "true",
                fields=fields,
            )
        )
    return refs


def parse_nwf(path: str | Path) -> WorkflowModel:
    path = Path(path)
    outer_root = ET.fromstring(path.read_text(encoding="utf-8-sig"))

    serialized_el = outer_root.find("ExportedWorkflowSeralized")
    if serialized_el is None or not serialized_el.text:
        raise ValueError(f"Brak ExportedWorkflowSeralized w pliku {path}")

    # Wewnetrzny XML jest zapisany jako escaped string (elementy w postaci &lt;Tag&gt;).
    inner_root = ET.fromstring(serialized_el.text)

    title = _text(inner_root.find("Title"))
    description = _text(inner_root.find("Description"))

    actions: list[ActionNode] = []
    action_configs_el = inner_root.find("Configurations/ActionConfigs")
    if action_configs_el is not None:
        for action_el in action_configs_el.findall("NWActionConfig"):
            actions.append(_parse_action(action_el))

    list_references = _parse_list_references(outer_root)

    return WorkflowModel(
        title=title,
        description=description,
        list_references=list_references,
        actions=actions,
        source_path=path,
    )


def iter_actions(actions: list[ActionNode]):
    """Generator plaskiego przejscia po drzewie akcji z zachowaniem glebokosci."""
    def _walk(nodes: list[ActionNode], depth: int):
        for node in nodes:
            yield node, depth
            yield from _walk(node.children, depth + 1)

    yield from _walk(actions, 0)
