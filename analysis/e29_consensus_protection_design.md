# E29: 相互一致する上流一対一辺のmotion保護

2026-09-13、Issue #15。親の事前設計案。独立評価/実装/実候補評価は未完了。
canonical、codex/issue-15-e29-consensus-protection。既存WIPとE28の凍結成果物を保全。

## 仮説と根拠

E23では上流辺が弱い加算bonusとしてmotionの一対一再割当に渡される。E26の全廃は
正解損失を伴い不採用。E27未選択priorとE28外観penaltyは固定eval12のpaired meanが
それぞれ約+0.0000922/+0.0000389で棄却。これらだけで信号の改善上限は推定しない。
新仮説: 上流の既存一対一辺のうち、primary順方向・primary逆方向・secondary順方向が
同じ対応を第一候補とする場合だけmotionで予約し、残りへ従来assignmentを適用すると、
強く支持される対応の幾何的な置換を減らし、固定CVを改善する。
全motion停止、bonus/距離閾値再調整、E28係数探索とは別の構造的介入。

## 保存情報の意味と保護条件（値/GTを集計する前）

packetはsource×target。primary_reverse_logitsは既にこの向きへtranspose済み。
secondary reverseは保存されていないので、四方向一致とは呼ばない。
各W2 packetの全detector候補で次を要求する。raw部分集合へ絞ってから順位を変えない。

- target j列でprimary_forward_logitsの一意最大sourceがi。
- 同じtarget j列でsecondary_forward_logitsの一意最大sourceがi。
- source i行でprimary_reverse_logitsの一意最大targetがj。

値のtieは保護しない。argmaxは各モデル・方向内のみで、seed横断logit比較/平均なし。
raw probabilityに新閾値を加えず、GTで係数やconfidenceを選ばない。絶対的信頼度や
calibrationを保証する条件ではない。logit軸の実推論sourceとの一致を実装前に照合する。

保護できるのは、元raw→現在nodeへの時刻/座標/IDの確定対応があるt→t+1辺で、
既存distance filter通過後の辺集合に実在し、元raw辺集合とdistance filter後集合の両方で
source outdegree1・target indegree1（片側armが距離filterで消えた既知分裂も予約不可）。
既存分裂の片側を強制予約しない。motion入口のrefined座標によるraw距離が既存tight gate
以内であることも必須。gate外・endpoint消失は保護しない。新しい辺やnodeを追加しない。
保護集合はsource/target競合なしを検証する。不正ID/方向/非有限/入力欠損は技術失敗。

## 一つだけ変える実装動作

各tのtight assignment前に保護対を予約し、そのsource/targetを未割当集合から除外。
残りは既存tight→relaxedのcost/順序/Hungarianをそのまま使用する。
予約辺にも現行raw/motion距離とselected probabilityを計算して記録し、同じ時点で
predecessor_positionを更新する。速度履歴の数式は変更しないが、予約に伴う履歴変化は
介入の下流効果として含む。appearance=None、E27追加priorなし。その他後処理・検出は不変更。
None指定は新引数すら渡さない旧経路とし、空の保護集合も基準と同値にする。
新学習・モデルpass・候補半径拡張・division規則変更はしない。

## 最小接続と受入

既存read_packetとdetector/raw写像・input binderを再利用し、一動画/一packetずつ処理。
新しい汎用runnerは作らず、既存生成/採点経路へE29識別を明示追加する。
APIの具体的署名と変更前source保全は実装単位で固定する。旧source/PLANは改変しない。
receiptに方向/順位条件/全packet bindings/予約候補IDと実予約・除外理由を残す。
単体条件: 各方向不一致、tie、軸違い、raw対応違い、分裂、gate外、競合、None/空同値、
予約と残余assignmentの一対一性、速度/telemetry、旧E27/E28不変。
None対照を新sourceでbyte再現後、同source・入力・予算の候補を直列生成する。

## 科学的採否と停止

E23を対照、CPU/seed0/threads1/動画順固定。known12生成の事前予算は1800秒、
child self peak RSS8GiB、親子出力256MiB。追加モデルpassなし、hidden実測保証ではない。
既存公式metric、max_distance7、eval12→24→36と全既定gateを変更しない。
eval12 paired mean>=+0.005を含むAND gate不合格なら追加24GTを開かず棄却。
接続TP/FP/FNとdivisionを分離し、node調整項だけで機序成功とは言わない。
既知12/36は露出済み診断集合であり独立holdoutではない。採用にはGoalの全リーク/追跡/
再現/CPU/形式/来歴と必要MAX評価が必要。Kaggle実行・提出は別途登録と全条件を満たす時のみ。
現在提出0/5、非改善2/8。予約対象ゼロは介入なしで科学的成功としない。
固定条件の単回検証とし、失敗後にconfidenceや距離を探索しない。

## packet→raw ID対応の先行契約

次のpure adapterはconsensus_edges.map_consensus_to_raw(pairs, source_detector_indices,
target_detector_indices, graph_to_detector, raw_node_ids)。pairsは全detector行列から既存helperが
得たindex対であり、raw部分集合でargmaxを再計算しない。source/target_indicesはread_packet
検証済みのglobal detector index列。graph_to_detectorはdetector_lookupの検証済み一対一写像。
adapter自身もbuiltin int、非負・重複なし・範囲内・index集合の非交差・raw IDの写像存在を
検証する。pairsは昇順・一対一とし、行/列範囲外は失敗。写像に欠けるpacket detectorは失敗。
有効なdetector pairでも一方のgraph IDがrawから消えていれば除外し、他の対へ代替しない。
raw部分集合には当該2frame以外のIDも存在してよい。返却はsorted builtin graph-ID tuple list。
入力不変、GT/IOなし。この段階ではraw座標/時刻や元辺次数・距離gateを再検証したことには
せず、loaderとmotion側の条件を後続で満たす。予約そのものをこのadapterへ入れない。

## 共通loaderの最小接続

appearance_inputs内の現load_appearance_frames本体をprivate _load_framesへ移し、
public load_appearance_framesは旧署名でconsensus_mode=False、new load_consensus_framesは
同じ署名でTrueを渡す。共有するのは既存の材料/hash/99packet/原座標/ID検証であり、
任意pluginやcallback registryは作らない。E28の返却frames/receiptを変えない。
E29はactive packetをread_packetで検証後、全detector行列へreciprocal_consensus_pairsを適用、
map_consensus_to_rawでraw IDへ写像する。各active tに空listも含めて記録。
raw degree/gateは後段なのでここで予約完了とは呼ばない。1packetのdense配列はfinallyで解放。
E29 receiptには専用schema、3logitの元signatures、全detector consensus数、raw ID対を記録。
終端reader.recheckは既存どおり。E28合成NPZテストを維持し、新E29非正方/欠損raw/空一致/
改変packet/座標違いの同じ実readerを通すテストで接続を検証する。

## 独立評価と親判断（実装前）

motion単位のAPIはkeyword-only reserved_pairs=None（一動画のsorted builtin graph-ID tuple list）。
これはloaderの全一致対そのものではなく、pipelineが元raw/距離filter双方の一対一辺へ
限定して渡す候補。Noneは旧コードと同値、空listでも既存assignmentを保つ。
motionはappearanceとの同時指定、disabled motion、無効ID/時刻/重複source/targetを拒否。
大frame fallbackはopt-in時に失敗。tight距離外は予約から除き、通常assignmentの対象に残す。
各frameの予約を先にframe_matchesへ追加して両端を未割当集合から除外。raw/motion/probの
算出式とpredecessor更新タイミングは従来どおり。motion_passはtightを維持し、新counter
motion_relink_reserved_edgesだけopt-in時に記録。予約された返却辺へconsensus_reserved=1を
付け、後段が実予約IDのreceiptを構築できるようにする。Noneの返却dict/statsは不変更。
このAPI単体は元raw存在/次数を保証せず、pipeline接続前に実候補へ使用しない。

MAX session85699、exit0。新しいprivate-score-sensitive構造変更を理由に1回評価。
reverse軸、未知分裂リスク、E29固有None対照の必要性は採用し検証条件へ残す。
親は次の解釈を不採用: 三重一致しない候補は削除されず従来assignmentに残るため、
条件を厳しくするだけでE26同様に辺を大量削除するという因果は成立しない。
予約辺を残余Hungarianのcostに再投入しないのでbonusの二重加算はしない。
一致条件の緩和/fallback追加は根拠のない別variantであり行わない。従来残余処理が既存経路。
改善量を未実験で数値予言することは受入条件にしない。正解辺を予約して競合先を奪う損失や
未知分裂の悪化は実在するriskで、固定CV/追跡gateを免除する理由にはならない。

実source照合: outputs/local/e23_association_capture_d3_20260908/prospective_e23_predict.py.txt
SHA256 8e7ac19e8b436d6777576b7ea2269464c4ed8842990b45448d40bf178f8f62de は
REFERENCE_PLANのsource_sha256.offと一致。594行以降でforwardはsrc,tgt、606行以降で
reverseはtgt,srcをpredict_edgesへ渡し、transpose(1,2)を実施。
association_instrumentationのhookはその直後・alignment前にraw reverseを保存する。
従ってreverse[i,:]は元source iに対するreverse側source（元target）選択の比較である。
上流mixed probabilityのalignment後source正規化を再現する案ではないことを明示する。

親判断: 条件を緩和せず、上記意味/既知分裂除外を固定したpure ranking helperの開発へ進む。
これは科学採用や実候補生成の許可ではない。統合・None parity・材料登録・予算・採点接続を
完了するまで物理候補を起動しない。E29に未知division保存の保証やprivate改善実績はない。
