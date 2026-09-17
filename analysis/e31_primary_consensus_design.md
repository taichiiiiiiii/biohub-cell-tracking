# E31 事前設計 — primary-only reciprocal consensus

更新日: 2026-09-13 (Asia/Tokyo)

## 仮説（1つ）

E29の3方向一致はknown12で`+0.0021092`だったが、E30でlogit符号を追加すると`+0.0015425`
へ悪化した。したがってE30の符号条件は採用せず、E31は **primary forward と primary reverse
の2方向だけが同一のunique argmaxを示す候補を予約**する。secondaryモデルの一致要求を外す
ことで、primaryモデルが正しく支持する辺の取りこぼしを減らせるかを検証する。

## 固定条件

- E29と同じ raw/filtered edge、degree=1、連続時刻、6um tight gate、競合排除、残差motion。
- secondary logitsの値・順位・符号はE31の選別に使用しない。
- E27 prior/E28 appearance/E30 positive filter/追加GT/閾値探索は使用しない。
- E27/E28/E29/E30経路は変更しない。E31専用receipt/schema/candidate IDを記録。

## 採否基準

固定known12 paired meanがベースラインを`>=+0.005`上回り、リーク・追跡・再現・CPU・形式・
binding gateを全て通過した場合のみ提出候補へ昇格。それ以外は非改善として台帳に記録し、
Kaggle提出は行わない（明示承認が必要）。
