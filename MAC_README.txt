Mac 使用说明

1. 先把整个项目文件夹拷到 Mac 上。
2. 如果双击脚本没有反应，先打开“终端”，进入项目目录后执行：
   chmod +x build_mac.command run_exporter_mac.command
3. 直接运行：
   双击 run_exporter_mac.command
4. 打包成 .app：
   双击 build_mac.command
   打包完成后，会在 dist_mac 目录生成 douban_record_export_mac.app

说明：
- 需要 Mac 上有 Python 3。
- 第一次运行时会自动创建本地虚拟环境并安装依赖。
- 如果 macOS 提示来源不明，请右键脚本或 .app，选择“打开”。
