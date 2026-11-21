import pytest

from tools.sp_automation.views import ViewScopeError, evaluate_view, parse_view_query


TYPES = {"ID": "Counter", "Status": "Choice", "Score": "Number", "Owner": "Lookup", "Done": "Boolean"}
ROWS = [
    {"ID": 1, "Status": "Open", "Score": 5, "Owner": 7, "Done": False},
    {"ID": 2, "Status": "Closed", "Score": 9, "Owner": None, "Done": True},
    {"ID": 3, "Status": "Open", "Score": 1, "Owner": 8, "Done": False},
]


def ids(caml, rows=ROWS):
    return evaluate_view(parse_view_query(caml), rows, TYPES)


def test_supported_subset_matches_sharepoint_membership():
    assert ids("") == [1, 2, 3]
    assert ids('<OrderBy><FieldRef Name="ID"/></OrderBy>') == [1, 2, 3]
    assert ids('<Where><And><Eq><FieldRef Name="Status"/><Value Type="Choice">Open</Value></Eq>'
               '<Gt><FieldRef Name="Score"/><Value Type="Number">2</Value></Gt></And></Where>') == [1]
    assert ids('<Where><Or><IsNull><FieldRef Name="Owner"/></IsNull>'
               '<Eq><FieldRef Name="Owner" LookupId="TRUE"/><Value Type="Lookup">8</Value></Eq>'
               '</Or></Where>') == [2, 3]
    assert ids('<Where><In><FieldRef Name="ID"/><Values><Value Type="Counter">1</Value>'
               '<Value Type="Counter">3</Value></Values></In></Where>') == [1, 3]
    assert ids('<Where><Eq><FieldRef Name="Done"/><Value Type="Boolean">1</Value></Eq></Where>') == [2]


@pytest.mark.parametrize("caml", [
    '<Where><Eq><FieldRef Name="Status"/><Value Type="DateTime"><Today/></Value></Eq></Where>',
    '<Where><Contains><FieldRef Name="Status"/><Value Type="Text">O</Value></Contains></Where>',
    '<Where><Eq><FieldRef Name="Owner"/><Value Type="Lookup">Anna</Value></Eq></Where>',
    '<Where><Eq><FieldRef Name="Missing"/><Value Type="Text">x</Value></Eq></Where>',
    '<Where><Lt><FieldRef Name="Status"/><Value Type="Text">M</Value></Lt></Where>',
    '<Where><Neq><FieldRef Name="Owner" LookupId="TRUE"/><Value Type="Lookup">7</Value></Neq></Where>',
    '<Where><Eq><FieldRef Name="Status"/><Value Type="Text">open</Value></Eq></Where>',
    '<Where><Eq><FieldRef Name="Status"/><Value Type="Text">x</Value></Eq><Eq/></Where>',
    '<Where><Eq><FieldRef Name="Status" Nullable="TRUE"/><Value Type="Text">x</Value></Eq></Where>',
    '<!DOCTYPE x [<!ENTITY e "x">]><Where/>',
    '<Joins/>',
    '<Where><broken',
])
def test_unverifiable_semantics_fail_closed(caml):
    with pytest.raises(ViewScopeError):
        ids(caml)


def test_unread_or_ambiguous_values_are_never_treated_as_empty():
    view = parse_view_query('<Where><IsNull><FieldRef Name="Status"/></IsNull></Where>')
    with pytest.raises(ViewScopeError):
        evaluate_view(view, [{"ID": 1}], TYPES)
    with pytest.raises(ViewScopeError):
        evaluate_view(view, [{"ID": 1, "Status": ""}], TYPES)
