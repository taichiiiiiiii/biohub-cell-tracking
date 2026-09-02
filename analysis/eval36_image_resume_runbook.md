# eval-36 train Zarr 再開・検証 runbook

## 境界と合格条件

これは eval-36 の **train image Zarr だけ**を再開し、固定済みの
[`data/manifest.csv`](../data/manifest.csv) と照合する fail-closed 手順である。現在の
部分ツリーは **evaluation-ready ではない**。最終ゲートがすべて PASS
するまで予測、採点、結果解釈に使わない。

この手順は Kaggle kernel の push/run、competition submission、Git push、commit、
データの削除・改名を許可しない。実行する外部操作は competition files の
読み取りと選択ファイルの download だけである。

完了の必要条件は次の同時成立とする。

- 期待 stem 集合が以下の 36 件と完全一致する。
- 36 root それぞれが manifest 上の 102 files（100 chunks + 2 `zarr.json`）を
  ちょうど含む。全体は 3,672 files / 15,932,872,938 bytes である。
- 不足、余分、サイズ不一致、symlink、`.kaggle-partial` が全て 0 である。
- 各 root の Zarr metadata が JSON として parse でき、期待ツリー検査が PASS する。

## 期待データセットと根拠

正の stem 集合は E22 v11 完了ログ
[`outputs/kaggle/e22_bidir030_eval36_reference/biohub-eval-train-raw.log`](../outputs/kaggle/e22_bidir030_eval36_reference/biohub-eval-train-raw.log)
の `VALIDATOR: selected 36` 行と、完全な 36 raw GEFF roots の stem 集合の一致で固定する。
後者の provenance は
[`DOWNLOAD_MANIFEST.json`](../outputs/kaggle/e22_bidir030_eval36_reference/DOWNLOAD_MANIFEST.json)
にある（raw GEFF: 36 roots / 1,188 files / 10,090,215 bytes）。画像のファイル名と
期待 byte size の source of truth は `data/manifest.csv`（24,886 rows,
1,187,624 bytes, SHA-256
`6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4`）である。
manifest はこの hash に一致しなければ中止し、この手順内で再生成しない。

```text
44b6_12dfb391  44b6_267148e4  44b6_2a2eff9f  44b6_341df25f
44b6_587a1e22  44b6_5f15d135  44b6_706092f0  44b6_74d0c52e
44b6_7a302da0  44b6_996155de  44b6_9be80b04  44b6_a21120c2
44b6_aaf8b0ea  44b6_c50204e0  44b6_c8e2a523  44b6_d2f34f90
44b6_d5e7d891  44b6_d754aa59  6bba_062c8d37  6bba_07e24132
6bba_085bf656  6bba_09961292  6bba_0e7c0d07  6bba_12665c0e
6bba_1d0d8384  6bba_207c6aaf  6bba_20852818  6bba_2312ac41
6bba_268e1230  6bba_2819ca14  6bba_32db13fc  6bba_337b1b3a
6bba_3abfe10a  6bba_3c5691b6  6bba_3db54e20  6bba_3fda6b25
```

## 現在の部分 snapshot

読み取り実測時刻: **2026-08-30 19:32:01 JST**
（2026-08-30T10:32:01Z）。大きな chunk は hash せず、パス・サイズだけを
manifest と照合した。

| 状態 | 実測 |
|---|---:|
| 期待 | 36 roots / 3,672 files / 15,932,872,938 bytes |
| 現存 | 5 non-empty roots / 434 files / 1,917,200,117 bytes |
| manifest とサイズ一致 | 432 files / 1,917,200,047 bytes |
| 完全 root | 4 / 36 |
| 不足 | 3,239 manifest files |
| サイズ不一致 | 1 file |
| manifest 外 | 1 file |
| 残り期待 payload | 14,015,672,891 bytes |

完全 root は `44b6_12dfb391`, `44b6_267148e4`, `44b6_2a2eff9f`,
`44b6_341df25f` の 4 件。`44b6_587a1e22` は partial で、24 件/
102,124,994 bytes だけが manifest と一致する。同 root には次の不完全状態がある。

```text
data/train/44b6_587a1e22.zarr/0/c/30/0/0/0
  have 0 bytes; want 4,345,297 bytes
data/train/44b6_587a1e22.zarr/0/c/30/0/0/0.kaggle-partial
  manifest 外; 70 bytes
```

これらは削除せず、既存の
[`scripts/download_data.py`](../scripts/download_data.py) に同じ論理パスを再取得させる。
完全な 4 roots は size-match により `skip` される。

2026-08-30 19:39 JST の再試行では competition-files preflight は一度 PASS
したが、最初の不足 file 取得時に `api.kaggle.com` の `NameResolutionError` が
再発した。`[1400/4942] ok=0 skip=988 fail=412` で手動停止し、単一 file probe
でも同じ DNS failure を確認した。新規取得成功は 0 件であり、上の部分
snapshot は evaluation-ready ではないまま変わらない。

### 2026-08-31 resume progress and rate-limit hold

2026-08-31 01:44 JST の再監査では、manifest SHA/行数、Kaggle CLI 2.2.4、
competition-files の認証/DNS preflight、固定 36 stems の dry-run
`4942 files, 17.84 GB selected` を再確認してから `--jobs 1` で再開した。
途中の不足 chunk を単一 CLI で取得できることも確認し、部分 tree は次まで
前進した。

| 状態 | 実測 |
|---|---:|
| 現存 | 7 non-empty roots / 669 files / 3,080,791,311 bytes |
| manifest とサイズ一致 | 669 files / 3,080,791,311 bytes |
| 完全 root | 6 / 36 |
| 不足 | 3,003 manifest files |
| サイズ不一致 / manifest 外 / partial marker | 0 / 0 / 0 |

完全 root は `44b6_12dfb391`, `44b6_267148e4`, `44b6_2a2eff9f`,
`44b6_341df25f`, `44b6_587a1e22`, `44b6_5f15d135`。現在の partial root
`44b6_706092f0` は 57/102 files がすべてサイズ一致している。

次の不足 file
`train/44b6_706092f0.zarr/0/c/60/0/0/0`（期待 5,509,026 bytes）の
単一-file probe は HTTP `429 Too Many Requests` を明示して終了した。全 download
process を停止し、tree に破損や `.kaggle-partial` がないことを確認済みである。
これは DNS/auth failure ではなく Kaggle competition-download API の rate limit
として分類する。cooldown 中は再試行を連打せず、次回は fresh preflight から同一
36-stem/one-job command を再開する。最終 verifier が PASS するまで引き続き
**NOT_READY** である。

### 2026-09-01 safe-stop snapshot

21 時間超の cooldown 後、manifest/CLI/help/disk gate と単一の
competition-files preflight が PASS し、固定 36 stems の dry-run が再び
`4942 files, 17.84 GB selected` と一致したため、同じ `--jobs 1` command を
再開した。TTY session `76864` の最後の進捗行は
`[2300/4942] ok=266 skip=2034 fail=0` だった。その後、Kaggle child がなく
tree 増分もない状態が 5 分を超えたため fail-closed に interrupt し、session は
exit 1 で終了した。終了後は downloader/Kaggle child とも 0 process である。
この resume 中の同型 stall は 1 回、先行 run を含む通算では 2 回である。

safe-stop 後の path/size 再監査は次のとおりであり、引き続き **NOT_READY** である。

| 状態 | 実測 |
|---|---:|
| 現存かつ manifest とサイズ一致 | 15 complete roots / 1,544 files / 7,292,313,882 bytes |
| 不足 | 2,128 files / 8,640,559,056 bytes |
| manifest 外 / サイズ不一致 / `.kaggle-partial` | 0 / 0 / 0 |

最後の complete root は `44b6_c8e2a523`。現在の partial root
`44b6_d2f34f90` は 14 files / 67,010,346 bytes がすべて manifest と
サイズ一致し、88 files が不足している。次の manifest-order missing file は
`train/44b6_d2f34f90.zarr/0/c/21/0/0/0`（期待 4,915,073 bytes）である。

次回も本 runbook の固定 `EVAL36` と同一 `--jobs 1 --fail-fast` command から再開する。
開始前に downloader/Kaggle child が 0 process であることを確認し、重複 process
を決して起動しない。script 自身も `data/.download_data.lock` の advisory lock を
non-blocking で取得し、別 downloader が所有中なら download 前に
`FAIL class=lock` で拒否する。既存の manifest-size exact files は script に skip
させる。

### 2026-09-02 HTTP 429 safe-stop snapshot

同一の `--jobs 1 --fail-fast` resume session は、次の不足 file
`train/6bba_09961292.zarr/0/c/48/0/0/0` の取得で HTTP `429 Too Many Requests` を受け、
`FAIL class=rate-limit` として fail-closed に停止した。session の終了コードは 1、
最後の進捗行は
`[3162/4942] ok=767 skip=2394 fail=1 cancel=0`、`not-started=1780` だった。
停止後の `pgrep` では downloader/Kaggle child はともに 0 process である。

停止後に exact final verifier を実行した結果は次のとおり。21/36 roots が complete、
現在の partial root `6bba_09961292` は 59 files 不足、残り 14 roots はそれぞれ
102 files 不足であり、合計不足数 `59 + 14 * 102 = 1,487` と一致する。失敗 file は
書き込まれておらず、次の manifest-order missing も引き続き
`train/6bba_09961292.zarr/0/c/48/0/0/0` である。

| 状態 | 実測 |
|---|---:|
| 期待 | 3,672 files / 15,932,872,938 bytes |
| manifest とパス・サイズ一致 | 2,185 files / 10,001,935,157 bytes |
| 完全 root | 21 / 36 |
| 不足 | 1,487 files / 5,930,937,781 bytes |
| mismatch / extra / symlink | 0 / 0 / 0 |
| `.kaggle-partial` / staging / ready | 0 / 0 / 0 |

したがって状態は引き続き **NOT_READY** である。429 停止直後の即時再試行は行わず、
十分な cooldown を置く。再開するときだけ、下記の既存 preflight を正確に再実行し、
すべて PASS した後に固定 `EVAL36` の同一 `--jobs 1 --fail-fast` command を使う。
単一 file probe を含む追加 request も cooldown 中は送らない。

## 実行前 preflight

以下は repo root で実行する。認証情報の値を印字する `env`, `cat`,
`kaggle config view`, shell trace (`set -x`) は使わない。

```zsh
cd '/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking'

test "$(shasum -a 256 data/manifest.csv | awk '{print $1}')" = \
  6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4
test "$(wc -l < data/manifest.csv | tr -d ' ')" = 24887

test -x .venv/bin/python
test -x .venv/bin/kaggle
test "$(.venv/bin/kaggle --version 2>&1)" = 'Kaggle CLI 2.2.4'
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/download_data.py --help >/dev/null
```

認証と DNS を同時に読み取り preflight する（トークンを出力しない）。
この 1 リクエストが PASS するまで download を始めない。

```zsh
.venv/bin/kaggle competitions files biohub-cell-tracking-during-development \
  --page-size 1 >/dev/null
```

空き容量は「残り 14,015,672,891 bytes + 2 GiB staging/headroom」以上、
すなわち **16,163,156,539 bytes 以上**を必須とする。snapshot 時の
available は 391,369,170,944 bytes で PASS だったが、実行直前に再評価する。

```zsh
python3 - <<'PY'
import shutil
from pathlib import Path
required = 14_015_672_891 + 2 * 1024**3
free = shutil.disk_usage(Path('data/train')).free
print(f'free={free} required={required}')
raise SystemExit(0 if free >= required else 1)
PY
```

## 再開コマンド

まず同一選択の dry-run を実行する。期待値は、既存 test/GT も選択する
script の仕様上 `4942 files, 17.84 GB selected` である。train image 部分の
完了条件は別途、36 roots / 3,672 files / 15,932,872,938 bytes である。

```zsh
EVAL36=(
  44b6_12dfb391 44b6_267148e4 44b6_2a2eff9f 44b6_341df25f
  44b6_587a1e22 44b6_5f15d135 44b6_706092f0 44b6_74d0c52e
  44b6_7a302da0 44b6_996155de 44b6_9be80b04 44b6_a21120c2
  44b6_aaf8b0ea 44b6_c50204e0 44b6_c8e2a523 44b6_d2f34f90
  44b6_d5e7d891 44b6_d754aa59 6bba_062c8d37 6bba_07e24132
  6bba_085bf656 6bba_09961292 6bba_0e7c0d07 6bba_12665c0e
  6bba_1d0d8384 6bba_207c6aaf 6bba_20852818 6bba_2312ac41
  6bba_268e1230 6bba_2819ca14 6bba_32db13fc 6bba_337b1b3a
  6bba_3abfe10a 6bba_3c5691b6 6bba_3db54e20 6bba_3fda6b25
)
test "${#EVAL36[@]}" = 36
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/download_data.py --train "${EVAL36[@]}" \
  --jobs 1 --fail-fast --dry-run
```

dry-run が一致したら、同じコマンドから `--dry-run` だけを外す。
`--jobs 1` は障害の切り分け、rate-limit 回避、再開ログの可読性を優先した
保守的な値である。中断後も同じコマンドをそのまま再実行する。

```zsh
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/download_data.py --train "${EVAL36[@]}" \
  --jobs 1 --fail-fast
```

script は manifest と同サイズの既存 **regular file** だけを `skip` し、
不足/サイズ不一致を
`kaggle competitions download -f ... --force` で取り直す。`--jobs 1` は executor を
作らない逐次実行である。`--jobs N`（N > 1）でも投入済み task は最大 N 件で、
全選択を先に executor queue へ積まない。eval-36 再開では `--fail-fast` を必須とし、
最初の FAIL 後は新しい file を開始しない。

各 download の開始時に `START path=... attempt=... deadline=...`、30 秒以上続く間は
`HEARTBEAT path=... elapsed=... deadline_in=...` が flush される。5 分の hard
timeout では Kaggle CLI の process group 全体を TERM、5 秒 grace 後も残れば KILL
し、timeout だけ最大 2 attempts とする。HTTP 429 は retry/backoff せず
`FAIL class=rate-limit` として `--fail-fast` の有無にかかわらず run 全体を止める。
DNS/auth/403/ENOSPC/unknown も同一 file で retry せず分類して FAIL する。
`KeyboardInterrupt` は現在 path を表示し、未開始 queue を cancel して稼働中 process
group を停止する。終了コードは 130 である。

target symlink は同サイズでも skip せず、成功時には regular file へ置換する。
一方、`data` から target parent までの既存 ancestor に symlink があれば、symlink を
follow せず `FAIL class=integrity` で download 前に止める。

CLI の出力先は target の親に作る一意な `.kaggle-staging` directory である。manifest
size 一致を確認した payload を同じ親の一意な `.kaggle-ready` file へ移し、staging
cleanup が成功した後だけ ready を target へ `os.replace` する。この順序により失敗、
timeout、interrupt、cleanup failure では再開前の target bytes または target symlink
を変更しない。cleanup は `FileNotFoundError` だけを許容する。それ以外は path 付きの
`FAIL class=cleanup`（interrupt 中は `CLEANUP FAIL`）として必ず表示し、残留 staging
を黙って success 扱いしない。表示された staging/ready path は証跡として記録し、
原因を解消するまで再開しない。

## 失敗の切り分け

| 分類 | 代表的な観測 | 対処 |
|---|---|---|
| DNS/network | `FAIL class=dns`, `NameResolutionError`, `Temporary failure in name resolution`, `Could not resolve host` | ローカルツリーを触らず中止。DNS/network 復旧後に preflight から再開。 |
| 認証 | HTTP `401`, `Unauthorized`, missing/invalid/expired credentials | secret をログに出さず Kaggle CLI で再認証。preflight PASS 後に再開。 |
| アクセス | HTTP `403`, `Forbidden`, competition rules acceptance required | browser 上の参加/規約同意の有無を確認。トークン再発行と混同しない。 |
| quota/rate | `FAIL class=rate-limit`, HTTP `429`, `Too Many Requests` | run は即時停止する。追加 request を送らず十分な cooldown 後に preflight から同一コマンドを再開。GPU quota とは無関係。 |
| hard timeout | `TIMEOUT ... stopping process group`, `FAIL class=timeout after 2 attempts` | process group が残っていないことを確認し、network/CLI 状態を調べて preflight から再開。 |
| local disk | `No space left on device`, `ENOSPC`, free-space gate FAIL | この runbook では他データを削除しない。容量確保の別途承認を取る。 |
| path safety | `FAIL class=integrity: symlink ancestor path=...` | symlink を follow せず中止する。この runbook 内ではリンクを削除・置換しない。意図した data tree か別途確認する。 |
| cleanup | `FAIL class=cleanup ... staging path=...`, `CLEANUP FAIL ...` | target は旧状態のまま。残留 path と元の failure/interrupt の両方を記録し、権限・filesystem 状態を直してから再開する。silent success とみなさない。 |
| integrity | CLI rc=0 後の `FAIL size mismatch`、zero-byte target、`.kaggle-partial`、最終 verifier の missing/extra/mismatch | evaluation-ready とせず同一コマンドを再実行。繰り返す場合はその path と expected/have size を保存して中止。 |

## ファイル単位の integrity policy

1. `data/manifest.csv` 自体は上記 SHA-256 で pin する。
2. 3,672 画像 files は、正確な relative path と manifest byte size を全件検査する。
3. competition manifest に per-file checksum がないため、ローカル SHA-256 のみで
   upstream 正本性を証明できない。したがって大きな 3,600 chunks の全量 hash は
   定常検証では行わない。後日、Kaggle から正の checksum が得られた場合のみ
   それと比較する。
4. 72 個の `zarr.json` は小さいため JSON parse し、必要なら完了後の
   provenance 用 SHA-256 を記録してよい。ただし upstream hash の代わりにはしない。
5. size が一致しても Zarr 読み取り中に codec/checksum エラーが出た root は
   integrity FAIL とする。実 eval 開始前に、別途、全 36 root の実データ読み取り
   smoke を実行する。

## 最終 36-root / manifest / tree verifier

次は読み取り専用。不一致を一つでも検出したら exit 1 にする。

```zsh
python3 - <<'PY'
from pathlib import Path
import csv
import hashlib
import json

root = Path.cwd()
data = root / 'data'
manifest = data / 'manifest.csv'
expected_manifest_sha = '6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4'
if hashlib.sha256(manifest.read_bytes()).hexdigest() != expected_manifest_sha:
    raise SystemExit('FAIL: manifest SHA-256 drift')

raw = root / 'outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0'
expected_stems = sorted(p.stem for p in raw.glob('*.geff'))
if len(expected_stems) != 36 or len(set(expected_stems)) != 36:
    raise SystemExit(f'FAIL: expected-stem source has {len(expected_stems)} roots')

with manifest.open(newline='') as handle:
    manifest_rows = {row['name']: int(row['size']) for row in csv.DictReader(handle)}

problems = []
total_files = 0
total_bytes = 0
complete = []
for stem in expected_stems:
    prefix = f'train/{stem}.zarr/'
    expected = {name: size for name, size in manifest_rows.items() if name.startswith(prefix)}
    tree = data / 'train' / f'{stem}.zarr'
    actual = {}
    if tree.exists():
        for path in tree.rglob('*'):
            if path.is_symlink():
                problems.append(f'symlink: {path}')
            elif path.is_file():
                actual[path.relative_to(data).as_posix()] = path.stat().st_size
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatch = sorted(name for name in set(expected) & set(actual)
                      if expected[name] != actual[name])
    if len(expected) != 102:
        problems.append(f'{stem}: manifest files={len(expected)}, want=102')
    if missing or extra or mismatch:
        problems.append(
            f'{stem}: missing={len(missing)} extra={len(extra)} mismatch={len(mismatch)}'
        )
    else:
        complete.append(stem)
        for metadata in (tree / 'zarr.json', tree / '0/zarr.json'):
            try:
                json.loads(metadata.read_text())
            except Exception as error:
                problems.append(f'{metadata}: invalid JSON: {error}')
    total_files += len(expected)
    total_bytes += sum(expected.values())

actual_roots = {p.stem for p in (data / 'train').glob('*.zarr')}
unexpected_roots = sorted(actual_roots - set(expected_stems))
partial_markers = sorted((data / 'train').rglob('*.kaggle-partial'))
if unexpected_roots:
    problems.append(f'unexpected train Zarr roots: {unexpected_roots}')
if partial_markers:
    problems.append(f'partial markers: {[str(p) for p in partial_markers]}')
if total_files != 3672 or total_bytes != 15_932_872_938:
    problems.append(f'aggregate drift: files={total_files} bytes={total_bytes}')
if len(complete) != 36:
    problems.append(f'complete roots={len(complete)}, want=36')

if problems:
    print('\n'.join(f'FAIL: {item}' for item in problems))
    raise SystemExit(1)
print('PASS: 36 roots; 3,672 exact manifest files; 15,932,872,938 bytes; metadata JSON valid')
PY
```

`unexpected train Zarr roots` は eval-36 外の正当なローカルデータでも fail させる。
これは削除指示ではない。eval 用 tree を独立パスに分離する別計画を承認後に
立てるか、verifier の root-set 条件を「期待 36 の不足なし」に緩和した事実を
明記する。現在は eval-36 外 train Zarr root は観測されていない。

## 完了後の境界

最終 verifier が PASS しても、それが証明するのは「固定 manifest に対する
画像 tree の完全性」だけである。予測 GEFF、GT GEFF、モデル重み、後処理
parity、公式 metric の正しさは別ゲートである。本 runbook の完了から
submission、kernel push/run、Git push/commit への暗黙の許可は発生しない。

残留する外部 blocker は **十分な cooldown 後に Kaggle API に到達でき、現行認証と
competition access/rate quota が有効な環境で、残り 5,930,937,781 bytes を取得すること**
である。2026-09-02 snapshot 時点でこれは未解消であり、状態は **NOT_READY** である。
