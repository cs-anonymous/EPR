# ABCX Aligned Format - 快速使用指南

## 文件扩展名

Aligned ABCX 格式使用 **`.abcxa`** 扩展名。

例如：
- `score.abcxa`
- `Tico-Tico.abcxa`

## 格式说明

使用 `H1`, `H2`, ... 标记乐句，`M1`, `M2`, ... 标记小节：

```abcx
X:1
T:Tico Tico no fubá
C:Zequinha Abreu
%%score { 1 | 2 }
L:1/16
Q:1/4=100
M:2/4
K:C
H1
M1	!f! [ee'][dd']2[cc'] [Bb]2[Aa]2 ; [E,E][D,D]2[C,C] [B,,B,]2[A,,A,]2
M2	[^G^g]2[Bb]2 [cc']2[dd']2 ; [^G,,^G,]2[=G,,=G,]2 [^F,,^F,]2[=F,,=F,]2
```

## 在 VS Code 中使用

1. **创建文件**：使用 `.abcxa` 扩展名
2. **语法高亮**：
   - **H1, H2, ...** 显示为**青色**（加粗）
   - **M1, M2, ...** 显示为**黄色**（加粗）
3. **预览**：点击右上角预览按钮
4. **导出**：MIDI、SVG、ABC 等格式

## 重新加载 VS Code

修改插件后需要重新加载：
- 按 `Ctrl+Shift+P`
- 输入 `Developer: Reload Window`
- 按回车

## 批量转换现有文件

```bash
# 转换单个文件
mv score_aligned.abcx score.abcxa

# 批量转换所有 _aligned.abcx 文件
find . -name "*_aligned.abcx" -exec bash -c 'mv "$0" "${0/_aligned.abcx/.abcxa}"' {} \;
```

完成！现在打开 `.abcxa` 文件即可看到语法高亮和预览功能。
