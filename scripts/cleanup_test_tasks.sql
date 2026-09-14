-- M5 数据卫生：shangzhu PG 测试残留任务清理
-- 用途：删除测试残留的空任务/默认命名任务，保留真实业务任务。
-- 安全：默认 DRY-RUN（只 SELECT 统计，不 DELETE）。确认无误后按步骤放开 DELETE。
-- 关联清理：messages 表有 ON DELETE CASCADE，删 task 自动清关联消息。

-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 0. 总览：当前有效任务数 vs 疑似测试残留数
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SELECT
  COUNT(*) FILTER (WHERE deleted_at IS NULL) AS active_total,
  COUNT(*) FILTER (WHERE deleted_at IS NULL
                    AND name = '新任务') AS unnamed_default,
  COUNT(*) FILTER (WHERE deleted_at IS NULL
                    AND name = '新任务'
                    AND turn = 0) AS untouched_test,
  COUNT(*) FILTER (WHERE deleted_at IS NULL
                    AND name = '新任务'
                    AND turn > 0) AS used_then_abandoned
FROM tasks;

-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 1. 预览 A：默认名「新任务」（含交互轮次统计，辅助判断是否误删）
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SELECT
  t.id,
  t.name,
  t.turn,
  t.created_at::date  AS created,
  t.updated_at::date  AS updated,
  (SELECT COUNT(*) FROM messages m WHERE m.task_id = t.id) AS msg_count
FROM tasks t
WHERE t.deleted_at IS NULL
  AND t.name = '新任务'
ORDER BY t.updated_at DESC;

-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 2. 预览 B：0 轮交互且创建超过 1 天的空任务（含非默认名的测试残留）
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SELECT
  t.id,
  t.name,
  t.turn,
  t.created_at::date AS created,
  t.updated_at::date AS updated,
  (SELECT COUNT(*) FROM messages m WHERE m.task_id = t.id) AS msg_count
FROM tasks t
WHERE t.deleted_at IS NULL
  AND t.turn = 0
  AND t.created_at < now() - INTERVAL '1 day'
ORDER BY t.updated_at DESC;

-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 3. 执行清理（确认后取消注释）
--    策略：只删默认名「新任务」且无有效交互（turn=0 或消息=0）的任务；
--    turn>0 或有消息的「新任务」保留给人工复核，避免误删真实业务。
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- DELETE FROM tasks
-- WHERE deleted_at IS NULL
--   AND name = '新任务'
--   AND (turn = 0
--        OR (SELECT COUNT(*) FROM messages m WHERE m.task_id = tasks.id) = 0);

-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 4. 复核：清理后剩余任务（应只剩有真实命名和交互的任务）
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- SELECT id, name, turn, updated_at::date AS updated
-- FROM tasks
-- WHERE deleted_at IS NULL
-- ORDER BY updated_at DESC;
