"""Reproducible local development replay; never reads organizer-only data."""
import argparse, datetime as dt, hashlib, importlib.util, json, platform, shutil, statistics, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'code'))
from main import Auditor, write_output
from evidence import read_csv
spec=importlib.util.spec_from_file_location('evaluation',ROOT/'code/evaluation/main.py')
ev=importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def quantile(values,q):
    x=sorted(values); return x[min(len(x)-1,int((len(x)-1)*q))]

def run(tag):
    out=ROOT/'runs'/tag; out.mkdir(parents=True,exist_ok=True)
    if (out/'result.json').exists(): raise FileExistsError('Completed run tags are immutable')
    source=out/'source'; source.mkdir()
    for name in ['main.py','evidence.py','evaluation/main.py']:
        p=source/name; p.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/'code'/name,p)
    started=dt.datetime.now(dt.timezone.utc).isoformat(); start=time.perf_counter()
    auditor=Auditor(ROOT); index_seconds=time.perf_counter()-start
    requests=sorted(read_csv(ROOT/'dataset/deletion_requests.csv'),key=lambda r:r['case_id'])
    latencies=[]; predictions=[]
    for case in requests:
        t=time.perf_counter(); predictions.append(auditor.audit_case(case)); latencies.append(time.perf_counter()-t)
    write_output(predictions,out/'output.csv'); generation_seconds=time.perf_counter()-start
    indexed_case_seconds=sum(latencies)
    if hasattr(auditor.evidence,'use_identity_index'):
        auditor.evidence.use_identity_index=False
        t=time.perf_counter(); brute=auditor.run(requests); brute_seconds=time.perf_counter()-t
        indexed_equals_brute=(brute==predictions)
        auditor.evidence.use_identity_index=True
    else:
        brute_seconds=None; indexed_equals_brute=None
    samples=auditor.run(read_csv(ROOT/'dataset/sample_deletion_requests.csv'))
    final_diagnostics={key:value for key,value in auditor.diagnostics.items() if value} if hasattr(auditor,'diagnostics') else {}
    write_output(samples,out/'sample_output.csv')
    gold=read_csv(ROOT/'dataset/sample_output.csv'); metrics=ev.compare_sample(samples,gold)
    sample_requests=read_csv(ROOT/'dataset/sample_deletion_requests.csv')
    reported=[{'case_id':r['case_id'],'deletion_status':'COMPLETE' if r['reported_status']=='COMPLETE' else 'INCOMPLETE','steps_json':'[]'} for r in sample_requests]
    original_audits=auditor.audits; auditor.audits=[]
    current_only=auditor.run(sample_requests); auditor.audits=original_audits
    ablations={'reported_status_only':ev.compare_sample(reported,gold),'current_identifiers_only':ev.compare_sample(current_only,gold),'full_engine':metrics}
    errors=ev.validate_output(ROOT,out/'output.csv',auditor); custom=ev.custom_tests(ROOT)
    coverage=ev.case_coverage_rows(ROOT,auditor,predictions)
    ev.write_case_coverage(out/'coverage.md',coverage)
    ev.write_sample_diff(ROOT,out/'sample_diff.md',samples,gold,auditor)
    ev.write_report(out/'evaluation_report.md',metrics,errors,custom,len(auditor.evidence.unparsed))
    result={'tag':tag,'started_at_utc':started,'python':sys.version,'platform':platform.platform(),
      'source_hashes':{n:sha(ROOT/'code'/n) for n in ['main.py','evidence.py','evaluation/main.py']},
      'input_hashes':{str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'dataset').rglob('*')) if p.is_file()},
      'output_sha256':sha(out/'output.csv'),'public_sample':metrics,
      'contract_errors':errors,'custom_passed':sum(x[1] for x in custom),'custom_total':len(custom),
      'unparsed':auditor.evidence.unparsed,'parsed_records':len(auditor.evidence.records),
      'generation_seconds':generation_seconds,'index_seconds':index_seconds,
      'indexed_case_seconds':indexed_case_seconds,'brute_case_seconds':brute_seconds,
      'indexed_equals_brute':indexed_equals_brute,'diagnostics':final_diagnostics,'ablations':ablations,
      'per_case_seconds':{'median':statistics.median(latencies),'p95':quantile(latencies,.95),'max':max(latencies)},
      'case_latencies_seconds':dict(zip([r['case_id'] for r in requests],latencies)),
      'solver_usage':{'provider_calls':0,'input_tokens':0,'output_tokens':0,'estimated_cost_usd':0},
      'coverage':coverage}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['tag','public_sample','generation_seconds','index_seconds','per_case_seconds','custom_passed','custom_total','unparsed','parsed_records','contract_errors']},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('tag'); run(p.parse_args().tag)
