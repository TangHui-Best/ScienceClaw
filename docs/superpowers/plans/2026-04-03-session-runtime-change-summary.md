# 会话级沙箱隔离改造说明

## 背景与目标

本次改造的目标，是将原本共享的 AIO sandbox 执行模式，升级为**会话级隔离的 runtime 执行模式**，以支持：

- 主聊天会话按 `session_id` 分配独立沙箱
- 录制技能 / RPA 会话按 `sandbox_session_id` 分配独立沙箱
- 前端继续只访问固定 backend 域名，不直接接触 sandbox 容器 / Pod 地址
- 本地先通过 Docker 验证隔离能力，后续在 beta 环境切换到 Kubernetes Pod

当前本地阶段已经完成主干实现，录制页主展示链路采用 **CDP screencast**。旧版 VNC/noVNC 路径不作为当前 beta phase 1 的阻塞项。

---

## 架构变化

### 改造前

- backend 基本上只认一个共享 sandbox
- 多个聊天会话 / 录制会话实际共享同一执行面
- 前端预览和 backend 执行很容易串到同一个 sandbox

### 改造后

- backend 作为控制平面，引入 `SessionRuntimeManager`
- 每个会话在首次执行时分配自己的 runtime
- runtime 创建方式由 `RuntimeProvider` 决定
- 前端所有 runtime 访问统一走 backend 代理
- runtime 生命周期由 backend 统一管理

当前架构主线：

1. 前端发起会话请求
2. backend 调 `SessionRuntimeManager.ensure_runtime(session_id, user_id)`
3. manager 通过 provider 创建 / 复用 runtime
4. DeepAgent 或 RPA 浏览器能力连接该 runtime
5. 前端对 runtime 的 HTTP / WS 请求统一通过 backend 转发

---

## 新增核心模块

新增目录：

- `ScienceClaw/backend/runtime/`

新增文件：

- `ScienceClaw/backend/runtime/__init__.py`
- `ScienceClaw/backend/runtime/models.py`
- `ScienceClaw/backend/runtime/repository.py`
- `ScienceClaw/backend/runtime/provider.py`
- `ScienceClaw/backend/runtime/shared_runtime_provider.py`
- `ScienceClaw/backend/runtime/docker_runtime_provider.py`
- `ScienceClaw/backend/runtime/k8s_runtime_provider.py`
- `ScienceClaw/backend/runtime/session_runtime_manager.py`
- `ScienceClaw/backend/runtime/ownership.py`

各模块职责：

- `models.py`
  - 定义 `SessionRuntimeRecord`
  - 表示会话与 runtime 的绑定关系

- `repository.py`
  - 提供 `session_runtimes` 集合访问入口

- `provider.py`
  - 定义 runtime provider 抽象与工厂
  - 负责根据 `RUNTIME_MODE` 选择 provider

- `shared_runtime_provider.py`
  - 兼容共享 sandbox 模式

- `docker_runtime_provider.py`
  - 本地验证模式
  - 为每个会话动态拉起 `scienceclaw-sess-*` 容器

- `k8s_runtime_provider.py`
  - beta / 生产部署模式
  - 为每个会话动态创建 Pod / Service

- `session_runtime_manager.py`
  - runtime 生命周期总入口
  - 提供 `ensure / get / list / destroy / cleanup` 能力

- `ownership.py`
  - 统一判断某个 runtime/session 是否真正属于当前用户
  - 同时覆盖聊天会话与 RPA 录制会话

---

## 后端改动点

### 1. 主聊天会话改为按会话分配 runtime

相关文件：

- `ScienceClaw/backend/deepagent/agent.py`
- `ScienceClaw/backend/deepagent/full_sandbox_backend.py`

改动内容：

- DeepAgent 执行前先 `ensure_runtime(session_id, user_id)`
- `FullSandboxBackend` 不再只依赖固定共享 sandbox 地址
- 改为按会话注入 `rest_base_url`

效果：

- 每个主聊天会话可绑定自己的独立 runtime
- 主聊天会话不再默认偷走共享 `sandbox-1`

### 2. 录制技能 / RPA 改为按会话分配 runtime

相关文件：

- `ScienceClaw/backend/route/rpa.py`
- `ScienceClaw/backend/rpa/cdp_connector.py`
- `ScienceClaw/backend/rpa/manager.py`
- `ScienceClaw/backend/rpa/assistant.py`

改动内容：

- RPA 启动时按 `sandbox_session_id` 获取独立 runtime
- `cdp_connector` 改为按 session 取 browser endpoint
- 录制页当前主展示采用 CDP screencast

效果：

- 不同录制会话可以落到不同 `scienceclaw-sess-rpa-*` 容器
- AI 操作页面和录制展示页面保持一致

### 3. 新增 runtime 代理层

相关文件：

- `ScienceClaw/backend/route/runtime_proxy.py`
- `ScienceClaw/backend/main.py`

改动内容：

- backend 新增 runtime 状态、列表、HTTP 代理、WebSocket 代理
- 所有 runtime 访问统一经 backend 路由
- 增加 ownership 校验，避免跨用户 / 跨会话访问

### 4. 会话生命周期增强

相关文件：

- `ScienceClaw/backend/route/sessions.py`
- `ScienceClaw/backend/main.py`
- `ScienceClaw/backend/runtime/session_runtime_manager.py`

改动内容：

- 删除聊天会话时尝试同步销毁 runtime
- backend 启动 / 关闭时做 orphan cleanup
- 增加 runtime TTL 清理循环
- stale runtime record 会自动清理
- stale `ready` runtime 会在 `ensure_runtime()` 时自动重建

---

## 前端改动点

相关文件：

- `ScienceClaw/frontend/src/api/agent.ts`
- `ScienceClaw/frontend/src/utils/sandbox.ts`
- `ScienceClaw/frontend/src/components/SandboxPreview.vue`
- `ScienceClaw/frontend/src/components/VNCViewer.vue`
- `ScienceClaw/frontend/src/components/toolViews/BrowserToolView.vue`
- `ScienceClaw/frontend/src/pages/rpa/RecorderPage.vue`

改动内容：

- session 相关的 sandbox URL 改为走 backend runtime proxy
- 录制页主展示改为 CDP screencast
- 录制页不再以旧 VNC/noVNC 作为当前本地主链路

---

## 新增 API

### 1. 查询单个会话 runtime 状态

- `GET /api/v1/runtime/session/{session_id}/status`

参数：

- `refresh=true` 可选

作用：

- 查询指定会话当前绑定的 runtime
- 用于定位 runtime 是否存在、是否 ready

### 2. 查询当前用户 runtime 列表

- `GET /api/v1/runtime/sessions`

参数：

- `refresh=true` 可选

作用：

- 返回当前用户所有可见 runtime
- 刷新时会过滤 stale / missing 记录

### 3. runtime HTTP 代理

- `GET|POST|PUT|PATCH|DELETE|OPTIONS /api/v1/runtime/session/{session_id}/http/{path}`

作用：

- 将前端对 runtime 的 HTTP 请求转发到该会话对应 runtime
- 用于 browser info、VNC 页面资源及其他 runtime HTTP 能力

### 4. runtime WebSocket 代理

- `WS /api/v1/runtime/session/{session_id}/http/{path}`

作用：

- 将前端对 runtime 的 websocket 请求转发到该会话对应 runtime
- 用于 websockify、shell 等 ws 通道

### 5. 既有 API 的行为增强

- `DELETE /api/v1/sessions/{session_id}`

增强点：

- 删除聊天会话时会同步尝试销毁对应 runtime

---

## 新增配置项及作用

### 一、通用 runtime 配置

- `RUNTIME_MODE`
  - 作用：控制 runtime 工作模式
  - 可选值：
    - `shared`：共享 sandbox
    - `docker`：本地按会话拉起独立容器
    - `session_pod`：K8s 中按会话拉起独立 Pod

- `RUNTIME_IDLE_TTL_SECONDS`
  - 作用：runtime 空闲多久后自动回收

- `SESSION_SANDBOX_IMAGE`
  - 作用：会话级 runtime 使用的 sandbox 镜像

- `SESSION_SANDBOX_PORT`
  - 作用：会话级 sandbox 的服务端口

- `RUNTIME_WAIT_TIMEOUT_SECONDS`
  - 作用：创建 runtime 后等待其 ready 的超时时间

- `SHARED_SANDBOX_REST_URL`
  - 作用：共享模式下的 sandbox REST 地址

### 二、本地 Docker runtime 配置

- `DOCKER_RUNTIME_NETWORK`
  - 作用：session 容器加入的 Docker 网络

- `DOCKER_RUNTIME_VOLUMES_FROM`
  - 作用：指定 session 容器继承哪个基础 sandbox 容器的挂载

- `DOCKER_RUNTIME_SHM_SIZE`
  - 作用：设置 session 容器共享内存大小，影响浏览器稳定性

- `DOCKER_RUNTIME_MEM_LIMIT`
  - 作用：限制单个 session 容器的内存上限

- `DOCKER_RUNTIME_SECURITY_OPT`
  - 作用：设置 Docker 安全选项，例如 seccomp

- `DOCKER_RUNTIME_EXTRA_HOSTS`
  - 作用：为 session 容器注入额外 hosts 映射

### 三、K8s runtime 配置

- `K8S_RUNTIME_NAMESPACE`
  - 作用：session Pod / Service 创建所在的 namespace

- `K8S_RUNTIME_SERVICE_ACCOUNT`
  - 作用：session Pod 使用的 ServiceAccount

- `K8S_RUNTIME_IMAGE_PULL_POLICY`
  - 作用：镜像拉取策略

- `K8S_RUNTIME_IMAGE_PULL_SECRETS`
  - 作用：拉取私有镜像所需 secret

- `K8S_RUNTIME_NODE_SELECTOR`
  - 作用：指定 session Pod 调度目标节点

- `K8S_RUNTIME_ENV`
  - 作用：向 session Pod 注入额外环境变量

- `K8S_RUNTIME_LABELS`
  - 作用：为 session Pod 添加额外 labels

- `K8S_RUNTIME_ANNOTATIONS`
  - 作用：为 session Pod 添加额外 annotations

- `K8S_RUNTIME_CPU_REQUEST`
  - 作用：CPU request

- `K8S_RUNTIME_CPU_LIMIT`
  - 作用：CPU limit

- `K8S_RUNTIME_MEMORY_REQUEST`
  - 作用：内存 request

- `K8S_RUNTIME_MEMORY_LIMIT`
  - 作用：内存 limit

- `K8S_RUNTIME_TOLERATIONS_JSON`
  - 作用：设置 tolerations

- `K8S_RUNTIME_WORKSPACE_VOLUME_NAME`
  - 作用：workspace 卷名称

- `K8S_RUNTIME_WORKSPACE_MOUNT_PATH`
  - 作用：workspace 在 session Pod 内的挂载路径

- `K8S_RUNTIME_WORKSPACE_PVC_CLAIM`
  - 作用：session Pod 使用的 workspace 持久化 PVC
  - 这是实现“runtime 可回收、workspace 不丢失”的关键配置

- `K8S_RUNTIME_EXTRA_VOLUMES_JSON`
  - 作用：额外 volume 定义

- `K8S_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON`
  - 作用：额外挂载定义

---

## 存储与依赖调整

### 存储层

相关文件：

- `ScienceClaw/backend/storage/__init__.py`

改动：

- 新增 `session_runtimes` 集合支持

### 依赖与编排

相关文件：

- `ScienceClaw/backend/requirements.txt`
- `docker-compose-china.yml`

改动：

- 新增 Docker/K8s runtime 所需依赖
- 开发编排透传 runtime 相关环境变量

---

## 当前已实现的能力边界

### 已完成

- 主聊天会话可分配独立 runtime
- 录制会话可分配独立 runtime
- runtime 代理能力可用
- ownership 校验已统一
- stale runtime 自动清理与自动重建已可用
- 本地 Docker 验证已通过

### 当前主路径

- 录制页主展示链路采用 **CDP screencast**

### 当前不作为 beta phase 1 阻塞项

- 旧版 VNC/noVNC 录制路径
- task-service 的 runtime 隔离
- Kubernetes 集群真实联调

---

## 本次改造的一句话总结

本次改造完成了从“共享 sandbox 执行”到“会话级 runtime 执行”的主干迁移，主聊天与录制技能都已具备按会话隔离的执行环境，并补充了 runtime 代理、ownership 校验、TTL 回收、stale runtime 恢复与后续 K8s beta 部署所需的配置能力。
