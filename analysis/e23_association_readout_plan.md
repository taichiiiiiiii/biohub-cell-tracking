# D3取得後の読み出し方針

2026-09-08。親単独。公開4 parity v1（kernelId133543583）の結果待ちに、
既往実験の失敗と次の情報要求を照合した。結果取得・精度改善・学習開始を意味しない。
実Kaggleの実行/停止条件は[e23_association_target_parity.md](e23_association_target_parity.md)を維持する。

## 既往との違いを先に確認する

- E9/E9-bはtop5にない候補を0へ置き、座標grid取り違えもあった。今回は完全matrixと
  実detector ID/座標写像を保存する。未計算pairはignoreであり、確率0や負例ではない。
- E11はfused確率/同target marginの剪定で、最良ΔJは約+0.0013/+0.0014だった。
  seed別logit/特徴も同じ上流モデル由来であり、保存しただけで独立情報とは呼ばない。
  fused確率だけの対照に対して追加の識別力があるかを、動画を跨ぐ予測で比較する必要がある。
- E12の3frame加速度はTP/FP medianが1.62/1.68µm、組合せ最良ΔJ約+0.0003。
  既存加速度の閾値調整を新仮説として再開しない。
- E13の候補拡張/ILP offset・division cost変更は最良約+0.0009、division TP/FP/FN不変。
  同じfused確率の候補集合・目的関数を再掃引するだけの計画へ置き換えない。

以上は旧経路/旧データの実測であり、同種手法が原理的に不可能という証明ではない。
今回の入口はE23の既露出eval12診断で338 FN中205が両端対応済み接続なしだった事実。
選択前matrixがない現在は、その205件を閾値/ILP/後処理のいずれが生んだか未分離である。

## parity結果の扱い

1. version受付・RUNNING・合成tests成功から、実OFF/ON一致を推定しない。
2. terminal時は全4動画×returned/pre/postの12記録、E23座標/保存raw参照、入力/source/
   重み/deps/RNG、ON全pairとgraph写像、時間/RSS/容量を確認する。
3. ERRORなら最初の失敗stageと実際に残った入力/出力を保存する。OFF失敗時にON未起動を
   確認し、予測差と計測器・環境の欠陥を区別する。条件を緩めてPASSにしない。
4. PASSでも公開4はin-sampleの計測器確認のみ。次に全36収集の固定入力/予算を別判断し、
   終了manifestだけでなく実array/graphと参照の対応を確認する。

## 全36収集後に必要な原因分解と学習の前提

- 既露出12本だけで、detector全nodeと選択前graphの公式matchingを別に記録し、
  旧最終CSVのmatchingをID一致だけで移植しない。ILPや後処理でnode集合/座標が変わる。
- 各GT edgeを、両端候補不在・全dense内に存在・既定0.48閾値後候補・ILP選択・
  最終出力の段階へ追跡する。新rawと旧rawに差がある場合はまず経路差として分ける。
  最終CSVだけのD2分類をこのstage因果へ自動変換しない。
- 学習labelは公式GT edgeの正例、疎GTで矛盾が確定する負例、未対応/未注釈ignoreを区別。
  娘2つを持つ正しい親を負例化せず、targetの親選択とdivision判定を分離する。
- targetごとの親選択をfused-only対照と比較する。候補密度/距離/確率分布だけで分離して
  見えないよう、動画単位の分割と系統別結果、正解候補被覆、変更動画数、worstを保存する。
  seed別特徴の追加効果が未確認なら新学習モデルを採用しない。
- 上流checkpointの学習露出と既往探索を確認し、既露出12/36を独立holdoutとは呼ばない。
  学習を設計する時点でtrain/validation Loss、有限値、best/last checkpoint、データ件数、
  学習停止と採否の数値gateを別に固定する。この文書だけではlabel生成/学習を起動しない。

E17外部rankerのsource/asset HOLD、E26不採用、E23 incumbent0.924は維持する。
新しい科学候補の公式評価と必要な提出を目指すが、この情報取得診断自体は提出しない。
