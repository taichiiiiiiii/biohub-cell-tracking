# E30 事前設計 — positive-logit reciprocal consensus

更新日: 2026-09-13 (Asia/Tokyo)

## 仮説（1つ）

E29 は reciprocal consensus の一対一候補を約18万件予約し、known12 score を
`+0.0021092146` 改善したが、採否閾値 `+0.005` に届かなかった。E29 の候補は
unique argmax だけで、logit の符号（モデルが負例より明確に支持したか）を使っていない。
E30 は **3つの固定済みlogit（primary forward / primary reverse / secondary forward）が
すべて正の候補だけ**を予約し、符号が不確かな候補は従来の残差 motion assignment に戻す。
これは閾値探索ではなく、既存logitの固定0境界による単一の構造条件である。

## 固定条件と非目的

- E29 と同じ raw/filtered edge、degree=1、連続時刻、tight gate、競合排除。
- E27 prior、E28 appearance、追加モデル、追加GT、閾値チューニングは使わない。
- E23 incumbent の byte、CPU 1 thread、1800秒/8GiB child、256MiB出力制限を維持。
- 既存E27/E28/None経路は変更しない。E30専用receiptに採用候補数と除外数を記録する。

## 採否基準（実行前固定）

known12 paired mean が E23/E27 baseline より `>= +0.005`、かつ全てのリーク・追跡・
再現・形式・CPU・binding gate を通過した場合のみ候補昇格する。それ以外は非改善として台帳に
記録し、Kaggle提出しない。実提出はユーザーの明示承認が必要。

## 次の実装単位

E29 loader の packet 読み取り時に3 logitsの値を保持する純粋なconfidence filterを追加し、
既存ID mapping/予約関数に渡す。Flashで実装し、2回失敗または複数module/private-score影響が
ある場合はMaxへ読み取り評価を1回依頼してから親が適用する。合成テストで正負混在・全負・tie・
入力不変性を確認し、通過後に新規runnnerをserial実行する。
