# 2026-09-08 公開情報の追加確認 — 未採用の候補

親単独。D3 public4の同一Kaggle v1がON実行中の待機時間に、公開情報だけを確認した。
実行中のsource/モデル/条件は不変更。新model/環境の導入、画像の外部送信、学習、提出はない。

## FOCUS-3Dによる密な教師データ → 軽量モデルへの蒸留

[コンペ議論738217](https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/discussion/738217)
を認証済みKaggle SDK `competition_list_topic_messages(..., 738217, page_size=-1)`で読んだ。
Web本文の直接openは空だったため、検索要約だけでなくSDKの本文/投稿日/message IDを確認した。

- 2026-09-04のmessage3520752には、FOCUS-3Dを直接提出推論へ使用して時間切れになった報告。
  返信3520759は、密な検出結果を教師にして単純なUNetの点検出器へ蒸留する案を提示する。
- 同日message3520950には、密な重心+Kaggle注釈で学習した
  [cell-point-detector](https://www.kaggle.com/code/hengck23/cell-point-detector)へのリンク。
  6秒/volume/T4という投稿者の報告はあるが、当方でsource・条件・runtime・LBは未検証。
- 2026-09-05の3521418は、密な教師重心とKaggle点注釈の差を別headで学習する案。
- 2026-09-06の3521474は、frame/augmented-frameの密な対応による接続学習を報告。
  一つの動画でdivisionを除いたedge recallの記載であり、公式総合点やhidden LBではない。

これらは投稿者の一次報告/提案であって、当方の実験証拠ではない。画像内の数字は読んでおらず、
良い可視化や投稿者順位から効果を推定しない。隠しtest上での学習など別返信の提案は採用しない。

### 公式公開物を確認した範囲

[FOCUS-3D公式repository](https://github.com/yu-lab-vt/FOCUS-3D)と
[研究室の紹介](https://www.quiclab.org.cn/focus-3d)を実際にopenした。
3D segmentation、事前学習モデル、手動修正/追加学習の経路が公開されている。
コードの[LICENSE](https://github.com/yu-lab-vt/FOCUS-3D/blob/main/LICENSE)はBSD-3-Clause表記。
ただし、**コードのlicenseをcheckpointや全学習データのlicenseへ移植しない**。
READMEで案内されたモデル配布先の本文は今回取得できず、重みのlicense/版/hashは未確定。

[著者preprint](https://www.biorxiv.org/content/10.64898/2026.08.25.746907v1)の検索取得abstractでは
多種の3D蛍光顕微鏡画像向けsegmentationを説明し、2026-08-28公開、CC-BY4.0と表示される。
全文/査読/コンペへの転移は未確認。論文の利用条件もcheckpointの条件と混同しない。

## 親の判断

これはE9〜E13の「同じ確率を再剪定」とは異なる、教師信号を増やす候補である。
一方、dense segmentationの誤りを正解とみなす危険、point annotationとの位置差、
外部データと評価動画の露出、推論時間を別に確認する必要がある。
現D3を途中でこの路線へ交換せず、D3の候補被覆/誤接続分解と合わせて優先順位を判断する。

もし着手する場合の必要確認は、公開checkpointの版/ライセンス/学習データ、teacher生成時間、
固定動画での公式matching recallと点位置誤差/予測数、蒸留studentのtarget時間、
動画分割・train/validation Loss・best/last checkpoint・疎GT ignore条件である。
単に画像の見栄えや学習Loss減少だけで採用せず、公式paired評価と必要な一回の提出へ接続する。
この文書は実験登録/実装開始/新GPU実行の完了記録ではない。

補足: 当日09:39 UTC公開の
[Post-Processing Plateau?](https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/discussion/740103)
は後処理で0.942頭打ちという一件の自己報告だけで、方法や回答は無かった。
現在のgold境界や当方E23の改善幅の根拠には使わない。
