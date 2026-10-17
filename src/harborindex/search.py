"""Scoped candidate pools and transparent one-based rank fusion."""

from dataclasses import dataclass, field
import heapq
import math

from .store import Store
from .validation import MAX_SCAN, cosine, integer, metadata, namespace, positive, require, text, unit_vector, words


@dataclass(frozen=True)
class Hit:
    id: str
    namespace: str
    title: str
    text: str = field(repr=False)
    metadata: dict = field(repr=False)
    rank: int
    score: float
    components: dict


@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]
    mode: str
    score_kind: str
    namespace: str
    candidate_limit: int
    lexical_candidates: int
    dense_candidates: int
    vectors_scanned: int
    rank_constant: int | None
    revision: int
    model: str | None
    filters: dict
    weights: dict | None


def fuse(lexical,dense,*,rank_constant=60,lexical_weight=1.0,dense_weight=1.0):
    integer(rank_constant,'Rank constant',1,1_000_000)
    weights={'lexical':positive(lexical_weight,'Lexical weight'),'dense':positive(dense_weight,'Dense weight')}
    scores={}
    components={}
    for name,ranking in (('lexical',lexical),('dense',dense)):
        require(isinstance(ranking,(list,tuple)) and len(ranking)<=200,'Candidate pools must contain at most 200 pairs')
        seen=set()
        for rank,pair in enumerate(ranking,1):
            require(isinstance(pair,(list,tuple)) and len(pair)==2,'Candidates must be ID and raw-score pairs')
            document_id,raw_score=pair
            text(document_id,'Candidate ID',256)
            require(type(raw_score) in (int,float),'Candidate raw scores must be numeric')
            try:
                finite=math.isfinite(raw_score)
            except OverflowError:
                finite=False
            require(finite,'Candidate raw scores must be finite')
            require(document_id not in seen,'A candidate pool repeats a document ID')
            seen.add(document_id)
            contribution=weights[name]/(rank_constant+rank)
            scores[document_id]=scores.get(document_id,0.0)+contribution
            components.setdefault(document_id,{})[name]={'rank':rank,'raw_score':raw_score,'rrf_contribution':contribution}
    return sorted(scores,key=lambda document_id:(-scores[document_id],document_id)),scores,components


class Index(Store):
    def search(self,namespace_name,*,query=None,vector=None,model=None,mode='hybrid',
               where=None,k=10,candidate_limit=50,rank_constant=60,
               lexical_weight=1.0,dense_weight=1.0,max_scan=MAX_SCAN):
        namespace(namespace_name)
        require(mode in ('lexical','dense','hybrid'),'Search mode must be lexical, dense or hybrid')
        integer(k,'Result limit',1,100)
        integer(candidate_limit,'Candidate limit',k,200)
        integer(max_scan,'Vector scan limit',1,MAX_SCAN)
        integer(rank_constant,'Rank constant',1,1_000_000)
        positive(lexical_weight,'Lexical weight')
        positive(dense_weight,'Dense weight')
        filters=metadata({} if where is None else where)
        match=words(query) if mode in ('lexical','hybrid') else None
        if mode=='dense': require(query is None,'Dense mode does not use query text; omit it')
        if mode=='lexical':
            require(vector is None and model is None,'Lexical mode does not accept embeddings or a model label')
            unit=None
        else:
            require(self.dimensions is not None,'This index has no vector configuration')
            text(model,'Query embedding model label',128)
            require(model==self.model,'Query model label does not match the index')
            unit=unit_vector(vector,self.dimensions)
        scope='d.namespace=?'
        parameters=[namespace_name]
        for key,value in filters.items():
            scope+=' AND json_extract(d.metadata,?)=?'
            parameters.extend(('$.'+key,value))
        with self._transaction():
            revision=self._db.execute('SELECT revision FROM harbor_meta WHERE singleton=1').fetchone()[0]
            lexical=[]
            if match is not None:
                lexical=[(row['id'],row['score']) for row in self._db.execute(
                    'SELECT d.id,bm25(harbor_fts,2.0,1.0) AS score FROM harbor_fts '
                    'JOIN harbor_documents d ON d.rowid=harbor_fts.rowid WHERE harbor_fts MATCH ? AND '+scope+
                    ' ORDER BY score,d.id LIMIT ?',(match,*parameters,candidate_limit))]
            dense=[]
            count=0
            if unit is not None:
                count=self._db.execute('SELECT COUNT(*) FROM harbor_documents d WHERE '+scope+' AND d.vector IS NOT NULL',parameters).fetchone()[0]
                require(count<=max_scan,'Scoped vector count exceeds the scan limit; narrow the scope or use a dedicated vector index')
                rows=self._db.execute('SELECT d.id,d.vector FROM harbor_documents d WHERE '+scope+' AND d.vector IS NOT NULL',parameters)
                candidates=((-cosine(unit,bytes(row['vector']),self.dimensions),row['id']) for row in rows)
                dense=[(document_id,-score) for score,document_id in heapq.nsmallest(candidate_limit,candidates)]
            if mode=='hybrid':
                ordered,scores,components=fuse(lexical,dense,rank_constant=rank_constant,
                                                lexical_weight=lexical_weight,dense_weight=dense_weight)
                score_kind='weighted_rrf'
            else:
                pool=lexical if mode=='lexical' else dense
                ordered=[document_id for document_id,_ in pool]
                scores={document_id:-score if mode=='lexical' else score for document_id,score in pool}
                components={document_id:{mode:{'rank':rank,'raw_score':score}} for rank,(document_id,score) in enumerate(pool,1)}
                score_kind='negative_bm25' if mode=='lexical' else 'cosine'
            selected=ordered[:k]
            documents=self._fetch(namespace_name,selected)
            require(len(documents)==len(selected),'Candidate document is missing from the index')
            hits=[Hit(**documents[document_id],rank=rank,score=scores[document_id],components=components[document_id]) for rank,document_id in enumerate(selected,1)]
        return SearchResult(hits,mode,score_kind,namespace_name,candidate_limit,len(lexical),len(dense),count,
                            rank_constant if mode=='hybrid' else None,revision,self.model,filters,
                            {'lexical':float(lexical_weight),'dense':float(dense_weight)} if mode=='hybrid' else None)
