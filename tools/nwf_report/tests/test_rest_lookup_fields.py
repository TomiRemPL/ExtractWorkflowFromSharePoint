"""Regression tests for SharePoint REST lookup field mappings."""
from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tools.nwf_report.action_catalog import describe_action
from tools.nwf_report.html_builder import _generate_html
from tools.nwf_report.metadata_loader import FieldResolver, SiteMetadata, load_site_metadata
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference, WorkflowModel, _parse_action
from tools.nwf_report.report_builder import build_report, build_workflow_data

SOURCE_ID = "{AAAAAAAA-1111-2222-3333-444444444444}"
TARGET_ID = "{BBBBBBBB-1111-2222-3333-444444444444}"
ORIGIN_ID = "{CCCCCCCC-1111-2222-3333-444444444444}"
PRIMARY_ID = "{DDDDDDDD-1111-2222-3333-444444444444}"
UNKNOWN_ID = "{EEEEEEEE-1111-2222-3333-444444444444}"


def _metadata(
    tmp_path: Path, *, field_ref: str = PRIMARY_ID, schema: str | None = None
) -> SiteMetadata:
    source = {
        "lista": {"Id": SOURCE_ID, "Title": "Source"},
        "kolumny": [
            {
                "Id": PRIMARY_ID,
                "InternalName": "Primary",
                "EntityPropertyName": "OData__Primary",
                "TypeAsString": "Lookup",
                "LookupList": TARGET_ID,
                "LookupField": "Label",
                "SchemaXml": "<Field Type='Lookup' />",
            },
            {
                "Id": "{FFFFFFFF-1111-2222-3333-444444444444}",
                "InternalName": "Secondary",
                "EntityPropertyName": "OData__Secondary",
                "TypeAsString": "Lookup",
                "LookupList": TARGET_ID,
                "LookupField": "Symbol",
                "SchemaXml": schema if schema is not None else f"<Field Type='Lookup' FieldRef='{field_ref}' />",
            },
            {
                "InternalName": "Scalar",
                "EntityPropertyName": "OData__Scalar",
                "TypeAsString": "Text",
            },
        ],
    }
    target = {
        "lista": {"Id": TARGET_ID, "Title": "Dictionary"},
        "kolumny": [
            {"InternalName": "Label", "EntityPropertyName": "OData__Label", "TypeAsString": "Text"},
            {"InternalName": "Symbol", "EntityPropertyName": "OData__Symbol", "TypeAsString": "Text"},
        ],
    }
    for name, data in (("Source", source), ("Dictionary", target)):
        (tmp_path / f"10_lista_{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return load_site_metadata(tmp_path)


def _source_fields() -> list[FieldRef]:
    return [
        FieldRef("Secondary", "Secondary", "Lookup"),
        FieldRef("Primary", "Primary", "Lookup"),
        FieldRef("Scalar", "Scalar", "Text"),
    ]


def test_combined_write_uses_list_specific_entity_property_name(tmp_path: Path) -> None:
    source = ListReference("Source", SOURCE_ID, True, _source_fields())
    target = ListReference("Dictionary", TARGET_ID, False, [FieldRef("Label", "Label", "Text")])
    actions = [
        ActionNode("SPSetFieldWithKeyAdapter", params={
            "LookupField": "Scalar", "LookupFieldType": "Text", "LookupFieldValue": "Source value",
        }),
        _parse_action(ET.fromstring(f"""<NWActionConfig><Type>SPUpdateItemWithKeyAdapter</Type><Enabled>true</Enabled>
          <Parameters>
            <Parameter Name="ListId"><PrimitiveValue Value="{TARGET_ID}" /></Parameter>
            <Parameter Name="LookupField"><PrimitiveValue Value="ID" /></Parameter>
            <Parameter Name="LookupFieldValue"><PrimitiveValue Value="1" /></Parameter>
          </Parameters>
          <FieldReferences>
            <FieldReference Value="Label" Type="Text"><PrimitiveValue Value="Target value" /></FieldReference>
          </FieldReferences>
        </NWActionConfig>""")),
    ]
    workflow = WorkflowModel("REST writes", "", [source, target], actions, Path("test.nwf"), "List")
    resolver = FieldResolver([source, target], _metadata(tmp_path), SOURCE_ID)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    code = spec["path_b_combined"]["plsql_code"]
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "'OData__Scalar' VALUE 'Source value'" in code
    assert "'OData__Label' VALUE 'Target value'" in code


def test_combined_write_requires_confirmed_entity_property_name(tmp_path: Path) -> None:
    source = ListReference("Source", SOURCE_ID, True, _source_fields())
    metadata = _metadata(tmp_path)
    metadata.lists_by_title["source"].columns["scalar"].entity_property_name = ""
    action = ActionNode("SPSetFieldWithKeyAdapter", params={
        "LookupField": "Scalar", "LookupFieldType": "Text", "LookupFieldValue": "value",
    })
    workflow = WorkflowModel("REST write", "", [source], [action], Path("test.nwf"), "List")
    spec = build_workflow_data(workflow, FieldResolver([source], metadata, SOURCE_ID))["apex_workflow_spec"]
    assert spec["path_b_combined_status"].startswith("Szablon")
    assert any("EntityPropertyName" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_combined_read_with_conflicting_list_metadata_type_is_guarded(tmp_path: Path) -> None:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Scalar", "Scalar", "Number")])
    read = ActionNode("NWWriteToHistoryListAdapter", params={"Message": "{ItemProperty:Scalar}"})
    workflow = WorkflowModel("Type conflict", "", [source], [read], Path("test.nwf"), "List")
    spec = build_workflow_data(workflow, FieldResolver([source], _metadata(tmp_path), SOURCE_ID))["apex_workflow_spec"]
    assert spec["path_b_combined_status"].startswith("Szablon")
    assert any("Scalar" in reason and "typ" in reason.casefold() for reason in spec["path_b_combined_blocking_reasons"])


def test_combined_write_with_conflicting_list_metadata_type_is_guarded(tmp_path: Path) -> None:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Scalar", "Scalar", "Number")])
    declaration = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWWorkflowVariablesAdapter</Type><Enabled>true</Enabled><WorkflowVariables>
        <Variable Name="Amount" Type="Number" DefaultValue="1" Initiate="false" Direction="None" />
      </WorkflowVariables>
    </NWActionConfig>"""))
    write = ActionNode("SPSetFieldWithKeyAdapter", params={"LookupField": "Scalar", "LookupFieldType": "Number"},
                       param_elements={"LookupFieldValue": ET.Element("Variable", {"Name": "Amount", "Type": "Number"})})
    workflow = WorkflowModel("Type conflict", "", [source], [declaration, write], Path("test.nwf"), "List")
    spec = build_workflow_data(workflow, FieldResolver([source], _metadata(tmp_path), SOURCE_ID))["apex_workflow_spec"]
    assert spec["path_b_combined_status"].startswith("Szablon")
    assert any("Scalar" in reason and "typ" in reason.casefold() for reason in spec["path_b_combined_blocking_reasons"])


def test_combined_create_item_uses_target_entity_property_name(tmp_path: Path) -> None:
    source = ListReference("Source", SOURCE_ID, True, _source_fields())
    target = ListReference("Dictionary", TARGET_ID, False, [FieldRef("Label", "Label", "Text")])
    create = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWCreateSiteSpecificItemAdapter</Type>
      <Enabled>true</Enabled><BLabel>Dictionary</BLabel>
      <FieldReferences><FieldReference Value="Label" Type="Text"><PrimitiveValue Value="Created" /></FieldReference></FieldReferences>
    </NWActionConfig>"""))
    workflow = WorkflowModel("REST create", "", [source, target], [create], Path("test.nwf"), "List")
    spec = build_workflow_data(workflow, FieldResolver([source, target], _metadata(tmp_path), SOURCE_ID))["apex_workflow_spec"]
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "'OData__Label' VALUE 'Created'" in spec["path_b_combined"]["plsql_code"]


def test_combined_write_to_primary_lookup_uses_entity_property_id(tmp_path: Path) -> None:
    source = ListReference("Source", SOURCE_ID, True, _source_fields())
    declaration = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWWorkflowVariablesAdapter</Type><Enabled>true</Enabled><WorkflowVariables>
        <Variable Name="RelatedId" Type="SPItemKey" DefaultValue="1" Initiate="false" Direction="None" />
      </WorkflowVariables>
    </NWActionConfig>"""))
    write = ActionNode("SPSetFieldWithKeyAdapter", params={"LookupField": "Primary", "LookupFieldType": "Lookup"},
                       param_elements={"LookupFieldValue": ET.Element("Variable", {"Name": "RelatedId", "Type": "SPItemKey"})})
    workflow = WorkflowModel("Primary lookup", "", [source], [declaration, write], Path("test.nwf"), "List")
    spec = build_workflow_data(workflow, FieldResolver([source], _metadata(tmp_path), SOURCE_ID))["apex_workflow_spec"]
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "'OData__PrimaryId' VALUE l_wf_relatedid" in spec["path_b_combined"]["plsql_code"]


def test_combined_write_to_projected_lookup_is_guarded(tmp_path: Path) -> None:
    source = ListReference("Source", SOURCE_ID, True, _source_fields())
    declaration = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWWorkflowVariablesAdapter</Type><Enabled>true</Enabled><WorkflowVariables>
        <Variable Name="RelatedId" Type="SPItemKey" DefaultValue="1" Initiate="false" Direction="None" />
      </WorkflowVariables>
    </NWActionConfig>"""))
    write = ActionNode("SPSetFieldWithKeyAdapter", params={"LookupField": "Secondary", "LookupFieldType": "Lookup"},
                       param_elements={"LookupFieldValue": ET.Element("Variable", {"Name": "RelatedId", "Type": "SPItemKey"})})
    workflow = WorkflowModel("Projected lookup", "", [source], [declaration, write], Path("test.nwf"), "List")
    spec = build_workflow_data(workflow, FieldResolver([source], _metadata(tmp_path), SOURCE_ID))["apex_workflow_spec"]
    assert spec["path_b_combined_status"].startswith("Szablon")
    assert any("Lookup" in reason and "Secondary" in reason for reason in spec["path_b_combined_blocking_reasons"])


def _set_from_this_item(name: str, field_type: str) -> ActionNode:
    return ActionNode(
        "SPSetVariableAdapter",
        param_elements={
            "VariableName": ET.fromstring(f"<Variable Name='Result{name}' Type='Text' />"),
            "Value": ET.fromstring(
                f"<ListLookup LookupType='ThisItemLookup'><Field Name='{name}' Type='{field_type}' /></ListLookup>"
            ),
        },
    )


def _cross_action(coercion: str) -> ActionNode:
    return ActionNode(
        "SPSetVariableAdapter",
        param_elements={
            "VariableName": ET.fromstring("<Variable Name='Result' Type='Text' />"),
            "Value": ET.fromstring(
                f"""<ListLookup LookupType='CrossItemLookup'>
                  <Lookup LookupType='ThisItemLookup'><Field Name='ID' Type='Counter' /></Lookup>
                  <ListId>{SOURCE_ID}</ListId><Field Name='Secondary' Type='Lookup' />
                  <CompareField Name='ID' /><Coercion>{coercion}</Coercion>
                </ListLookup>"""
            ),
        },
    )


def _source_spec(tmp_path: Path, *, field_ref: str = PRIMARY_ID, schema: str | None = None):
    source = ListReference("Source", SOURCE_ID, True, _source_fields())
    resolver = FieldResolver([source], _metadata(tmp_path, field_ref=field_ref, schema=schema), SOURCE_ID)
    actions = [_set_from_this_item(f.internal_name, f.field_type) for f in source.fields]
    workflow = WorkflowModel("Test", "", [source], actions, Path("test.nwf"), workflow_type="List")
    return build_workflow_data(workflow, resolver)["apex_workflow_spec"]


def test_projected_lookup_uses_primary_navigation_and_actual_target_fields(tmp_path: Path) -> None:
    spec = _source_spec(tmp_path)
    parse = next(a for a in spec["standard_activities"] if a["node_id"] == "std_parse")["plsql_code"]

    assert spec["shp_query"] == (
        "$select=OData__Primary/Id,OData__Primary/OData__Symbol,"
        "OData__Primary/OData__Label,OData__Scalar&$expand=OData__Primary"
    )
    assert ":SP_SECONDARY := apex_json.get_varchar2(p_path => 'data.OData__Primary.OData__Symbol');" in parse
    assert ":SP_SECONDARY_ID := apex_json.get_number(p_path => 'data.OData__Primary.Id');" in parse
    assert ":SP_PRIMARY := apex_json.get_varchar2(p_path => 'data.OData__Primary.OData__Label');" in parse
    assert ":SP_SCALAR := apex_json.get_varchar2(p_path => 'data.OData__Scalar');" in parse
    combined = spec["path_b_combined"]["plsql_code"]
    assert "l_sp_secondary := apex_json.get_varchar2(p_path => 'data.OData__Primary.OData__Symbol'" in combined
    assert "l_sp_secondary_id := apex_json.get_number(p_path => 'data.OData__Primary.Id'" not in combined
    assert "l_sp_primary := apex_json.get_varchar2(p_path => 'data.OData__Primary.OData__Label'" in combined
    assert "l_sp_scalar := apex_json.get_varchar2(p_path => 'data.OData__Scalar'" in combined


def test_projected_lookup_id_is_parsed_when_actually_used(tmp_path: Path) -> None:
    source = ListReference("Source", SOURCE_ID, True, _source_fields())
    resolver = FieldResolver([source], _metadata(tmp_path), SOURCE_ID)
    declaration = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWWorkflowVariablesAdapter</Type><Enabled>true</Enabled><WorkflowVariables>
        <Variable Name="RelatedId" Type="SPItemKey" DefaultValue="1" Initiate="false" Direction="None" />
      </WorkflowVariables>
    </NWActionConfig>"""))
    action = ActionNode("SPSetVariableAdapter", param_elements={
        "VariableName": ET.fromstring("<Variable Name='RelatedId' Type='SPItemKey' />"),
        "Value": ET.fromstring("""<ListLookup LookupType='ThisItemLookup'>
          <Field Name='Secondary' Type='Lookup' /><Coercion>LookupIdOnlyAsInteger</Coercion>
        </ListLookup>"""),
    })
    workflow = WorkflowModel("Lookup ID", "", [source], [declaration, action], Path("test.nwf"), "List")
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    combined = spec["path_b_combined"]["plsql_code"]

    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "l_sp_secondary_id := apex_json.get_number(p_path => 'data.OData__Primary.Id'" in combined
    assert "brak skladowej data.OData__Primary.Id" not in combined
    assert "ELSE\n        l_sp_secondary_id := NULL;\n    END IF;" in combined
    assert "data.OData__Primary.OData__Symbol" not in combined


def test_corrected_query_and_parse_reach_markdown_and_html(tmp_path: Path) -> None:
    source = ListReference("Source", SOURCE_ID, True, _source_fields())
    resolver = FieldResolver([source], _metadata(tmp_path), SOURCE_ID)
    actions = [_set_from_this_item(f.internal_name, f.field_type) for f in source.fields]
    workflow = WorkflowModel("Test", "", [source], actions, Path("test.nwf"), workflow_type="List")
    data = build_workflow_data(workflow, resolver)
    query = data["apex_workflow_spec"]["shp_query"]

    report = build_report(workflow, resolver)
    html = _generate_html([data])
    match = re.search(r'<script id="workflows-data" type="application/json">\s*(.*?)\s*</script>', html, re.DOTALL)

    assert query in report
    assert match is not None
    spec = json.loads(match.group(1))[0]["apex_workflow_spec"]
    assert spec["shp_query"] == query
    get_item = next(a for a in spec["standard_activities"] if a["node_id"] == "std_get_item")
    assert next(p["value"] for p in get_item["parameter_mapping"] if p["parameter"] == "p_query") == query
    parse = next(a for a in spec["standard_activities"] if a["node_id"] == "std_parse")
    assert "data.OData__Primary.OData__Symbol" in parse["plsql_code"]


@pytest.mark.parametrize(
    ("coercion", "property_name"),
    [("Text", "OData__Symbol"), ("LookupIdOnlyAsInteger", "Id")],
)
def test_cross_list_projected_lookup_uses_same_mapping(
    tmp_path: Path, coercion: str, property_name: str
) -> None:
    origin = ListReference("Origin", ORIGIN_ID, True, [])
    source = ListReference("Source", SOURCE_ID, False, _source_fields())
    resolver = FieldResolver([origin, source], _metadata(tmp_path), ORIGIN_ID)

    description = describe_action(_cross_action(coercion), resolver)

    assert not description.blocking_reasons
    assert (
        f"p_query      => '$select=OData__Primary/{property_name}&$expand=OData__Primary'"
        in description.plsql_code
    )
    assert f"$.data.OData__Primary.{property_name}" in description.plsql_code


@pytest.mark.parametrize(
    ("field_ref", "schema"),
    [(UNKNOWN_ID, None), (PRIMARY_ID, "<Field")],
)
def test_unresolved_projected_lookup_blocks_migration(
    tmp_path: Path, field_ref: str, schema: str | None
) -> None:
    spec = _source_spec(tmp_path, field_ref=field_ref, schema=schema)
    reasons = " ".join(spec["path_a_blocking_reasons"])

    assert spec["migration_status"] == "Zablokowany"
    assert "Secondary" in reasons
    assert "OData__Secondary" not in spec["shp_query"]
    guard = next(a for a in spec["standard_activities"] if a["node_id"] == "migration_guard")
    assert "RAISE_APPLICATION_ERROR" in guard["plsql_code"]
    get_item = next(a for a in spec["standard_activities"] if a["node_id"] == "std_get_item")
    assert any("Blokada:" in note and "Secondary" in note for note in get_item["config_notes"])


@pytest.mark.parametrize(
    ("field_ref", "schema"),
    [(UNKNOWN_ID, None), (PRIMARY_ID, "<Field")],
)
def test_unresolved_cross_list_lookup_blocks_action(
    tmp_path: Path, field_ref: str, schema: str | None
) -> None:
    origin = ListReference("Origin", ORIGIN_ID, True, [])
    source = ListReference("Source", SOURCE_ID, False, _source_fields())
    resolver = FieldResolver([origin, source], _metadata(tmp_path, field_ref=field_ref, schema=schema), ORIGIN_ID)

    description = describe_action(_cross_action("Text"), resolver)

    assert any("Secondary" in reason for reason in description.blocking_reasons)
    assert "RAISE_APPLICATION_ERROR" in description.plsql_code
    assert "get_list_item" not in description.plsql_code


def test_missing_cross_list_rest_metadata_is_reported() -> None:
    origin = ListReference("Origin", ORIGIN_ID, True, [])
    source = ListReference("Source", SOURCE_ID, False, _source_fields())
    resolver = FieldResolver([origin, source], source_list_id=ORIGIN_ID)

    description = describe_action(_cross_action("Text"), resolver)

    assert not description.blocking_reasons
    assert any("Brak metadanych REST pola Secondary" in line for line in description.technical_lines)


def test_non_guid_fieldref_is_not_treated_as_a_projected_lookup(tmp_path: Path) -> None:
    spec = _source_spec(tmp_path, field_ref="ID")

    assert not any("Secondary" in reason for reason in spec["path_a_blocking_reasons"])
    get_item = next(a for a in spec["standard_activities"] if a["node_id"] == "std_get_item")
    assert any("systemowy FieldRef ID" in note for note in get_item["config_notes"])


def test_missing_source_rest_metadata_is_reported() -> None:
    source = ListReference("Source", SOURCE_ID, True, _source_fields())
    resolver = FieldResolver([source], source_list_id=SOURCE_ID)
    actions = [_set_from_this_item("Secondary", "Lookup")]
    workflow = WorkflowModel("Test", "", [source], actions, Path("test.nwf"), workflow_type="List")

    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    get_item = next(a for a in spec["standard_activities"] if a["node_id"] == "std_get_item")

    assert spec["shp_query"] == "$select=Secondary/Id,Secondary/Title&$expand=Secondary"
    assert any("Brak metadanych REST pola Secondary" in note for note in get_item["config_notes"])
