# コントリビューションガイド（elderithm GitHub 運用）

elderithm org の private リポジトリ共通の、Issue・ラベル・Project・PR の運用ルールです。Issue を Claude Code / 開発者がそのまま着手できる粒度で管理することを目的にしています。

## 0. 全体像

| 要素 | 役割 |
|---|---|
| Issueテンプレート4種 | 起票フォーマットの統一・着手可能な粒度の強制 |
| ラベル体系 | type / priority / area(プロダクト名) / agent / 例外status で多軸分類 |
| Project「elderithm 開発」 | 5レーンのボードで全 private リポを集約管理 |
| 自動化（auto-add + status遷移） | issue自動追加・レーン自動移動 |

## 1. Issue を起票する

各リポの **Issues → New issue** で4つから選択（この順で表示）：

| テンプレート | いつ使う | 初期ラベル |
|---|---|---|
| **バグ報告** | 不具合・リグレッション・クラッシュ | `type: bug` |
| **機能要望・改善提案** | アイデア〜提案段階（仕様はこれから） | `type: feature` |
| **開発タスク** | 仕様確定・すぐ着手できるもの | `type: task` |
| **Blank issue** | 自由記述（雑メモ・調査依頼など） | なし |

**共通ルール**：観測事実・確定仕様のみ記入し、埋められない項目は空欄にせず `NOT_ENOUGH_INFO` と書く（＝未確定であることが情報）。推測混じりの曖昧な起票を避けます。

**開発タスク**は「ゴール / 対象リポ・ファイル範囲 / 実装方針 / 受け入れ条件 / テスト要件 / 対象外」を埋める構成。**これが揃った状態＝Claude Code にそのまま渡せる状態**です。

## 2. ラベルの使い方（軸ごと）

| 軸 | ラベル | 使い方 |
|---|---|---|
| **種別** | `type: bug/feature/task/docs/chore/spike` | テンプレで自動付与。必要に応じ変更 |
| **優先度** | `P0 / P1 / P2 / P3` | P0=本番障害・即対応。トリアージ時に付ける |
| **領域(プロダクト)** | `area: <リポ名>`（例 `area: vowde`） | どのプロダクトか。各リポには自身の area ラベルを用意 |
| **担い手** | `agent: ready` / `needs-human` | `agent: ready`＝仕様確定・Claudeが着手可。`needs-human`＝人の判断/対人が必要 |
| **例外状態** | `status: blocked` / `status: needs-decision` | ブロック中・判断待ちを issue 上で可視化 |

> ライフサイクル（Backlog→Done）は**ボードの Status が正**です。

## 3. ボード（Project「elderithm 開発」）

5レーン：**Backlog → Ready → In progress → In review → Done**

| レーン | 意味 |
|---|---|
| Backlog | 起票直後・未整理 |
| Ready | 仕様確定・着手可（Claudeに渡せる） |
| In progress | 実装着手中 |
| In review | PRレビュー中 |
| Done | マージ/クローズ |

カードのフィールド：**Status / Priority / Area(プロダクト) / Owner（Claude/Human/Pair） / Estimate** ＋ 標準の Repository・Labels 等。全 private リポを1ボードに集約しているので、**Repository / Area 列でプロダクトを区別**し、**Group by / Filter** で絞り込みます。

## 4. 自動化（自動 / 手動）

| 遷移 | 自動/手動 | 仕組み |
|---|---|---|
| 起票 → **Backlog** | 自動 | ネイティブ「item added」＋ auto-add |
| `agent: ready` 付与 → **Ready** | 自動 | GitHub Action |
| 着手 → **In progress** | **手動**（カードをドラッグ） | 着手検知が不確実なため |
| `Closes #◯` のPR作成 → **In review** | 自動 | GitHub Action |
| マージ/クローズ → **Done** | 自動 | ネイティブ「item closed」 |

**手動なのは In progress だけ**。実装を始めたらカードを In progress に移動してください。

## 5. 実践フロー（1リポで完結する場合）

```
1. New issue → 開発タスク で起票（ゴール〜対象外を記入）
   └ 自動で Backlog に載る
2. 優先度・area ラベルを付与
3. 仕様が固まったら agent: ready を付与
   └ 自動で Ready に移動
4. 着手時：カードを In progress にドラッグ
5. issue URL を Claude Code に渡して実装 → PR作成（本文に Closes #◯）
   └ 自動で In review に移動
6. レビュー → マージ
   └ issue が自動クローズ → 自動で Done
```

## 6. 複数リポにまたがる作業

**1つの issue に全部詰めない**（Claude Code は1リポ単位で動くため）。「親＋サブ」に分割します：

- 親 issue を主となるリポに作り、各リポの issue を **Sub-issues** として紐付け（別リポの子も可）
- **`agent: ready` や PR は「子」に紐づける** → 子が Ready→In review→Done と流れる
- **親はトラッカー**：Backlog 据え置き＋ `Sub-issues progress`（例 2/3）で進捗把握
- ボードで **Group by → Parent issue** にすると親ごとにまとまって見えます

## 7. PR の作り方

- **本文に必ず `Closes #<子issue番号>`**（PRテンプレに欄あり）。これが In review 自動移動とマージ時の自動クローズの両方を駆動します
- チェックリスト（受け入れ条件を満たす／テスト追加／対象外に踏み込まない／シークレット非混入）を確認

## 8. 注意点・制約

- **In review 自動化は `Closes #` が前提**。書き忘れるとレーン移動しません
- **構築前からある既存 issue は自動追加されません** → 手動でボードに Add
- 自動化には org secret / repo secret `ADD_TO_PROJECT_PAT`（Projects書き込み権限のPAT）が必要
- Free プランのため auto-add はビルトインではなく GitHub Action 方式で実装
