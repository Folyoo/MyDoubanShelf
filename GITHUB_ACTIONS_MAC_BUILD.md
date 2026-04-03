# GitHub Actions 打包 Mac 版

这个项目已经带上了 GitHub Actions 工作流：

- 工作流文件：`.github/workflows/build-macos.yml`
- 触发方式：
  - 推送到 `master` 或 `main`
  - 手动在 GitHub 的 `Actions` 页面点 `Run workflow`
  - 推送 tag，例如 `v1.0.0`

## 你需要做什么

1. 把当前项目推到 GitHub 仓库。
2. 打开仓库的 `Actions` 页面。
3. 找到 `Build macOS App` 工作流。
4. 运行后下载产物：
   - 普通构建：在该次 workflow run 的 `Artifacts` 里下载 zip
   - tag 构建：除了 artifact，还会自动附加到 GitHub Release

## 推荐发布方式

如果你想让朋友直接下载：

```bash
git tag v1.0.0
git push origin master --tags
```

推送 tag 后，工作流会：

1. 在 GitHub 的 macOS runner 上打包 `.app`
2. 生成 zip
3. 上传到 workflow artifacts
4. 自动附加到同名 GitHub Release

## 朋友拿到的文件

下载文件名类似：

- `douban_record_export_mac-v1.0.0.zip`

解压后可以得到：

- `douban_record_export_mac.app`

第一次打开时，如果 macOS 提示来源不明，可以右键 `.app` 后选择“打开”。
