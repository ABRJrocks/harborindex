"""Transactional documents and FTS rows in a standalone SQLite index."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3

from .validation import MAX_BATCH_BYTES, HarborError, integer, namespace, prepare, require, text

SCHEMA = (
    'CREATE TABLE harbor_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, dimensions INTEGER, model TEXT)',
    '''CREATE TABLE harbor_documents(
        rowid INTEGER PRIMARY KEY, namespace TEXT NOT NULL, id TEXT NOT NULL,
        title TEXT NOT NULL, text TEXT NOT NULL, metadata TEXT NOT NULL,
        vector BLOB, UNIQUE(namespace,id))''',
    "CREATE VIRTUAL TABLE harbor_fts USING fts5(title,text,tokenize='unicode61 remove_diacritics 2')",
    'CREATE INDEX harbor_scope ON harbor_documents(namespace)',
)


def connection(path, *, read_only=False):
    if str(path)==':memory:':
        require(not read_only,'An in-memory index cannot be reopened read-only')
        db=sqlite3.connect(':memory:',isolation_level=None,timeout=5)
    else:
        mode='ro' if read_only else 'rw'
        db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode='+mode,uri=True,isolation_level=None,timeout=5)
    try:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        require(db.execute('PRAGMA journal_mode').fetchone()[0] in ('delete','memory'),
                'This release supports DELETE journaling only; WAL indexes are unsupported')
        db.execute("SELECT json_extract('{\"probe\":\"ok\"}', '$.probe')")
        if read_only: db.execute('PRAGMA query_only=ON')
        return db
    except BaseException:
        db.close()
        raise


class Store:
    def __init__(self, database, *, read_only=False):
        self._db=database
        self.read_only=read_only
        try:
            row=database.execute('SELECT version,dimensions,model FROM harbor_meta WHERE singleton=1').fetchone()
            require(row is not None and row['version']==1,'Unsupported HarborIndex schema')
            self.dimensions=row['dimensions']
            self.model=row['model']
            self._configuration(self.dimensions,self.model)
            database.execute('SELECT rowid FROM harbor_fts LIMIT 0')
        except BaseException:
            database.close()
            raise

    @staticmethod
    def _configuration(dimensions,model):
        if dimensions is None:
            require(model is None,'A model label requires dimensions')
        else:
            integer(dimensions,'Dimensions',1,2048)
            text(model,'Embedding model label',128)

    @classmethod
    def create(cls,path,*,dimensions=None,model=None):
        cls._configuration(dimensions,model)
        if str(path)!=':memory:':
            descriptor=os.open(Path(path).resolve(),os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
            os.close(descriptor)
        db=connection(path)
        try:
            db.execute('BEGIN IMMEDIATE')
            for statement in SCHEMA: db.execute(statement)
            db.execute('INSERT INTO harbor_meta VALUES(1,1,?,?)',(dimensions,model))
            db.commit()
        except BaseException:
            if db.in_transaction: db.rollback()
            db.close()
            raise
        return cls(db)

    @classmethod
    def open(cls,path,*,read_only=False):
        return cls(connection(path,read_only=read_only),read_only=read_only)

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()

    @contextmanager
    def _transaction(self,*,write=False):
        require(not self._db.in_transaction,'Nested index transactions are unsupported')
        require(not write or not self.read_only,'This index was opened read-only')
        self._db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        try:
            yield
            self._db.commit()
        except BaseException:
            if self._db.in_transaction: self._db.rollback()
            raise

    def upsert(self,namespace_name,documents):
        namespace(namespace_name)
        rows=[]
        size=0
        ids=set()
        for document in documents:
            require(len(rows)<1000,'A batch may contain at most 1000 documents')
            row=prepare(document,self.dimensions)
            require(row[0] not in ids,'Document IDs must be unique within a batch')
            ids.add(row[0])
            size+=sum(len(value.encode()) if isinstance(value,str) else len(value or b'') for value in row)
            require(size<=MAX_BATCH_BYTES,'Batch exceeds 16 MiB')
            rows.append(row)
        with self._transaction(write=True):
            for document_id,title,body,meta,vector in rows:
                existing=self._db.execute('SELECT rowid FROM harbor_documents WHERE namespace=? AND id=?',
                                          (namespace_name,document_id)).fetchone()
                if existing:
                    rowid=existing[0]
                    self._db.execute('DELETE FROM harbor_fts WHERE rowid=?',(rowid,))
                    self._db.execute('UPDATE harbor_documents SET title=?,text=?,metadata=?,vector=? WHERE rowid=?',
                                     (title,body,meta,vector,rowid))
                else:
                    rowid=self._db.execute('INSERT INTO harbor_documents(namespace,id,title,text,metadata,vector) VALUES(?,?,?,?,?,?)',
                                           (namespace_name,document_id,title,body,meta,vector)).lastrowid
                self._db.execute('INSERT INTO harbor_fts(rowid,title,text) VALUES(?,?,?)',(rowid,title,body))
        return len(rows)

    def delete(self,namespace_name,ids):
        namespace(namespace_name)
        bounded=[]
        for document_id in ids:
            require(len(bounded)<1000,'Delete accepts at most 1000 IDs')
            bounded.append(text(document_id,'Document ID',256))
        count=0
        with self._transaction(write=True):
            for document_id in dict.fromkeys(bounded):
                row=self._db.execute('SELECT rowid FROM harbor_documents WHERE namespace=? AND id=?',
                                     (namespace_name,document_id)).fetchone()
                if row:
                    self._db.execute('DELETE FROM harbor_fts WHERE rowid=?',(row[0],))
                    self._db.execute('DELETE FROM harbor_documents WHERE rowid=?',(row[0],))
                    count+=1
        return count

    def stats(self,namespace_name):
        namespace(namespace_name)
        row=self._db.execute('SELECT COUNT(*) AS documents,COUNT(vector) AS vectors FROM harbor_documents WHERE namespace=?',
                             (namespace_name,)).fetchone()
        return {'namespace':namespace_name,'documents':row['documents'],'vectors':row['vectors'],
                'model':self.model,'dimensions':self.dimensions,'schema_version':1}

    def _fetch(self,namespace_name,ids):
        if not ids: return {}
        placeholders=','.join('?' for _ in ids)
        rows=self._db.execute('SELECT * FROM harbor_documents WHERE namespace=? AND id IN ('+placeholders+')',
                              (namespace_name,*ids))
        return {row['id']:{'id':row['id'],'namespace':row['namespace'],'title':row['title'],
                          'text':row['text'],'metadata':json.loads(row['metadata'])} for row in rows}
