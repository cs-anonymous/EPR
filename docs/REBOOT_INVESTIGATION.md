# 系统重启问题调查报告

## 问题描述

训练过程中发生了两次意外重启，导致训练中断：

1. **第一次重启**：5月22日 16:26
   - 训练进度：step ~7996 (接近 checkpoint-8000)
   - checkpoint-8000 所有文件都是 0 字节（保存时被中断）
   - 用户 gkw 在 15:07 登录，16:26 会话crash

2. **第二次重启**：5月23日 02:37（凌晨）
   - 训练进度：step ~9999 (接近 checkpoint-10000)
   - checkpoint-10000 未创建
   - 无用户登录，自动重启

## 可疑的巧合

### 重启时机分析

| 重启次数 | 时间 | 训练步数 | 最近的checkpoint | 状态 |
|---------|------|---------|-----------------|------|
| 第1次 | 16:26 | ~7996 | checkpoint-8000 | 正在保存，文件0字节 |
| 第2次 | 02:37 | ~9999 | checkpoint-10000 | 未创建 |

**共同点：**
- ✅ 都在接近 X000 步时重启（8000, 10000）
- ✅ 都在保存checkpoint的时间点附近
- ✅ 间隔约2000步（约4-5小时）

## 可能的原因

### 1. 硬件问题（可能性：中等）

**电源问题：**
- GPU功耗峰值：4×350W = 1400W
- 保存checkpoint时可能触发磁盘I/O峰值
- 电源供应不足或不稳定

**过热问题：**
- 长时间高负载运行
- 保存checkpoint时CPU和磁盘同时高负载
- 触发过热保护自动重启

**建议检查：**
```bash
# 检查温度（需要安装 lm-sensors）
sudo apt install lm-sensors
sudo sensors-detect
sensors

# 检查电源日志
sudo journalctl -b -1 | grep -i "power\|thermal\|shutdown"
```

### 2. 内存/磁盘I/O问题（可能性：低）

**当前状态：**
- 系统内存：251GB（充足）
- 磁盘空间：520GB 可用（充足）
- 每个checkpoint：521MB

**不太可能是原因：**
- 内存充足，不会OOM
- 磁盘空间充足
- checkpoint大小不大

### 3. NVIDIA驱动/CUDA问题（可能性：中等）

**观察到的：**
- 最近更新了NVIDIA驱动（580.126.09 → 580.142）
- 第一次重启后使用新驱动
- 可能存在驱动稳定性问题

**建议：**
```bash
# 检查NVIDIA错误日志
nvidia-smi -q | grep -i "error\|ecc"

# 降级驱动（如果问题持续）
sudo apt install nvidia-driver-580=580.126.09-0ubuntu0.24.04.2
```

### 4. 系统自动维护任务（可能性：高）

**第二次重启（凌晨2:37）特别可疑：**
- 凌晨时间
- 无用户登录
- 典型的系统维护时间窗口

**需要检查：**
```bash
# 检查所有定时任务
sudo crontab -l
crontab -l
ls -la /etc/cron.d/
ls -la /etc/cron.daily/
ls -la /etc/cron.weekly/

# 检查systemd定时器
systemctl list-timers --all

# 检查是否有自动重启脚本
sudo grep -r "reboot\|shutdown" /etc/cron.* /etc/systemd/
```

### 5. 训练脚本bug（可能性：低但需排除）

**理论上可能：**
- 保存checkpoint时触发某个bug
- 导致系统调用 reboot（不太可能）
- 或者触发kernel panic

**排除方法：**
- 检查训练脚本中是否有系统调用
- 监控下次保存checkpoint时的系统行为

## 立即行动建议

### 1. 禁用自动重启（必须）

```bash
# 明确禁用自动重启
echo -e "// 明确禁用自动重启\nUnattended-Upgrade::Automatic-Reboot \"false\";\nUnattended-Upgrade::Automatic-Reboot-WithUsers \"false\";" | sudo tee /etc/apt/apt.conf.d/51disable-auto-reboot

# 验证
cat /etc/apt/apt.conf.d/51disable-auto-reboot
```

### 2. 检查定时任务（必须）

```bash
# 检查所有可能导致重启的定时任务
sudo crontab -l | grep -i "reboot\|shutdown\|restart"
systemctl list-timers | grep -i "reboot\|shutdown\|restart"
```

### 3. 增加监控（推荐）

创建监控脚本：
```bash
#!/bin/bash
# /home/sy/monitor_training.sh

while true; do
    echo "$(date): Training status check" >> /home/sy/training_monitor.log
    ps aux | grep torchrun | grep -v grep >> /home/sy/training_monitor.log
    nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv,noheader >> /home/sy/training_monitor.log
    free -h | grep "内存" >> /home/sy/training_monitor.log
    echo "---" >> /home/sy/training_monitor.log
    sleep 300  # 每5分钟记录一次
done
```

### 4. 修改训练参数（可选）

如果问题持续，考虑：
```bash
# 增加 save_total_limit，减少删除操作
--save-total-limit 5

# 或者禁用自动删除
# 手动管理checkpoint
```

### 5. 与系统管理员沟通（必须）

- 询问是否有定时维护任务
- 询问是否有自动重启策略
- 请求在训练期间暂停维护

## 下一步

1. **立即执行**：禁用自动重启配置
2. **今天执行**：检查所有定时任务
3. **持续监控**：观察下次保存checkpoint时是否再次重启
4. **如果再次重启**：
   - 检查 `/var/log/syslog` 中的重启原因
   - 考虑硬件问题（电源、过热）
   - 考虑降级NVIDIA驱动

## 当前状态

✅ 训练已从 checkpoint-9500 恢复
✅ 当前进度：63% (9505/14982)
✅ 预计完成时间：今晚 19:00-20:00
✅ 使用 tmux 会话 `cpt_training`

---

**更新时间：** 2026-05-23 07:15
**下次检查：** 观察是否在 checkpoint-10000 附近再次重启
