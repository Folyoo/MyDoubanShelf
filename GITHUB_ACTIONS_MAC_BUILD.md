# GitHub Actions 自动发布

这个项目已经配置好了自动构建和自动发布。

- 工作流文件：`.github/workflows/build-macos.yml`
- 工作流名称：`Build Release Assets`

## 触发方式

- 推送到 `master` 或 `main`
- 手动在 GitHub 的 `Actions` 页面点击 `Run workflow`
- 推送版本 tag，例如 `v1.0.0`

## 会产出的文件

### 普通构建

在某次 workflow run 的 `Artifacts` 里可以下载：

- `douban_record_export_mac-<ref>.zip`
- `douban_record_export.exe`
- `douban_record_export_cli.exe`
- `douban_record_export_windows-<ref>.zip`

### tag 构建

如果推送的是 tag，例如：

```bash
git tag v1.0.0
git push origin master --tags
```

工作流会自动把下面这些文件挂到 GitHub Release：

- `douban_record_export_mac-v1.0.0.zip`
- `douban_record_export.exe`
- `douban_record_export_cli.exe`
- `douban_record_export_windows-v1.0.0.zip`

## 推荐下载方式

- Mac 用户：下载 `douban_record_export_mac-v1.0.0.zip`
- Windows 用户：
  - 可以直接下载 `douban_record_export.exe`
  - 也可以下载 `douban_record_export_windows-v1.0.0.zip`

## 发布流程建议

如果你想做正式发布，推荐这样做：

1. 提交并推送当前代码
2. 打一个版本 tag
3. 推送 tag
4. 等 GitHub Actions 跑完
5. 到 `Releases` 页面检查三个平台资产是否都已挂上

## 备注

- GitHub Actions 的 artifact 更适合测试下载
- GitHub Release 更适合正式对外分发
- 如果 macOS 提示来源不明，可以右键 `.app` 后选择“打开”
