import copy
import json
from types import SimpleNamespace
import pytest
from geohazard_platform import provisional_risk as pr
from geohazard_platform.soil_calibration import load_parameters
from geohazard_platform.telemetry import ingest_telemetry
from geohazard_platform.connectors import save_connector, ConnectorError
from test_ingestion import db,payload,rows
from test_provisional_risk import sample

def context():return {"firmware_elf_sha256":load_parameters()["firmware_elf_sha256"],"firmware_evidence":"synthetic_test_fixture"}

@pytest.mark.parametrize('raws,expected', [((20718,20945,20606),0),((13032,13118,13004),100)])
def test_all_three_channels_and_formal_fields_unchanged(db,payload,raws,expected):
    p=sample(payload)
    for k,v in zip(('top_raw','middle_raw','toe_raw'),raws):p['soil'][k]=v
    original=copy.deepcopy(p)
    ingest_telemetry(db,p,source='REAL',scope='TEST_ONLY',context=context())
    r=pr.latest(db,site_id=p['site_id'],device_id=p['device_id'])
    assert r['features']['soil_w_rel_pct']==dict.fromkeys(('top','middle','toe'),expected)
    assert r['soil_calibration']['applicable'] is True
    assert r['calibration_version'] is None and r['fusion_eligible'] is False
    assert p==original and rows(db,'alarms')==[]
    assert p['soil']==original['soil']

@pytest.mark.parametrize('ctx',[{}, {'firmware_elf_sha256':'0'*64}])
def test_missing_or_old_firmware_does_not_use_endpoints(payload,ctx):
    r,_=pr.compute(sample(payload),context=ctx)
    assert all(v is None for v in r['features']['soil_w_rel_pct'].values())
    assert r['soil_calibration']['applicable'] is False

def test_missing_and_clip_are_explicit(payload):
    p=sample(payload);p['soil'].update(top_raw=None,middle_raw=0,toe_raw=32767)
    r,_=pr.compute(p,context=context())
    assert r['features']['soil_w_rel_pct']=={'top':None,'middle':100,'toe':0}
    assert 'soil.top:MISSING' in r['quality_flags']
    assert 'soil.toe:CLIPPED' in r['quality_flags']

def test_connector_firmware_is_device_scoped_and_validated(db):
    firmware=context()['firmware_elf_sha256']
    data={'name':'fixture','kind':'mqtt','enabled':False,'source':'REAL',
          'config':{'host':'127.0.0.1','site_id':'SITE01','topic':'zhifang/v2/SITE01/NODE-01/telemetry','firmware_elf_sha256':firmware}}
    item=save_connector(db,data)
    assert item['config']['firmware_elf_sha256']==firmware
    invalid=copy.deepcopy(data);invalid['config']['topic']='zhifang/v2/SITE01/+/telemetry'
    with pytest.raises(ConnectorError):save_connector(db,invalid)
    invalid=copy.deepcopy(data);invalid['config']['firmware_elf_sha256']='wrong'
    with pytest.raises(ConnectorError):save_connector(db,invalid)
    item=save_connector(db,{'config':{'firmware_elf_sha256':None}},connector_id=item['id'])
    assert item['config'].get('firmware_elf_sha256') is None

def test_mqtt_context_reaches_saved_result(db,payload):
    from geohazard_platform.connectors import _MQTTSession
    p=sample(payload);p['soil'].update(top_raw=13032,middle_raw=13118,toe_raw=13004)
    topic=f"zhifang/v2/{p['site_id']}/{p['device_id']}/telemetry"
    session=_MQTTSession(db,{'id':'test-only','source':'MOCK','config':{'topic':topic,'scope':'TEST_ONLY','firmware_elf_sha256':context()['firmware_elf_sha256']}})
    session._on_message(None,None,SimpleNamespace(topic=topic,retain=False,payload=json.dumps(p).encode()))
    r=pr.latest(db,site_id=p['site_id'],device_id=p['device_id'])
    assert r['features']['soil_w_rel_pct']['toe']==100
    assert r['soil_calibration']['evidence']=='operator_declared_connector_not_attestation'
    assert rows(db,'alarms')==[]

def test_session_binding_conflict_latches_until_new_boot_and_survives_restart(db,payload):
    first=sample(payload)
    ingest_telemetry(db,first,source='REAL',scope='TEST_ONLY',context=context())
    latest=lambda:pr.latest(db,site_id=first['site_id'],device_id=first['device_id'])
    assert latest()['soil_calibration']['hardware_verified'] is False
    assert latest()['soil_calibration']['session_identity']['boot_id']==1
    changed={'firmware_elf_sha256':'0'*64}
    ingest_telemetry(db,sample(payload,2),source='REAL',scope='TEST_ONLY',context=changed)
    assert latest()['soil_calibration']['session_binding_consistent'] is False
    db.close();db.initialize()
    ingest_telemetry(db,sample(payload,3),source='REAL',scope='TEST_ONLY',context=context())
    assert all(v is None for v in latest()['features']['soil_w_rel_pct'].values())
    assert 'FIRMWARE_DECLARATION_CHANGED_WITHIN_BOOT' in latest()['quality_flags']
    ingest_telemetry(db,sample(payload,1,boot=2),source='REAL',scope='TEST_ONLY',context=context())
    assert latest()['soil_calibration']['applicable'] is True
    assert latest()['soil_calibration']['hardware_verified'] is False
    assert rows(db,'alarms')==[]

def test_duplicate_does_not_relabel_existing_calibration(db,payload):
    p=sample(payload)
    ingest_telemetry(db,p,source='REAL',scope='TEST_ONLY')
    old=pr.latest(db,site_id=p['site_id'],device_id=p['device_id'])
    receipt=ingest_telemetry(db,p,source='REAL',scope='TEST_ONLY',context=context())
    assert receipt['status']=='duplicate'
    assert pr.latest(db,site_id=p['site_id'],device_id=p['device_id'])==old

def test_unverified_old_session_cannot_be_promoted_by_filling_hash(db,payload):
    p=sample(payload)
    ingest_telemetry(db,p,source='REAL',scope='TEST_ONLY')
    ingest_telemetry(db,sample(payload,2),source='REAL',scope='TEST_ONLY',context=context())
    r=pr.latest(db,site_id=p['site_id'],device_id=p['device_id'])
    assert r['soil_calibration']['parameter_match'] is True
    assert r['soil_calibration']['applicable'] is False
    assert r['soil_calibration']['hardware_verified'] is False

def test_legacy_state_without_binding_uses_original_saved_context(db,payload):
    p=sample(payload)
    receipt=ingest_telemetry(db,p,source='REAL',scope='TEST_ONLY')
    with db.connection() as c:
        row=c.execute('SELECT state_json FROM provisional_risk WHERE telemetry_id=?',(receipt['telemetry_id'],)).fetchone()
        state=json.loads(row['state_json']);state.pop('firmware_binding')
        c.execute('UPDATE provisional_risk SET state_json=? WHERE telemetry_id=?',(json.dumps(state),receipt['telemetry_id']))
    ingest_telemetry(db,sample(payload,2),source='REAL',scope='TEST_ONLY',context=context())
    r=pr.latest(db,site_id=p['site_id'],device_id=p['device_id'])
    assert r['soil_calibration']['parameter_match'] is True
    assert r['soil_calibration']['applicable'] is False
