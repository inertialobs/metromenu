# Metro Menu

一个仿 Windows 10 的经典开始菜单：左侧应用列表，右侧 Metro 磁贴，无边框窗口，
支持搜索、磁贴缩放/换色/分组、实时磁贴和电源操作。

实现基于 **PyGObject + GTK3**。应用发现与启动逻辑参考了
[xfce4-whiskermenu-plugin](https://gitlab.xfce.org/panel-plugins/xfce4-whiskermenu-plugin)。

- **Xfce**：可作为原生面板插件。
- **LXQt**：作为独立应用 + 面板 Custom Command。
- **其他 GTK3 桌面**：作为独立应用运行，自行绑定快捷键。

## 特性

- **两栏布局**：左栏应用列表 / 搜索，右栏分组磁贴；左下角固定“设置 / 用户 / 电源”。
- **Metro 磁贴**：`small / medium / wide / large` 四种尺寸，任意配色与分组。
- **实时磁贴**：`@clock` 时钟、`@date` 日期、`@system` CPU/内存。
- **应用列表**：常用 / 所有应用（首字母分组）；搜索按名称、注释、关键词等加权。
- **右键菜单**：Windows 10 风格，并按 Linux 习惯扩展。
- **跨桌面**：电源、设置、终端、文件管理器按运行中的桌面与可用性选择。
- **无边框窗口**：点击外部或 `Esc` 关闭，再次触发切换显示/隐藏。
- **纯 JSON 配置**：`~/.config/metromenu/config.json`。

## 安装

### 依赖

- Python 3 + PyGObject（`python3-gi`）
- GTK 3 运行时（`gir1.2-gtk-3.0`）
- 可选集成：Xfce 的 `xfconf` / `xfce4-panel`，或 LXQt 的 `lxqt-panel` /
  `lxqt-leave` / `lxqt-config` / `lxqt-globalkeys`
- 可选电源：`systemctl` / `loginctl`

Debian/Ubuntu：

```bash
sudo apt install python3-gi gir1.2-gtk-3.0
```

编译原生 Xfce 面板插件另需：`sudo apt install libgtk-3-dev libxfce4panel-2.0-dev`。

### 从源码运行

```bash
./bin/metromenu
```

### 安装到用户目录

```bash
./scripts/install.sh                    # 命令 + 桌面项 + 图标
./scripts/install.sh --panel            # 额外在面板最左侧添加按钮（Xfce / LXQt）
./scripts/install.sh --hotkey           # 额外绑定 <Super>
./scripts/install.sh --panel --hotkey='<Super>s'
```

写入位置：`~/.local/bin/metromenu`、`~/.local/share/metromenu/`、桌面项与 hicolor 图标。

### 卸载

```bash
./scripts/uninstall.sh --panel --hotkey --purge
```

不带 `--purge` 时保留 `~/.config/metromenu`。

## 使用

### 界面与交互

- 左栏“常用 / 所有应用”，顶部搜索框同时过滤列表与磁贴。
- 方向键选择、回车启动；`Esc` 或点击外部关闭。
- 左下角：系统设置、用户菜单（锁定/注销/关机、恢复隐藏的应用）、电源
  （锁定/注销/切换用户/挂起/休眠/重启/关机）。

### 右键菜单

磁贴与应用列表项共用一套菜单：

| 菜单项 | 说明 |
| --- | --- |
| 打开 / 操作 ▸ | 启动应用 / 执行 `.desktop` 的 Desktop Actions |
| 调整大小 ▸ | 磁贴尺寸（小/中/宽/大） |
| 更改颜色 ▸ | 色块 + 颜色名，另有“自定义颜色…” |
| 移动到分组 ▸ | 磁贴分组 |
| 实时磁贴 ▸ | 时钟/日期/系统磁贴开关 |
| 置顶 | 磁贴移到本组最前；列表项移到“常用”最前 |
| 固定 / 取消固定 | 增删磁贴 |
| 打开文件位置 | 在文件管理器中选中该 `.desktop` |
| 编辑菜单项 | 用默认编辑器打开 `.desktop` |
| 复制启动命令 | 复制 `Exec` 到剪贴板 |
| 添加到桌面 | 复制 `.desktop` 到桌面目录 |
| 添加到面板 | 追加为面板按钮（Xfce / LXQt） |
| 隐藏此应用 | 不再显示；用户菜单可恢复 |

### 快捷键

```bash
./scripts/menu-hotkey.sh '<Super>'
./scripts/menu-hotkey.sh '<Super>s'
```

- Xfce：写入 xfconf（`xfce4-keyboard-shortcuts`）。单独的 `<Super>` 会以`Super_L` / `Super_R`（keysym）写入。
- LXQt：写入 `~/.config/lxqt/globalkeyshortcuts.conf`（`<Super>` → `Meta`）。
- 若 `Super` 无响应，检查是否被窗口管理器或其他菜单占用；Xfce 下可重新运行
  `./scripts/menu-hotkey.sh '<Super>'`

### 配置

`~/.config/metromenu/config.json`：

```json
{
  "width": 680,
  "height": 672,
  "left_width": 312,
  "opacity": 0.96,
  "keep_alive": false,
  "groups": ["效率", "媒体与娱乐", "实用工具"],
  "tiles": [
    {"id": "@clock",  "size": "medium", "group": "效率", "color": "#0078d7"},
    {"id": "firefox-esr.desktop", "size": "wide", "group": "效率", "color": "#2d7d9a"}
  ]
}
```

- 删除该文件即可恢复默认布局。
- `@clock` / `@date` / `@system` / `@recent` 为内置特殊磁贴。
- `keep_alive` 见“性能与缓存”。

## 桌面集成

### Xfce

**方式一：原生面板插件（推荐）**

```bash
./scripts/install-panel-plugin.sh          # 编译并安装（用户级，无需 root）
./scripts/install-panel-plugin.sh --add    # 并插入 panel-1 最左侧
```

装好后也会出现在面板的 *添加新项目* 列表里；点击按钮通过单实例切换菜单，并把
弹窗锚定到按钮旁。

**方式二：Launcher 按钮**

```bash
./scripts/integrate-panel.sh
```

在 panel-1 最左侧注册一个运行 `metromenu` 的 launcher。

### LXQt

```bash
./scripts/integrate-panel.sh
```

写入 `~/.config/lxqt/panel.conf` 的 Custom Command 组件并置于最左；面板通常会自动
重载。若未出现，可在“添加部件 → Custom Command”里手动添加（命令与图标均为
`metromenu`）。

> LXQt 面板不能加载 `panel-plugin/` 的原生插件（那是 `libxfce4panel` 的 ABI）。

### 跨桌面行为

以下命令均按可用性选择：

| 操作 | 解析顺序 |
| --- | --- |
| 锁定 | `lxqt-leave` → `xflock4` → `loginctl` |
| 注销 / 挂起 / 休眠 / 重启 / 关机 | `lxqt-leave` → Xfce 注销对话框或 `systemctl` |
| 系统设置 | `lxqt-config` → `xfce4-settings-manager` → `systemsettings` → `gnome-control-center` |
| 终端 | `$TERMINAL` → 当前桌面的终端 → 常见终端列表 |
| 文件管理器 | `FileManager1` → 当前桌面的文件管理器 → 其他常见文件管理器 |
| 编辑器 | `featherpad` → `mousepad` → … → `xdg-open` |

应用发现遵循 freedesktop 规范，`OnlyShowIn` / `NotShowIn` 按运行中的桌面判断。

## 缩放与 HiDPI

- 有 XSETTINGS 的桌面（Xfce / GNOME 等）由 GTK 自动取整数缩放，metromenu 不覆盖。
- LXQt 用 `Xft.dpi` 表达缩放；metromenu 在 LXQt 下据此自动设置
  `GDK_SCALE`（例如 192 DPI → 2x）。
- 显式 `METROMENU_SCALE` / `GDK_SCALE` 优先。
- 窗口的 `width` / `height` / `left_width` 按逻辑像素配置，设备像素 = 逻辑值 × 缩放。

## 性能与缓存

菜单是单实例 `Gtk.Application`。

| 模式 | 空闲内存 | 打开体验 |
| --- | --- | --- |
| `keep_alive: false`（默认） | 无常驻（进程退出） | 每次冷启动；窗口先出现，列表/磁贴随后补齐 |
| `keep_alive: true` | 常驻一个 Python+GTK 进程（数十 MB 级） | 瞬时切换 |


缓存位于 `~/.cache/metromenu`：


## 故障排查

- **点面板按钮没反应**：确认 `metromenu` 可执行，并重载/重启面板；Xfce 检查插件是否加载。
- **`Super` 不生效**：可能被窗口管理器或其他菜单占用；LXQt 需重新登录或运行
  `lxqt-config-globalkeyshortcuts`。
- **圆角/透明失效**：没有合成器（LXQt + openbox 可安装 picom）。
- **高分屏菜单过小或过大**：用 `METROMENU_SCALE=1` / `=2` 覆盖，或检查 `Xft.dpi`。

## 开发

```bash
python3 -m py_compile metromenu/*.py
bash -n scripts/*.sh bin/metromenu
./scripts/install-panel-plugin.sh   # 需要 GTK/面板开发头文件
```

源码树内用 `./bin/metromenu` 运行（会自动设置 `PYTHONPATH`）。

## 目录结构

```
metromenu/
├── metromenu/
│   ├── application.py   # Gtk.Application / 单实例切换 / 缩放
│   ├── window.py        # 无边框窗口与交互
│   ├── apps.py          # 应用发现、搜索、启动、缓存
│   ├── tiles.py         # Metro 磁贴与网格
│   ├── icons.py         # 图标加载与磁盘缓存
│   ├── config.py        # 配置与默认磁贴
│   ├── actions.py       # 打开位置 / 编辑 / 加桌面 / 加面板等
│   ├── desktop.py       # 桌面检测与命令解析
│   ├── timing.py        # 启动计时（METROMENU_TIMING=1）
│   └── style.css        # Metro 主题
├── assets/              # 图标
├── data/                # .desktop 模板
├── bin/metromenu        # 源码树启动器
├── panel-plugin/        # 原生 Xfce 面板插件（C）
└── scripts/             # 安装 / 卸载 / 面板集成 / 快捷键
```


## 许可证

[GPL-3.0-or-later](LICENSE)
