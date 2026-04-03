# 豆瓣标记导出器

这个工具用于抓取豆瓣公开标记页中的书、影、音、游戏、舞台剧信息，并导出成 CSV 和 HTML 表格。

支持的分类与状态：
- 读书：想读 / 在读 / 读过
- 影视：想看 / 在看 / 看过
- 音乐：想听 / 在听 / 听过
- 游戏：想玩 / 在玩 / 玩过
- 舞台剧：想看 / 看过

## 导出结果

每次导出都会生成：
- `douban_marks_all.csv`：全部明细
- `douban_summary.csv`：分类汇总
- `douban_book_marks.csv`
- `douban_movie_marks.csv`
- `douban_music_marks.csv`
- `douban_game_marks.csv`
- `douban_drama_marks.csv`
- `index.html`：总览页
- `book.html`
- `movie.html`
- `music.html`
- `game.html`
- `drama.html`

## 字段说明

明细表包含这些核心字段：
- `title`：标题
- `rating`：个人评分
- `marked_date`：标记日期
- `content_date`：从简介里提取出的最早相关时间
- `intro`：简介，已去掉日期片段和价格信息
- `comment`：短评

## HTML 功能

每个分类页面都提供：
- 搜索框：支持按标题、相关时间、简介、短评、条目 ID 搜索
- 状态筛选
- 标记日期范围筛选
- 排序功能：可按标记日期、相关时间、标题、评分、状态排序
- 默认每页显示 20 条，并可切换每页条数
- 上一页 / 下一页分页
- 点击表头快速排序

## 运行

桌面界面：

```bat
run_exporter.bat
```

或：

```powershell
python app.py
```

命令行模式：

```powershell
python app.py --account "https://www.douban.com/people/sheagu/" --no-gui
```

可选参数：
- `--output-dir`
- `--cookie`
- `--categories`
- `--statuses`

## 说明

- 默认抓取豆瓣公开页面，不需要密码。
- 如果账号是私密的，或者你希望尽量按“登录后自己看到的列表”导出，可以提供 Cookie。
- 豆瓣列表页最后一条记录有时会使用 `item last` 类名，当前版本已兼容。
- 有些豆瓣公开列表页会在页头显示总数，但页面实际并不会把所有条目 HTML 都输出出来。当前版本只导出页面真实可见、可抓取的条目；如果你希望尽量按登录后的视图导出，建议补充 Cookie。
