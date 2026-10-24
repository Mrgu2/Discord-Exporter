#!/usr/bin/env python3
"""Check reachable Git history and pending source for privacy risks.

Use with `gitleaks git --log-opts=--all --redact` and manual prose review.
Only categories and locations are printed; matching content is never printed.
"""
import re
import subprocess
from pathlib import Path, PurePosixPath

PATTERNS = {
    'personal home path': re.compile(r'/(?:Users|home|homes)/(?!example(?:/|\b)|username(?:/|\b)|你的名字/|用户名/)[^/\s`\'"<>]+/'.encode()),
    'real Discord channel link': re.compile(rb'discord\.com/channels/\d{17,20}/'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
}
DOC_PATTERNS = {
    'private artifact identifier': re.compile(rb'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I),
    'content fingerprint in prose': re.compile(rb'\b[0-9a-f]{64}\b', re.I),
    'personal device record': re.compile(rb'\b(?:iPhone\s+\d{2}|iOS\s+\d{2}\.\d)'),
}
PRIVATE_ROOTS = {'data', 'output', 'artifacts', 'dist', '.local', '.runtime', '.venv', 'node_modules', '.ssh'}
PRIVATE_SUFFIXES = {'.db', '.pem', '.key', '.p12', '.pfx', '.bundle', '.tar', '.zip', '.7z', '.dmg', '.exe', '.crx', '.mobileprovision'}


def git(*args, cwd=None):
    return subprocess.check_output(['git', *args], cwd=cwd)


def inspect_file(path, content):
    findings = set()
    parts = PurePosixPath(path).parts
    name = parts[-1]
    if (parts[0] in PRIVATE_ROOTS or any(p.startswith('.env') for p in parts)
            or PurePosixPath(path).suffix.lower() in PRIVATE_SUFFIXES
            or re.search(r'\.(?:sqlite3?|db)(?:-.*)?$', name)
            or name in {'credentials.json', 'access-code.txt', 'id_rsa', 'id_ed25519', 'known_hosts', 'Cookies', 'Login Data', 'Local State'}
            or name.startswith(('config.local.', 'settings.local.'))):
        findings.add(('private/generated file', path))
    if b'\0' in content:
        findings.add(('binary file requires privacy review', path))
    patterns = {**PATTERNS, **(DOC_PATTERNS if path.endswith('.md') else {})}
    for category, pattern in patterns.items():
        if pattern.search(content):
            findings.add((category, path))
    return findings


def inspect_repository(root):
    root = Path(root)
    findings = set()
    commits = git('rev-list', '--all', cwd=root).decode().splitlines()
    for commit in commits:
        metadata = git('show', '-s', '--format=%ae%n%ce', commit, cwd=root).decode().splitlines()
        if any(not email.endswith('@users.noreply.github.com') for email in metadata):
            findings.add(('private commit email', commit[:12]))
    # Enumerate every tree, since rev-list --objects may report a reused blob
    # under only one path, concealing a private name in another snapshot.
    files = set()
    for commit in commits:
        for row in git('ls-tree', '-rz', commit, cwd=root).split(b'\0'):
            if not row:
                continue
            info, raw_path = row.split(b'\t', 1)
            mode, kind, sha = info.split()
            path = raw_path.decode('utf-8', 'replace')
            if mode in {b'120000', b'160000'}:
                findings.add(('link or submodule requires privacy review', path))
            if kind == b'blob':
                files.add((sha.decode(), path))
    cache = {}
    for sha, path in files:
        if sha not in cache:
            cache[sha] = git('cat-file', 'blob', sha, cwd=root)
        findings.update(inspect_file(path, cache[sha]))
    # Also check the index (including staged-only content) and untracked files.
    for row in git('ls-files', '--stage', '-z', cwd=root).split(b'\0'):
        if not row:
            continue
        info, raw_path = row.split(b'\t', 1)
        mode, sha, stage = info.split()
        path = raw_path.decode('utf-8', 'replace')
        if mode in {b'120000', b'160000'}:
            findings.add(('link or submodule requires privacy review', path))
        else:
            findings.update(inspect_file(path, git('cat-file', 'blob', sha.decode(), cwd=root)))
    paths = git('ls-files', '--cached', '--others', '--exclude-standard', '-z', cwd=root).split(b'\0')
    for raw_path in paths:
        if raw_path:
            path = raw_path.decode('utf-8', 'replace')
            source = root / path
            if source.is_symlink():
                findings.add(('link or submodule requires privacy review', path))
            elif source.is_file():
                findings.update(inspect_file(path, source.read_bytes()))
    return findings, len(commits), len(cache)


def main():
    findings, commits, blobs = inspect_repository(Path.cwd())
    for category, location in sorted(findings):
        print(f'{category}: {location}')
    print(f'{commits} commits, {blobs} unique blobs, {len(findings)} privacy findings')
    return bool(findings)


if __name__ == '__main__':
    raise SystemExit(main())
