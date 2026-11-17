#!/usr/bin/env python3
"""Opt-in, private development memory; source files remain authoritative."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time
import state

KINDS = {'architecture', 'decision', 'requirement', 'component', 'interface', 'test', 'experiment', 'handoff'}
RELATIONS = {'depends_on', 'implements', 'verifies', 'constrains', 'supersedes'}

def directory(root):
    root = Path(root).resolve()
    target = root / '.project-master/private/development'
    if any(p.is_symlink() for p in [target, target.parent, target.parent.parent]):
        raise ValueError('memory directories cannot be symlinks')
    return target
def db_path(root): return directory(root) / 'index.sqlite3'
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def tokens(value): return math.ceil(len(json.dumps(value, ensure_ascii=False)) / 3)

def safe_path(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('relative project path required')
    if any(p.is_symlink() for p in [path, *path.parents] if p != root and root in p.parents):
        raise ValueError('symlinks are not memory sources')
    if not path.resolve().is_relative_to(root): raise ValueError('path escapes project')
    if any(p in {'.git', '.env'} or p.startswith('.env.') for p in Path(relative).parts):
        raise ValueError('sensitive source rejected')
    return path

def load(root):
    data = json.loads((directory(root) / 'registry.json').read_text())
    if data.get('schema') != 1: raise ValueError('unsupported development memory schema')
    return data

@contextmanager
def transaction(root):
    lock = directory(root) / 'write.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        data = load(root)
        yield data
        data['revision'] += 1
        state.atomic_write(directory(root) / 'registry.json', json.dumps(data, ensure_ascii=False, indent=2))
    finally:
        lock.unlink()

def enable(root, apply=False):
    root = Path(root).resolve()
    if not (root / '.project-master').is_dir(): raise ValueError('initialize Project Master first')
    target = directory(root)
    if target.exists(): return {'status': 'already_enabled', 'path': str(target)}
    plan = {'status': 'plan', 'create': str(target), 'existing_schema': 'unchanged', 'backup': 'private/development-backups'}
    if not apply: return plan
    private = root / '.project-master/private'
    if private.is_symlink(): raise ValueError('private directory cannot be a symlink')
    private.mkdir(mode=0o700, exist_ok=True)
    backup = private / 'development-backups' / str(time.time_ns())
    backup.mkdir(parents=True, mode=0o700)
    for name in ('STATE.yaml', 'CURRENT_STATE.md'):
        src = root / '.project-master' / name
        if src.is_file(): shutil.copy2(src, backup / name)
    target.mkdir(mode=0o700)
    state.atomic_write(target / 'registry.json', json.dumps({'schema': 1, 'revision': 1, 'sources': {}, 'edges': []}))
    return dict(plan, status='enabled', backup=str(backup))

def register(root, identifier, path, kind, summary):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', identifier): raise ValueError('invalid source ID')
    if kind not in KINDS or not summary.strip(): raise ValueError('kind and meaningful summary required')
    source = safe_path(root, path)
    if not source.is_file() or source.stat().st_size > 1024 * 1024: raise ValueError('source must be a text file <= 1 MiB')
    source.read_text(encoding='utf-8')
    with transaction(root) as data:
        previous = data['sources'].get(identifier, {})
        if previous.get('status') == 'archived': raise ValueError('restore archived source explicitly first')
        data['sources'][identifier] = dict(previous, path=path, kind=kind, summary=summary, hash=digest(source), status='active')

def close(root, identifier, outcome):
    if outcome not in {'failed', 'rejected', 'successful'}: raise ValueError('invalid outcome')
    with transaction(root) as data:
        item = data['sources'][identifier]
        if item['kind'] != 'experiment': raise ValueError('only experiments have experiment lifecycle')
        item['outcome'] = outcome
        item['closed'] = True

def archive(root, identifier, lesson):
    if not lesson.strip(): raise ValueError('negative lesson required')
    with transaction(root) as data:
        item = data['sources'][identifier]
        if item['kind'] != 'experiment' or not item.get('closed') or item.get('outcome') not in {'failed', 'rejected'}:
            raise ValueError('only explicitly closed failed/rejected experiments may be archived')
        if any(e['evidence'] == item['path'] and data['sources'][e['source']]['status'] == 'active' and e['source'] != identifier for e in data['edges']):
            raise ValueError('experiment evidence is referenced by an active graph source')
        item.update(status='archived', lesson=lesson)

def restore(root, identifier):
    with transaction(root) as data: data['sources'][identifier]['status'] = 'active'

def link(root, source, target, relation, evidence):
    path = safe_path(root, evidence)
    if not path.is_file() or relation not in RELATIONS: raise ValueError('relation and existing evidence required')
    with transaction(root) as data:
        if source not in data['sources'] or target not in data['sources']: raise ValueError('unknown graph node')
        edge = {'source': source, 'target': target, 'relation': relation, 'evidence': evidence, 'hash': digest(path)}
        if source == target: raise ValueError('self links are not allowed')
        if edge not in data['edges']: data['edges'].append(edge)
        if relation == 'supersedes':
            data['sources'][target].update(status='superseded', superseded_by=source)

def fresh(root, item):
    try: return digest(safe_path(root, item['path'])) == item['hash']
    except (OSError, ValueError): return False

def neighbors(root, identifier, limit=12):
    data = load(root)
    return [e for e in data['edges'] if identifier in (e['source'], e['target']) and all(data['sources'][node]['status'] == 'active' and fresh(root, data['sources'][node]) for node in (e['source'], e['target'])) and fresh(root, {'path': e['evidence'], 'hash': e['hash']})][:max(0, min(limit, 50))]

def git_snapshot(root):
    def run(*args):
        p = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None
    diff = run('diff', 'HEAD', '--binary')
    untracked = run('ls-files', '--others', '--exclude-standard', '-z')
    untracked_hashes = {}
    for name in (untracked or '').split('\0'):
        if not name or name.startswith('.project-master/'): continue
        try:
            path = safe_path(root, name)
            if path.is_file(): untracked_hashes[name] = digest(path)
        except (OSError, ValueError): untracked_hashes[name] = 'unavailable'
    return {'head': run('rev-parse', 'HEAD'), 'branch': run('symbolic-ref', '--short', '-q', 'HEAD'),
            'dirty': run('status', '--porcelain', '--untracked-files=normal'),
            'untracked_hashes': untracked_hashes,
            'diff_hash': hashlib.sha256(diff.encode()).hexdigest() if diff is not None else None}

def revisions(root):
    result = {}
    for rel in ('.project-master/STATE.yaml', '.project-master/private/MISSION.json'):
        p = safe_path(root, rel)
        result[rel] = digest(p) if p.exists() else None
    return result

def checkpoint(root):
    with transaction(root) as data:
        before = revisions(root)
        result = {'sources': {k: v['hash'] for k, v in data['sources'].items()}, 'git': git_snapshot(root), 'revisions': before, 'created_at': time.time()}
        if before != revisions(root): raise ValueError('concurrent STATE/MISSION update; retry checkpoint')
        data['checkpoint'] = result
    return result

def context(root, core, budget=3000):
    if budget < 1: raise ValueError('budget must be positive')
    data = load(root)
    result = {'core': core, 'summaries': [], 'lessons': [], 'stale': [], 'omitted': [], 'token_count_kind': 'estimate_chars_div_3', 'budget': budget}
    cp = data.get('checkpoint')
    if cp:
        result['workspace_changed'] = cp['git'] != git_snapshot(root)
        result['source_store_changed'] = cp['revisions'] != revisions(root)
    else: result['checkpoint_missing'] = True
    for identifier, item in data['sources'].items():
        if not fresh(root, item): result['stale'].append(identifier)
        if item.get('lesson'): result['lessons'].append({'id': identifier, 'lesson': item['lesson']})
    # Mandatory core and negative lessons never silently disappear to meet a budget.
    for identifier, item in data['sources'].items():
        if item['status'] != 'active' or identifier in result['stale']: continue
        summary = {'id': identifier, 'kind': item['kind'], 'summary': item['summary'], 'source': item['path']}
        result['summaries'].append(summary)
        if tokens(result) > budget and item['kind'] not in {'architecture', 'decision', 'handoff'}:
            result['summaries'].pop(); result['omitted'].append(identifier)
    result['estimated_tokens'] = 0
    result['budget_exceeded'] = False
    for _ in range(3):
        result['estimated_tokens'] = tokens(result)
        result['budget_exceeded'] = result['estimated_tokens'] > budget
    return result

def chunks(text):
    # Stable bounded paragraphs; oversized paragraphs split deterministically.
    for paragraph in text.split('\n\n'):
        for start in range(0, len(paragraph), 1600):
            part = paragraph[start:start + 1600].strip()
            if part: yield part

def index(root, semantic=False):
    data = load(root)
    from local_embeddings import embed, identity
    model = identity() if semantic else None
    path = db_path(root)
    try:
        conn = sqlite3.connect(path)
        conn.execute('PRAGMA quick_check').fetchall()
    except sqlite3.DatabaseError:
        try: conn.close()
        except Exception: pass
        path.rename(path.with_name('corrupt-' + str(time.time_ns()) + '.sqlite3'))
        conn = sqlite3.connect(path)
    updated = 0
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS chunks (id TEXT, ordinal INTEGER, hash TEXT, text TEXT, model TEXT, vector TEXT, PRIMARY KEY(id, ordinal))')
        conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(id UNINDEXED, ordinal UNINDEXED, text)')
        for identifier, item in data['sources'].items():
            if not fresh(root, item):
                conn.execute('DELETE FROM chunks WHERE id=?', (identifier,)); continue
            old = conn.execute('SELECT hash, model FROM chunks WHERE id=? LIMIT 1', (identifier,)).fetchone()
            if old and old[0] == item['hash'] and (not semantic or old[1] == model): continue
            parts = list(chunks(safe_path(root, item['path']).read_text()))
            cached = {hashlib.sha256(text.encode()).hexdigest(): json.loads(vector) for text, stored_model, vector in conn.execute('SELECT text, model, vector FROM chunks WHERE id=?', (identifier,)) if vector and stored_model == model}
            vectors = [None] * len(parts)
            if semantic:
                missing = [i for i, part in enumerate(parts) if hashlib.sha256(part.encode()).hexdigest() not in cached]
                generated = embed([parts[i] for i in missing]) if missing else []
                for i, vector in zip(missing, generated): vectors[i] = vector
                for i, part in enumerate(parts):
                    if vectors[i] is None: vectors[i] = cached[hashlib.sha256(part.encode()).hexdigest()]
            conn.execute('DELETE FROM chunks WHERE id=?', (identifier,))
            conn.executemany('INSERT INTO chunks VALUES (?,?,?,?,?,?)', [(identifier, i, item['hash'], part, model, json.dumps(v) if v is not None else None) for i, (part, v) in enumerate(zip(parts, vectors))])
            updated += 1
        if data['revision'] != load(root)['revision']: raise ValueError('registry changed during index; retry')
        conn.execute('DELETE FROM search_fts')
        conn.execute('INSERT INTO search_fts SELECT id, ordinal, text FROM chunks')
        conn.commit()
    finally: conn.close()
    return {'updated_sources': updated, 'semantic': semantic, 'model': model}

def search(root, query, limit=5, include_archive=False, semantic=False):
    if not query.strip(): raise ValueError('query is empty')
    limit = max(1, min(limit, 20))
    data = load(root)
    eligible = {k: v for k, v in data['sources'].items() if fresh(root, v) and (include_archive or v['status'] == 'active')}
    rows, mode, warning = [], 'text', None
    try:
        with sqlite3.connect(f'file:{db_path(root)}?mode=ro', uri=True) as conn:
            if semantic:
                rows = conn.execute('SELECT id, ordinal, hash, text, model, vector FROM chunks').fetchall()
            else:
                terms = re.findall(r'\w+', query)
                expression = ' OR '.join('"' + word + '"' for word in terms)
                rows = conn.execute('SELECT c.id,c.ordinal,c.hash,c.text,c.model,c.vector FROM chunks c JOIN search_fts f ON c.id=f.id AND c.ordinal=f.ordinal WHERE search_fts MATCH ?', (expression,)).fetchall() if expression else []
    except sqlite3.Error:
        mode, warning = 'files', 'index unavailable; rebuild with index'
        for k, item in eligible.items(): rows += [(k, i, item['hash'], p, None, None) for i, p in enumerate(chunks(safe_path(root, item['path']).read_text()))]
    words = set(re.findall(r'\w+', query.lower()))
    query_vector = None
    if semantic:
        try:
            from local_embeddings import embed, identity
            query_vector = embed([query])[0]; mode = 'hybrid'
        except (ImportError, RuntimeError, OSError, ValueError) as exc:
            warning = 'local embeddings unavailable; using text search'
    results = []
    for identifier, ordinal, source_hash, text, model, vector in rows:
        if identifier not in eligible or source_hash != eligible[identifier]['hash']: continue
        score = len(words & set(re.findall(r'\w+', text.lower()))) / max(1, len(words))
        if query_vector is not None and vector and model == identity():
            from local_embeddings import cosine
            score += max(0, cosine(query_vector, json.loads(vector)))
        if score > 0:
            results.append({'id': identifier, 'chunk': ordinal, 'source': eligible[identifier]['path'], 'status': eligible[identifier]['status'], 'hash': source_hash, 'text': text, 'score': round(score, 5)})
    results.sort(key=lambda r: (-r['score'], r['id'], r['chunk']))
    return {'mode': mode, 'warning': warning, 'results': results[:limit], 'omitted': max(0, len(results)-limit)}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    sub = p.add_subparsers(dest='command', required=True)
    e = sub.add_parser('enable'); e.add_argument('--apply', action='store_true')
    r = sub.add_parser('register'); r.add_argument('id'); r.add_argument('path'); r.add_argument('--kind', choices=sorted(KINDS), required=True); r.add_argument('--summary', required=True)
    c = sub.add_parser('close'); c.add_argument('id'); c.add_argument('--outcome', required=True)
    a = sub.add_parser('archive'); a.add_argument('id'); a.add_argument('--lesson', required=True)
    r = sub.add_parser('restore'); r.add_argument('id')
    l = sub.add_parser('link'); l.add_argument('source'); l.add_argument('target'); l.add_argument('relation'); l.add_argument('--evidence', required=True)
    n = sub.add_parser('neighbors'); n.add_argument('id'); n.add_argument('--limit', type=int, default=12)
    sub.add_parser('checkpoint')
    i = sub.add_parser('index'); i.add_argument('--semantic', action='store_true')
    s = sub.add_parser('search'); s.add_argument('query'); s.add_argument('--limit', type=int, default=5); s.add_argument('--include-archive', action='store_true'); s.add_argument('--semantic', action='store_true')
    a = p.parse_args(); root = a.root.resolve()
    try:
        if a.command == 'enable': result = enable(root, a.apply)
        elif a.command == 'register': result = register(root, a.id, a.path, a.kind, a.summary)
        elif a.command == 'close': result = close(root, a.id, a.outcome)
        elif a.command == 'archive': result = archive(root, a.id, a.lesson)
        elif a.command == 'restore': result = restore(root, a.id)
        elif a.command == 'link': result = link(root, a.source, a.target, a.relation, a.evidence)
        elif a.command == 'neighbors': result = neighbors(root, a.id, a.limit)
        elif a.command == 'checkpoint': result = checkpoint(root)
        elif a.command == 'index': result = index(root, a.semantic)
        else: result = search(root, a.query, a.limit, a.include_archive, a.semantic)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (ValueError, OSError, KeyError, sqlite3.Error, ImportError, RuntimeError) as exc:
        print(f'ERROR: {exc}'); return 2

if __name__ == '__main__': raise SystemExit(main())
