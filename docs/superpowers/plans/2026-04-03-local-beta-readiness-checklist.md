# 本地 Beta 就绪验收清单

## 目标

这份清单用于判断：当前“会话级沙箱隔离”方案，是否已经完成本地签收，可以进入 beta 环境验证。

这份清单有意保持收敛，只关注：

- 会话级 runtime 隔离是否成立
- 本地生命周期是否闭环
- 录制链路是否具备可试用能力

这份清单**不**用于阻塞以下事项：

- 旧版 VNC/noVNC 录制链路
- Kubernetes 真实集群联调
- task-service 的运行时隔离
- 不影响会话隔离语义的细节打磨

## 本地前置条件

- `.env` 中使用 `RUNTIME_MODE=docker`
- `backend` 已经重启并加载最新 runtime 代码
- 前端可访问：`http://localhost:5173`
- 后端可访问：`http://localhost:12001`

推荐重启命令：

```powershell
cd E:\Work-Project\OtherWork\ScienceClaw
docker compose -f docker-compose-china.yml up -d --build backend frontend
```

## 验收项

### 1. 聊天会话 runtime 分配

- 在主聊天页面创建会话 A
- 在主聊天页面创建会话 B
- 每个会话各发送一条简单消息
- 分别查询：

```text
GET http://localhost:12001/api/v1/runtime/session/<A>/status?refresh=true
GET http://localhost:12001/api/v1/runtime/session/<B>/status?refresh=true
```

预期结果：

- 两个接口都返回 `status=success`
- 两条 runtime 记录都是 `ready`
- `pod_name`、`service_name`、`rest_base_url` 都不相同

### 2. runtime 列表一致性

查询：

```text
GET http://localhost:12001/api/v1/runtime/sessions?refresh=true
```

预期结果：

- 列表里只出现当前用户自己的 runtime
- 已经 `missing` 的 stale runtime 不会继续残留在刷新后的列表里
- 列表结果和单条 `status` 查询结果一致

### 3. 删除会话后的 runtime 回收

- 在左侧会话列表中删除一个聊天会话
- 然后重新查询：

```text
GET http://localhost:12001/api/v1/runtime/sessions?refresh=true
```

预期结果：

- 被删除会话对应的 runtime 消失
- 未删除的聊天会话 runtime 仍然存在

### 4. 录制会话可用性

- 打开 RPA 录制页面
- 启动一个新的录制会话
- 确认页面通过 CDP screencast 能看到当前浏览器画面
- 输入一个简单指令，例如打开 GitHub

预期结果：

- 录制页面能看到正在操作的浏览器页面
- AI 操作和中间预览画面一致
- 启动录制时不会再出现 runtime / sandbox 相关致命错误

### 5. stale runtime 恢复能力

- 保留一个已有聊天会话的 runtime
- 重启 `backend`
- 重新打开该聊天会话，或者重新查询其 `status?refresh=true`

预期结果：

- 如果旧 runtime 已经不存在，不会盲目复用仓库里旧的 `ready` 记录
- stale `missing` record 会被清掉
- 系统可以干净地重新拉起一个新的 runtime

## 第一阶段 Beta 不阻塞项

以下问题不是本地签收的阻塞项：

- 录制页旧版 VNC/noVNC 路径
- Kubernetes provider 的真实集群验证
- task-service 的运行时隔离
- 不影响会话级隔离语义的 UI 或日志细节问题

## 本地签收标准

当以下条件都满足时，可以认为本地阶段已经完成，可以转入 beta 环境验证：

- 聊天会话 A 和 B 会分配到不同 runtime
- 删除聊天会话会同步移除其 runtime
- 刷新后的 runtime 列表不会继续保留 stale missing 记录
- 录制页通过 CDP screencast 可正常试用
- backend 重启后不会被 stale ready runtime 卡住

## 本地签收完成后的下一步

当以上检查全部通过后，应立即切换到 beta 落地阶段，而不是继续本地打磨：

1. 冻结本地功能开发
2. 除非暴露真实缺陷，否则不再继续扩 runtime 抽象
3. 开始准备 `RUNTIME_MODE=session_pod` 的 beta 环境配置
4. 在 Kubernetes 中只验证“环境差异”，不再把功能开发和环境联调混在一起
