# 進行チェックリスト — Biohub Cell Tracking

順序に意味があります。**Day 1 を飛ばすと、Week 1 以降の作業が丸ごと無駄になり得ます。**

| 確定事項（2026-08-24 API 確認） | 値 |
|---|---|
| 提出形式 | **コード提出のみ**（`isKernelsSubmissionsOnly`）。カーネルが hidden test に対して `submission.csv` を書く |
| 提出上限 | **5 件/日**（UTC 00:00 回復） |
| 締切 | 2026-09-29 23:59 UTC（チーム合流・新規参加は **09-22**） |
| 指標 | `adj_edge_jaccard + 0.1 × division_jaccard`（`official/metrics.md`） |
| 評価単位 | 動画。2 系統（`44b6` / `6bba`）で GT の疎さが大きく違う（ローカル 5 本の実測: ノード数比 ≈17 倍、n=5） |
| 公開 test | 4 本＝**ダミー**（train と同一・GT 付き。主催者回答 Discussion #716062）。LB はすべて hidden |
| hidden test | train と重複なし、**規模は train と同程度**（Overview 引用 #734237 ≈ 200 本）。系統比・public/private の内訳は未確認。採点は「ランダムな疎部分集合」 |
| 採点時間 | ノートブック実行の約 50 倍、9〜12 時間の報告あり（#734237）。上限値は未確認 |
| 指標の改訂 | 2026-07-22 に division 指標の exploit をパッチ・全提出を再採点済（#728324, #727154） |

---

## Day 1 — 測定器を検定する（最優先・Issue #2）

- [x] **依存を入れる。** `uv sync --extra dev`（torch なし）。公式メトリクステストが通ることを確認済（102 件）。
- [x] **hidden test の規模を調べる。** Overview 引用（#734237）: train と同規模（≈200 本）。
- [ ] **系統比と public/private の内訳を調べる。** Discussion を MCP で走査（`list_competition_topics` 75 件）。
      公開 test 4 本の値は hidden の値ではない。
- [x] **雑音床を測る。** `scripts/noise_floor_tracking.py` とeval-12で動画単位
      ブートストラップを実施。hidden 199本換算SD 0.0045、LB差<0.005を
      判定不能帯として台帳へ固定（2026-08-24）。
- [ ] **誤差の集中度を確認する。** FN / FP が少数の動画に集中していないか（`6bba` の大きい動画が
      マイクロ平均を支配する構造）。系統別にも出す。
- [ ] **オラクル上界を出す。** GT 自身を提出したときの adjusted Jaccard（N_pred = GT ノード数は
      N_true より小さいので J=1 だが division と疎さの影響を確認）。
      検出のみ完璧・リンクだけ自前、の上界も出す（検出器とリンカのどちらに伸び代があるか）。
- [x] **同一コードを 2 回提出して LB のばらつきを測る。** base1を2回実行し、
      両方0.908。表示3桁未満（<0.001）を再実行ばらつきの観測上限として記録。

> **ゲート**: 狙っている改善幅が雑音床を超えないなら、スコアを追う作業は打ち切る。
> 検出器の置き換え・系統別の扱い・分裂検出など、桁の違う軸に移る。

- [ ] **E23ローカルparityを固定する。** LB 0.924 notebookの全ノード重心補正、
      mid-track親、mutual-NN、t+2 divergence、DeepCenter設定を`src/biohub/public_postproc/`
      へ移植する。notebook内の独自division proxyは採用せず、各armをCSV化して
      `src/biohub/evaluate.py`から公式metricを直呼びする。node/edge/丸め後座標、
      telemetry、per-video公式countsがE23経路と一致するまで性能実験を開始しない。

---

## Week 1 — 土台を作る

- [ ] **公開ノートブックの実力を自分で測り直す。** 表示スコアを信用しない。対象:
      `yusuketogashi/clean-approach-lightweight-local-cv-no-hack`（clean 0.908 と自称）、
      `thibautgoldsborough/unet-baseline-inference-submission`（公式 UNet）、
      `pilkwang/biohub-cell-tracking-data-model-eda-baseline`（rule-based）。
      **「metric hack」を含む NB は系譜から外す**（負の t、体積外座標、クリップ跨ぎ、人工ハブ）。
- [ ] **ローカル検証を動画単位・系統層化で作る。** 行単位やフレーム単位の分割は同一動画が
      train と検証にまたがる。fixed-8（各系統 4 本）のような固定セットを決めて台帳に書く。
- [ ] **事前学習済み資産の有無を確認する。** 公開 NB が添付する weights（例: `pilkwang/biohub-tracking-support-pack-*`）
      は train の一部を学習済み。**その weights を使う限り、学習に使った動画は検証に使えない**。
      split を確認し、未接触の動画だけで測る。
- [ ] **カーネルの実行時間を測る。** hidden ≈ 200 本。1 動画あたりの秒数 × 200 を台帳に書き、
      実行時間上限（**未確認**。Rules/Code Requirements ページで確認して台帳に書く）と比べる。
- [ ] **提出 CSV のバリデーションを固定する。** `scripts/local_eval.py` が raise する条件
      （列・重複 node_id・dangling edge）に加え、edge t→t+1・体積内座標を submitter の検査項目として守る。

---

## 実験のたびに

- [ ] **Issue を起票してから着手する。** ブランチ `feat/issueN-slug`。
- [ ] **判定規則を結果が届く前に台帳へ書く。** 「score Δ ≥ 雑音床 かつ 両系統で符号一致」のように数値で。
- [ ] **対照アームを用意する。** 閾値を下げるなら上げる腕も出す。片方向だけでは「効いた」と
      「測定器が壊れている」を区別できない。
- [ ] **変更が発火しているかを 1 動画で先に確かめる。** 設定を変えても出力が変わらない前科あり。
- [ ] **per-dataset を見る。** マイクロ平均だけで判断しない。系統別に符号を確認する。
- [ ] **ノード数を監視する。** adjusted J のペナルティ α=0.1 は N_pred に線形。検出を増やす施策は
      J の改善とペナルティ増の差し引きで評価する。
- [ ] **雑音床以下の差を「改善」と書かない。**
- [ ] **長い掃引は逐次保存する。** 1 アームごとに `outputs/<issueN>/<arm>.json`。

---

## 終盤 2 週間

- [ ] **チーム判断は 09-22 まで。** 合流するなら merger deadline 前に。
- [ ] **提出枠の消費計画。** 5 件/日。コード提出の採点は hidden 全量を走らせるため時間がかかる。
      締切前日までに実験を終える。
- [ ] **最終候補の系統（ファミリー）平均を出す。** 単発の最良ドローで選ばない。
- [ ] **2 枠は「平均 − ヘッジ」で選ぶ。** ヘッジは別ファミリー（検出器が違う / リンカが違う）で脱相関。
      雑音床を超える差がない候補同士なら、どれを選んでも同じと認める。
- [ ] **ランタイム超過を確認する。** 採点が `error` になった提出は無得点。

---

## 締切当日

- [ ] **朝イチで枠を使い切る。**
- [ ] **最終選択を Web UI で明示的に行う。** 自動選択（public 最良 2 件）に任せない。
      public/private が hidden をどう分けているかは未確認。
- [ ] **選択を API で読み戻して検証する。** `uv run python scripts/submission_status.py --final-check <ref1> <ref2>`
- [ ] **`error_description` が空か確認する。**

---

## 終了後

- [ ] **public と private の関係を測る。** 自分の全提出で相関を出す。
- [ ] **撤回すべき結論を台帳の「撤回した結論」に書く。**
- [ ] **再利用できる教訓を `templates-private` へ戻す**（実失敗 + 機序 + 実データ検証があるものだけ）。
