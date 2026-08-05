-- 0007: OTP 发送失败标志。
-- 发送失败的 challenge 不能删除（删除会把签发限流的计数记录一并抹掉，
-- 造成对故障邮箱/短信通道的无限重试）；改为打标志：
--   * 签发限流照常把该行计入 target/ip/global 窗口；
--   * 验证选取跳过 delivery_failed 行，先前已成功送达的旧码不被遮蔽。

ALTER TABLE otp_challenges
    ADD COLUMN IF NOT EXISTS delivery_failed BOOLEAN NOT NULL DEFAULT FALSE;
