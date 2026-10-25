"""Generate pinned FinRCA data, then extract isolated, model-visible review packets."""
from pathlib import Path
import csv, json, subprocess, sys, copy
import yaml

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / 'packages/data/upstream'
sys.path.insert(0, str(UP))
from src.schema import TABLE_SCHEMAS, MONEY_FIELDS, PRIMARY_KEYS

TABLES = ['vendors','vendor_change_log','invoices','payments','payment_allocations','gl_entries','bank_transactions','bank_statements','audit_log']
schema = {t: {'columns': TABLE_SCHEMAS[t], 'money': list(MONEY_FIELDS.get(t, [])), 'primaryKey': list(PRIMARY_KEYS[t])} for t in TABLES}
out = ROOT / 'packages/data/src'
out.mkdir(parents=True, exist_ok=True)
(out/'schema.json').write_text(json.dumps(schema,indent=2)+'\n',encoding='utf-8')
cfg=yaml.safe_load((UP/'config.yaml').read_text())
cfg['scale']['cases_per_failure']=16
cfg['scale']['non_failure_cases']=96
cfg['output_dir']=str(ROOT/'.local/prepared-upstream')
cfgpath=ROOT/'.local/prepare-config.yaml'
cfgpath.parent.mkdir(exist_ok=True)
cfgpath.write_text(yaml.safe_dump(cfg),encoding='utf-8')
subprocess.run([sys.executable,str(UP/'generate_finrca_bench.py'),'--config',str(cfgpath)],check=True,cwd=ROOT)
base=ROOT/'.local/prepared-upstream/benchmark'
rows={t:list(csv.DictReader((base/'full'/f'{t}.csv').open(encoding='utf-8',newline=''))) for t in TABLES}
truth=[json.loads(line) for line in (base/'rca_ground_truth.jsonl').read_text().splitlines()]
families=['F06','F11','F12','F14','NO_FAILURE']
used=set(); selected=[]
normal_categories={'LEGITIMATE_SPLIT_PAYMENT','LEGITIMATE_BATCH_PAYMENT','LEGITIMATE_NET_FEE_ACCOUNTING','LEGITIMATE_RECENT_PENDING_SETTLEMENT','LEGITIMATE_ACCOUNTED_BANK_FEE','LEGITIMATE_WEEKEND_CLEARING','LEGITIMATE_CHECK_CLEARING'}
for family in families:
    candidates=[x for x in truth if x['failure_type'].startswith(family) and (x['primary_entity']['type']=='payment' or family=='F06')]
    if family=='NO_FAILURE':
        candidates=[x for x in candidates if any(word in x['root_cause_category'] for word in ['SPLIT_PAYMENT','BATCH_PAYMENT','NET_FEE','PENDING_SETTLEMENT','ACCOUNTED_BANK_FEE','WEEKEND','CHECK_CLEARING'])]
    for i in range(12):
        chosen=next((x for x in candidates if x['group_vendor_id'] not in used),None)
        if chosen is None: raise RuntimeError(f'Not enough isolated vendors for {family}')
        used.add(chosen['group_vendor_id']); selected.append((chosen,'development' if i<8 else 'heldout'))

packets=[];labels=[]
for number,(gt,split) in enumerate(selected,1):
    vid=gt['group_vendor_id']; pid=gt['primary_entity']['id'] if gt['primary_entity']['type']=='payment' else [x['id'] for x in gt['affected_entities'] if x['type']=='payment'][-1]
    payments=[p for p in rows['payments'] if p['vendor_id']==vid]
    pids={p['payment_id'] for p in payments}; refs={p['reference_number'] for p in payments}
    invoices=[i for i in rows['invoices'] if i['vendor_id']==vid]
    iids={i['invoice_id'] for i in invoices}
    bank=[b for b in rows['bank_transactions'] if b['payment_reference'] in refs]
    bids={b['bank_transaction_id'] for b in bank}; accounts={b['bank_account_id'] for b in bank}
    tables={
      'vendors':[v for v in rows['vendors'] if v['vendor_id']==vid],
      'vendor_change_log':[v for v in rows['vendor_change_log'] if v['vendor_id']==vid],
      'invoices':invoices,'payments':payments,
      'payment_allocations':[a for a in rows['payment_allocations'] if a['payment_id'] in pids and a['invoice_id'] in iids],
      'bank_transactions':bank,
      'bank_statements':[s for s in rows['bank_statements'] if s['bank_account_id'] in accounts],
      'gl_entries':[g for g in rows['gl_entries'] if g['source_transaction_id'] in pids|iids|bids],
      'audit_log':[a for a in rows['audit_log'] if a['entity_id'] in pids|iids|bids|{vid}],
    }
    # Bank statements contain aggregate accounts beyond the vendor packet. They are
    # retained as source observations, not asserted to balance the extracted subset.
    manifest={'name':f'Review packet {number:03d}', 'asOf':'2026-06-30T23:59:59Z','clearingDays':10,'currency':next(p['payment_currency'] for p in payments if p['payment_id']==pid),'focusPaymentIds':[pid],
      'coverage':{t:{'status':'complete','from':'2024-01-01T00:00:00Z','to':'2026-06-30T23:59:59Z'} for t in TABLES}}
    packet={'manifest':manifest,'tables':tables}
    expected='no_anomaly_supported' if gt['failure_type']=='NO_FAILURE' else 'anomaly_supported'
    labels.append({'packet':manifest['name'],'split':split,'paymentId':pid,'expectedOutcome':expected,'category':gt['failure_type'],'evidenceIds':gt['evidence_ids'],'evidenceTables':gt['evidence_required'],'rootCause':gt['root_cause'],'upstreamCaseId':gt['case_id'],'vendorGroup':vid})
    packets.append(packet)

# Stress packets are explicit derived fixtures, with evaluation labels outside app data.
for i in range(10):
    packet=copy.deepcopy(packets[0 if i%2==0 else 12]);pid=packet['manifest']['focusPaymentIds'][0]
    packet['manifest']['name']=f'Coverage packet {i+1:03d}'
    if i%3==0:
        packet['manifest']['coverage']['bank_transactions']['status']='partial'
        packet['tables']['bank_transactions']=[]
    elif i%3==1:
        packet['manifest']['coverage']['audit_log']['status']='unavailable'
        packet['tables']['audit_log']=[]
    else:
        packet['tables']['audit_log']=[]
        packet['manifest']['coverage']['vendor_change_log']['status']='partial'
    labels.append({'packet':packet['manifest']['name'],'split':'stress','paymentId':pid,'expectedOutcome':'insufficient_evidence','category':'DERIVED_INCOMPLETE_COVERAGE','evidenceIds':[],'evidenceTables':[]})
    packets.append(packet)

(ROOT/'data').mkdir(exist_ok=True)
(ROOT/'evaluation/labels').mkdir(parents=True,exist_ok=True)
(ROOT/'data/builtin.json').write_text(json.dumps(packets,separators=(',',':'))+'\n',encoding='utf-8')
(ROOT/'evaluation/labels/cases.json').write_text(json.dumps(labels,indent=2)+'\n',encoding='utf-8')
(ROOT/'data/PROVENANCE.json').write_text(json.dumps({'repository':'https://github.com/PratikGhawate/FinRCA-AI-Bench','commit':(UP/'UPSTREAM_COMMIT').read_text().strip(),'seed':42,'selection':'vendor-disjoint review packets; 40 development, 20 heldout, 10 derived coverage stress cases','upstreamQualityReport':json.loads((base/'dataset_quality_report.json').read_text())},indent=2)+'\n',encoding='utf-8')
print(f'Prepared {len(packets)} packets; evaluation labels stored separately.')
