#!/bin/bash
# ABCX Aligned Format - 安装和使用指南

echo "==================================="
echo "ABCX Aligned Format 插件增强"
echo "==================================="
echo ""

echo "📦 安装步骤："
echo ""
echo "1. 重新加载 VS Code 窗口"
echo "   - 按 Ctrl+Shift+P (Mac: Cmd+Shift+P)"
echo "   - 输入 'Developer: Reload Window'"
echo "   - 按 Enter"
echo ""

echo "2. 打开测试文件"
echo "   - 文件: PianoCoRe/aligned/Abreu,_Zequinha/Tico-Tico_no_fubá/score_aligned.abcx"
echo "   - 或: abcx/test/test_aligned.abcx"
echo ""

echo "3. 验证语法高亮"
echo "   - H1, H2, ... 应显示为青色/蓝绿色（加粗）"
echo "   - M1, M2, ... 应显示为黄色（加粗）"
echo ""

echo "4. 测试预览功能"
echo "   - 点击编辑器右上角的预览按钮（眼睛图标）"
echo "   - 或按 Ctrl+Shift+P → 'ABC: Show Preview'"
echo ""

echo "5. 测试导出功能"
echo "   - 在预览窗口中点击 MID、SVG、ABC 等按钮"
echo ""

echo "==================================="
echo "✅ 功能验证"
echo "==================================="
echo ""

# 运行测试
if [ -f "test_aligned_format.js" ]; then
    echo "运行自动化测试..."
    echo ""
    node test_aligned_format.js
    echo ""
else
    echo "⚠️  测试文件未找到: test_aligned_format.js"
    echo ""
fi

echo "==================================="
echo "📚 文档链接"
echo "==================================="
echo ""
echo "- 快速入门: abcx/QUICKSTART_CN.md"
echo "- 完整文档: abcx/ALIGNED_FORMAT_CN.md"
echo "- 更改日志: abcx/CHANGES.md"
echo "- 实现总结: ALIGNED_IMPLEMENTATION_SUMMARY.md"
echo ""

echo "==================================="
echo "🎵 示例文件"
echo "==================================="
echo ""
echo "- 简单示例: abcx/test/test_aligned.abcx"
echo "- 完整乐曲: PianoCoRe/aligned/Abreu,_Zequinha/Tico-Tico_no_fubá/score_aligned.abcx"
echo ""

echo "==================================="
echo "🔧 故障排除"
echo "==================================="
echo ""
echo "如果语法高亮不显示："
echo "  1. 确保文件扩展名为 .abcx"
echo "  2. 重新加载 VS Code 窗口"
echo "  3. 检查文件格式（H 标记单独一行，M 标记使用 Tab）"
echo ""
echo "如果预览显示错误："
echo "  1. 查看预览窗口顶部的诊断信息"
echo "  2. 确保每个小节都有分号 (;) 分隔声部"
echo "  3. 检查 Tab 字符是否正确"
echo ""

echo "==================================="
echo "✨ 完成！"
echo "==================================="
echo ""
echo "ABCX 插件现已支持 aligned 格式！"
echo "请在 VS Code 中重新加载窗口以激活新功能。"
echo ""
