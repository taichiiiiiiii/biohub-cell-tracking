# E27採点実行環境の別版修正（Issue #9）

2026-09-13。旧analysis/e27_prior_scoring_design.mdを科学的契約として継承する。
仮説、既知12動画、baseline selected_only、recorded_prior値、公式metric、距離7、
seed0、数値gate、24GTへの停止条件、予算、非提出flagを変更しない。
前回生成v2は退役記録40b28539…により永久未採点・再利用禁止。旧scorer/契約/PLAN/
生成/採点失敗成果物は既存pathのbytesを保存する。

## 変更の範囲

旧Qwen実装をscripts/e27_prior_score_v2.pyへ版分けし、差分を以下に限定する。
PLAN schemaをE27_EVAL12_PLAN_V2へ変更し、子起動moduleも新pathへ固定する。
candidate_idは同じ科学仮説E27_RECORDED_PRIOR_V1を保持し、実行ID/出力は新規とする。
source bindingsに新scorer、本契約、旧科学契約、環境helper、環境設定元3依存sourceと
同梱libtccを含める。生成source closureと公式source全件は従来どおり照合する。
既存planのpath/hashを書き換えて再利用しない。全検証後に新しいPLAN/PREGENを作成し、
新規candidateを再生成する。旧候補をコピー・移動して新規生成と見せない。

## 環境の由来と値

起動時はe26_screen.generation_environmentの厳密allowlistとfresh/noTorch検査を維持。
CUDA_VISIBLE_DEVICESの空文字はGPU無効化の既定値であり、勝手に削除/置換しない。
依存import後はscripts/e27_score_environment_v2.verify_import_environmentを使用する。
起動時全キー/値を保持した上で、次の追加のみ値の完全一致を許す。

- threadpoolctl.py: KMP_DUPLICATE_LIB_OK = True
- polars/__init__.py: _RJEM_MALLOC_CONF = dirty_decay_ms:500,muzzy_decay_ms:1000
- blosc2/__init__.py: ME_DSL_JIT_LIBTCC_PATH = canonical ROOT以下の
  .venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib（絶対path）

上記3sourceファイルとlibtccのpath/bytes/SHAをPLAN.score_sourcesへ追加し、既存の
採点前後source全照合で検証する。observed環境から期待値やpathを採取しない。
helperは純粋な完全一致検査であり、単体では依存由来を証明しない。
未知追加、既存キーの欠落/変更、既知追加の値違い、起動時の既知追加混入を拒否。
環境を書き換えて一致させることはしない。

SCORE_STARTED_V2にはenvironmentとして元の起動allowlistを記録し、別field
import_environment_additionsで検証済みの3項目を記録する。親は旧schemaを拒否し、
起動env一致に加えてこの追加fieldを同じhelper/固定pathで照合する。
CORE/RESULTの数値/由来検証、失敗出力保存と成功sealの隔離は変更しない。

## 実行前の受入条件

新旧scorer差分が上記のみに限定されること、旧ファイルhash不変、関連lifecycle/
監督テストの新module向け再利用、追加値改変を親が拒否するテストを要求する。
新規プロセスで、実際のverify_plan/対照verify_generationによる入力照合と
公式scorerのimportまで実行して環境検査成功を確認する。GT意味読取・採点はこの
事前検証では行わない。依存3件だけの合成importテスト成功をこの代わりにしない。
新しい環境境界差分とテスト証拠をMAXで1回評価し、親が採否を決めてから
新規事前登録/直列生成/known12採点へ進む。科学的改善は公式比較結果で判定する。
