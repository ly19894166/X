"""Phase7 Review A1；仅新增测试，不修改原551项。"""
import json
import pytest
from pydantic import ValidationError
from test_phase7_research import seed, w, run, configure, second_company, rebuild
from xevent.research.provider import MockModelProvider, mock_output
from xevent.research.contracts import AnalysisRun, HypothesisSet, RedTeamReport, Adjudication
from xevent.research.validation import validate_output, validate_decision, ResearchInvalid
from xevent.ledger.store import ref

FAKE='公司已经获得核心客户独家订单'


def responder(verdict='UNCHANGED', recommended='TARGET', adjudication=None, prose=False):
    def respond(kind,data):
        out=mock_output(kind,data)
        if kind=='PRIMARY' and prose:
            out['target']['reasoning_summary_zh']=FAKE
        if kind=='RED_TEAM':
            out.update(verdict=verdict,recommended_id=recommended)
        if kind=='ADJUDICATION' and adjudication:
            out.update(selected_id=adjudication,reasoning_summary_zh='依据主研究评论选择主要假设')
        return out
    return MockModelProvider(respond)


@pytest.mark.parametrize('verdict,selected,source',[
    ('NULL_PREFERRED','NULL','RED_TEAM'),
    ('UNCHANGED','TARGET','PRIMARY'),
    ('TARGET_WEAKENED','TARGET','PRIMARY'),
    ('TARGET_INVALIDATED','NULL','RED_TEAM'),
])
def test_a1_without_adjudication_decision_source(w,verdict,selected,source):
    configure(w,allow_adjudication=False)
    result,p=run(w,responder(verdict,selected))
    assert result.final_choice==selected
    assert result.final_hypothesis_id==selected
    assert result.decision_source==source
    assert result.final_result_ref==(result.red_team_ref if source=='RED_TEAM' else result.primary_result_ref)
    assert len(p.calls)==2
    assert AnalysisRun.model_validate_json(result.model_dump_json())==result


def test_a1_adjudication_alt_is_final_source(w):
    second_company(w)
    result,p=run(w,responder('ALT_STRONGER','ALT_0'))
    assert result.final_choice=='ALT' and result.final_hypothesis_id=='ALT_0'
    assert result.decision_source=='ADJUDICATION'
    assert result.final_result_ref==result.adjudication_ref
    assert len(p.calls)==3


def test_a1_red_team_alt_without_adjudication(w):
    second_company(w); configure(w,allow_adjudication=False)
    result,_=run(w,responder('ALT_STRONGER','ALT_0'))
    assert result.final_choice=='ALT' and result.decision_source=='RED_TEAM'
    assert result.final_result_ref==result.red_team_ref


@pytest.mark.parametrize('selected',['NULL','ALT_0'])
def test_a1_weakened_cannot_change_selected(w,selected):
    second_company(w)
    result,_=run(w,responder('TARGET_WEAKENED',selected))
    assert 'INVALID_REFERENCE' in result.hold_reasons
    assert result.decision_source=='HOLD_GATE' and result.final_result_ref is None
    assert result.final_hypothesis_id is None


@pytest.mark.parametrize('failure',['budget','provider','schema','reference','numeric','timeout','crash'])
def test_a1_gate_never_claims_model_decision(w,failure):
    p=MockModelProvider()
    if failure=='budget': configure(w,budget_policy={'max_requests':1})
    if failure=='provider': p.is_mock=False
    if failure=='timeout':
        configure(w,timeout_seconds=0.01)
        p=MockModelProvider(delay_seconds=1)
    if failure in ('schema','reference','numeric'):
        def respond(kind,data):
            out=mock_output(kind,data)
            if kind=='RED_TEAM':
                if failure=='schema': return '{}'
                if failure=='reference': out['evidence_refs']=[dict(object_id='FAKE',version=1)]
                if failure=='numeric': out['reasoning_summary_zh']='利润30%'
            return out
        p=MockModelProvider(respond)
    if failure=='crash':
        def fault(stage):
            if stage=='after_model_result': raise RuntimeError('A1_CRASH')
        w['ledger'].fault=fault
        with pytest.raises(RuntimeError): run(w,p)
        w['ledger'].fault=lambda _:None
    result,_=run(w,p)
    assert result.analysis_status=='HOLD' and result.decision_source=='HOLD_GATE'
    assert result.final_result_ref is None and result.final_hypothesis_id is None


def test_a1_schema_rejects_wrong_source_reference(w):
    result,_=run(w)
    data=result.model_dump()
    data.update(final_result_ref=result.red_team_ref)
    with pytest.raises(ValidationError,match='DECISION_SOURCE'):
        AnalysisRun.model_validate(data)
    data=result.model_dump(); data['decision_source']='MODEL_GUESS'
    with pytest.raises(ValidationError): AnalysisRun.model_validate(data)


@pytest.mark.parametrize('field,value',[('final_hypothesis_id','NULL'),('final_choice','ALT')])
def test_a1_resolved_result_validates_hypothesis_and_choice(w,field,value):
    result,_=run(w)
    changed=result.model_copy(update={field:value})
    primary=w['ledger'].get(result.primary_result_ref.object_id,result.primary_result_ref.version)
    red=w['ledger'].get(result.red_team_ref.object_id,result.red_team_ref.version)
    with pytest.raises(ResearchInvalid,match='DECISION_SOURCE'):
        validate_decision(changed,primary,red,None)


def test_a1_commentary_not_forwarded_or_promoted(w):
    original=mock_output('PRIMARY',w['research'].provider_data(w['packet']))
    result,p=run(w,responder('NULL_PREFERRED','NULL',prose=True))
    primary=w['ledger'].get(result.primary_result_ref.object_id,1).primary
    assert primary.target.reasoning_summary_zh==FAKE
    assert not primary.target.statements
    assert [ref(r) for r in primary.target.supporting_evidence_refs]==original['target']['supporting_evidence_refs']
    assert FAKE not in json.dumps(w['research'].provider_data(w['packet']),ensure_ascii=False)
    for call in p.calls[1:]:
        assert FAKE not in json.dumps(call['untrusted_data'],ensure_ascii=False)
        assert 'reasoning_summary_zh' not in call['untrusted_data']['primary']['target']
    assert result.decision_source=='ADJUDICATION'


def test_a1_commentary_cannot_resurrect_invalidated_target(w):
    result,p=run(w,responder('TARGET_INVALIDATED','NULL','TARGET',prose=True))
    assert result.final_choice=='NULL' and result.analysis_status=='HOLD'
    assert result.decision_source=='HOLD_GATE'
    assert result.final_result_ref is None and result.adjudication_ref is None
    assert 'INVALID_REFERENCE' in result.hold_reasons
    assert all(FAKE not in json.dumps(c['untrusted_data'],ensure_ascii=False) for c in p.calls[1:])


@pytest.mark.parametrize('kind',['PRIMARY','RED_TEAM','ADJUDICATION'])
@pytest.mark.parametrize('claim_kind',['CONFIRMED_FACT','COUNTEREVIDENCE'])
def test_a1_formal_statements_cannot_launder_commentary(w,kind,claim_kind):
    data=w['research'].provider_data(w['packet'])
    primary=HypothesisSet.model_validate(mock_output('PRIMARY',data))
    red=RedTeamReport.model_validate(mock_output('RED_TEAM',{**data,'primary':primary.model_dump(mode='json')}))
    statement=dict(kind=claim_kind,text_zh=FAKE,evidence_ref=ref(w['event_evidence']),quoted_span=FAKE)
    if kind=='PRIMARY':
        output=primary.model_dump(); output['target']['statements']=[statement]
        parsed=HypothesisSet.model_validate(output)
    elif kind=='RED_TEAM':
        parsed=RedTeamReport.model_validate({**red.model_dump(),'statements':[statement]})
    else:
        parsed=Adjudication.model_validate(dict(selected_id='NULL',evidence_refs=[],reasoning_summary_zh='保留未知',statements=[statement]))
    with pytest.raises(ResearchInvalid):
        validate_output(parsed,w['packet'],w['research'].view(w['packet'].as_of),w['ledger'],primary,red)


@pytest.mark.parametrize('kind',['RED_TEAM','ADJUDICATION'])
def test_a1_valid_structured_fact_survives_downstream_gate(w,kind):
    def respond(role,data):
        out=mock_output(role,data)
        if role=='RED_TEAM': out.update(verdict='NULL_PREFERRED',recommended_id='NULL')
        if role==kind:
            out['statements']=[dict(kind='COUNTEREVIDENCE',text_zh='明确宣布铜供应减少',
                evidence_ref=ref(w['event_evidence']),quoted_span='明确宣布铜供应减少')]
        return out
    result,p=run(w,MockModelProvider(respond))
    assert result.analysis_status=='MOCK_PASS'
    if kind=='RED_TEAM':
        assert p.calls[-1]['untrusted_data']['red_team']['statements'][0]['kind']=='COUNTEREVIDENCE'


@pytest.mark.pit
def test_a1_decision_audit_replay_not_rewritten(w):
    old,_=run(w)
    at=w['clock'](); before=w['ledger'].replay(at)
    configure(w,allow_adjudication=False)
    new,_=run(w,responder('NULL_PREFERRED','NULL'),identity='A1_NEW')
    assert old.decision_source=='PRIMARY' and new.decision_source=='RED_TEAM'
    assert w['ledger'].replay(at)==before
    assert w['ledger'].replay(w['clock']())==w['ledger'].replay(w['clock']())


@pytest.mark.pit
def test_a1_freshness_hold_has_no_formal_result(w):
    def respond(kind,data):
        out=mock_output(kind,data)
        if kind=='RED_TEAM': rebuild(w)
        return out
    result,_=run(w,MockModelProvider(respond))
    assert result.analysis_status=='HOLD' and result.decision_source=='HOLD_GATE'
    assert result.final_result_ref is None and result.final_hypothesis_id is None


def test_a1_commentary_schema_is_explicit():
    for cls in (HypothesisSet,RedTeamReport,Adjudication):
        schema=json.dumps(cls.model_json_schema(),ensure_ascii=False)
        assert 'INFERENCE_ONLY / RESEARCH_COMMENTARY' in schema