"""Capture a recoverable source snapshot and hashes without changing old evidence."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from datetime import datetime, timezone


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def capture(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite baseline: {output}')
    git = lambda *args: subprocess.check_output(['git', *args], cwd=root)
    names = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')
    dirty = git('diff', '--name-only', '-z').decode().split('\0')
    source_suffixes = {'.py', '.md', '.json', '.toml', '.lock', '.yaml', '.yml', '.ini', '.cfg', '.s2k', '.html', '.js', '.css', '.sh', '.txt'}
    protected = [root/'initial_imperfection_material/results/full_tower_cyclic', root/'initial_imperfection_material/results/convergence_diagnosis']
    files = []
    for name in sorted(set(names)):
        path = root/name
        if not name or not path.is_file() or path.is_symlink():
            continue
        parts = path.relative_to(root).parts
        if any(part in {'.git', '.venv', '__pycache__', '.pytest_cache'} for part in parts):
            continue
        generated = 'results' in parts or 'static' in parts
        if (not generated and path.suffix.lower() in source_suffixes) or name in dirty or path.name in {'.gitignore', 'Dockerfile'}:
            files.append(path)
    output.mkdir(parents=True, exist_ok=False)
    archive = output/'source_snapshot.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for path in files:
            tar.add(path, arcname=path.relative_to(root), recursive=False)
    source_inventory = [{'path':str(p.relative_to(root)), 'size_bytes':p.stat().st_size, 'sha256':digest(p)} for p in files]
    evidence_inventory = [{'path':str(p.relative_to(root)), 'size_bytes':p.stat().st_size, 'sha256':digest(p)} for directory in protected for p in sorted(directory.rglob('*')) if p.is_file()]
    import openseespy.opensees as ops
    payload = {
        'schema':'otw2.source_snapshot.v1', 'created_at':datetime.now(timezone.utc).isoformat(),
        'root':str(root), 'branch':git('branch', '--show-current').decode().strip(),
        'head':git('rev-parse', 'HEAD').decode().strip(), 'git_status':git('status','--short').decode(),
        'python':sys.version, 'executable':sys.executable, 'engine_version':ops.version(),
        'package_version':importlib.metadata.version('openseespy'),
        'archive':archive.name, 'archive_sha256':digest(archive), 'source_files':source_inventory,
        'protected_evidence':evidence_inventory,
        'coverage':'Tracked/untracked non-generated source and configuration plus modified tracked files; ignored files and environments excluded. Protected old evidence remains in place and is fully hashed, not archived.',
    }
    (output/'baseline_inventory.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
    return payload


def verify(root: Path, inventory: Path) -> dict:
    data=json.loads(inventory.read_text(encoding='utf-8'))
    changed=[]
    shared_memory_changes=[]
    for item in data['protected_evidence']:
        path=root/item['path']
        if not path.is_file() or digest(path)!=item['sha256']:
            # SQLite read locks/read marks live in SHM and can change under a
            # read-only client. WAL is NOT excluded: it can contain durable data.
            if path.name.endswith('.sqlite-shm'):
                shared_memory_changes.append(item['path'])
            else:
                changed.append(item['path'])
    archive=inventory.parent/data['archive']
    archive_valid=archive.is_file() and digest(archive)==data['archive_sha256']
    return {'protected_count':len(data['protected_evidence']), 'changed':changed,
            'sqlite_read_lock_shared_memory_changes':shared_memory_changes,
            'wal_files_checked_as_durable_evidence':True,
            'archive_valid':archive_valid, 'passed':not changed and archive_valid}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--output',type=Path)
    parser.add_argument('--verify',type=Path)
    args=parser.parse_args()
    if args.verify:
        report=verify(args.root,args.verify)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        if not report['passed']:
            raise SystemExit(1)
    elif args.output:
        result=capture(args.root,args.output)
        print(json.dumps({'source_files':len(result['source_files']), 'protected_files':len(result['protected_evidence']), 'engine':result['engine_version'], 'archive_sha256':result['archive_sha256']},indent=2))
    else:
        parser.error('Supply --output or --verify')


if __name__=='__main__':
    main()
