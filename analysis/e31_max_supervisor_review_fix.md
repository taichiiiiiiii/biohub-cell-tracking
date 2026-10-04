Issue17 QwenCloud Max authoring no tools. Return ONLY three exact snippets. Parent independent review actual run_workers found cleanup/identity gaps; reproducibility seed explicit. No science threshold/model changes.
A add immediately after env=os.environ.copy(): set env['PYTHONHASHSEED']='0' for both childprocesses before interpreter spawn. This is explicit reproducibility change recorded byparent; v2 exact output parity must still be checked.
B replace existing finally body below with two-phase cleanup: FIRST loop allprocs, poll and send SIGTERM to every live processgroup (guard ProcessLookupError), THEN loop allprocs and p.wait(timeout=30), if TimeoutExpired signalgroup SIGKILL guard and wait(timeout=30). No unboundedwait. Waiting alreadyexitedprocesses immediate okay. Do not defer sibling signal while waitingfirst. Keep indentation (finally at8spaces).
        finally:
            for p in procs:
                if p.poll() is None:
                    try:
                        os.killpg(p.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        p.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(p.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        p.wait(timeout=30)
C after ExitStack complete, BEFORE receipt=merge_shards(...), rehash each relative path in hashes with _stream_sha256(payloadroot/rel) comparing expected and raise ValueError ifchanged. Existing hashes dictionary and safe relativepaths verified beforestart. No neednewhelper. This binds observed immutablepayload at both boundaries; don't merely copy E31_HASHES again.
