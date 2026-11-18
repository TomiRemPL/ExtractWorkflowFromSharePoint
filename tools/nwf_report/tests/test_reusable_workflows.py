"""Tests for Reusable / GloballyReusable workflow parsing, metadata resolution, and APEX generation."""

from pathlib import Path
from xml.sax.saxutils import escape

from tools.nwf_report.apex_workflow_guide import generate_apex_workflow_spec
from tools.nwf_report.metadata_loader import ColumnInfo, FieldResolver, ListInfo, SiteMetadata
from tools.nwf_report.nwf_parser import parse_nwf
from tools.nwf_report.report_builder import build_dispatcher_package, build_report, build_workflow_data


def _write_reusable_nwf(path: Path) -> Path:
    inner = """<?xml version="1.0" encoding="utf-8"?>
<ExportedWorkflow xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Title>R0001 Reusable Test</Title>
  <Description>Test reusable workflow</Description>
  <Configurations>
    <ActionConfigs>
      <NWActionConfig>
        <Type>Nintex.Workflow.Activities.Adapters.NWSetFieldValueAdapter</Type>
        <TLabel>Ustaw pole Symbol ryzyka</TLabel>
        <Enabled>true</Enabled>
        <Parameters>
          <Parameter Name="FieldName">
            <PrimitiveValue><Value xsi:type="xsd:string">Symbol_x0020_ryzyka</Value></PrimitiveValue>
          </Parameter>
          <Parameter Name="Value">
            <PrimitiveValue><Value xsi:type="xsd:string">ICT-01</Value></PrimitiveValue>
          </Parameter>
        </Parameters>
      </NWActionConfig>
    </ActionConfigs>
  </Configurations>
</ExportedWorkflow>"""
    outer = f"""<?xml version="1.0" encoding="utf-8"?>
<ExportedWorkflowWithListMetdata xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <ExportedWorkflowSeralized>{escape(inner)}</ExportedWorkflowSeralized>
  <ListReferences />
  <SourceContentType>
    <Id>0x0100B7D0D8BE3EE8A94495853B2FFD09C4610E</Id>
    <Name>ICTRM-360 MR - Rejestr Ryzyk - Ocena ryzyka</Name>
    <Fields>
      <FieldReference>
        <InternalName>Symbol_x0020_ryzyka</InternalName>
        <DisplayName>Symbol ryzyka</DisplayName>
        <FieldType>Text</FieldType>
      </FieldReference>
    </Fields>
  </SourceContentType>
  <WorkflowType>Reusable</WorkflowType>
</ExportedWorkflowWithListMetdata>"""
    path.write_text(outer, encoding="utf-8")
    return path


def _build_site_metadata() -> SiteMetadata:
    list_info = ListInfo(
        title="(R0001) Rejestr Ryzyk ICT",
        list_id="ce6558a9-430c-4077-a46a-efeddf26661b",
        columns={
            "symbol_x0020_ryzyka": ColumnInfo(
                title="Symbol ryzyka",
                internal_name="Symbol_x0020_ryzyka",
                type_as_string="Text",
                entity_property_name="Symbol_x0020_ryzyka",
            )
        },
        content_types=[
            (
                "0x0100B7D0D8BE3EE8A94495853B2FFD09C4610E002B52B402342F9342869308A27030BDC9",
                "ICTRM-360 MR - Rejestr Ryzyk - Ocena ryzyka",
            )
        ],
    )
    return SiteMetadata(
        lists_by_id={"ce6558a9-430c-4077-a46a-efeddf26661b": list_info},
        lists_by_title={"(r0001) rejestr ryzyk ict": list_info},
    )


def test_reusable_workflow_parses_content_type_and_generates_apex_list_steps(tmp_path: Path):
    nwf_path = _write_reusable_nwf(tmp_path / "R0001_Reusable.nwf")
    wf = parse_nwf(nwf_path)

    assert wf.workflow_type == "Reusable"
    assert wf.source_content_type is not None
    assert wf.source_content_type.id == "0x0100B7D0D8BE3EE8A94495853B2FFD09C4610E"
    assert wf.source_content_type.name == "ICTRM-360 MR - Rejestr Ryzyk - Ocena ryzyka"
    assert len(wf.source_content_type.fields) == 1

    meta = _build_site_metadata()
    resolver = FieldResolver(
        wf.list_references,
        meta,
        source_list_id="",
        source_content_type=wf.source_content_type,
    )
    assert resolver.source_list_name == "(R0001) Rejestr Ryzyk ICT"
    assert len(resolver.associated_lists) == 1

    wf_data = build_workflow_data(wf, resolver)
    assert wf_data["source_list_name"] == "(R0001) Rejestr Ryzyk ICT"
    assert wf_data["workflow_type"] == "Reusable"

    spec = wf_data["apex_workflow_spec"]
    std_ids = [a["node_id"] for a in spec["standard_activities"]]
    assert "std_get_item" in std_ids
    assert "std_payload" in std_ids
    assert "std_parse" in std_ids

    dispatcher_sql = build_dispatcher_package([wf_data])
    assert "WHEN 'R0001 Reusable Test'" in dispatcher_sql

    md = build_report(wf, resolver)
    assert "(R0001) Rejestr Ryzyk ICT" in md
    assert "ICTRM-360 MR - Rejestr Ryzyk - Ocena ryzyka" in md
