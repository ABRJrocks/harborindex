"""Static comparison reports contain the full selected document content."""

from dataclasses import asdict
from importlib.resources import files
import json

from .validation import integer, metadata, require, text


def compare(index,namespace,queries,*,model,k=5,candidate_limit=50,rank_constant=60,
            lexical_weight=1.0,dense_weight=1.0):
    require(isinstance(queries,list) and 1<=len(queries)<=20,'A report needs 1 to 20 query cases')
    cases=[]
    revision=None
    names=set()
    for case in queries:
        require(type(case) is dict and not set(case)-{'name','query','vector','where'},'Query case has unknown fields')
        name=text(case.get('name'),'Query case name',120)
        require(name not in names,'Query case names must be unique')
        names.add(name)
        query=text(case.get('query'),'Query',1024)
        filters=metadata(case.get('where',{}))
        modes={}
        for mode in ('lexical','dense','hybrid'):
            params={'query':query} if mode!='dense' else {}
            if mode!='lexical': params.update(vector=case.get('vector'),model=model)
            result=index.search(namespace,mode=mode,where=filters,k=k,candidate_limit=candidate_limit,
                                rank_constant=rank_constant,lexical_weight=lexical_weight,dense_weight=dense_weight,**params)
            if revision is None: revision=result.revision
            require(result.revision==revision,'Index changed during report generation; retry with a quiet index or a snapshot copy')
            modes[mode]=asdict(result)
        cases.append({'name':name,'query':query,'where':filters,'results':modes})
    return {'format':'harborindex-report-v1','namespace':namespace,'model':model,
            'dimensions':index.dimensions,'revision':revision,'toy_vectors':False,'cases':cases}


def render(report):
    require(type(report) is dict and report.get('format')=='harborindex-report-v1','Unsupported report format')
    raw=json.dumps(report,ensure_ascii=True,allow_nan=False,separators=(',',':'))
    require(len(raw.encode())<=16*1024*1024,'Report exceeds 16 MiB; reduce queries or result depth')
    safe=raw.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template=files('harborindex').joinpath('report.html').read_text(encoding='utf-8')
    require(template.count('HARBORINDEX_DATA_PLACEHOLDER')==1,'Invalid report template')
    return template.replace('HARBORINDEX_DATA_PLACEHOLDER',safe)


def write_report(path,report):
    html=render(report)
    with open(path,'x',encoding='utf-8') as output:
        output.write(html)
