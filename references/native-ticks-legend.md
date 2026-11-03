# 原生半刻度与图例

2026-10-08用户要求保留半刻度并学习图例科学内容/位置；2026-11-03进一步明确可见刻度朝外、所有文字常规体、曲线0.5pt。后者取代旧向内刻度和粗体设置。字号、配色、画布、符号大小、半刻度数量及科学图例规则保持。

## 半刻度

- 对可见的连续**线性**X/Y/Y2轴，每两主刻度之间设1个不标数字的次刻度；位置为两主刻度的算术中点。主间隔仍由真实轴范围和既有nice increment选择，不固定为5或20。
- 可见主次刻度向外；主长度3pt，次长度1.5pt。上轴、普通右框保持既有无刻度设置，循环右CE轴实际显示主次刻度。轴框和主次刻度线宽各保持1.0pt，不由曲线0.5pt反推。
- Origin原生接口：主`TicksByData$=""`、`inc`；次`mticksbydata$=""`、`minorTicks=1`；主次向外`ticks=10`。清除模板继承的自定义次位置，避免“count1”却不在中点。保存重开核对count、mask、长度、custom positions、原有尺度/方向和常规体状态。
- ICP元素分类X轴不加数值半格；连续Y照常。对数轴不继承线性算术半步；默认关闭次刻度，要用log独立计数需明确`axis_ticks.log_minor_tick_count`及尺度。已有log10 D数值使用线性Y，其次刻度按线性处理。
- 本机Origin2024独立探针`ticklength=3, mticklength=1.5`保存回读一致，85mm/1005 SVG单位导出主13/次6（整数舍入）；中点误差≤0.5 SVG单位。`mticklength=0`会画零长线，不能当Auto。历史missing sentinel只代表未取得明确数值。
- 线性反向轴使用带方向的增量。**反向log10目前显式拦截**：本机探针中交换端点可能触发Origin自动改界；试验修正后虽可保存端点与图例，却在导出中改变Y轴物理位置并裁切。没有完整验收，实验修正不进入运行能力，不能只看reverse标志或端点宣称成功。合成探针不是GITT推荐科学尺度。

历史方向和刻度观察不替代当前任务配置；公开版使用模板中的向外刻度。

**历史XRD观察**：`XRD.opju Graph1 L1`、`XRD aftercycle.opju Graph1`底轴`ticks=10`向外且Y刻度/数字隐藏；2026-11-03的`B1 XRD.opju Graph1`底轴也为向外。当前统一向外来自用户明确指令，不复制这些图的隐藏轴/数字设置。B1主图的轴框宽度混合、刻度宽与次长部分未取得有效值，因此维持已有1.0pt轴框/刻度宽和3/1.5pt长度。细节见 [参考取舍](visual-application.md)。

## 内容与位置

图例内容来自已核对的计划身份，不来自文件名或历史截图。比较样品则写样品；比较循环则写圈数；倍率GCD的比较对象可以是倍率。多样品多圈应保留两种身份。只有科学身份和样式共享的充放两支才可合并图例；reference与测量角色不得混为一项；拟合/背景/组分曲线不在本技能范围。

|历史结构|观察位置|可复用逻辑/来源|
|---|---|---|
|单样品多圈GCD|左下|图例是圈数；GCD另写样品。`Sample_A 比容量-电压图.opju Graph2 Legend`。旧5nd/10nd/40nd文字错误不沿用。|
|首圈多样品GCD|左下|每样品一项，两支不重复；`首圈充放电曲线 dqdv.opju Graph1 Legend`链接1/3/5。|
|EIS|左上|每实测样品一项；`EIS beforecycle.opju Graph1 Legend`。已有明确参考另保留角色，不接拟合曲线。|
|循环容量/CE|左下|每样品一行，容量实心/CE空心并列，名字一次；`循环 100圈.opju Graph1 Legend/Text`。左右轴及指标说明明确。|
|倍率性能|阶段下方；原图无样品legend|stage文字表示连续Rate条件，不替代样品名；`倍率.opju Graph1 Text~Text5`。新多样品输入仍需样品legend。|
|Na–电压|右下|每样品一项；`钠含量-电压.opju Graph1 Text`。不同样品文本与E/F、I/J列身份冲突，只学位置不抄标签。|
|GITT结果|左下/拼图面板空白|样品legend，Charge/Discharge另作分支/子图说明；`GITT\GITT.opju Graph1/2`与`PNG\GITT成图.png`不是同一布局版本。|
|XRD、ICP|右上|样品legend；PDF身份另写，元素是ICP横轴。`XRD.opju Graph1 Legend/Text`、`ICP.opju Graph1 Legend`。XRD旧legend样品/列身份互换不能沿用。|

这些位置仅是候选，不能强制所有新数据套同一个角落。`legend.position`支持`auto/top_left/top_right/bottom_left/bottom_right`；auto在四角和内部网格以**实际原生文字包围框**检查点、连线和已有native标签，考虑各曲线自己的Y/Y2、log和轴方向。图例、阶段及其他原生文字均常规体，字号保持。图例attach0层框，阶段标注仍attach2科学坐标。保留完整名称和`\l(n)`实际曲线链接，改名ScientificLegend防默认重建覆盖。尺寸放不下时明确报告，不缩字、截名、删数据或改画布。

图例最后使用官方可读写的`left/top`物理坐标定位并回读，不用数据轴x/y中心换算定位；后者在本机反向log轴中实测不能可靠保持文字框。未配置的点径/线宽只读Origin实际值用于避让，不写默认样式。

循环默认`legend.layout=paired_samples`，原生每行链接实际容量/CE符号series_id，由通用后端解析到真实plot ordinal；不硬编码历史plot顺序。`series_entries`保留之前每Sample×Metric独立项兼容布局。配对标题按先容量、再CE说明，不进行数值计算。保存重开验证完整文字（含链接），actual bbox及attachment；编辑性探针的新换行经原生Label -sa解析，修改副本后独立捕获新边界。

几何评分0不能代替查看导出图。存在碰撞或未量测标签保留needs_image_review；完整验收仍走五阶段gate。继承文字装饰、过密点、科学来源不完整等问题不能因为刻度/图例局部通过而宣称整图通过。

## 一手接口

- [Origin Scale](https://docs.originlab.com/origin-help/axesref-scale/)：By Counts=1定义半步。
- [Line and Ticks](https://docs.originlab.com/origin-help/axesref-lineticks/)：对话框minor Auto为主长度一半；程序本次用显式半长度。
- [Layer.Axis](https://docs.originlab.com/labtalk/ref/layer-axis-obj/)：inc/minorTicks/ticks/length属性。
- [Graphic Objects](https://docs.originlab.com/labtalk/ref/graphic-objs/)：attach、数据中心与物理文字框。
- [Label](https://docs.originlab.com/labtalk/ref/label-cmd/)：百分比定位、左对齐和换行转换。
- [Manual Legend Control](https://docs.originlab.com/origin-help/legend-manualcontrol/)：改名与保留原生符号链接。

详细历史审计和测试只留任务目录，运行时按需读本页。仅采用当前用户明确授权且已取得有效读值的参考参数，不整包导入旧OPJU样式或整张图片。
