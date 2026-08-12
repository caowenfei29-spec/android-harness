# 技能：应用安装（APP_INSTALL）

目标：安装指定应用并验证可用。

流程：
1. 用 get_state 检查是否已安装（读包名列表或商店状态）
2. 已安装：launch_app 验证后 done
3. 未安装：play_store_search
4. 选择官方/名称匹配项，避开山寨与广告
5. 详情页有 Install 且无需登录：tap 安装
6. wait 并轮询 Pending/Downloading/Installing/Open/已安装
7. launch_app 最终验证
8. 若商店要求登录/绑卡/审核：need_user 或 failed，说明原因

成功证据：
- 已装列表出现，或
- 可成功 launch，或
- 商店显示 Open/已安装 + 启动验证通过

回复必须给出：完整步骤、包名、验证结果。
