# `ccx`

`ccx` 是一个纯 Shell 实现的 Claude Code 会话级配置切换工具。

它不会修改 `cc-switch` 或全局 Claude 设置，仅通过在当前终端中包装 `claude --settings <profile.json>` 来实现按终端窗口的配置覆盖。不同终端可以同时使用不同的配置。

## 文件结构

- `ccx.sh` — source 到 Shell 中使用的主脚本
- `sync_ccswitch_profiles.sh` — 从 `cc-switch` 数据库同步配置
- `profiles/*.json` — 每个文件对应一个 Claude 配置方案

## 安装

在 `~/.zshrc` 中添加：

```sh
export CCX_ROOT="/path/to/ccx"
source "$CCX_ROOT/ccx.sh"
```

或仅在当前 Shell 中临时加载：

```sh
export CCX_ROOT="/Users/cliffkai/Code/ccx"
source "$CCX_ROOT/ccx.sh"
```

## 命令一览

| 命令                                | 说明                                                       |
| ----------------------------------- | ---------------------------------------------------------- |
| `ccx_list`                          | 列出所有可用配置。从 cc-switch 导入的会显示 `别名 -> 原名` |
| `ccx_sync`                          | 从 cc-switch 数据库导入所有 Claude 配置并刷新快捷命令      |
| `ccx_use <配置名>`                  | 切换当前终端到指定配置                                     |
| `ccx_current`                       | 显示当前使用的配置，未选择时显示 `cc-switch default`       |
| `ccx_reset`                         | 清除当前终端的配置覆盖，恢复 cc-switch 默认行为            |
| `ccx_run <配置名> [claude 参数...]` | 用指定配置执行一次 Claude 命令，不改变当前 Shell 状态      |
| `ccx_reload`                        | 重新扫描 `profiles/*.json` 并注册新增配置的快捷命令        |

## 快捷切换

每个 `profiles/` 下的 JSON 文件会自动注册为同名 Shell 函数。例如存在 `profiles/openrouter.json`，则可以直接输入：

```sh
openrouter      # 等同于 ccx_use openrouter
```

对于从 cc-switch 导入的含空格名称，使用 `ccx_list` 查看对应的别名，或直接用原名：

```sh
openrouter                    # 使用别名
ccx_use "Google AI Studio"    # 带空格的名称需要引号
```

选择配置后，直接运行 `claude` 即可自动附带 `--settings` 参数。

## 工作原理

`ccx` 通过 Shell 函数包装 `claude` 命令。当设置了配置时，自动注入 `--settings /path/to/profile.json`；未设置时，`claude` 行为与原始完全一致。

因为覆盖仅存在于当前 Shell 的环境变量中，所以不同终端窗口可以同时使用不同的 API 配置。

## 配置文件格式

每个 profile JSON 是标准的 Claude settings 片段，支持的字段包括：

- `env` — 环境变量（如 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`）
- `model` — 模型选择
- `effortLevel` — 推理力度
- `enabledPlugins` — 启用的插件
- `permissions` — 权限设置

未在 profile 中指定的字段会沿用 cc-switch 及其他来源的默认值。

## 自定义同步源

默认从以下路径读取 cc-switch 数据：

```sh
~/Library/Mobile Documents/com~apple~CloudDocs/密钥/cc-switch
```

可通过环境变量覆盖：

```sh
export CCX_CCSWITCH_DIR="/other/path/to/cc-switch"
```
