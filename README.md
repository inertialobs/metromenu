# Metro Menu —— Windows 10 风格开始菜单（Xfce / LXQt）

一个在 Xfce 桌面上运行的、仿 Windows 10 的经典开始菜单：左侧应用列表，右侧
Metro 磁贴，无边框窗口，支持搜索、磁贴缩放/换色/分组、实时磁贴和电源操作。

实现基于 **PyGObject + GTK3**（原生 GTK 渲染，非 Web 栈），应用发现与启动逻辑
参考了 [xfce4-whiskermenu-plugin](https://gitlab.xfce.org/panel-plugins/xfce4-whiskermenu-plugin)
的做法（freedesktop `.desktop` 解析、XDG 目录去重、`%` 字段码展开、终端启动）。

## 特性

- **两栏布局**：左栏为应用列表 / 搜索，右栏为分组磁贴，左下角固定“设置 / 用户 /
  电源”按钮（设置按钮在用户按钮上方，打开系统设置）。
- **Metro 磁贴**：`small / medium / wide / large` 四种尺寸，任意配色，右键可
  调整大小、更改颜色、移动分组、取消固定。
- **实时磁贴**：`@clock` 时钟、`@date` 日期、`@system` CPU/内存占用，每秒刷新。
- **应用列表**：默认显示“常用”，可切换到“所有应用”（按首字母分组），
  条目右键支持打开、固定、置顶、打开文件位置、编辑、复制命令、加桌面/面板、隐藏。
- **右键菜单**：磁贴与应用列表项共用一套 Windows 10 风格菜单，并按 Linux 特点扩展
  （打开文件位置、编辑菜单项、复制启动命令、添加到桌面/面板、隐藏应用）。
- **搜索**：按名称 / GenericName / 注释 / 关键词 / 可执行文件加权排序，同时过滤
  左侧列表与右侧磁贴。
- **原生集成**：可从面板 Launcher 按钮启动，也可编译为**原生面板插件**
  （等同 Whisker，出现在“添加新项目”里），还可绑定键盘快捷键（如 `Super`）唤醒。
- **无边框窗口**：`decorated=False`，锚定屏幕工作区左下角，点击外部自动关闭，
  再次触发则切换显示/隐藏。
- **可配置**：布局保存在 `~/.config/metromenu/config.json`（纯 JSON）。

## 右键菜单

磁贴与应用列表项共用一套菜单（`window.py:_build_app_menu`），参照 Windows 10
开始菜单并做了 Linux 化：

| 菜单项 | 说明 |
| --- | --- |
| 打开 / 操作 ▸ | 启动应用 / 执行 `.desktop` 的 Desktop Actions |
| 调整大小 ▸ | 磁贴尺寸（小/中/宽/大，带勾选） |
| 更改颜色 ▸ | **色块 + 中文颜色名**，另有“自定义颜色…”打开取色器 |
| 移动到分组 ▸ | 磁贴分组（带勾选） |
| 实时磁贴 ▸ | 仅时钟/日期/系统磁贴，可开/关 |
| 置顶 | 磁贴移到本组最前；列表项移到“常用”最前 |
| 固定到“开始”屏幕 / 取消固定 | 增删磁贴 |
| 打开文件位置 | `org.freedesktop.FileManager1.ShowItems` 在文件管理器中选中该 `.desktop`（回退打开所在目录） |
| 编辑菜单项 | 用默认编辑器打开 `.desktop` |
| 复制启动命令 | 复制 `Exec` 到剪贴板 |
| 添加到桌面 | 复制 `.desktop` 到桌面目录并标记可信 |
| 添加到面板 | 作为 launcher 项追加到 Xfce 面板 |
| 隐藏此应用 | 记入 `config["hidden"]`，不再显示（用户菜单里“恢复隐藏的应用”可全部还原） |

说明：列表项右键是在 `Gtk.ListBox` 上统一处理的（`_on_list_button_press`）——因为
`Gtk.ListBoxRow` 没有自己的 `GdkWindow`，行级事件不会触发。

## 进程生命周期与开销

菜单是单实例 `Gtk.Application`。默认 `"keep_alive": false`：点击外部 / `Esc` /
启动应用后窗口隐藏，**进程随即退出**（空闲占用为 0）。下次打开需要冷启动。

若希望像 Whisker 那样常驻（再次触发瞬间切换、不重新扫描），把配置改成
`"keep_alive": true`。代价是常驻一个 Python + GTK 进程，实测 RSS 约 **84 MB**
（Whisker 是 C 面板插件，菜单窗口寄居在 `xfce4-panel` 进程内，不额外起进程，
通常十几 MB）。

| 模式 | 空闲内存 | 打开延迟（缓存热） |
| --- | --- | --- |
| `keep_alive: false`（默认） | ~0 | 首帧 ~0.39s，内容 ~0.44s |
| `keep_alive: true` | ~84 MB | 瞬时 |

### 冷启动优化（参考 Whisker 的做法）

Whisker 之所以“秒开”，是因为它常驻面板进程、在**后台线程**里加载菜单并缓存结果。
我们无法常驻（Python+GTK 冷启动约 190ms 不可避免），于是采用等价思路：

1. **先显示后填充**：窗口先 map/绘制（只剩竖栏与搜索框），应用列表与磁贴随后在
   `GLib.idle_add` 里填充 —— 首帧 ~0.39s，内容再花 ~50ms 出现。
2. **应用列表落盘缓存**：解析结果缓存在 `~/.cache/metromenu/apps.json`。
3. **图标落盘缓存**：渲染后的图标 PNG 缓存在 `~/.cache/metromenu/icons/`
   （20 个图标从 ~100ms 降到 ~5ms）。

**缓存如何失效（安装新软件会自动重扫）**：缓存里存有一份 `.desktop` 文件的指纹
——对每个文件记录 `路径 + mtime + 大小` 后取 SHA1。**安装、卸载或原地修改**任何
`.desktop` 都会改变指纹，下次打开菜单即触发重新扫描（仅 stat 文件，不解析，实测
~10ms）。此外还带 7 天 TTL 兜底。想强制重扫可用 `metromenu --no-cache`。



## 目录结构

```
metromenu/
├── metromenu/          # Python 包
│   ├── application.py       # Gtk.Application / 单实例切换
│   ├── window.py            # 无边框开始菜单窗口与交互
│   ├── apps.py              # freedesktop 应用发现、搜索、启动
│   ├── tiles.py             # Metro 磁贴控件与网格排布
│   ├── icons.py             # 图标加载与缓存
│   ├── config.py            # 配置读写与默认磁贴
│   └── style.css            # Metro 主题
├── assets/                  # 图标（SVG + 多尺寸 PNG）
├── data/                    # .desktop 模板
├── bin/metromenu       # 源码树内可直接运行的启动器
├── panel-plugin/            # 原生 Xfce 面板插件（C 源码 + 描述文件；LXQt 用 Custom Command 代替）
├── scripts/                 # 安装 / 卸载 / 面板集成 / 快捷键（自适应 Xfce 与 LXQt）
└── reference/whiskermenu/   # 参考用的 whisker 源码（git clone）
```

## 依赖

- Python 3 与 PyGObject（`python3-gi`）
- GTK 3 运行时、`gir1.2-gtk-3.0`
- 可选：Xfce 用 `xfconf`、`xfce4-panel`；LXQt 用 `lxqt-panel`、`lxqt-leave`、
  `lxqt-config`、`lxqt-globalkeys`（用于集成与电源/设置操作）；
  `systemctl` / `loginctl`（电源兜底）

Debian/Ubuntu：

```bash
sudo apt install python3-gi gir1.2-gtk-3.0
```

## 直接运行（源码树）

```bash
./bin/metromenu
```

## 安装到用户目录

```bash
./scripts/install.sh              # 安装命令 + 桌面项 + 图标
./scripts/install.sh --panel      # 额外在面板最左侧添加开始按钮
./scripts/install.sh --hotkey     # 额外绑定 <Super> 键
./scripts/install.sh --panel --hotkey='<Super>s'
```

安装脚本会写入：

- `~/.local/share/metromenu/`（程序）
- `~/.local/bin/metromenu`（命令包装器）
- `~/.local/share/applications/metromenu.desktop`
- `~/.local/share/icons/hicolor/*/apps/metromenu.png|svg`

## 在 LXQt 上使用

代码本身是独立的 GTK3 应用，可直接在 LXQt（X11）下运行；仓库里与 Xfce 绑定的
集成点已改为按运行时桌面自适应：

| 位置 | 过去（写死 Xfce） | 现在 |
| --- | --- | --- |
| 电源/注销/设置 `window.py` | `xflock4` / `xfce4-session-logout` / `xfce4-settings-manager` | 优先 `lxqt-leave --lockscreen/--logout/--suspend/--reboot/--shutdown`、`lxqt-config`、`lxqt-admin-user`，再回退 Xfce |
| 应用发现 `apps.py` | `OnlyShowIn`/`NotShowIn` 硬编码 `XFCE` | 按 `XDG_CURRENT_DESKTOP` 动态匹配（LXQt 下不再误隐藏 `OnlyShowIn=LXQt` 的应用） |
| 默认磁贴 `config.py` | thunar / xfce4-terminal … | pcmanfm-qt / qterminal / featherpad / lximage-qt / lxqt-archiver / lxqt-config …（Xfce 项保留为兜底） |
| 终端/文件管理器/编辑器 | 缺 qterminal / pcmanfm-qt / featherpad | 已加入 |
| 添加到面板 `actions.py` | xfconf | LXQt 写 `~/.config/lxqt/panel.conf` 的 Custom Command 组件，Xfce 走原 xfconf 路径 |

> 注意：LXQt 1.4 的 `lxqt-leave` 没有 `--switch-user`，菜单里的“切换用户”
> 会尝试 `dm-tool`；若没有显示管理器该操作无效。

安装与集成（脚本已按 LXQt 分支）：

```bash
./scripts/install.sh --panel          # 安装 + 在面板最左侧加“自定义命令”按钮
./scripts/install.sh --hotkey         # 绑定 <Super>（写入 lxqt globalkeyshortcuts.conf）
./scripts/uninstall.sh --panel --hotkey --purge
```

- 面板按钮：`integrate-panel.sh` 会在 `~/.config/lxqt/panel.conf` 里追加一个
  `type=customcommand`、`command=metromenu` 的组件，并插到 `plugins=` 最前面；
  LXQt 面板会监视该文件并自动重载。若未生效，可在面板“添加部件”里手动选
  **Custom Command**，命令填 `metromenu`、图标选 `metromenu`。
- 快捷键：`menu-hotkey.sh` 把 `<Super>` 等 GTK 写法转换成 LXQt 的 `Meta%2B…`
  写入 `~/.config/lxqt/globalkeyshortcuts.conf`；若未立即生效，运行
  `lxqt-config-globalkeyshortcuts` 或重新登录。
- 合成器：LXQt + openbox 默认无合成器，窗口 `opacity` 与圆角不会混合，
  会退化为不透明方角；需要毛玻璃效果时装 picom 即可。
- **HiDPI / 缩放**：GTK 只会从 XSETTINGS 的 `Gdk/WindowScalingFactor` 自动取整数
  缩放，而 LXQt 没有 XSETTINGS 守护进程，它改写的是 `Xft.dpi`（2x 桌面通常为 192）。
  因此启动时若 `GDK_SCALE` 未设置，metromenu 会读取 `Xft.dpi` 并自动设置
  `GDK_SCALE`（192 → 2x），让菜单与桌面其它程序一致；否则菜单会以 1x 渲染，在高分屏
  上看起来只有一半大小。想手动指定可用环境变量 `METROMENU_SCALE=2`（或 `GDK_SCALE`），
  `METROMENU_SCALE=1` 可强制回到 1x。窗口的 `width`/`height`/`left_width` 仍按逻辑像素
  配置（`config.json`），实际设备像素 = 逻辑值 × 缩放。

LXQt 面板**不能**加载 `panel-plugin/` 里的原生插件——那是 `libxfce4panel` 的
ABI（`xfce_panel_module_construct`），与 LXQt 的 `ILxQtPanelPlugin`（Qt）不兼容。
`install-panel-plugin.sh` 在 LXQt 下会直接提示改用上面的 Custom Command。

## 面板集成原理（Xfce）

Xfce 4.20 支持**用户级**面板插件：描述文件放在
`~/.local/share/xfce4/panel/plugins/`，模块 `.so` 放在
`~/.local/lib/<multiarch>/xfce4/panel/plugins/`（见面板源码
`panel-module-factory.c`，它会从 `XDG_DATA_DIRS`/用户数据目录推导路径）。
插件本质是导出 `xfce_panel_module_construct` 的 `.so`，由面板加载。

### 方式一：原生插件（推荐，等同 Whisker）

```bash
# 一次性安装开发头文件
sudo apt install libgtk-3-dev libxfce4panel-2.0-dev

./scripts/install-panel-plugin.sh          # 编译并安装（用户级，无需 root）
./scripts/install-panel-plugin.sh --add    # 顺便插入 panel-1 最左侧并重启面板
```

`panel-plugin/metromenu-plugin.c` 是一个约 120 行的 C 插件：面板按钮点击时，
若已有实例则通过 D-Bus（`org.gtk.Application.Activate`）让其切换，否则启动
`metromenu --anchor=x,y,w,h`，把菜单锚定到按钮旁边（面板在下→弹在按钮上方）。
装好后它也会出现在面板的 *添加新项目* 列表里。

### 方式二：Launcher 按钮（无需编译）

Xfce 面板的 Launcher 插件把每个按钮存成
`~/.config/xfce4/panel/launcher-<插件ID>/*.desktop`，并在 xfconf 里登记：

```
/plugins/plugin-<N>        = "launcher"
/plugins/plugin-<N>/items  = [item.desktop]
/panels/panel-1/plugin-ids = [<N>, 7, 2, ...]
```

`scripts/integrate-panel.sh` 会找到空闲插件 ID `N`，创建 `launcher-N/` 目录并写入
一个 `Exec=metromenu` 的桌面项，注册 `plugin-N` 并插到 plugin-ids 最前面，
最后 `xfce4-panel --restart`。

因为程序是单实例 `Gtk.Application`，再次点击按钮会切换显示/隐藏。

卸载：

```bash
./scripts/uninstall.sh --panel --hotkey --purge
```

## 快捷键

```bash
./scripts/menu-hotkey.sh '<Super>'      # Windows 键
./scripts/menu-hotkey.sh '<Super>s'
```

若 `Super` 无响应，请在 *设置 → 键盘 → 应用程序快捷键* 中确认它没有被
xfwm4 或 Whisker 菜单占用。

在 LXQt 下脚本会改写入 `~/.config/lxqt/globalkeyshortcuts.conf`（把 `<Super>`
翻译成 `Meta`）；若未立即生效，用 `lxqt-config-globalkeyshortcuts` 添加一条
“命令”快捷键指向 `~/.local/bin/metromenu`，或重新登录。

## 配置示例

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

删除该文件即可恢复默认布局；`"@clock"` / `"@date"` / `"@system"` / `"@recent"`
为内置特殊磁贴。

## 许可证

GPL-2.0-or-later（与参考的 Whisker Menu 保持一致）。
