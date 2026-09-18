"""Test fixtures and synthetic XML/JSON data for nwf_report tests."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference

# Minimal complete .nwf document containing outer XML and escaped inner XML
MINIMAL_INNER_WORKFLOW_XML = """<ExportedWorkflow>
  <Title>Test Workflow</Title>
  <Description>Workflow testowy description</Description>
  <Configurations>
    <ActionConfigs>
      <NWActionConfig>
        <Type>Nintex.Workflow.Activities.Adapters.NWWorkflowVariablesAdapter</Type>
        <Enabled>true</Enabled>
        <ConditionUse>None</ConditionUse>
        <Parameters>
          <Parameter Name="StartManually"><PrimitiveValue Value="True" /></Parameter>
          <Parameter Name="StartOnCreate"><PrimitiveValue Value="False" /></Parameter>
          <Parameter Name="StartOnChange"><PrimitiveValue Value="True" /></Parameter>
        </Parameters>
      </NWActionConfig>
      <NWActionConfig>
        <Type>Nintex.Workflow.Activities.Adapters.SPSetVariableAdapter</Type>
        <Enabled>true</Enabled>
        <ConditionUse>None</ConditionUse>
        <TLabel>Ustawienie zmiennej testowej</TLabel>
        <BLabel>WartoscBLabel</BLabel>
        <Parameters>
          <Parameter Name="VariableName">
            <Variable Name="varTestowa" />
          </Parameter>
          <Parameter Name="Value">
            <ListLookup LookupType="ThisItemLookup">
              <Field Name="Pole_x0020_Zrodlowe" Type="Text" />
            </ListLookup>
          </Parameter>
        </Parameters>
      </NWActionConfig>
    </ActionConfigs>
  </Configurations>
</ExportedWorkflow>"""

def build_exported_nwf_xml(inner_xml: str = MINIMAL_INNER_WORKFLOW_XML) -> str:
    """Escapes inner XML and wraps it in ExportedWorkflowWithListMetdata root."""
    # ElementTree handles entity unescaping when reading .text from XML
    escaped_inner = (
        inner_xml.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<ExportedWorkflowWithListMetdata>
  <ExportedWorkflowSeralized>{escaped_inner}</ExportedWorkflowSeralized>
  <ListReferences>
    <ListReference>
      <ListName>Lista Testowa A</ListName>
      <ListId>{{AAAAAAAA-1111-2222-3333-444444444444}}</ListId>
      <IsSourceList>true</IsSourceList>
      <Fields>
        <FieldReference>
          <InternalName>Pole_x0020_Zrodlowe</InternalName>
          <DisplayName>Pole Źródłowe A</DisplayName>
          <FieldType>Text</FieldType>
        </FieldReference>
        <FieldReference>
          <InternalName>Wspolna_x0020_Nazwa</InternalName>
          <DisplayName>Wspólna Kolumna w Liście A</DisplayName>
          <FieldType>Choice</FieldType>
        </FieldReference>
      </Fields>
    </ListReference>
    <ListReference>
      <ListName>Lista Testowa B</ListName>
      <ListId>{{BBBBBBBB-1111-2222-3333-444444444444}}</ListId>
      <IsSourceList>false</IsSourceList>
      <Fields>
        <FieldReference>
          <InternalName>Wspolna_x0020_Nazwa</InternalName>
          <DisplayName>Wspólna Kolumna w Liście B (Inne Znaczenie)</DisplayName>
          <FieldType>Lookup</FieldType>
        </FieldReference>
        <FieldReference>
          <InternalName>Pole_x0020_Docelowe_B</InternalName>
          <DisplayName>Pole Docelowe B</DisplayName>
          <FieldType>Text</FieldType>
        </FieldReference>
      </Fields>
    </ListReference>
  </ListReferences>
</ExportedWorkflowWithListMetdata>"""

SAMPLE_CONDITION_PAIR_XML = """<Condition xsi:type="ConditionPair" Operator="Or" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Left xsi:type="NWConditionConfig" Name="Jeśli pole równe">
    <Params>
      <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
      <Param Name="left"><ListLookup LookupType="ThisItemLookup"><Field Name="Status_x0020_Pola" Type="Choice" /></ListLookup></Param>
      <Param Name="right"><PrimitiveValue Value="Aktywny" ValueType="Choice" /></Param>
    </Params>
  </Left>
  <Right xsi:type="NWConditionConfig" Name="Jeśli pole zawiera">
    <Params>
      <Param Name="operator"><PrimitiveValue Value="Contains" /></Param>
      <Param Name="left"><ListLookup LookupType="ThisItemLookup"><Field Name="Opis_x0020_Pola" Type="Text" /></ListLookup></Param>
      <Param Name="right"><PrimitiveValue Value="Pilne" ValueType="Text" /></Param>
    </Params>
  </Right>
</Condition>"""

SAMPLE_CROSS_LOOKUP_XML = """<ListLookup LookupType="CrossItemLookup">
  <Lookup LookupType="ThisItemLookup">
    <ListId>{AAAAAAAA-1111-2222-3333-444444444444}</ListId>
    <Field Name="KluczLookup" Type="Lookup" />
  </Lookup>
  <Coercion>LookupIdOnlyAsInteger</Coercion>
  <ListId>{BBBBBBBB-1111-2222-3333-444444444444}</ListId>
  <Field Name="Pole_x0020_Docelowe_B" Type="Text" />
  <CompareField Name="ID" Type="Counter" />
</ListLookup>"""

