"""Bounded inputs and stable vector arithmetic."""

import json
import math
import re
import struct
from dataclasses import dataclass, field

MAX_BATCH_BYTES = 16 * 1024 * 1024
MAX_SCAN = 10_000


class HarborError(ValueError):
    """Invalid input, unsupported index or an unsafe operation."""


def require(condition, message):
    if not condition:
        raise HarborError(message)


def integer(value, name, minimum, maximum):
    require(type(value) is int and minimum <= value <= maximum,
            f'{name} must be an integer from {minimum} to {maximum}')
    return value


def text(value, name, maximum, *, empty=False):
    require(isinstance(value,str) and len(value)<=maximum and (empty or value.strip()),
            f'{name} must be bounded text of up to {maximum} characters')
    require(not any(ord(c)<32 and c not in '\n\t' or ord(c)==127 for c in value),
            f'{name} contains unsupported control characters')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise HarborError(f'{name} must be valid UTF-8') from exc
    return value


def namespace(value):
    require(isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',value),
            'Namespace must be a safe identifier of 1 to 128 characters')
    return value


def metadata(value):
    require(type(value) is dict and len(value)<=32,'Metadata must contain at most 32 string pairs')
    result = {}
    for key,item in value.items():
        require(isinstance(key,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',key),
                'Metadata keys must be identifiers of up to 64 characters')
        result[key] = text(item,'Metadata value',1024,empty=True)
    require(len(json.dumps(result,ensure_ascii=False).encode())<=16_384,'Metadata exceeds 16 KiB')
    return result


def positive(value, name):
    require(type(value) in (int,float),f'{name} must be numeric')
    try:
        value=float(value)
    except (OverflowError,ValueError) as exc:
        raise HarborError(f'{name} must be finite') from exc
    require(math.isfinite(value) and 0<value<=1_000_000,f'{name} must be finite and positive, up to one million')
    return value


def unit_vector(vector, dimensions):
    require(isinstance(vector,(list,tuple)) and len(vector)==dimensions,
            'Vector dimension does not match the index')
    values=[]
    for item in vector:
        require(type(item) in (int,float),'Vector elements must be numbers, not booleans')
        try:
            value=float(item)
        except (OverflowError,ValueError) as exc:
            raise HarborError('Vector elements must be finite') from exc
        require(math.isfinite(value),'Vector elements must be finite')
        values.append(value)
    scale=max(map(abs,values))
    require(scale>0,'Zero vectors cannot be searched or indexed')
    scaled=[value/scale for value in values]
    norm=math.sqrt(math.fsum(value*value for value in scaled))
    return tuple(value/norm for value in scaled)


def pack(vector, dimensions):
    return struct.pack(f'<{dimensions}f',*unit_vector(vector,dimensions))


def cosine(unit_query, blob, dimensions):
    require(isinstance(blob,bytes) and len(blob)==4*dimensions,'Stored vector has invalid dimensions')
    values=struct.unpack(f'<{dimensions}f',blob)
    require(all(math.isfinite(value) for value in values),'Stored vector is not finite')
    norm=math.sqrt(math.fsum(value*value for value in values))
    require(norm>0,'Stored vector is zero')
    return max(-1.0,min(1.0,math.fsum(a*b for a,b in zip(unit_query,values))/norm))


@dataclass(frozen=True)
class Document:
    id: str
    text: str = field(repr=False)
    title: str = ''
    metadata: dict = field(default_factory=dict,repr=False)
    vector: list | tuple | None = field(default=None,repr=False)


def prepare(document, dimensions):
    require(isinstance(document,Document),'Upsert expects Document objects')
    document_id=text(document.id,'Document ID',256)
    title=text(document.title,'Title',256,empty=True)
    body=text(document.text,'Document text',65_536)
    require(len(body.encode())<=65_536,'Document text exceeds 64 KiB')
    meta=json.dumps(metadata(document.metadata),sort_keys=True,separators=(',',':'),ensure_ascii=False)
    require(document.vector is None or dimensions is not None,'This index was created without vector support')
    vector=pack(document.vector,dimensions) if document.vector is not None else None
    return document_id,title,body,meta,vector


def words(query):
    text(query,'Query',1024)
    terms=list(dict.fromkeys(re.findall(r'[^\W_]+',query,re.UNICODE)))
    require(1<=len(terms)<=64,'Query must contain 1 to 64 distinct word tokens')
    return ' OR '.join('"'+term+'"' for term in terms)
