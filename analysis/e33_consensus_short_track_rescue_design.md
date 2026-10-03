# E33: consensus-proven short-track rescue

## 仮説

baseline の最小track長6による一律short-track除去が、実際の5-node線形成分を失わせている。
全4辺が既存3方向 reciprocal consensusで証明される、forkなし・時刻連続の5-node鎖だけを
除去前に救済すれば、node recallを上げつつ誤リンクを増やさずscoreを改善できる。

## 固定条件と対象

- E29の3方向consensus証明集合をread-onlyで再利用する。
- 長さはexact 5、全4辺が証明集合、forkなし、時刻連続、synthetic/gap辺なしに固定。
- associationの辺選択、閾値、bonus、学習、追加GT、データ取得は変更しない。
- 証明集合が空、または条件を1つでも満たさない場合はbaselineと同じ除去。

## 採否基準

固定known12で baseline 比 paired mean `>= +0.005`、median `>= 0`、worst動画が既存gate内、
node/edge/division、リーク、追跡、再現、CPU、形式、receipt/bindingを全て通過した場合のみ採用。
救済0件は科学的無効として非改善カウント対象外。基準未達はE33=7/8として棄却し、追加GT・提出なし。
