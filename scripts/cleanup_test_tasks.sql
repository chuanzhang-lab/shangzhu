-- M5 数据卫生：shangzhu PG 测试残留任务清理（待用户确认后执行）
-- 用途：删除测试残留「新任务」，保留真实任务。
-- 安全：默认 DRY-RUN（只 SELECT 不 DELETE）。确认后把下面 DELETE 前的注释去掉再执行。

-- ① 预览：将被删除的候选（13 条「新任务」，含今天与历史测试残留）
SELECT id, name, turn, created_at::date AS created, updated_at::date AS updated
FROM tasks
WHERE deleted_at IS NULL
  AND name = '新任务'
ORDER BY updated_at DESC;

-- ② 实际清理（等用户确认后取消下面注释，替换上方 SELECT）
-- DELETE FROM tasks
-- WHERE deleted_at IS NULL
--   AND name = '新任务';

-- ③ 复核：删除后剩余（应只剩 real 任务，如「端到端咖啡店」）
-- SELECT id, name, turn, updated_at::date FROM tasks WHERE deleted_at IS NULL ORDER BY updated_at DESC;
