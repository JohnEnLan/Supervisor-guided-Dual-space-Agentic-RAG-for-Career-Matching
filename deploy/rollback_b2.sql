-- B2 回滚状态迁移（方案 §8）：仅在决定回滚到 B2 之前的旧包时执行。
-- 顺序（写死）：① systemctl stop career-rag（停服，杜绝并发写回窗口）
--             ② sudo -u postgres psql -d career_rag -v ON_ERROR_STOP=1 -f 本文件
--             ③ 换回旧 app 包 + 旧前端（symlink 翻回旧 release）
--             ④ systemctl start career-rag
-- 含 resume_queued：停服杀死在途任务后该状态无人认领，不迁移会让旧前端永久轮询。
BEGIN;
UPDATE session_state
SET status = 'awaiting_resume', updated_at = now()
WHERE status IN ('resume_uploaded', 'resume_queued');
DELETE FROM resume_uploads;
COMMIT;
