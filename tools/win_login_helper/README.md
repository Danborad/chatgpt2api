# ChatGPT2API Windows 桌面原生批量登录助手

专为配合 **ChatGPT2API** 打造的 Windows 本地自动化登录与凭据同步工具。

通过直接调用 Windows 系统原生浏览器（Microsoft Edge 或 Google Chrome），在纯净隔离的无痕沙盒环境下模拟真实用户执行登录，彻底突破 Cloudflare 防护机制，并在登录完成后自动将全权限凭据上传至您的 ChatGPT2API 服务器。

---

## 一、核心特性与优势

1. **真实桌面浏览器环境（过盾率接近 100%）**：
   - 直接调用 Windows 本机已安装的原生 Edge 或 Chrome 浏览器；
   - 具备完整的桌面 GPU 硬件加速、系统字体库及合法渲染环境，绝不暴露无头特征；
   - 遇到偶发的人机验证或滑块时，浏览器窗口在屏幕上直接可见，用户可随时用鼠标辅助点击。
2. **多服务器智能均衡分发**：
   - 支持配置多台 ChatGPT2API 服务器（如主节点、备用节点、内网节点等）；
   - 支持两种分发策略：
     - `round_robin`（**均匀轮流分发**）：账号 1 导入服务器 A，账号 2 导入服务器 B，账号 3 导入服务器 A... 平衡负载；
     - `single`（**指定单机导入**）：全部账号集中导入指定的某一台服务器。
3. **全局自动排重（避免重复登录）**：
   - 启动前自动拉取所有目标服务器中已存在的正常/限流账号；
   - 自动对比并跳过已存在的账号，不浪费时间与代理流量。
4. **Resin 粘性代理池原生联动（一号一独立 IP）**：
   - 支持填写 Resin 代理（如 `http://user@proxy-pool.local:2260`）；
   - 程序自动为每个账号派生独立的会话租约（如 `user.acc_user1@...`），实现**登录一个账号切一个全新干净 IP**，且该账号登录全程保持 IP 粘性。
5. **失败自动换 IP 重试与故障归档**：
   - 遇到网络波动、密码输错或代理中断时，自动派生全新 IP 重新尝试（默认重试 2 次）；
   - 永久失败的账号自动记录至 `failed_accounts.txt`，附带具体报错原因。
6. **全权限凭据自动提取入库**：
   - 自动完成 2FA TOTP 动态验证码计算与填充；
   - 自动提取 Web Access Token、Session Token，并静默换取长期 Platform OAuth Refresh Token（支持后续临期自动续期）。

---

## 二、Windows 快速开始使用

### 步骤 1：下载并解压
在 Windows 电脑上将本文件夹解压至任意目录（例如 `D:\win_login_helper\`）。

### 步骤 2：环境准备（首次运行）
确保 Windows 电脑已安装 **Python 3.10** 或更高版本：
- 前往 Python 官网下载：[https://www.python.org/downloads/](https://www.python.org/downloads/)
- **注意**：安装第一步务必勾选底部 **“Add Python to PATH”**（将 Python 添加到环境变量）！
- Windows 10/11 均自带 **Microsoft Edge** 浏览器，默认开箱即用，无需额外配置。

### 步骤 3：配置服务器与代理 (`config.json`)
用记事本或 VS Code 打开 `config.json`，按需修改：
```json
{
  "servers": [
    {
      "name": "NAS主服务器",
      "url": "http://10.0.0.10:3005",
      "auth_key": "your_auth_key",
      "enabled": true,
      "target_group_id": null
    },
    {
      "name": "异地备用节点",
      "url": "http://10.0.0.20:3005",
      "auth_key": "your_auth_key",
      "enabled": false,
      "target_group_id": null
    }
  ],
  "import_strategy": "round_robin",
  "target_server": "NAS主服务器",
  "base_proxy": "http://user@proxy-pool.local:2260",
  "browser": {
    "channel": "msedge",
    "headless": false,
    "timeout_seconds": 90,
    "slow_mo_ms": 50
  },
  "max_retries": 2,
  "accounts_file": "accounts.txt",
  "failed_file": "failed_accounts.txt"
}
```

#### 配置参数说明：
- `servers`: ChatGPT2API 服务器节点列表：
  - `name`: 节点名称（用于日志和识别）；
  - `url`: 你的 ChatGPT2API 访问地址（例如 `http://10.0.0.10:3005`）；
  - `auth_key`: 你的管理员密钥；
  - `enabled`: 是否启用此节点；
  - `target_group_id`: 导入到该服务器时的指定分组 ID（填 `null` 则不指定）。
- `import_strategy`: 分发策略：
  - `"round_robin"`: 在所有启用的服务器节点间轮流平均导入（推荐多服务器时使用）；
  - `"single"`: 全部账号导入到 `target_server` 所指定的单台服务器。
- `target_server`: 当 `import_strategy` 设为 `single` 时生效的目标服务器名称。
- `base_proxy`: 代理出口配置：
  - 填入你的代理地址，如 Resin 代理池 `http://user@proxy-pool.local:2260`；
  - 若留空 `""`，则使用 Windows 本机的直连网络环境。
- `browser.channel`: 浏览器选择：
  - `"msedge"`: 推荐，Windows 10/11 系统自带；
  - `"chrome"`: 本地安装的 Google Chrome；
  - `"chromium"`: Playwright 自带内核。
- `browser.headless`:
  - `false`（推荐）：有头可见模式，屏幕上能看到浏览器自动操作，遇到验证码可人工点击通过；
  - `true`：后台完全静默无界面运行。
- `max_retries`: 登录失败自动换 IP 重试的次数（默认 2 次）。

### 步骤 4：填入卡密 (`accounts.txt`)
打开 `accounts.txt`，粘贴你的账号卡密，支持单行和多行格式，支持任意分隔符（`----`, `---`, 空格, 竖线, 逗号等）：
```text
user1@icloud.com----Password123----652NE5KDRH6BEL7VUVYBVIPI3RHAF2VH
user2@icloud.com----Password456----P26TUU4ATP42WRYU2EVBI3JQ3ELASZRH
user3@icloud.com----Password789
```

### 步骤 5：一键运行
直接双击运行 **`run.bat`** 即可！
脚本会自动安装依赖库，检查服务器连通性，自动排重，并逐一拉起无痕浏览器执行登录与入库。

---

## 三、代码结构与二次修改指南

如果你懂 Python，想自行修改或扩展功能，可参考以下模块划分：

```text
tools/win_login_helper/
├── main.py                   # 主入口与执行调度引擎
├── config.json               # 配置文件
├── run.bat                   # Windows 启动脚本
└── core/
    ├── browser.py            # 浏览器自动化与 2FA 认证
    ├── client.py             # ChatGPT2API 服务端 API 通信
    ├── dispatcher.py         # 多服务器分发与全局排重
    └── proxy.py              # 动态粘性代理池（Resin）派生
```

### 常见修改场景：

1. **OpenAI 登录页面如果改版，如何调整选择器？**
   - 打开 `core/browser.py`；
   - 邮箱输入框定位：修改 `email_input_sel`；
   - 密码输入框定位：修改 `password_input_sel`；
   - 2FA 验证码输入框定位：修改 `otp_sel`。

2. **调整账号导入后的分组策略：**
   - 打开 `config.json`，在 `servers` 中针对每个节点配置 `target_group_id`。

3. **增加其它代理协议支持：**
   - 打开 `core/proxy.py` 中的 `derive_isolated_proxy` 函数，可扩展其它第三方住宅代理（如 BrightData、IPRoyal 等）的用户会话格式。
