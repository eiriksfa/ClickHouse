---
machine_translated: true
machine_translated_rev: 72537a2d527c63c07aa5d2361a8829f3895cf2bd
toc_priority: 44
toc_title: "\u30E1\u30E2\u30EA"
---

# メモリ {#memory}

メモリエンジンは、非圧縮形式でRAMにデータを格納します。 データは、読み取り時に受信されるのとまったく同じ形式で格納されます。 言い換えれば、この表からの読書は完全に無料です。
同時データアクセスは同期されます。 ロックは短く、読み取り操作と書き込み操作は互いにブロックしません。
索引はサポートされません。 読み取りは並列化されます。
単純なクエリでは、ディスクからの読み取り、データの解凍、または逆シリアル化が行われないため、最大生産性(10GB/秒以上)に達します。 （多くの場合、MergeTreeエンジンの生産性はほぼ同じくらい高いことに注意してください。)
サーバーを再起動すると、テーブルからデータが消え、テーブルが空になります。
通常、このテーブルエンジンの使用は正当化されません。 ただし、テストや、比較的少数の行(最大約100,000,000)で最大速度が必要なタスクに使用できます。

メモリーのエンジンを使用するシステムの一時テーブルの外部クエリデータの項をご参照ください “External data for processing a query”グローバルでの実装については、セクションを参照 “IN operators”).

[元の記事](https://clickhouse.com/docs/en/operations/table_engines/memory/) <!--hide-->