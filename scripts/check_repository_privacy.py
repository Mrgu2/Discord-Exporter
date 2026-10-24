#!/usr/bin/env python3
"""Check every reachable commit for private paths, Discord links, and data files.

Run alongside `gitleaks git --log-opts=--all --redact`; neither check proves that
arbitrary private prose is absent. Prints locations/categories, never matches.
"""
import re
import subprocess
from pathlib import PurePosixPath


def git(*args):
    return subprocess.check_output(['git', *args])


def main():
    findings = set()
    patterns = {
        'personal home path': re.compile(r'/(?:Users|home)/(?!example(?:/|\b)|username(?:/|\b)|你的名字/|用户名/)[^/\s`\'"<>]+/'.encode()),
        'real Discord channel link': re.compile(rb'discord\.com/channels/\d{17,20}/'),
        'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    }
    commits = git('rev-list', '--all').decode().splitlines()
    for commit in commits:
        metadata = git('show', '-s', '--format=%ae%n%ce', commit).decode().splitlines()
        if any(not email.endswith('@users.noreply.github.com') for email in metadata):
            findings.add(('private commit email', commit[:12]))
    objects = git('rev-list', '--objects', '--all').splitlines()
    blobs = 0
    for row in objects:
        sha, _, raw_path = row.partition(b' ')
        if not raw_path or git('cat-file', '-t', sha.decode()).strip() != b'blob':
            continue
        blobs += 1
        path = raw_path.decode('utf-8', 'replace')
        parts = PurePosixPath(path).parts
        if (parts[0] in {'data', 'output', 'artifacts', 'dist', '.local', '.runtime', '.venv', 'node_modules'}
                or any(p.startswith('.env') for p in parts)
                or PurePosixPath(path).suffix in {'.sqlite', '.sqlite3', '.db', '.pem', '.key', '.p12', '.pfx'}):
            findings.add(('private/generated file', path))
        content = git('cat-file', 'blob', sha.decode())
        for category, pattern in patterns.items():
            if pattern.search(content):
                findings.add((category, path))
    for category, location in sorted(findings):
        print(f'{category}: {location}')
    print(f'{len(commits)} commits, {blobs} blobs, {len(findings)} privacy findings')
    return bool(findings)


if __name__ == '__main__':
    raise SystemExit(main())
