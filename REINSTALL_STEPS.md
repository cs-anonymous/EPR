# 重新安装步骤

1. **完全卸载旧版本**
   - 在 VS Code 中打开扩展面板（Ctrl+Shift+X）
   - 搜索 "ABCX Tools"
   - 点击卸载

2. **重新加载 VS Code**
   - 按 Ctrl+Shift+P
   - 输入 "Developer: Reload Window"
   - 按回车

3. **安装新版本**
   ```bash
   code --install-extension /home/sy/EPR/abcx/abcx-tools-0.3.3.vsix
   ```

4. **再次重新加载 VS Code**
   - 按 Ctrl+Shift+P
   - 输入 "Developer: Reload Window"
   - 按回车

5. **测试**
   - 打开 aligned 格式的 .abcx 文件
   - 点击预览按钮
   - 应该看到每个乐句（H1, H2, ...）在单独的行上
   - 每个乐句前面应该显示起始小节号
