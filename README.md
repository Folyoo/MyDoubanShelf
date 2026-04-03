# 豆瓣记录导出

这个工具用于抓取豆瓣账号的标记记录，并导出为 CSV 和可筛选的 HTML 页面。

当前版本支持：

- 读书：想读 / 在读 / 读过
- 影视：想看 / 在看 / 看过
- 音乐：想听 / 在听 / 听过
- 游戏：想玩 / 在玩 / 玩过
- 舞台剧：想看 / 看过

## 主要功能

- 导出总表 CSV、汇总 CSV、分类 CSV
- 生成分类 HTML 页面和总览首页
- 页面内支持搜索、状态筛选、标记日期范围筛选、作品时间范围筛选
- 支持按表头快速排序
- 支持分页，默认每页 20 条
- 长文本字段支持折叠：
  - 作者 / 演职信息 / 表演者等列
  - 短评列
- 支持“我的评分”和“豆瓣评分”
- 默认优先使用本地上一次导出做增量更新，减少重复抓取
- 如果需要，可以切换为全量刷新

## 导出结果

每次导出会生成一个带时间戳的目录，包含：

- `douban_marks_all.csv`
- `douban_summary.csv`
- `douban_book_marks.csv`
- `douban_movie_marks.csv`
- `douban_music_marks.csv`
- `douban_game_marks.csv`
- `douban_drama_marks.csv`
- `index.html`
- `book.html`
- `movie.html`
- `music.html`
- `game.html`
- `drama.html`

## 主要字段

明细表包含这些核心字段：

- `title`：标题
- `douban_rating`：豆瓣公开评分
- `rating`：我的评分
- `marked_date`：标记日期
- `content_date`：从简介里提取出的最早相关时间
- `intro`：作者 / 演职信息 / 表演者 / 平台类型等
- `comment`：短评

## 图形界面

直接运行：

```bat
run_exporter.bat
```

或者：

```powershell
python app.py
```

界面里可以设置：

- 豆瓣账号或主页链接
- 导出目录
- 是否优先复用上一次导出，只更新差异部分
- Cookie（可选）

## 命令行

基础用法：

```powershell
python app.py --account "https://www.douban.com/people/example-user/" --no-gui
```

常用参数：

- `--output-dir`
- `--cookie`
- `--categories`
- `--statuses`
- `--full-refresh`
- `--no-gui`

示例：

```powershell
python app.py --account example-user --categories book,movie --statuses wish,collect --no-gui
```

强制全量刷新：

```powershell
python app.py --account example-user --full-refresh --no-gui
```

## 增量更新说明

当前版本默认会尝试读取同一导出根目录下、同一账号的最近一次导出结果。

如果网页新数据和旧结果之间能找到稳定重叠区间，就会直接复用旧尾部，只更新差异部分。这样在“最近新增不多”的情况下会明显更快。

如果找不到稳定重叠区间，程序会自动回退到全量抓取，不需要手动处理。

## Cookie 说明

- 默认抓取公开可见页面
- 不需要豆瓣密码
- 如果公开页抓不到、被限制，或者你希望尽量按登录后视图导出，可以提供 Cookie
- 工具不会单独保存你在界面里粘贴的 Cookie

建议不要把 Cookie 文件提交到 Git 仓库。

## 打包与发布

### Windows

当前项目里的可执行文件在 `dist/`：

- `douban_record_export.exe`
- `douban_record_export_cli.exe`

### Mac

项目中已经提供：

- `build_mac.command`
- `run_exporter_mac.command`
- `MAC_README.txt`
- GitHub Actions 工作流：`.github/workflows/build-macos.yml`

如果你把项目推到 GitHub：

- 推送到 `master` 或 `main` 会自动构建 macOS 包并上传为 Actions artifact
- 推送 tag（例如 `v1.0.0`）时，会额外把 macOS 压缩包挂到 GitHub Release

详细说明见：

- `GITHUB_ACTIONS_MAC_BUILD.md`

## 推荐发布方式

如果只是自己本地使用，直接运行源码或 `dist/` 里的 exe 就够了。

如果要发给别人，推荐优先用：

1. GitHub Release
2. GitHub Actions artifact

这通常比把大型二进制文件长期提交到 Git 仓库更合适。

## 开发提示

- Windows 打包缓存目录：`build/`
- Mac 打包缓存目录：`build_mac/`
- 本地评分缓存目录：`.douban_cache/`

这些目录通常不需要提交。
