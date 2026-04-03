# Mac

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


# 推荐发布方式

如果只是自己本地使用，直接运行源码或 `dist/` 里的 exe 就够了。

如果要发给别人，推荐优先用：

1. GitHub Release
2. GitHub Actions artifact

这通常比把大型二进制文件长期提交到 Git 仓库更合适。

# 开发提示

- Windows 打包缓存目录：`build/`
- Mac 打包缓存目录：`build_mac/`
- 本地评分缓存目录：`.douban_cache/`

这些目录通常不需要提交。