# Origin 点线效果与真实单位

2026-11-03当前规则：所有数据曲线统一0.5pt、文字常规体、可见刻度向外。循环/倍率圆点仍为5.8pt全点符号；颜色、字号、字体家族与画布沿用原配置。GCD仍为无圆点实线，不把倍率圆点加到GCD。刻度及图例另见 [对应规则](native-ticks-legend.md)。

2026-10-08倍率参考图曾测得圆点直径约为绘图区宽度3.31%、连线约为圆点直径18%，并采用过1.1pt连线。该旧线宽/比例已被0.5pt新指令取代，不能再用旧比例恢复粗线；5.8pt点径与实心容量/空心CE区别保留。点数增多造成重叠须如实披露，不自动删点、稀疏化或改变画布。`B1 XRD.opju`主图与辅助页线宽不一致，取舍见 [视觉配置](visual-application.md)；0.5pt依据是用户明确指令。

普通数据连线由全局`curves.line_width`提供，GCD及容量/CE样式中的显式线宽同步使用0.5pt。processed XY的line/line_points也必须明确写入和回读该值，不能继承Origin模板的旧线宽；scatter维持不连线。`0.8pt Line.otpu`只是既有模板名称，不代表当前曲线线宽。

## 后端约束

- Origin `set ... -z` 使用 **pt**，直接写symbol_size_pt，不能再乘pt_to_mm。
- 连线优先 `set ... -wp` 直接写 **pt**；旧 `-w` 使用pt×500，不能乘1000。
- 圆形 `-k 2`；实心 `-kf 0`、空心 `-kf 1`。颜色继续由既有plot/color配置传入。
- `-e` 控制数据显示末行，不能用于符号边宽；`-qf` 控制数据标签字体，不能用于填充色。这两个误用已删除。
- 符号边宽 `-kh` 的单位依赖“Scale by Symbol Size”：不能沿用连线单位换算。当前保留Origin模板的实际边框，不宣称0.8pt符号边框已实机兑现；待获得明确单位状态后再扩展，不猜属性名。
- 保存重开后读取 `get ... -z/-k/-kf/-wp`，对比实际点径、形状、填充和线宽；另外检查导出图像中的点线关系。倍率阶段标签垂直避让同时考虑文字及圆点，水平位置仍按连续阶段中心。

[Origin Symbols 官方接口](https://docs.originlab.com/labtalk/ref/options_for_symbols/)、[Lines 官方接口](https://docs.originlab.com/labtalk/ref/options_for_lines/)、[Symbol Tab](https://docs.originlab.com/origin-help/pd-dialog-sym-tab/)、[Set](https://docs.originlab.com/labtalk/ref/set-cmd/)。本机独立Origin2024实测 -z3.5/6.5、-wp0.8、-w400、-kf0/1均可按相应值回读，证据保存在优化任务目录。
