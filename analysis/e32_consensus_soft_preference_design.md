# E32: consensus soft preference

## 仮説

E31 の hard reservation は primary consensus 辺を Hungarian 割当から先に除外するため、
幾何・速度・他候補との競合を十分に比較できない。E31 と同じ consensus 情報を、既存の
assignment cost に対する soft preference として扱えば、誤予約を減らし known12 の追跡
score を改善できる可能性がある。

## 固定条件

- E29/E30/E31、baseline の挙動は変更しない。
- 新しい閾値・学習・追加GT・データ取得は行わない。
- 固定 known12 CV、CPU serial、既存のリーク・receipt・再現性・提出形式 gate を使用する。
- consensus 辺への優先度は既存 `MOTION_RELINK_LEARNED_BONUS` の範囲だけを使い、後調整しない。

## 採否基準

baseline 比 paired mean `>= +0.005` を満たし、全ての既存 gate に合格した場合のみ候補化する。
それ以外は不採用として台帳に失敗理由を記録し、Kaggle提出は行わない。

## 停止条件

E32 が有効な非改善なら連続非改善は 6/8。根拠の薄い派生variantは作らず、残り2回を
構造的に独立した仮説へ限定する。
