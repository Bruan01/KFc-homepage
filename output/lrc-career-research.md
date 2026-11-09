# 具身智能就业子方向 · 检索与可靠性说明

- 检索日期：2026-11-05
- 配套结构化数据：`output/lrc-career-tracks.json`（8 个子方向 + 三阶段求职时间线 + 简历建议 + 通用面试考点）
- 面向人群：零基础 / 跨专业转行求职者
- 本文目的：说明数据是怎么来的、哪些能信、哪些不能信、以及转行第一步该做什么

---

## 0. 来源性质分级（全文统一口径）

本文与 JSON 中所有信息都按三类标注，JSON 中每个 `tracks[].sourceBasis` 字段即为此用途：

| 标签 | 含义 | 可信度与使用方式 |
|---|---|---|
| **【官方 JD】** | 企业官方招聘页，或企业在招聘平台 / 高校就业网 / 政府就业平台上直接发布的岗位职责与任职要求 | 可用来确认「岗位真实存在、需要什么技能、用什么框架」。但其中的**挂牌薪资只是单个岗位区间**，不是行业水平 |
| **【官方开源项目文档】** | 项目官网、GitHub 仓库、官方文档（LeRobot、OpenVLA、robosuite、ORB-SLAM3、Isaac Lab 等） | 可用来确认「工具真实存在、入门项目可做」 |
| **【媒体转引】** | 政府网站转载的媒体报道、行业报告站的二次摘要、猎头 / 招聘平台公众号、研报汇编 | **只用于了解趋势方向，所有具体数字不采信**，除非注明口径 |
| **【厂商博客 / 行业评论】** | 企业博客、技术社区文章（如 Bifrost 的 VLA benchmark 选型文） | 可用于技术选型参考，但带产品推广立场，结论需回查一手论文 / 仓库 |
| **【行业推测】** | 本报告基于上述材料做的综合判断：热度评级、面试考点、新手坑、练手题目、学习路线 slug | 属建议性质，不是事实，尤其不能当薪资或需求依据 |

> 说明：部分「官方 JD」实际由**猎头或人才经纪人代发**（例：智联招聘上的「VLA 算法工程师 / 具身智能」由安徽金智人力资源杭州分公司发布、客户公司为浙江华锐捷；猎聘上「岗位 3：仿真与数据高级工程师」由锐仕方达猎头顾问汇总）。这类条目的岗位职责文本仍可用，但发布主体不是用人企业，权威性低于企业自己的招聘页，本文在来源清单中已注明。

---

## 1. 检索方法

共 4 轮，中英文混合，全部基于真实检索结果，未使用任何训练记忆中的公司名、薪资或岗位：

1. **第 1 轮**：具身智能算法工程师通用 JD、VLA 微调 / 评测岗、运动控制与规划岗。
2. **第 2 轮**：感知 / SLAM / 3D 视觉岗、仿真与数据工程岗、部署与工程化岗、本体与硬件岗。
3. **第 3 轮**：评测 / benchmark / 安全 / 产品岗、行业人才需求报告、开源入门项目核验。
4. **第 4 轮**：WebFetch 全文核验 2 份一手页面（Agile Robots SE 的 VLA Training & Evaluation JD、腾讯招聘官方「具身智能工业行业产品经理」JD）、核验 VLA 评测基准清单、检索零基础转行学习路线。

一次 WebFetch（广西自贸区钦州港片区政府网转载的《具身智能产业打响人才攻坚战》）抓取失败，相关内容以检索结果返回的正文片段为准，并已按「政府网站转载媒体报道」降级处理。

**样本**：本轮实际读到较完整岗位职责文本的岗位条目约 35 条，覆盖 8 个子方向；另有 2 份公众号汇编（南方新华薪资地图、高校就业「智企资讯」校招名录）。这是一份**便利样本（convenience sample）**，不是任何招聘平台的全量抓取，不能据此推断岗位占比、增长率或行业平均薪资。

---

## 2. 检索到的代表性岗位方向

8 个方向按「产出物不同」切分，彼此不重叠：VLA 交付策略 checkpoint、IL/RL 交付训练曲线与策略、运控交付控制器、感知交付地图与位姿、仿真数据交付数据集、部署交付端侧服务、硬件交付整机、评测产品交付指标与验收标准。

| # | 方向 | 代表性真实岗位（来源性质） | 典型职责关键词（来自 JD 原文） |
|---|---|---|---|
| 1 | VLA / 具身多模态大模型 | 智联招聘「VLA 算法工程师 / 具身智能」【官方 JD·猎头代发】；南昌大学就业网「厦门松霖机器人 VLA 算法工程师」【官方 JD·高校就业网】；猎聘「黑芝麻智能 VLA 大模型算法工程师（机器人）(J11193)」【官方 JD】；Agile Robots SE「Machine Learning Engineer – VLA Training & Evaluation」【官方 JD·WebFetch 已核验】 | 预训练 / SFT 微调、LoRA、动作分块、扩散策略、评测体系、真机部署 |
| 2 | 模仿学习与强化学习 | BOSS 直聘「甲壳虫智能 具身智能算法工程师」【官方 JD】；鱼泡直聘「乐聚智能 具身智能算法研发工程师」【官方 JD】；猎聘「具身算法工程师」【官方 JD】 | 机械臂 RL / IL、sim2real、ACT / RDT、任务成功率 |
| 3 | 运动控制与规划 | 猎聘「机器人规划控制算法（上 / 深 / 北）」【官方 JD】；江苏 24365 平台「豪森股份 运动控制工程师」【官方 JD·政府就业平台】；高才网「广州广日 机器人工程师（运动与控制方向）」【官方 JD·校招】 | MPC / WBC / LQR、QP 优化、轨迹规划、EtherCAT、真机调试、Safety Shield |
| 4 | 感知 / SLAM / 3D 视觉 | 猎聘「Lumos Robotics SLAM 算法工程师（具身智能方向）」【官方 JD】；湖南大学就业网「东阳光 感知算法工程师」【官方 JD】；智联招聘「三一集团 感知算法工程师（激光 / slam）」【官方 JD】 | 多传感器融合、VIO、回环 / 重定位、标定与时间同步、6D 位姿、3DGS / NeRF |
| 5 | 仿真与数据工程 | 猎聘「杭州市具身智能应用中试基地 数据算法工程师」【官方 JD】；猎聘「光轮智能 具身仿真数据采集项目经理」【官方 JD】；江苏 24365 平台「苏州珀瑞缇 具身数据算法工程师」【官方 JD】 | 数据采集管线、Episode 管理、域随机化、动作切分、数据飞轮、Real2Sim2Real |
| 6 | 部署与工程化 | 猎聘「吉翼具身智能 VLA 软件集成工程师」【官方 JD】；智联招聘「杭州美梦空间 模型部署 & SDK 开发工程师（具身端侧）」【官方 JD】；Renesas「具身智能 AI 前沿部署工程师」【官方 JD】 | ROS2 节点封装、TensorRT / ONNX、INT8 量化、Jetson、时延与长时稳定性 |
| 7 | 本体与硬件 | 猎聘「斜跃智能 嵌入式硬件工程师（轮式人形电控整机）」【官方 JD】；江苏人才网「立臻科技 智能体-电子工程师（人形机器人方向）」【官方 JD】 | 多层 PCB、FOC、EtherCAT / CAN、STM32 / RTOS、EMC、DFM / 量产 |
| 8 | 评测 / 安全 / 产品 | 腾讯招聘「具身智能工业行业产品经理」【官方 JD·企业官网，WebFetch 已核验，更新于 2026-10-08】；猎聘「逐际动力 具身智能产品经理（具身 Agent 方向）」【官方 JD】 | 评测集与成功率指标、bad case 归因、数据采集规范、节拍 / ROI / 回本周期、Agent Eval |

**关于「评测 / 安全」为何与 VLA 分开**：多份 VLA JD（智联 VLA 岗、Agile Robots VLA Training & Evaluation）确实把「建立评测体系」写进算法岗职责，但腾讯、逐际动力、TheJobsMap、广东亿迅等岗位把指标定义、失败归因、场景选型、PRD、ROI 作为**独立岗位**交付，且其技能组合（实验设计 + 统计 + 产品判断）与 VLA 微调不同，对零基础 / 非算法背景转行更友好，故单列。

---

## 3. 招聘关键词统计依据

### 3.1 统计口径（必须先读）

- **样本**：第 1 节所述约 35 条岗位条目，去重后按 8 方向归类；**不含**媒体转引文章里的「热门关键词总结」，只统计我自己读到的 JD 原文。
- **统计单位**：一个词在「多少份 JD 的职责 / 要求文本里出现」，不是词频，也不是全平台岗位数。
- **不能做的事**：这个样本**无法**得出「某关键词占全部岗位的百分之多少」「某方向招聘量增长多少」「哪个方向最缺人」这类结论。任何占比、增速、排名都需要平台全量数据，本轮没有。
- **因此**：JSON 里的 `demand`（hot / steady / niche）是**【行业推测】**，依据是「该方向在本样本中出现的 JD 份数 + 多份 JD 是否明确写成独立岗位 + 是否要求硕士 / 真机等稀缺条件」，**不是**任何平台统计结果。

### 3.2 高频词分层（样本内，约 35 条 JD）

| 层级 | 关键词 | 出现的方向 | 备注 |
|---|---|---|---|
| 几乎全方向公共 | Python、C++、PyTorch、Linux、ROS / ROS 2、真机部署 / 调试、硕士及以上 | 8 / 8 | 「硕士及以上」在算法端几乎成为常态，但数据 / 调试 / 交付端 JD 明确写了本科入口，故不能笼统说「全部要硕士」 |
| 高频（≥ 半数字方向） | 强化学习 / 模仿学习、Sim2Real、数据采集 / 遥操作、评测 / 任务成功率、Isaac Sim / MuJoCo / Gazebo、模型量化 / 推理加速、多传感器融合 | 5–7 / 8 | 「评测」「数据」「部署」三类词在 2026 年的 JD 里明显从算法岗溢出成独立职责 |
| 方向专属（集中出现） | VLA / SFT / LoRA / action chunk（方向 1）；ACT / Diffusion Policy / PPO / 离线 RL（方向 2）；MPC / WBC / QP / EtherCAT（方向 3）；SLAM / VIO / 点云 / 6D 位姿 / 回环（方向 4）；Episode / 域随机化 / 数据飞轮 / UMI（方向 5）；TensorRT / ONNX / INT8 / Jetson（方向 6）；PCB / FOC / STM32 / EMC / DFM（方向 7）；benchmark / bad case 归因 / ROI / PRD（方向 8） | 各 1–2 / 8 | 这些词最适合写进对应方向简历，因为就是 JD 原词 |

### 3.3 关键词的「可信度差异」

- **可直接采信**：工具名与框架名（LeRobot、OpenVLA、openpi、GR00T N1、SmolVLA、ACT、Diffusion Policy、ORB-SLAM3、FAST-LIO、LIO-SAM、Ceres / GTSAM、Pinocchio、OSQP、Isaac Sim / Isaac Lab、MuJoCo、TensorRT、ONNX Runtime、Jetson Orin / Thor、EtherCAT、Parquet / HDF5、Ray / Celery、LIBERO / MetaWorld / CALVIN / robosuite 等），因为它们在 JD 原文或官方项目文档里可回查。
- **需注明口径**：「熟悉 / 精通 / 掌握」这类动词在 JD 里的强度差异、以及「加分项」与「硬性要求」的区别，本报告按 JD 原文区分，但不做量化。
- **不采信为统计结论**：媒体文章里「运动控制、多模态感知、强化学习、VLA、VLM、世界模型是岗位描述中出现频率最高的关键词」这类表述（见 NSTL 门户转载文），它是二手总结，未给样本量与口径，本报告未把它计入 3.2 的表格。

---

## 4. 薪资与需求数字的不确定性（重点）

### 4.1 结论先说

> **本轮检索到的所有「行业平均薪资」「岗位增长倍数」「人才缺口人数」「需供比」数字，都属于【媒体转引】，本报告一律不采信、不写入 JSON、不作为求职或谈薪依据。** 唯一与薪资相关的、相对可核验的事实，是企业官方 JD 上针对**单个岗位**的挂牌区间，而它也不能代表行业水平。

### 4.2 官方 JD 上的挂牌薪资：为什么也不能当行业薪资

多份 JD 确实带薪资，但口径混乱，例如同一批 VLA / 算法岗里同时出现 `30-45K·15薪`、`25-45k·15薪`、`70-100k·15薪`、`18K-28K/月`、`2.5-5万/月·13薪`、`20-40k`、`2.8-5万·14薪`、`面议` 等写法。问题在于：

- **薪数不同**：13 / 14 / 15 / 16 薪混用，月薪与年薪、年包混用，税前税后未标明。
- **平台限制**：BOSS 直聘某 JD 原文就写「因 BOSS 薪资范围设限，实际上限不止显示的上限」；另有 JD 标注「面议」。
- **样本偏差**：高薪区间多来自资深 / 架构师 / 猎头高端岗位，校招岗与调试运维岗明显更低，把它们平均没有意义。
- **范围极宽**：同一方向 18K 到 100K 都有，说明它反映的是「岗位层级」而非「方向薪资」。

因此 JSON 里没有任何公司名、薪资数字或具体岗位名称，只有可迁移的技能、工具、关键词和项目。

### 4.3 媒体转引数字：逐条标注「不采信 / 注明口径」

以下数字均来自政府网站转载的媒体报道、报告站二次摘要、猎头公众号或研报汇编，**本报告不采信**，列出仅为了说明「为什么不能信」：

| 数字（原样摘录） | 转引出处 | 问题 / 口径 |
|---|---|---|
| 2026 年 1–4 月具身智能岗位招聘量同比暴涨 **15 倍**；招聘指数 **36 → 579** | 脉脉《2026 春招职场洞察报告》，经政府网站 / NSTL 门户 / 三个皮匠报告多次转引 | 「招聘指数」是平台自建指标，非职位数；时间窗只有 1–4 月；与下面「+75.26%」不可互相印证。**不采信** |
| 具身智能岗位平均月薪 **5.9 万 → 6.2 万**；具身智能平均月薪 **62000 元** | 脉脉同上 / 报告站汇编 | 与「机器人领域平均年薪 32.80 万」口径冲突（6.2 万/月 ≈ 74 万/年），样本定义完全不同。**不采信** |
| 近一年机器人领域新发职位 **+75.26%**，人形机器人 **+147.02%**；2026 年 1–7 月 **+60.17%** | 猎聘大数据研究院《2026 具身智能产业机器人领域人才供需洞察报告》，经报告站 / 门户转引 | 「新发职位数」与脉脉「招聘指数」、智联「职位数同比」是三个不同指标；时间窗（近一年 / 1–7 月 / 节后一个月）不一致。**不采信为可比较数字** |
| 机器人行业职位数同比 **+36.6%**；一季度行业职位增速 **38%** | 智联招聘数据，经报告站转引 | 又是另一套口径与分母。**不采信为可比较数字** |
| 人形机器人招聘平均年薪 **42.63 万元**，30 万以上岗位占 **62.88%**；机器人领域平均年薪 **32.80 万元** | 猎聘，经门户 / 报告站 / 南方新华公众号反复转引 | 三个数字被不同文章安到「具身智能」「人形机器人」「机器人」三个不同集合上，互相套用。**不采信** |
| 具身智能中位年薪 **80–200 万**；运动控制 3–5 年 **60–120 万**；具身智能算法工程师 **60–200 万**；应届算法岗 50 万年包被称「白菜价」；首席科学家 **1500 万起** | 南方新华猎头公众号（自述「数据来源于猎头交付案例」）、三个皮匠报告汇编 | **猎头交付案例 + 头部 offer + 媒体二次转引**，是典型的选择性样本与营销口径。**明确不采信** |
| 人才缺口 **100 万人**（北理工调研）／ **450 万人**（人社部预测） | 政府网站转载媒体文、南方新华公众号 | 450 万是「智能制造领域」全口径，不是具身智能；100 万是「调研口径」。领域不同却被并列引用。**不采信** |
| 需供比 **5.2:1**、求人倍率 **2.3**、人才供需比 **0.26** | 国务院研究室 / 南方新华 / 脉脉，分别转引 | 三个指标定义相反（岗位:人 vs 人:岗位），**混用会得出完全相反的结论**。**不采信** |
| 2030 年市场规模 **770 亿美元**、CAGR **94%**（IDC）；2035 年破**万亿**（国务院发展研究中心《中国发展报告 2025》） | 政府网站转载媒体文 | 属长期预测，不是招聘数据；本报告未用于任何方向判断。**不作为求职依据** |
| 2026 年 4 月教育部首批 **9 所**高校获批具身智能本科专业 | 政府网站转载媒体文 | 属政策类事实，但仍是媒体转引，**需以教育部原始专业目录核对**；可用来判断「科班供给短期跟不上」，不用来判断薪资 |

**一句话**：这些数字彼此矛盾（32.80 万 / 42.63 万 / 74 万 / 80–200 万）、指标互斥（招聘指数 / 新发职位 / 职位数）、主体混杂（平台大数据 / 猎头交付案例 / 研报测算 / 公众号二次转引），**不具备可交叉验证性**。转行者最该防范的，就是拿「平均年薪 XX 万」去规划转行预期或谈薪。

---

## 5. 转行者最该先补的三件事

按「先用最小成本换到最大面试面」排序，均为【行业推测】，但依据来自第 1 节的【官方 JD】与【官方开源项目文档】：

### 第一件：补齐公共底座 —— Python / C++ / Linux / 数学，而不是先买机器人

几乎所有 8 个方向的 JD 都写「精通 C++、Python」「扎实的数理基础（线性代数、概率论、优化方法）」「熟悉 Linux 开发」。零基础最容易犯的错是先买机械臂或先追 VLA 论文。**0–3 个月不要买硬件**（这也与仓库内既有 `output/embodied-ai-research.md` 的阶段一避坑建议一致）：用 Linux + Python + PyTorch + ROS 2 官方教程 + 公开数据集就能跑通第一个闭环。C++ 不必一开始就精通，但要能读懂节点与推理服务代码。

### 第二件：跑通一条「数据 → 训练 → 评测」最小闭环，并把它做成可点开的仓库

这是简历上唯一能替代「相关工作经验」的东西。推荐零硬件路径：Hugging Face Robotics Course（免硬件）→ LeRobot `lerobot/pusht` 训 Diffusion Policy → `lerobot-eval` 在 LIBERO / MetaWorld 统计成功率 → 用可视化工具浏览社区数据集。产出必须是 **GitHub 仓库 + README + 复现命令 + 成功率数字**，而不是「学过 LeRobot」。多份 JD 把「高质量 GitHub 开源项目、代码与完整文档」直接列为加分项，把「复现过 OpenVLA / ACT / RDT」列为优先项。

### 第三件：选定一条赛道，做出「带基线对比和失败分析」的作品集，并诚实标注仿真 / 真机

- 选赛道建议按背景挑：**软件 / 后端 → 仿真数据工程、部署工程化、评测产品**（对数学和真机要求相对低，本轮 JD 里这些岗位本科入口更明确）；**CV / NLP → VLA 微调、感知**；**自动化 / 机械 / 电控 → 运控、硬件**。
- 作品集的关键不是「跑通了」，而是「能对比、能归因」：同一任务上 BC / ACT / Diffusion Policy 的**成功率对比**、带**随机种子与 rollout 次数**、**失败案例分析**、**sim2real 差距来源**（视觉 / 动力学 / 传感器噪声）。这正是 JD 里「开展消融实验、基准测试与失败案例分析」「以任务成功率和系统稳定性为目标持续迭代」的原话。
- **诚实标注**：运控、感知、VLA 多个 JD 把「真机调试 / 端到端真机验证」列为硬性要求或加分项。纯仿真项目就写「仿真」，不要含糊成真机——这是转行者最容易在面试里被追问穿帮的地方。
- 顺带：不要只报一个 LIBERO 高分。Bifrost 厂商博客【行业评论】指出标准 LIBERO 已饱和（97% 量级），应搭配扰动版（LIBERO-Plus / PRO）或按因素拆分；该结论带产品推广立场，请回查各基准一手论文 / 仓库后再引用。

> 补充：JSON 中 `relatedTaskSlugs` 采用用户给定的 `lrc-s{阶段}-{序号}` 约定生成（如 `lrc-s1-2`）。仓库内既有 `output/embodied-ai-research.md` 只定义了 **L0–L5 分层**与 **0–3 / 3–6 / 6–12 三阶段**，未找到逐任务的 slug 注册表，因此这些 slug 属【行业推测】，**需与正式学习路线任务表逐条核对后使用**；`relatedLayers` 的 L0–L5 则与该既有文件的分层定义一致。

---

## 6. 主要来源清单（标题 + URL）

### 6.1 企业官方招聘页 / 可核验 JD（【官方 JD】）

1. 腾讯招聘 · 具身智能工业行业产品经理（更新于 2026-10-08，含评测集、成功率、bad case 归因、ROI 指标）— https://careers.tencent.com/jobdesc.html?postId=2108193780900478976
2. Machine Learning Engineer (m/f/d) VLA Training & Evaluation · Agile Robots SE（2026-10-15 发布，含 LoRA / diffusion policy / benchmarks / transfer studies）— https://www.digitaljobs.com/job/agile-robots-se-machine-learning-engineer-m-f-d-vla-training-and-evaluation-munich-engineering
3. VLA 算法工程师 · 厦门松霖机器人科技有限公司（南昌大学就业信息网，2026-10-16）— http://jy.ncu.edu.cn:8086/detail/job?id=3244836&online_id=3628700
4. VLA 算法工程师 / 具身智能 · 智联招聘（浙江华锐捷技术，安徽金智人力代发）— https://m.zhaopin.com/sou/jl530/kwFEBMPLATSLT0MNG8
5. VLA 大模型算法工程师（机器人）(J11193) · 黑芝麻智能 · 猎聘 — https://www.liepin.com/job/1985696103.shtml
6. 知名具身机器人公司 - VLA 模型工程师 · 猎聘 — https://m.liepin.com/a/79403955.shtml
7. 具身智能算法工程师 · 深圳甲壳虫智能 · BOSS 直聘 — https://www.zhipin.com/job_detail/d067cb62fb4e2b1d03R62du_FlJZ.html
8. 具身智能算法工程师 · 上海帕西尼感知科技 · BOSS 直聘 — https://www.zhipin.com/job_detail/5e5d11384c3f667d0nZ7296_FFNX.html
9. 具身智能算法研发工程师 · 乐聚智能（深圳）· 鱼泡直聘 — https://m.yupao.com/zhaogong/360149971.html
10. 具身算法工程师 · 猎聘 — https://m.liepin.com/job/1982566189.shtml
11. 机器人规划控制算法（上 / 深 / 北）· 猎聘 — https://m.liepin.com/a/79818297.shtml
12. 运控算法架构师 · 猎聘 — https://m.liepin.com/a/80571211.shtml
13. 运动控制工程师 · 豪森股份 · 江苏 24365 大学生就业服务平台 — https://employment.jiangsu.smartedu.cn/recruitment/jobDetails?xxdm=00000&zpgwid=1000000000753940
14. 机器人工程师（运动与控制方向）· 广州广日股份 · 高才网 — https://m.gaoxiaojob.com/job/detail/2311001.html
15. SLAM 算法工程师（具身智能方向）· Lumos Robotics · 猎聘 — https://m.liepin.com/job/1985384953.shtml
16. 感知算法工程师（机器人 / 传感器）· 猎聘 — https://m.liepin.com/a/80735823.shtml
17. 感知算法工程师 · 深圳市东阳光实业 · 湖南大学就业信息网 — https://scc.hnu.edu.cn/detail/job?id=3235760
18. 感知算法工程师（激光 / slam）· 三一集团 · 智联招聘 — https://m.zhaopin.com/jobs/CC134218700J40887244610.htm
19. 机器人视觉工程师 · 江苏隆盛唯睿具身智能机器人创新中心 · 91job — https://www.91job.org.cn/recruitment/jobDetails?dwid=1000000002398249&zpgwid=1000000000769522
20. 仿真与数据高级工程师（岗位 3，锐仕方达猎头代发）· 猎聘 — https://www.liepin.com/a/80904205.shtml
21. 数据算法工程师 · 杭州市具身智能应用中试基地 · 猎聘 — https://m.liepin.com/job/1983967001.shtml
22. 具身仿真数据采集项目经理 (A112754) · 光轮智能 · 猎聘 — https://m.liepin.com/job/1984723435.shtml
23. 具身数据算法工程师 · 苏州珀瑞缇 · 江苏 24365 平台 — https://jseti.91job.org.cn/recruitment/jobDetails?dwid=1000000002398054&zpgwid=1000000000768631
24. 具身智能数据采集业务经理 · 清雁科技（北京）· 智联 / BeBee — https://bebee.com/cn/jobs/job--techmap_cn_CCL1451173410J40887723405
25. VLA 软件集成工程师 · 吉翼具身智能机器人 · 猎聘 — https://m.liepin.com/job/1986100663.shtml
26. 端侧模型部署和优化工程师（巡检机器人）· 猎聘 — https://m.liepin.com/a/78689723.shtml
27. 模型部署 & SDK 开发工程师（具身端侧）· 杭州美梦空间 · 智联招聘 — https://m.zhaopin.com/jobs/CCL1523215890J40963872615.htm
28. Principal / Sr. Staff Forward Deployed Engineer（具身智能 AI 前沿部署工程师）· Renesas Electronics — https://freehire.me/jobs/principal-sr-staff-forward-deployed-engineer-ju-shen-zhi-neng-aiqian-yan-bu-shu-gong-cheng-shi-renesas-electronics-xawik6ek
29. 具身智能视觉工程师 (J10235) · 广州虹科电子 · 国聘 — https://www.iguopin.com/job/detail?id=220533673970107617
30. 嵌入式硬件工程师（轮式人形电控整机）· 斜跃智能 · 猎聘 — https://m.liepin.com/job/1984695855.shtml
31. 硬件工程师（具身智能 + UMI 方向）· 猎聘 — https://m.liepin.com/job/1973823919.shtml
32. 智能体-电子工程师（人形机器人方向）· 立臻科技（昆山）· 江苏人才网 — https://www.chinajsjob.com/job1778133381.shtml
33. 具身智能产品经理（具身 Agent 方向）· 深圳逐际动力 · 猎聘 — https://www.liepin.com/job/1985224875.shtml
34. 具身 Agent 产品经理 · TheJobsMap — https://www.thejobsmap.com/job/5fb4d4c8-db4b-4fc2-8815-83c8bbbf1263
35. 具身智能产品经理 · BOSS 直聘 — https://m.zhipin.com/job_detail/69f90b6c95cf418a0nV43t61EldZ.html
36. 具身智能数据平台产品经理 · 广东亿迅科技 · 智联招聘 — https://m.zhaopin.com/jobs/CC121094310J40796970906.htm

### 6.2 校招岗位名录（【媒体转引】，仅用于确认岗位类型存在）

37. 智企资讯（第 14 期）· 企业招聘资讯速递（汇编优必选、埃夫特、优艾智合、珞石、普渡、极智嘉、拓斯达、灵西 8 家 2027 届校招岗位：步态控制 / SLAM 导航 / 3D 视觉 / 伺服硬件 / 电控 / 嵌入式 / 系统测试）— http://mp.weixin.qq.com/s?__biz=MzA3NDM3NjAyMg==&mid=2651709323&idx=2&sn=1dbe22bacf1ee9eaacb91b8b01994d84

### 6.3 行业需求与薪资报道（【媒体转引】，数字全部不采信，见第 4 节）

38. 具身智能产业打响人才「攻坚战」· 中国（广西）自由贸易试验区钦州港片区（政府网站转载媒体报道；含脉脉 15 倍、IDC 770 亿美元、北理工 100 万缺口、教育部 9 所高校等转引）— https://qzftz.gxzf.gov.cn/ztzl/rdjj/jkdzxxcyjq/cyxw/t28115259.shtml
39. 平均月薪 5 万+？具身智能机器人行业，最赚钱的岗位出现了！· NSTL 重点领域信息门户（转载新战略移动机器人产业研究所 / 智联猎头 / 猎聘等多方数据）— http://dtjc.gdinfo.net/dynamic/recordShow/20034003/216/a0b88456defef3dde441014f5f52d019
40. 2026 年中国具身智能机器人产业发展人才报告 · 三个皮匠报告（报告站二次摘要）— https://www.sgpjbg.com/searchtag/27212977.html
41. 2026 具身智能产业机器人领域人才供需洞察报告 · 三个皮匠报告（报告站二次摘要）— https://www.sgpjbg.com.cn/searchtag/27130379.html
42. 2026 年人才需求 · 三个皮匠报告（含 62000 元平均月薪、需供比表等）— https://www.sgpjbg.com/searchtag/26677595.html
43. 缺人！缺人！缺人！年薪至高 240 万！· 南方新华猎头公众号（自述「数据来源于猎头交付案例」，含 80–200 万中位年薪、450 万缺口、求人倍率 2.3 等）— http://mp.weixin.qq.com/s?__biz=MzYzNDA3NDQ0NA==&mid=2247484734&idx=1&sn=8f6d9987c3ecc34fe8f8b4a397522568

### 6.4 开源项目 / 学习路线 / 技术评论（用于核验 `tools` 与 `entryProjects`）

44. LeRobot 官方文档 — https://huggingface.co/docs/lerobot/index
45. Hugging Face Robotics Course（免硬件）— https://huggingface.co/learn/robotics-course/unit0/1
46. OpenVLA 项目页 — https://openvla.github.io/
47. openpi（π0 / π0-FAST）· Physical Intelligence — https://github.com/Physical-Intelligence/openpi
48. NVIDIA Isaac-GR00T — https://github.com/Nvidia/Isaac-GR00T
49. LeRobot SO-101 配置指南 — https://huggingface.co/docs/lerobot/so101
50. MuJoCo Playground · Google DeepMind — https://github.com/google-deepmind/mujoco_playground
51. Isaac Lab — https://github.com/isaac-sim/IsaacLab
52. robosuite（MuJoCo 驱动的机器人学习仿真与基准）— https://robosuite.ai/
53. LeRobot 项目库条目（策略 / 数据格式 / 基准一览）— https://projects.imakething.com/projects/317
54. 一条 send_action 跑通模仿学习：LeRobot 上手实践 · CSDN（含常见坑：端口、loss 不降、真机延迟）— https://blog.csdn.net/gitblog_00373/article/details/160143336
55. LeRobot：把视觉语言指令变成机械臂动作的开源框架 · CSDN — https://blog.csdn.net/gitblog_01051/article/details/156501058
56. Best Simulation Benchmarks For VLA Models In 2026 · Bifrost AI（【厂商博客 / 行业评论】，含 LIBERO 饱和、LIBERO-Plus/PRO、RoboCasa365、RoboTwin 2.0、SimplerEnv、ManiSkill3、CALVIN、BEHAVIOR-1K、Meta-World 的用途对比）— https://www.bifrost.ai/blog/best-simulation-benchmarks-for-vla-models/
57. Imitator-Game Baselines（ACT / Diffusion Policy / VQ-BeT / GR00T / RDT / π0 / OpenVLA-OFT 统一 LeRobot 数据契约）— https://imitator-game.github.io/docs/baselines.html
58. How to Become a Robotics Engineer: A 6-Month Roadmap · YouMind（【行业推测】，6 个月路线与开源项目清单）— https://youmind.com/landing/x-viral-articles/robotics-engineer-6-month-roadmap
59. 具身智能入门指南：岗位要求、技能拆解与系统学习路线 · CSDN（【行业推测】，五阶段路线与不同背景切入建议）— https://blog.csdn.net/weixin_30952479/article/details/164438939
60. 具身智能学习路线 · CSDN 具身智能社区（【行业推测】，四阶段路线）— https://jszn.csdn.net/69c37e7e54b52172bc641bf3.html
61. 人形机器人生产落地：从 ROS2 开发到工程实践的技术栈解析（【行业推测】，含功能安全与学习路线）— https://www.hqwc.cn/a/1481065.html
62. 仓库内既有资料：`output/embodied-ai-research.md`（L0–L5 分层、0–3 / 3–6 / 6–12 三阶段路线、三种硬件条件替代路径）— 本地文件，非网络来源

---

## 7. 给使用者的一句话提醒

**这份数据里真正 hard 的事实，只有「官方 JD 写了什么技能」和「开源项目真实存在」；热度评级、面试考点、练手题目、时间线都是建议；而所有薪资与需求增长数字都是媒体转引，互相矛盾，一律不采信。** 转行决策请回到自己能跑通、能展示、能讲清楚失败原因的项目上，而不是回到任何一个「平均年薪」数字上。
