#!/usr/bin/env python3
"""Basit, bağımlılıksız sızıntı taraması (Faz 12) — CI'da çalışır.

Amaç: `.env`, gerçek API anahtarları, veya hardcoded token'ların yanlışlıkla
commit edilmesini yakalamak. Kapsamlı bir secret-scanner (ör. gitleaks/
trufflehog) yerine geçmez — bu, ek bağımlılık kurmadan hızlı bir ilk savunma
hattıdır. Bulgu varsa çıkış kodu 1 ile başarısız olur (CI'ı kırar).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Taranacak, git tarafından izlenen dosyalar (build çıktıları/venv hariç).
_EXCLUDE_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}
_EXCLUDE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".lock", ".db"}

# Bilinen sağlayıcı anahtar formatları + genel "high-entropy" hardcoded atama sezgisi.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Anthropic API anahtarı", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    ("OpenAI API anahtarı", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("AWS Access Key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Genel private key bloğu", re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----")),
    (
        "Hardcoded şifre/anahtar ataması (örnek/placeholder olmayan)",
        re.compile(
            r'(?i)\b(password|passwd|secret|api_key|apikey|access_token)\s*=\s*'
            r'["\'](?!<|\.\.\.|xxx|changeme|your[-_]|example|test|dummy)[^"\']{8,}["\']'
        ),
    ),
]

# Bu betiğin kendi PATTERN tanımları veya .env.example gibi kasıtlı örnekler
# false-positive üretmesin diye tarama dışı bırakılan dosyalar.
_EXCLUDE_FILES = {"scripts/check_secrets.py", ".env.example"}


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout
        return [REPO_ROOT / line for line in out.splitlines() if line]
    except Exception:
        # git yoksa (ör. izole test ortamı) çalışma dizinini tara.
        return [p for p in REPO_ROOT.rglob("*") if p.is_file()]


def scan() -> list[str]:
    findings: list[str] = []
    for path in _tracked_files():
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _EXCLUDE_FILES:
            continue
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in _EXCLUDE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for label, pattern in _PATTERNS:
            for m in pattern.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                findings.append(f"{rel}:{line_no}: {label}")
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("Olası sızıntı bulundu:")
        for f in findings:
            print(f"  - {f}")
        print(f"\n{len(findings)} bulgu. Gerçek bir sırsa hemen döndür/rotate et; "
              "yanlış pozitifse .env.example gibi kasıtlı örnek olduğundan emin ol.")
        return 1
    print("Sızıntı taraması temiz.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
