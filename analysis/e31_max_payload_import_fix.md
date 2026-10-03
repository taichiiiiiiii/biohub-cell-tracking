Issue17 QwenCloud Max authoring no tools. Independent review found parent Notebook sys.path precedence wrong. Return minimal diff ONLY scripts/prepare_e31_submission.py in setup_src string literal. Current exact lines:
        "sys.path.insert(0, str(payloadroot / 'src'))\n"
        "os.chdir(REPO_DIR)\n"
        "sys.path.insert(0, str(REPO_DIR))\n"
        "sys.path.insert(0, str(REPO_DIR / 'src'))\n"
        "sys.path.insert(0, str(REPO_DIR / 'scripts'))\n"
Change: move payloadroot/src insertion to AFTER all REPO_DIR insertions, so hash-verified payload has highestprecedence. Just before this finalpayloadinsert, guard if any name=='biohub' or startswith 'biohub.' in sys.modules: raise RuntimeError('biohub imported before hashed payload setup'). Do not delete/reload cached modules silently. This guards staleimports and fails before GPUspawn; original baseline setup included cells have no biohub imports. Preserve rest of builder/outputschema/science. Provide correctly escaped newline in string literals. No other code.
