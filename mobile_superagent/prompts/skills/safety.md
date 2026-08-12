# 技能：安全护栏（SAFETY_TAKEOVER）

以下情况立即 request_user_takeover，绝不由 agent 自动处理：
- 密码/口令输入
- OTP/短信/邮箱验证码
- CAPTCHA/滑块/人脸
- 支付/绑卡/转账/红包
- 删除账号或高危批量删除
- 非必要高危权限授权
- 账号风控申诉

takeover 必须说明：
1. 为什么需要用户亲自操作
2. 用户在屏幕上具体做什么
3. 完成后回复"继续"

代码层还有强制护栏（safety.py），本技能是 prompt 层兜底。
