# SQLite Migration 1

入口：`src/xevent/ledger/schema.py::migrate`，使用已锁定SQLAlchemy Core生成DDL。
空库升级 `PRAGMA user_version=0 → 1`；已有版本1可幂等打开；更高版本HOLD，禁止自动降级。
未知业务表检查仅用于user_version=0：只要已有非SQLite内部表就拒绝初始化。
user_version=1会幂等创建缺失的声明表/触发器，不拒绝额外未知表，也不全面比对已有列、约束或触发器定义；
因此这不是完整Schema一致性审计，不宣称所有版本的未知业务表都会HOLD。
仅支持本子系统的新独立数据库，没有Market Engine数据库迁移。

| 表 | 主键/约束 | 内容 |
|---|---|---|
| batches | batch_id唯一 | 稳定幂等键及输入指纹；同键不同内容拒绝 |
| raw_archive | raw_id唯一；batch_id外键 | 原始BLOB、原始/规范化hash、来源、定位、版本、first_seen/collected |
| versions | (object_id, version)复合主键；batch_id外键 | 不可变JSON描述及摘要；kind区分领域对象 |
| commit_receipts | batch_id唯一外键 | 业务COMMIT成功后的观测时间、契约校验完成时间、是否保守恢复 |
| publication_fences | batch_id唯一外键指向commit_receipts | 回执本身COMMIT完成后的可用时间测量、是否恢复发布 |

所有表安装BEFORE UPDATE/DELETE拒绝触发器；追加版本不能改旧行。
Source、EvidenceVersion、EventVersion及7个Phase2契约共享版本表，RawObservation保留独立完整接收描述。
Outbox PENDING与Evidence/Event/Ledger同一事务；消费DONE另追加版本。SourceHealth/Cursor每次尝试追加版本。
没有执行SQL UPDATE的“状态字段”；没有数据库外的archive文件需要双写提交。

连接明确配置WAL、foreign_keys=ON、synchronous=FULL、busy_timeout=5000。
业务写入通过BEGIN IMMEDIATE串行化、明确COMMIT，异常由连接回滚。
暂定单写入者；不支持网络共享文件系统或跨主机多写入部署。
数据库迁移/事务故障回归见test_phase2_ledger.py；实际文件同步能力依赖SQLite与操作系统/磁盘保证，不能宣称抗硬件谎报。
