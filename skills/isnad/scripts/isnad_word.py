"""Yönlendirici (shim): kanonik betik `isnad-word/scripts/isnad_word.py`'dir.

Bu dosya yalnızca çağrıyı kanonik betiğe devreder; tüm geliştirmeler orada yapılır.
v1 yedeği: `isnad_word.v1.bak`.
"""
import os
import runpy
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
CANON = os.path.normpath(os.path.join(_HERE, "..", "..", "isnad-word", "scripts",
                                       "isnad_word.py"))

if not os.path.isfile(CANON):
    sys.stderr.write("Kanonik betik bulunamadı: {}\n".format(CANON))
    raise SystemExit(2)

sys.argv[0] = CANON
runpy.run_path(CANON, run_name="__main__")
